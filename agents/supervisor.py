"""
Supervisor Node — orchestrates parsing, classification, chunking, and DB setup.
Adds DB persistence and document chunking to the original supervisor logic.
"""
from pathlib import Path
from rich.console import Console

from agents.state import GraphState
from utils.xml_parser import parse_xml
from utils.xml_to_json import baseline_to_flat_facts
from utils.file_classifier import classify_directory, print_classification
from config import get_logger

logger = get_logger(__name__)
console = Console()


def supervisor_node(state: GraphState) -> GraphState:
    console.rule("[bold cyan]🏦 SUPERVISOR — MORTGAGE VERIFICATION[/bold cyan]")

    # Parse XML
    console.print(f"[dim]→ Parsing XML: {state.xml_path}[/dim]")
    try:
        baseline = parse_xml(state.xml_path)
        state.baseline = baseline
        state.flat_facts = baseline_to_flat_facts(baseline)
    except Exception as e:
        logger.error(f"XML parse failed: {e}")
        raise

    console.print(
        f"[green]✓ Parsed:[/green] {len(baseline.borrowers)} borrower(s) | "
        f"{len(baseline.assets)} asset(s) | "
        f"{len(baseline.employments)} employment(s) | "
        f"{len(baseline.real_estate_owned)} REO(s)"
    )

    # Classify PDFs
    console.print(f"[dim]→ Classifying PDFs in: {state.pdf_dir}[/dim]")
    classified = classify_directory(state.pdf_dir)
    state.classified_files = classified
    print_classification(classified)

    # Chunking (if session_id provided)
    session_id = getattr(state, "session_id", None)
    if session_id:
        _run_chunking(state, classified, session_id)
        _run_file_matching(state, classified, baseline)

    return state


def _run_chunking(state: GraphState, classified: dict, session_id: str) -> None:
    try:
        from pipelines.chunking import DocumentChunker
        from database import get_db, ChunkRepository

        chunker = DocumentChunker()
        all_chunks = chunker.chunk_directory(classified)
        total = sum(len(v) for v in all_chunks.values())
        console.print(f"[cyan]→ Created {total} chunks from PDFs[/cyan]")

        with get_db() as db:
            repo = ChunkRepository(db)
            chunk_rows = []
            for doc_type_str, chunks in all_chunks.items():
                for c in chunks:
                    chunk_rows.append({
                        "session_id": session_id,
                        "file_id": session_id,
                        "chunk_index": c.chunk_index,
                        "page_number": c.page_number,
                        "source_file": c.source_file,
                        "domain": c.domain,
                        "doc_type": c.doc_type,
                        "text": c.text,
                        "token_count": c.token_count,
                        "extra_metadata": c.metadata,
                    })
            if chunk_rows:
                repo.bulk_create(chunk_rows)
        state.all_chunks = all_chunks
    except Exception as e:
        logger.warning(f"Chunking step failed (non-fatal): {e}")


def _run_file_matching(state: GraphState, classified: dict, baseline) -> None:
    try:
        from services.file_matcher import FileMatcher
        matcher = FileMatcher()
        match_results = matcher.batch_match_files(classified, baseline.borrowers)
        state.file_match_results = match_results
        console.print(f"[cyan]→ File matching: {len(match_results)} document(s) matched[/cyan]")
    except Exception as e:
        logger.warning(f"File matching step failed (non-fatal): {e}")
