"""Unit tests for the file matching service."""
import pytest
from unittest.mock import patch, MagicMock
from services.file_matcher import FileMatcher, MatchResult


class TestMatchResult:
    def test_creation(self):
        r = MatchResult(
            matched=True,
            confidence=0.92,
            reason="Name and address match",
            matched_fields=["name", "address"],
            source_doc="license.pdf",
            target_entity="John Doe",
        )
        assert r.matched is True
        assert r.confidence == pytest.approx(0.92)
        assert "name" in r.matched_fields


class TestFileMatcher:
    @patch("services.file_matcher.OpenAI")
    @patch("services.file_matcher.get_ner_pipeline")
    def test_match_borrower_success(self, mock_ner, mock_openai_cls):
        # Mock NER pipeline
        mock_ner.return_value.predict.return_value = []

        # Mock OpenAI response
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"matched": true, "confidence": 0.95, "reason": "Name found", "matched_fields": ["name"]}'))]
        )

        matcher = FileMatcher()
        result = matcher.match_document_to_borrower(
            doc_text="DRIVER LICENSE: JOHN DOE, DOB: 01/15/1980",
            doc_type="driver_license",
            borrower_name="John Doe",
            source_file="license.pdf",
        )

        assert result.matched is True
        assert result.confidence == pytest.approx(0.95)
        assert result.source_doc == "license.pdf"

    @patch("services.file_matcher.OpenAI")
    @patch("services.file_matcher.get_ner_pipeline")
    def test_match_borrower_fallback_on_error(self, mock_ner, mock_openai_cls):
        """When LLM fails, fallback to regex name check."""
        mock_ner.return_value.predict.side_effect = Exception("NER error")
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("LLM unavailable")

        matcher = FileMatcher()
        result = matcher.match_document_to_borrower(
            doc_text="This document references John Doe at 123 Main St",
            doc_type="driver_license",
            borrower_name="John Doe",
            source_file="license.pdf",
        )

        # Fallback should still return a result
        assert isinstance(result, MatchResult)
        assert 0.0 <= result.confidence <= 1.0

    @patch("services.file_matcher.OpenAI")
    @patch("services.file_matcher.get_ner_pipeline")
    def test_match_bank_statement(self, mock_ner, mock_openai_cls):
        mock_ner.return_value.predict.return_value = []
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"matched": true, "confidence": 0.88, "reason": "Account last4 and holder name found", "matched_fields": ["account_number", "holder_name"]}'))]
        )

        matcher = FileMatcher()
        result = matcher.match_bank_statement_to_account(
            doc_text="Account ending in 4921. Holder: Jane Doe. Balance: $12,400.00",
            account_id="XXXX-4921",
            holder_name="Jane Doe",
            expected_balance=12400.00,
            source_file="bank_stmt.pdf",
        )

        assert result.matched is True
        assert result.confidence >= 0.8

    @patch("services.file_matcher.OpenAI")
    @patch("services.file_matcher.get_ner_pipeline")
    def test_no_match_low_confidence(self, mock_ner, mock_openai_cls):
        mock_ner.return_value.predict.return_value = []
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"matched": false, "confidence": 0.1, "reason": "Name not found", "matched_fields": []}'))]
        )

        matcher = FileMatcher()
        result = matcher.match_document_to_borrower(
            doc_text="This is a completely unrelated document about car insurance.",
            doc_type="driver_license",
            borrower_name="Patrick Durst",
            source_file="unrelated.pdf",
        )

        assert result.matched is False
        assert result.confidence < 0.6
