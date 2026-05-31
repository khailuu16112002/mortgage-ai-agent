"""
Document chunking pipeline.

Strategy:
  1. Extract text from PDF (text or vision)
  2. Split into overlapping chunks using RecursiveCharacterTextSplitter
  3. Attach metadata: chunk_id, page, source file, domain, doc_type
  4. Optionally count tokens via tiktoken

Architecture:
  PDF → extract_text → split_into_chunks → list[DocumentChunk]
"""
from __future__ import annotations
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import get_settings, get_logger

logger = get_logger(__name__)


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    page_number: int
    chunk_index: int
    source_file: str
    domain: Optional[str]
    doc_type: Optional[str]
    token_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "source_file": self.source_file,
            "domain": self.domain,
            "doc_type": self.doc_type,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }


class RecursiveTextSplitter:
    """
    Recursive character text splitter — mimics LangChain's approach
    without adding the full dependency.
    Splits on: paragraphs → sentences → words → characters
    """
    SEPARATORS = ["\n\n\n", "\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""]

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 150, min_chunk: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk = min_chunk

    def split(self, text: str) -> list[str]:
        chunks = self._split_recursive(text, self.SEPARATORS)
        return [c for c in chunks if len(c.strip()) >= self.min_chunk]

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]

        sep = separators[0]
        remaining_seps = separators[1:]

        if sep:
            parts = text.split(sep)
        else:
            parts = list(text)

        chunks: list[str] = []
        current = ""

        for part in parts:
            piece = (current + sep + part).lstrip(sep) if current else part
            if len(piece) <= self.chunk_size:
                current = piece
            else:
                if current:
                    chunks.append(current)
                # If single part is too big, recurse with finer separator
                if remaining_seps and len(part) > self.chunk_size:
                    chunks.extend(self._split_recursive(part, remaining_seps))
                    current = ""
                else:
                    current = part

        if current:
            chunks.append(current)

        # Apply overlap: prepend tail of previous chunk to next
        if self.chunk_overlap > 0 and len(chunks) > 1:
            overlapped = [chunks[0]]
            for i in range(1, len(chunks)):
                # Only take overlap if it won't push us way over chunk_size
                prev_tail = chunks[i - 1][-self.chunk_overlap:].strip()
                candidate = prev_tail + " " + chunks[i] if prev_tail else chunks[i]
                # If candidate exceeds 2x chunk_size, skip the overlap
                if len(candidate) > self.chunk_size * 2:
                    overlapped.append(chunks[i])
                else:
                    overlapped.append(candidate)
            return overlapped

        return chunks


def count_tokens(text: str) -> int:
    """Approximate token count. Uses tiktoken if available, else word estimate."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # Rough estimate: 1 token ≈ 0.75 words
        return int(len(text.split()) * 1.3)


class DocumentChunker:
    """
    Main chunking service.
    Converts PDF files into lists of DocumentChunk objects.
    """

    def __init__(self):
        cfg = get_settings().chunking
        self.splitter = RecursiveTextSplitter(
            chunk_size=cfg.chunk_size,
            chunk_overlap=cfg.chunk_overlap,
            min_chunk=cfg.min_chunk_length,
        )
        self.max_chunks = cfg.max_chunks_per_doc

    def chunk_pdf(
        self,
        pdf_path: str,
        domain: str | None = None,
        doc_type: str | None = None,
    ) -> list[DocumentChunk]:
        """Extract text from a PDF and return chunked DocumentChunks."""
        from utils.pdf_reader import extract_pdf_text, read_pdf_smart

        path = Path(pdf_path)
        source_file = path.name

        # Try to get text; fall back to vision text placeholder
        info = read_pdf_smart(pdf_path)
        if info["mode"] == "images":
            # For image PDFs, we can't chunk without OCR — return a placeholder chunk
            logger.debug(f"Image PDF — cannot chunk text: {source_file}")
            return [DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                text=f"[IMAGE PDF: {source_file}]",
                page_number=1,
                chunk_index=0,
                source_file=source_file,
                domain=domain,
                doc_type=doc_type,
                token_count=5,
                metadata={"is_image": True},
            )]

        text = info["text"]
        return self.chunk_text(text, source_file, domain, doc_type)

    def chunk_text(
        self,
        text: str,
        source_file: str,
        domain: str | None = None,
        doc_type: str | None = None,
    ) -> list[DocumentChunk]:
        """Split plain text into DocumentChunks."""
        raw_chunks = self.splitter.split(text)
        raw_chunks = raw_chunks[:self.max_chunks]

        chunks = []
        for i, chunk_text in enumerate(raw_chunks):
            # Estimate page number from position ratio
            page_est = max(1, int(i / max(len(raw_chunks), 1) * 10) + 1)

            token_count = count_tokens(chunk_text)
            chunks.append(DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                text=chunk_text.strip(),
                page_number=page_est,
                chunk_index=i,
                source_file=source_file,
                domain=domain,
                doc_type=doc_type,
                token_count=token_count,
                metadata={"char_count": len(chunk_text)},
            ))

        logger.debug(f"Chunked {source_file}: {len(chunks)} chunks from {len(text)} chars")
        return chunks

    def chunk_directory(
        self,
        classified_files: dict,
    ) -> dict[str, list[DocumentChunk]]:
        """
        Process all classified files.
        Returns {doc_type: [chunks]} mapping.
        """
        from utils.file_classifier import DOMAIN_MAP

        # Build reverse map: DocType → domain
        type_to_domain: dict[str, str] = {}
        for domain, types in DOMAIN_MAP.items():
            for t in types:
                type_to_domain[t] = domain

        all_chunks: dict[str, list[DocumentChunk]] = {}
        for doc_type_key, files in classified_files.items():
            if not files:
                continue
            type_name = str(doc_type_key)
            domain = type_to_domain.get(doc_type_key, "unknown")
            type_chunks: list[DocumentChunk] = []
            for fpath in files:
                try:
                    fc = self.chunk_pdf(fpath, domain=domain, doc_type=type_name)
                    type_chunks.extend(fc)
                except Exception as e:
                    logger.warning(f"Chunking failed for {fpath}: {e}")
            all_chunks[type_name] = type_chunks

        total = sum(len(v) for v in all_chunks.values())
        logger.info(f"Total chunks created: {total} across {len(all_chunks)} doc types")
        return all_chunks


def get_chunks_as_context(chunks: list[DocumentChunk], max_tokens: int = 6000) -> str:
    """
    Flatten a list of chunks into a single context string for LLM,
    respecting a token budget.
    """
    parts = []
    running_tokens = 0
    for c in chunks:
        if running_tokens + c.token_count > max_tokens:
            break
        parts.append(f"--- [{c.source_file} | chunk {c.chunk_index}] ---\n{c.text}")
        running_tokens += c.token_count
    return "\n\n".join(parts)
