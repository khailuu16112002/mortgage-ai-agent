"""
SQLAlchemy ORM models for the Mortgage Verification System.
Supports SQLite (dev) and PostgreSQL (prod) via DATABASE_URL.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, Float, Boolean, Integer, DateTime, Text,
    ForeignKey, JSON, Enum as SAEnum, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
import enum


class Base(DeclarativeBase):
    pass


class ValidationStatus(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    PENDING = "PENDING"


class SessionStatus(str, enum.Enum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Processing Session ─────────────────────────────────────────────────────────
class ProcessingSession(Base):
    __tablename__ = "processing_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(20), default=SessionStatus.CREATED)
    xml_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pdf_count: Mapped[int] = mapped_column(Integer, default=0)
    overall_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # PASS/FAIL
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processing_time_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    missing_files_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list

    # Relationships
    uploaded_files = relationship("UploadedFile", back_populates="session", cascade="all, delete-orphan")
    validation_results = relationship("ValidationResult", back_populates="session", cascade="all, delete-orphan")
    agent_logs = relationship("AgentLog", back_populates="session", cascade="all, delete-orphan")
    chunks = relationship("ExtractedChunk", back_populates="session", cascade="all, delete-orphan")


# ── Uploaded Files ─────────────────────────────────────────────────────────────
class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("processing_sessions.id"))
    filename: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    doc_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    is_image_scan: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # LLM matching result
    matched_borrower: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    match_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    session = relationship("ProcessingSession", back_populates="uploaded_files")
    chunks = relationship("ExtractedChunk", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_uploaded_files_session", "session_id"),
        Index("ix_uploaded_files_doc_type", "doc_type"),
    )


# ── Extracted Chunks ───────────────────────────────────────────────────────────
class ExtractedChunk(Base):
    __tablename__ = "extracted_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("processing_sessions.id"))
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("uploaded_files.id"))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    source_file: Mapped[str] = mapped_column(String(255))
    domain: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session = relationship("ProcessingSession", back_populates="chunks")
    file = relationship("UploadedFile", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_session_domain", "session_id", "domain"),
        Index("ix_chunks_file", "file_id"),
    )


# ── Validation Results ─────────────────────────────────────────────────────────
class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("processing_sessions.id"))
    agent_name: Mapped[str] = mapped_column(String(50))
    domain: Mapped[str] = mapped_column(String(50))
    field_name: Mapped[str] = mapped_column(String(255))
    expected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default=ValidationStatus.PENDING)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False)
    source_chunk_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session = relationship("ProcessingSession", back_populates="validation_results")

    __table_args__ = (
        Index("ix_validation_session_domain", "session_id", "domain"),
        Index("ix_validation_status", "status"),
    )


# ── Agent Logs ─────────────────────────────────────────────────────────────────
class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("processing_sessions.id"))
    agent_name: Mapped[str] = mapped_column(String(50))
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session = relationship("ProcessingSession", back_populates="agent_logs")

    __table_args__ = (
        Index("ix_agent_logs_session", "session_id"),
    )
