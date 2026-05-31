"""Shared state dataclasses for the LangGraph pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any

# Các chuỗi pdf_value được coi là "không đọc được" → is_missing=True
_MISSING_SENTINELS = {
    "", "không đọc được", "không tìm thấy", "not found",
    "n/a", "none", "missing", "no data",
}


def make_finding(
    field_name: str,
    xml_value: Any,
    pdf_value: Any,
    matched: Optional[bool],
    force_missing: bool = False,
) -> "ValidationFinding":
    """
    Tạo ValidationFinding với logic phân biệt FAIL vs MISSING:
    - MISSING: pdf_value trống / không đọc được, hoặc force_missing=True
    - FAIL:    đọc được nhưng không khớp xml_value
    - PASS:    matched=True
    """
    pdf_str = str(pdf_value).strip().lower() if pdf_value is not None else ""
    is_missing = force_missing or (pdf_str in _MISSING_SENTINELS)
    # Nếu is_missing thì không tính là fail
    if is_missing:
        matched = None   # không rõ → không thể xét pass/fail
    return ValidationFinding(field_name, xml_value, pdf_value, matched, is_missing)


@dataclass
class ValidationFinding:
    field_name: str
    xml_value: Any
    pdf_value: Any
    matched: Optional[bool]
    is_missing: bool = False


@dataclass
class AgentResult:
    domain: str
    status: str = "pending"
    findings: list[ValidationFinding] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    missing_docs: list[str] = field(default_factory=list)
    # Files cụ thể cần user upload lại (tên file + lý do)
    files_to_reupload: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class GraphState:
    xml_path: str = ""
    pdf_dir: str = ""
    session_id: Optional[str] = None
    baseline: Any = None
    flat_facts: dict = field(default_factory=dict)
    classified_files: dict = field(default_factory=dict)
    all_chunks: dict = field(default_factory=dict)
    file_match_results: dict = field(default_factory=dict)
    borrower_result: Optional[AgentResult] = None
    asset_result: Optional[AgentResult] = None
    employment_result: Optional[AgentResult] = None
    reo_result: Optional[AgentResult] = None
    final_report: str = ""
    all_pass: bool = False
    # Danh sách file cần upload lại (tổng hợp từ tất cả agents)
    missing_files_summary: list[dict] = field(default_factory=list)
