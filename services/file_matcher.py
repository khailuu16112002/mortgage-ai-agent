"""
LLM-based file matching service.

Uses LLM + entity extraction to match documents to applicants/records.
Returns structured confidence scores and reasoning.

Examples:
  Driver License ↔ Borrower (Patrick Durst / Rebecca Durst)
  Paystub ↔ Employment record (Rebecca → Employer A)
  Bank Statement ↔ Asset account (...4921)
  W2 ↔ Employment record
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from config import get_settings, get_logger
from pipelines.onnx_inference import get_ner_pipeline

logger = get_logger(__name__)


@dataclass
class MatchResult:
    matched: bool
    confidence: float
    reason: str
    matched_fields: list[str]
    source_doc: str
    target_entity: str


MATCH_SYSTEM_PROMPT = """You are a mortgage document verification specialist.
Your job: determine if a document matches a specific borrower/account/entity.

Analyze the document excerpt and entity profile.
Return ONLY valid JSON (no markdown):
{
  "matched": true|false,
  "confidence": 0.0-1.0,
  "reason": "brief explanation (1-2 sentences)",
  "matched_fields": ["field1", "field2", ...]
}

Rules:
- confidence 0.9-1.0: strong match (name + date/address/number match)
- confidence 0.6-0.9: likely match (name matches, other fields partial)
- confidence 0.3-0.6: weak match (partial name or indirect indicator)
- confidence < 0.3: no match
- matched = confidence >= 0.6"""


def _extract_entities_from_text(text: str) -> dict:
    """Use NER pipeline to extract named entities from document text."""
    try:
        ner = get_ner_pipeline()
        entities = ner.predict(text[:2000])  # limit input length
        grouped: dict[str, list[str]] = {}
        for e in entities:
            grouped.setdefault(e.label, []).append(e.text)
        return {k: list(set(v)) for k, v in grouped.items()}
    except Exception as exc:
        logger.debug(f"NER extraction failed: {exc}")
        return {}


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    return raw.strip()


class FileMatcher:
    """LLM-powered document ↔ entity matching."""

    def __init__(self):
        self.client = OpenAI(api_key=get_settings().llm.openai_api_key)
        self.model = get_settings().llm.default_model

    def match_document_to_borrower(
        self,
        doc_text: str,
        doc_type: str,
        borrower_name: str,
        borrower_dob: str = "",
        borrower_address: str = "",
        source_file: str = "",
    ) -> MatchResult:
        """Match a document to a specific borrower."""
        # Extract entities from doc
        entities = _extract_entities_from_text(doc_text)
        entity_str = json.dumps(entities, ensure_ascii=False)[:500]

        # Truncate document text for context
        doc_excerpt = doc_text[:3000]

        profile = {
            "borrower_name": borrower_name,
            "dob": borrower_dob,
            "address": borrower_address,
        }

        user_prompt = f"""Document type: {doc_type}
Source file: {source_file}

Extracted entities: {entity_str}

Document excerpt:
{doc_excerpt}

---
Borrower profile to match against:
{json.dumps(profile, ensure_ascii=False)}

Does this document belong to/reference this borrower?"""

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=300,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": MATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = _clean_json(resp.choices[0].message.content)
            data = json.loads(raw)
            return MatchResult(
                matched=bool(data.get("matched", False)),
                confidence=float(data.get("confidence", 0.0)),
                reason=data.get("reason", ""),
                matched_fields=data.get("matched_fields", []),
                source_doc=source_file,
                target_entity=borrower_name,
            )
        except Exception as exc:
            logger.warning(f"LLM match failed for {source_file} ↔ {borrower_name}: {exc}")
            # Fallback: simple name check
            name_parts = borrower_name.lower().split()
            text_lower = doc_text.lower()
            found = sum(1 for p in name_parts if p in text_lower)
            confidence = found / max(len(name_parts), 1) * 0.7
            return MatchResult(
                matched=confidence >= 0.6,
                confidence=confidence,
                reason=f"Fallback name check: {found}/{len(name_parts)} name parts found",
                matched_fields=["name"] if found else [],
                source_doc=source_file,
                target_entity=borrower_name,
            )

    def match_bank_statement_to_account(
        self,
        doc_text: str,
        account_id: str,
        holder_name: str,
        expected_balance: float,
        source_file: str = "",
    ) -> MatchResult:
        """Match a bank statement to an account record."""
        account_last4 = account_id.replace("-", "").replace(" ", "")[-4:]

        profile = {
            "account_last4": account_last4,
            "holder_name": holder_name,
            "expected_balance": f"${expected_balance:,.2f}",
        }

        user_prompt = f"""Document type: bank_statement
Source file: {source_file}

Document excerpt:
{doc_text[:2500]}

---
Account to match:
{json.dumps(profile)}

Does this bank statement contain data for this account?"""

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=250,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": MATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = _clean_json(resp.choices[0].message.content)
            data = json.loads(raw)
            return MatchResult(
                matched=bool(data.get("matched", False)),
                confidence=float(data.get("confidence", 0.0)),
                reason=data.get("reason", ""),
                matched_fields=data.get("matched_fields", []),
                source_doc=source_file,
                target_entity=f"Account ...{account_last4} ({holder_name})",
            )
        except Exception as exc:
            logger.warning(f"LLM bank match failed: {exc}")
            # Fallback: last4 check
            found_last4 = account_last4 in doc_text
            found_name = holder_name.split()[-1].lower() in doc_text.lower()
            confidence = (0.5 if found_last4 else 0.0) + (0.3 if found_name else 0.0)
            return MatchResult(
                matched=confidence >= 0.6,
                confidence=confidence,
                reason=f"Fallback: last4={'found' if found_last4 else 'missing'}, name={'found' if found_name else 'missing'}",
                matched_fields=[f for f, ok in [("account_number", found_last4), ("holder_name", found_name)] if ok],
                source_doc=source_file,
                target_entity=f"Account ...{account_last4}",
            )

    def batch_match_files(
        self,
        classified_files: dict,
        borrowers: list,  # list of Borrower dataclass
    ) -> dict[str, MatchResult]:
        """
        Match all files to their most likely borrower.
        Returns {file_path: MatchResult}
        """
        from utils.pdf_reader import read_pdf_smart
        from utils.file_classifier import DocType

        results: dict[str, MatchResult] = {}
        borrower_docs = [
            DocType.DRIVER_LICENSE, DocType.W2, DocType.PAYSTUB, DocType.TAX_RETURN
        ]

        for doc_type_key, files in classified_files.items():
            if doc_type_key not in borrower_docs:
                continue
            for fpath in files:
                try:
                    info = read_pdf_smart(fpath)
                    doc_text = info["text"] if info["mode"] == "text" else f"[Image PDF: {fpath}]"

                    best: MatchResult | None = None
                    for bx in borrowers:
                        result = self.match_document_to_borrower(
                            doc_text=doc_text,
                            doc_type=str(doc_type_key),
                            borrower_name=bx.full_name,
                            borrower_dob=bx.dob,
                            borrower_address=bx.current_address,
                            source_file=fpath,
                        )
                        if best is None or result.confidence > best.confidence:
                            best = result

                    if best:
                        results[fpath] = best
                        logger.info(
                            f"File match: {fpath} → {best.target_entity} "
                            f"(conf={best.confidence:.2f})"
                        )
                except Exception as exc:
                    logger.warning(f"Batch match failed for {fpath}: {exc}")

        return results
