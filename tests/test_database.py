"""Unit tests for database models and repositories."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, ProcessingSession, UploadedFile, ValidationResult, AgentLog
from database.repository import (
    SessionRepository, FileRepository, ValidationRepository, LogRepository
)


@pytest.fixture
def db_session():
    """In-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(engine)


class TestSessionRepository:
    def test_create_session(self, db_session):
        repo = SessionRepository(db_session)
        session = repo.create(xml_filename="test.xml")
        assert session.id is not None
        assert session.xml_filename == "test.xml"
        assert session.status == "CREATED"

    def test_get_session(self, db_session):
        repo = SessionRepository(db_session)
        created = repo.create("test.xml")
        db_session.commit()
        found = repo.get(created.id)
        assert found is not None
        assert found.id == created.id

    def test_get_nonexistent(self, db_session):
        repo = SessionRepository(db_session)
        assert repo.get("nonexistent-id") is None

    def test_update_status(self, db_session):
        repo = SessionRepository(db_session)
        session = repo.create("test.xml")
        db_session.commit()
        repo.update_status(session.id, "PROCESSING")
        db_session.commit()
        updated = repo.get(session.id)
        assert updated.status == "PROCESSING"

    def test_complete_session(self, db_session):
        repo = SessionRepository(db_session)
        session = repo.create("test.xml")
        db_session.commit()
        repo.complete(session.id, all_pass=True, summary="All good", elapsed=12.3)
        db_session.commit()
        updated = repo.get(session.id)
        assert updated.status == "COMPLETED"
        assert updated.overall_status == "PASS"
        assert updated.processing_time_sec == pytest.approx(12.3)

    def test_fail_session(self, db_session):
        repo = SessionRepository(db_session)
        session = repo.create("test.xml")
        db_session.commit()
        repo.fail(session.id, "Some error occurred")
        db_session.commit()
        updated = repo.get(session.id)
        assert updated.status == "FAILED"
        assert "Some error" in updated.error_message

    def test_list_recent(self, db_session):
        repo = SessionRepository(db_session)
        for i in range(5):
            repo.create(f"file_{i}.xml")
        db_session.commit()
        sessions = repo.list_recent(3)
        assert len(sessions) == 3


class TestFileRepository:
    def test_create_file(self, db_session):
        s_repo = SessionRepository(db_session)
        session = s_repo.create("test.xml")
        db_session.commit()

        f_repo = FileRepository(db_session)
        f = f_repo.create(
            session_id=session.id,
            filename="doc.pdf",
            original_name="document.pdf",
            file_path="/tmp/doc.pdf",
            file_size=1024,
            doc_type="driver_license",
            domain="borrower",
        )
        db_session.commit()
        assert f.id is not None
        assert f.doc_type == "driver_license"

    def test_update_ocr(self, db_session):
        s_repo = SessionRepository(db_session)
        session = s_repo.create("test.xml")
        f_repo = FileRepository(db_session)
        f = f_repo.create(session.id, "doc.pdf", "doc.pdf", "/tmp/doc.pdf", 500)
        db_session.commit()

        f_repo.update_ocr(f.id, "extracted text here", is_scan=True, page_count=3)
        db_session.commit()

        updated = db_session.query(UploadedFile).filter(UploadedFile.id == f.id).first()
        assert updated.ocr_text == "extracted text here"
        assert updated.is_image_scan is True
        assert updated.page_count == 3

    def test_update_match(self, db_session):
        s_repo = SessionRepository(db_session)
        session = s_repo.create("test.xml")
        f_repo = FileRepository(db_session)
        f = f_repo.create(session.id, "doc.pdf", "doc.pdf", "/tmp/doc.pdf", 500)
        db_session.commit()

        f_repo.update_match(f.id, "John Doe", 0.95, "Name and address match")
        db_session.commit()

        updated = db_session.query(UploadedFile).filter(UploadedFile.id == f.id).first()
        assert updated.matched_borrower == "John Doe"
        assert updated.match_confidence == pytest.approx(0.95)


class TestValidationRepository:
    def _make_finding(self, field="ssn", xml_val="123", pdf_val="123", matched=True, missing=False):
        from dataclasses import dataclass
        from typing import Any, Optional

        @dataclass
        class MockFinding:
            field_name: str
            xml_value: Any
            pdf_value: Any
            matched: Optional[bool]
            is_missing: bool

        return MockFinding(field, xml_val, pdf_val, matched, missing)

    def test_bulk_create(self, db_session):
        s_repo = SessionRepository(db_session)
        session = s_repo.create("test.xml")
        db_session.commit()

        findings = [
            self._make_finding("first_name", "John", "John", True),
            self._make_finding("last_name", "Doe", "Doh", False),
            self._make_finding("ssn", "123-45-6789", None, None, missing=True),
        ]

        val_repo = ValidationRepository(db_session)
        val_repo.bulk_create_from_findings(session.id, "borrower", "borrower", findings)
        db_session.commit()

        results = val_repo.list_for_session(session.id)
        assert len(results) == 3

    def test_summary(self, db_session):
        s_repo = SessionRepository(db_session)
        session = s_repo.create("test.xml")
        db_session.commit()

        findings = [
            self._make_finding("f1", "a", "a", True),
            self._make_finding("f2", "b", "c", False),
            self._make_finding("f3", "d", None, None, missing=True),
        ]
        val_repo = ValidationRepository(db_session)
        val_repo.bulk_create_from_findings(session.id, "borrower", "borrower", findings)
        db_session.commit()

        summary = val_repo.summary(session.id)
        assert summary["total"] == 3
        assert summary["pass"] == 1
        assert summary["fail"] == 1
        assert summary["missing"] == 1


class TestLogRepository:
    def test_add_and_list(self, db_session):
        s_repo = SessionRepository(db_session)
        session = s_repo.create("test.xml")
        db_session.commit()

        log_repo = LogRepository(db_session)
        log_repo.add(session.id, "borrower", "INFO", "Processing started")
        log_repo.add(session.id, "borrower", "WARNING", "Missing document", {"doc": "license"})
        db_session.commit()

        logs = log_repo.list_for_session(session.id)
        assert len(logs) == 2
        assert logs[0].agent_name == "borrower"
        assert logs[1].level == "WARNING"
        assert logs[1].extra_data == {"doc": "license"}
