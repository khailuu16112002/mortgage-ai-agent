"""
CLI entry point for the Mortgage Verification System.

Usage:
  python main.py --xml data/sample.xml --pdfs data/pdfs/
  python main.py --xml data/sample.xml --pdfs data/pdfs/ --session-id my-session
"""
import argparse
import sys
import time
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

from config import get_settings, setup_logging, get_logger
from database import create_tables


def main():
    parser = argparse.ArgumentParser(
        description="Mortgage Document Verification System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--xml", required=True, help="Path to MISMO XML baseline file")
    parser.add_argument("--pdfs", required=True, help="Directory containing mortgage PDFs")
    parser.add_argument("--session-id", help="Optional session ID (auto-generated if not provided)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--no-db", action="store_true", help="Skip DB persistence")
    args = parser.parse_args()

    cfg = get_settings()
    setup_logging(args.log_level, cfg.logging.format)
    logger = get_logger("main")

    # Validate inputs
    xml_path = Path(args.xml)
    pdf_dir = Path(args.pdfs)
    if not xml_path.exists():
        logger.error(f"XML file not found: {xml_path}")
        sys.exit(1)
    if not pdf_dir.exists():
        logger.error(f"PDF directory not found: {pdf_dir}")
        sys.exit(1)

    # Init DB
    if not args.no_db:
        create_tables()

    # Generate or use session ID
    import uuid
    session_id = args.session_id or str(uuid.uuid4())
    logger.info(f"Session ID: {session_id}")

    # Create DB session record
    if not args.no_db:
        from database import get_db, SessionRepository
        with get_db() as db:
            repo = SessionRepository(db)
            existing = repo.get(session_id)
            if not existing:
                repo.create(
                    session_id=session_id,
                    xml_filename=str(xml_path)
            )

    # Build initial state
    initial = {
        "xml_path": str(xml_path),
        "pdf_dir": str(pdf_dir),
        "session_id": session_id if not args.no_db else None,
        "baseline": None,
        "flat_facts": {},
        "classified_files": {},
        "all_chunks": {},
        "file_match_results": {},
        "borrower_result": None,
        "asset_result": None,
        "employment_result": None,
        "reo_result": None,
        "final_report": "",
        "all_pass": False,
    }

    # Run pipeline
    t0 = time.time()
    logger.info("Starting verification pipeline...")

    from graph import build_graph
    final = build_graph().invoke(initial)

    elapsed = time.time() - t0
    logger.info(f"Pipeline completed in {elapsed:.1f}s | all_pass={final.get('all_pass', False)}")

    # Persist final results
    if not args.no_db:
        from agents.state import AgentResult
        from database import get_db, SessionRepository, ValidationRepository, LogRepository

        with get_db() as db:
            val_repo = ValidationRepository(db)
            log_repo = LogRepository(db)
            session_repo = SessionRepository(db)

            for key in ["borrower_result", "asset_result", "employment_result", "reo_result"]:
                result = final.get(key)
                if result and hasattr(result, "findings") and result.findings:
                    val_repo.bulk_create_from_findings(
                        session_id=session_id,
                        agent_name=key.replace("_result", ""),
                        domain=result.domain,
                        findings=result.findings,
                    )

            session_repo.complete(
                session_id=session_id,
                all_pass=final.get("all_pass", False),
                summary=final.get("final_report", ""),
                elapsed=elapsed,
            )

        logger.info(f"Results saved to database. Session: {session_id}")

    return 0 if final.get("all_pass", False) else 1


if __name__ == "__main__":
    sys.exit(main())
