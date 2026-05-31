"""
FastAPI backend for Mortgage Verification System.

Routes:
  POST /upload        — upload documents + XML
  POST /process       — start processing session
  GET  /results/{id}  — get validation results
  GET  /logs/{id}     — get agent logs
  GET  /sessions      — list recent sessions
  GET  /chunks/{id}   — preview document chunks
  GET  /health        — health check
"""
import os
import sys
import uuid
import time
import asyncio
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings, setup_logging, get_logger
from database import (
    get_db_dependency, create_tables,
    SessionRepository, FileRepository, ValidationRepository, LogRepository,
    SessionStatus
)

cfg = get_settings()
setup_logging(cfg.logging.level, cfg.logging.format)
logger = get_logger(__name__)

app = FastAPI(
    title="Mortgage Verification API",
    description="Multi-agent mortgage document verification system",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(cfg.api.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
async def startup():
    create_tables()
    logger.info("Database initialized")


# ── Schemas ────────────────────────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    session_id: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/upload", summary="Upload mortgage documents and XML baseline")
async def upload_files(
    xml_file: UploadFile = File(..., description="MISMO XML baseline file (.xml)"),
    pdf_files: List[UploadFile] = File(..., description="Mortgage PDFs (one or more)"),
    db: Session = Depends(get_db_dependency),
):
    """
    Upload 1 XML baseline + 1 or more mortgage PDF files.
    Returns a **session_id** — use it to call POST /process.
    """
    session_repo = SessionRepository(db)
    file_repo = FileRepository(db)

    # Create session
    session = session_repo.create(xml_filename=xml_file.filename)
    session_id = session.id
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # ── Save XML ───────────────────────────────────────────────────────────────
    xml_save_path = session_dir / "baseline.xml"
    xml_content = await xml_file.read()
    with open(xml_save_path, "wb") as f:
        f.write(xml_content)

    file_repo.create(
        session_id=session_id,
        filename="baseline.xml",
        original_name=xml_file.filename or "baseline.xml",
        file_path=str(xml_save_path),
        file_size=len(xml_content),
        doc_type="xml",
        domain="baseline",
    )

    # ── Save PDFs ──────────────────────────────────────────────────────────────
    pdf_dir = session_dir / "pdfs"
    pdf_dir.mkdir(exist_ok=True)
    saved_pdfs = []

    for pdf in pdf_files:
        safe_name = Path(pdf.filename).name if pdf.filename else f"doc_{uuid.uuid4().hex[:8]}.pdf"
        save_path = pdf_dir / safe_name
        data = await pdf.read()
        with open(save_path, "wb") as f:
            f.write(data)

        # Classify doc type
        try:
            from utils.file_classifier import classify_file
            doc_type = classify_file(str(save_path))
            domain = _doc_type_to_domain(doc_type)
            doc_type_str = str(doc_type)
        except Exception:
            doc_type_str = "unknown"
            domain = "unknown"

        file_repo.create(
            session_id=session_id,
            filename=safe_name,
            original_name=pdf.filename or safe_name,
            file_path=str(save_path),
            file_size=len(data),
            doc_type=doc_type_str,
            domain=domain,
        )
        saved_pdfs.append(safe_name)

    session_repo.update_status(session_id, SessionStatus.CREATED, pdf_count=len(saved_pdfs))
    db.commit()

    logger.info(f"Session {session_id}: uploaded 1 XML + {len(saved_pdfs)} PDFs")
    return {
        "session_id": session_id,
        "xml_file": xml_file.filename,
        "pdf_count": len(saved_pdfs),
        "pdf_files": saved_pdfs,
        "message": "Upload successful. Call POST /process to start verification.",
    }


@app.post("/process", summary="Start verification processing")
async def process(
    req: ProcessRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_dependency),
):
    """Start async processing for a session. Poll GET /results/{session_id} for status."""
    session_repo = SessionRepository(db)
    session = session_repo.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == SessionStatus.PROCESSING:
        return {"message": "Already processing", "session_id": req.session_id}

    session_repo.update_status(req.session_id, SessionStatus.PROCESSING)
    db.commit()

    background_tasks.add_task(_run_processing, req.session_id)
    return {
        "session_id": req.session_id,
        "message": "Processing started. Poll GET /results/{session_id} for results.",
    }


@app.get("/results/{session_id}", summary="Get validation results")
async def get_results(session_id: str, db: Session = Depends(get_db_dependency)):
    session_repo = SessionRepository(db)
    val_repo = ValidationRepository(db)

    session = session_repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    results = val_repo.list_for_session(session_id)
    summary = val_repo.summary(session_id)

    # Deserialize missing_files_summary from JSON string
    import json as _json
    try:
        missing_files = _json.loads(session.missing_files_summary or "[]")
    except Exception:
        missing_files = []

    by_domain: dict = {}
    for r in results:
        by_domain.setdefault(r.domain, []).append({
            "field_name": r.field_name,
            "expected_value": r.expected_value,
            "extracted_value": r.extracted_value,
            "status": r.status,
            "confidence": r.confidence,
            "is_missing": r.is_missing,
            "agent_name": r.agent_name,
        })

    return {
        "session_id": session_id,
        "status": session.status,
        "overall_status": session.overall_status,
        "processing_time_sec": session.processing_time_sec,
        "summary": summary,
        "results_by_domain": by_domain,
        "missing_files_to_reupload": missing_files,
        "error_message": session.error_message,
    }


@app.get("/logs/{session_id}", summary="Get agent execution logs")
async def get_logs(session_id: str, db: Session = Depends(get_db_dependency)):
    session_repo = SessionRepository(db)
    if not session_repo.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    log_repo = LogRepository(db)
    logs = log_repo.list_for_session(session_id)
    return {
        "session_id": session_id,
        "logs": [
            {
                "agent_name": l.agent_name,
                "level": l.level,
                "message": l.message,
                "created_at": l.created_at.isoformat(),
                "extra": l.extra_data,
            }
            for l in logs
        ],
    }


@app.get("/sessions", summary="List recent sessions")
async def list_sessions(db: Session = Depends(get_db_dependency)):
    repo = SessionRepository(db)
    sessions = repo.list_recent(20)
    return {
        "sessions": [
            {
                "session_id": s.id,
                "status": s.status,
                "overall_status": s.overall_status,
                "xml_filename": s.xml_filename,
                "pdf_count": s.pdf_count,
                "created_at": s.created_at.isoformat(),
                "processing_time_sec": s.processing_time_sec,
            }
            for s in sessions
        ]
    }


@app.get("/chunks/{session_id}", summary="Preview document chunks")
async def get_chunks(
    session_id: str,
    domain: Optional[str] = None,
    db: Session = Depends(get_db_dependency),
):
    from database import ChunkRepository
    from database.models import ExtractedChunk

    repo = ChunkRepository(db)
    if domain:
        chunks = repo.list_for_domain(session_id, domain)
    else:
        chunks = (db.query(ExtractedChunk)
                  .filter(ExtractedChunk.session_id == session_id)
                  .limit(50).all())

    return {
        "session_id": session_id,
        "total_returned": len(chunks),
        "chunks": [
            {
                "chunk_index": c.chunk_index,
                "source_file": c.source_file,
                "domain": c.domain,
                "doc_type": c.doc_type,
                "page_number": c.page_number,
                "token_count": c.token_count,
                "text_preview": c.text[:200] + "..." if len(c.text) > 200 else c.text,
            }
            for c in chunks
        ],
    }


@app.get("/files/{session_id}", summary="List uploaded files for a session")
async def list_files(session_id: str, db: Session = Depends(get_db_dependency)):
    file_repo = FileRepository(db)
    files = file_repo.list_for_session(session_id)
    return {
        "session_id": session_id,
        "files": [
            {
                "filename": f.filename,
                "original_name": f.original_name,
                "doc_type": f.doc_type,
                "domain": f.domain,
                "file_size_bytes": f.file_size_bytes,
                "matched_borrower": f.matched_borrower,
                "match_confidence": f.match_confidence,
            }
            for f in files
        ],
    }


# ── Background Processing ──────────────────────────────────────────────────────

async def _run_processing(session_id: str) -> None:
    from database import get_db, SessionRepository, ValidationRepository, LogRepository

    t_start = time.time()
    try:
        session_dir = UPLOAD_DIR / session_id
        xml_path = session_dir / "baseline.xml"
        pdf_dir = session_dir / "pdfs"

        if not xml_path.exists():
            raise FileNotFoundError(f"XML not found: {xml_path}")

        from graph import build_graph

        initial = {
            "xml_path": str(xml_path),
            "pdf_dir": str(pdf_dir),
            "session_id": session_id,
            "baseline": None, "flat_facts": {}, "classified_files": {},
            "all_chunks": {}, "file_match_results": {},
            "borrower_result": None, "asset_result": None,
            "employment_result": None, "reo_result": None,
            "final_report": "", "all_pass": False,
            "missing_files_summary": [],
        }

        final = await asyncio.to_thread(build_graph().invoke, initial)
        elapsed = time.time() - t_start

        with get_db() as db:
            val_repo = ValidationRepository(db)
            log_repo = LogRepository(db)
            session_repo = SessionRepository(db)

            for result_key in ["borrower_result", "asset_result", "employment_result", "reo_result"]:
                agent_result = final.get(result_key)
                if agent_result and hasattr(agent_result, "findings") and agent_result.findings:
                    val_repo.bulk_create_from_findings(
                        session_id=session_id,
                        agent_name=result_key.replace("_result", ""),
                        domain=agent_result.domain,
                        findings=agent_result.findings,
                    )
                    log_repo.add(
                        session_id=session_id,
                        agent_name=result_key.replace("_result", ""),
                        level="INFO",
                        message=f"Agent completed: status={agent_result.status}, "
                                f"findings={len(agent_result.findings)}, "
                                f"mismatches={len(agent_result.mismatches)}",
                    )

            session_repo.complete(
                session_id=session_id,
                all_pass=final.get("all_pass", False),
                summary=final.get("final_report", ""),
                elapsed=elapsed,
                missing_files=final.get("missing_files_summary", []),
            )

        logger.info(f"Session {session_id} completed in {elapsed:.1f}s")

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"Session {session_id} failed: {e}", exc_info=True)
        with get_db() as db:
            SessionRepository(db).fail(session_id, str(e))


def _doc_type_to_domain(doc_type) -> str:
    try:
        from utils.file_classifier import DOMAIN_MAP
        for domain, types in DOMAIN_MAP.items():
            if doc_type in types:
                return domain
    except Exception:
        pass
    return "unknown"
