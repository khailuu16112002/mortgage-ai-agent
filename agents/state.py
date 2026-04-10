"""
LangGraph State — 4 domain chính: borrower, assets, employment, real_estate_owned
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationFinding:
    field_name: str
    xml_value: str
    pdf_value: str
    matched: bool
    is_missing: bool = False


@dataclass
class AgentResult:
    domain: str
    status: str = "pending"       # pending | pass | missing | mismatch
    findings: list = field(default_factory=list)   # list[ValidationFinding]
    missing_docs: list = field(default_factory=list)
    mismatches: list = field(default_factory=list)
    notes: list = field(default_factory=list)


@dataclass
class GraphState:
    xml_path: str = ""
    pdf_dir: str = ""

    # Filled by supervisor
    baseline: Any = None
    flat_facts: dict = field(default_factory=dict)
    classified_files: dict = field(default_factory=dict)

    # Filled by each sub-agent
    borrower_result: Any = field(default_factory=lambda: AgentResult("borrower"))
    asset_result: Any = field(default_factory=lambda: AgentResult("assets"))
    employment_result: Any = field(default_factory=lambda: AgentResult("employment"))
    reo_result: Any = field(default_factory=lambda: AgentResult("real_estate_owned"))

    # Final
    final_report: str = ""
    all_pass: bool = False
