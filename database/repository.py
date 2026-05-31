"""Repository pattern for database operations."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from .models import (
    ProcessingSession, UploadedFile, ExtractedChunk,
    ValidationResult, AgentLog, SessionStatus, ValidationStatus
)


class SessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        session_id: str | None = None,
        xml_filename: str | None = None,
    ) -> ProcessingSession:

        import uuid

        session = ProcessingSession(
            id=session_id or str(uuid.uuid4()),
            xml_filename=xml_filename,
            status=SessionStatus.CREATED,
        )

        self.db.add(session)
        self.db.flush()
        return session

    def get(self, session_id: str) -> Optional[ProcessingSession]:
        return self.db.query(ProcessingSession).filter(ProcessingSession.id == session_id).first()

    def list_recent(self, limit: int = 20) -> list[ProcessingSession]:
        return (self.db.query(ProcessingSession)
                .order_by(ProcessingSession.created_at.desc())
                .limit(limit).all())

    def update_status(self, session_id: str, status: str, **kwargs) -> None:
        session = self.get(session_id)
        if session:
            session.status = status
            session.updated_at = datetime.utcnow()
            for k, v in kwargs.items():
                setattr(session, k, v)
            self.db.flush()

    def complete(self, session_id: str, all_pass: bool, summary: str, elapsed: float,
                 missing_files: list | None = None) -> None:
        import json
        self.update_status(
            session_id,
            status=SessionStatus.COMPLETED,
            overall_status="PASS" if all_pass else "FAIL",
            summary=summary,
            processing_time_sec=elapsed,
            missing_files_summary=json.dumps(missing_files or [], ensure_ascii=False),
        )

    def fail(self, session_id: str, error: str) -> None:
        self.update_status(session_id, status=SessionStatus.FAILED, error_message=error)


class FileRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self, session_id: str, filename: str, original_name: str,
        file_path: str, file_size: int, doc_type: str | None = None,
        domain: str | None = None,
    ) -> UploadedFile:
        f = UploadedFile(
            session_id=session_id,
            filename=filename,
            original_name=original_name,
            file_path=file_path,
            file_size_bytes=file_size,
            doc_type=doc_type,
            domain=domain,
        )
        self.db.add(f)
        self.db.flush()
        return f

    def update_ocr(self, file_id: str, ocr_text: str, is_scan: bool, page_count: int) -> None:
        f = self.db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if f:
            f.ocr_text = ocr_text
            f.is_image_scan = is_scan
            f.page_count = page_count
            self.db.flush()

    def update_match(self, file_id: str, borrower: str, confidence: float, reason: str) -> None:
        f = self.db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if f:
            f.matched_borrower = borrower
            f.match_confidence = confidence
            f.match_reason = reason
            self.db.flush()

    def list_for_session(self, session_id: str) -> list[UploadedFile]:
        return self.db.query(UploadedFile).filter(UploadedFile.session_id == session_id).all()


class ChunkRepository:
    def __init__(self, db: Session):
        self.db = db

    def bulk_create(self, chunks: list[dict]) -> list[ExtractedChunk]:
        objs = [ExtractedChunk(**c) for c in chunks]
        self.db.bulk_save_objects(objs)
        self.db.flush()
        return objs

    def list_for_domain(self, session_id: str, domain: str) -> list[ExtractedChunk]:
        return (self.db.query(ExtractedChunk)
                .filter(ExtractedChunk.session_id == session_id,
                        ExtractedChunk.domain == domain)
                .order_by(ExtractedChunk.chunk_index)
                .all())

    def count_for_session(self, session_id: str) -> int:
        return self.db.query(ExtractedChunk).filter(ExtractedChunk.session_id == session_id).count()


class ValidationRepository:
    def __init__(self, db: Session):
        self.db = db

    def bulk_create_from_findings(
        self, session_id: str, agent_name: str, domain: str,
        findings: list,  # list of ValidationFinding
    ) -> None:
        from agents.state import ValidationFinding
        rows = []
        for f in findings:
            status = ValidationStatus.MISSING if f.is_missing else \
                     (ValidationStatus.PASS if f.matched else ValidationStatus.FAIL)
            rows.append(ValidationResult(
                session_id=session_id,
                agent_name=agent_name,
                domain=domain,
                field_name=f.field_name,
                expected_value=str(f.xml_value) if f.xml_value is not None else None,
                extracted_value=str(f.pdf_value) if f.pdf_value is not None else None,
                status=status,
                confidence=1.0 if f.matched else 0.0,
                is_missing=f.is_missing,
            ))
        self.db.bulk_save_objects(rows)
        self.db.flush()

    def list_for_session(self, session_id: str) -> list[ValidationResult]:
        return (self.db.query(ValidationResult)
                .filter(ValidationResult.session_id == session_id)
                .order_by(ValidationResult.domain, ValidationResult.field_name)
                .all())

    def summary(self, session_id: str) -> dict:
        rows = self.list_for_session(session_id)
        total = len(rows)
        passed = sum(1 for r in rows if r.status == ValidationStatus.PASS)
        failed = sum(1 for r in rows if r.status == ValidationStatus.FAIL)
        missing = sum(1 for r in rows if r.status == ValidationStatus.MISSING)
        return {"total": total, "pass": passed, "fail": failed, "missing": missing}


class LogRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, session_id: str, agent_name: str, level: str, message: str, extra: dict | None = None) -> None:
        log = AgentLog(
            session_id=session_id,
            agent_name=agent_name,
            level=level,
            message=message,
            extra_data=extra,
        )
        self.db.add(log)
        self.db.flush()

    def list_for_session(self, session_id: str) -> list[AgentLog]:
        return (self.db.query(AgentLog)
                .filter(AgentLog.session_id == session_id)
                .order_by(AgentLog.created_at)
                .all())
