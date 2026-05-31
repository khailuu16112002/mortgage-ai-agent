"""Integration tests for FastAPI endpoints."""
import io
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Use in-memory SQLite for tests
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["OPENAI_API_KEY"] = "test-key"

from api.main import app
from database import create_tables

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    create_tables()
    yield


class TestHealth:
    def test_health_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestSessions:
    def test_list_sessions_empty(self):
        r = client.get("/sessions")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_results_not_found(self):
        r = client.get("/results/nonexistent-session-id")
        assert r.status_code == 404

    def test_logs_not_found(self):
        r = client.get("/logs/nonexistent-session-id")
        assert r.status_code == 404


class TestUpload:
    def _make_xml(self) -> bytes:
        return b"""<?xml version="1.0"?>
<MISMO_VERSION_3_4>
  <DEAL_SETS>
    <DEAL_SET>
      <DEALS>
        <DEAL>
          <PARTIES>
            <PARTY><INDIVIDUAL><NAME><FirstName>John</FirstName><LastName>Doe</LastName></NAME></INDIVIDUAL></PARTY>
          </PARTIES>
        </DEAL>
      </DEALS>
    </DEAL_SET>
  </DEAL_SETS>
</MISMO_VERSION_3_4>"""

    def _make_pdf(self) -> bytes:
        return b"%PDF-1.4 fake pdf content for testing"

    def test_upload_creates_session(self):
        xml_bytes = self._make_xml()
        pdf_bytes = self._make_pdf()

        r = client.post(
            "/upload",
            files=[
                ("xml_file", ("test.xml", io.BytesIO(xml_bytes), "application/xml")),
                ("pdf_files", ("license.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ],
        )
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        assert data["pdf_count"] == 1
        return data["session_id"]

    def test_upload_missing_xml(self):
        """Upload without XML should fail."""
        pdf_bytes = self._make_pdf()
        r = client.post(
            "/upload",
            files=[
                ("pdf_files", ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ],
        )
        assert r.status_code == 422  # Validation error

    def test_process_nonexistent_session(self):
        r = client.post("/process", json={"session_id": "nonexistent"})
        assert r.status_code == 404

    def test_process_existing_session(self):
        # First upload
        xml_bytes = self._make_xml()
        pdf_bytes = self._make_pdf()
        upload_r = client.post(
            "/upload",
            files=[
                ("xml_file", ("test.xml", io.BytesIO(xml_bytes), "application/xml")),
                ("pdf_files", ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ],
        )
        session_id = upload_r.json()["session_id"]

        # Then process (background task won't fully run in test)
        r = client.post("/process", json={"session_id": session_id})
        assert r.status_code == 200
        assert "session_id" in r.json()

    def test_results_after_upload(self):
        """Results endpoint works even before processing completes."""
        xml_bytes = self._make_xml()
        pdf_bytes = self._make_pdf()
        upload_r = client.post(
            "/upload",
            files=[
                ("xml_file", ("test.xml", io.BytesIO(xml_bytes), "application/xml")),
                ("pdf_files", ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ],
        )
        session_id = upload_r.json()["session_id"]
        r = client.get(f"/results/{session_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == session_id
        assert "summary" in data

    def test_chunks_endpoint(self):
        xml_bytes = self._make_xml()
        pdf_bytes = self._make_pdf()
        upload_r = client.post(
            "/upload",
            files=[
                ("xml_file", ("test.xml", io.BytesIO(xml_bytes), "application/xml")),
                ("pdf_files", ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ],
        )
        session_id = upload_r.json()["session_id"]
        r = client.get(f"/chunks/{session_id}")
        assert r.status_code == 200
        assert "chunks" in r.json()
