"""
LangGraph Pipeline — Mortgage Verification
Supervisor → Borrower → Asset → Employment → REO → Aggregator
"""
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from agents.state import GraphState
from agents.supervisor import supervisor_node
from agents.borrower_agent import borrower_agent_node
from agents.asset_agent import asset_agent_node
from agents.employment_agent import employment_agent_node
from agents.reo_agent import reo_agent_node
from agents.aggregator import aggregator_node


# LangGraph requires TypedDict state
class GState(TypedDict, total=False):
    xml_path: str
    pdf_dir: str
    baseline: Any
    flat_facts: dict
    classified_files: dict
    borrower_result: Any
    asset_result: Any
    employment_result: Any
    reo_result: Any
    final_report: str
    all_pass: bool


FIELDS = [
    "xml_path", "pdf_dir", "baseline", "flat_facts", "classified_files",
    "borrower_result", "asset_result", "employment_result",
    "reo_result", "final_report", "all_pass",
]


def _wrap(fn):
    """Wrap GraphState-based node functions for LangGraph dict state."""
    def wrapped(state_dict: dict) -> dict:
        gs = GraphState(**{k: state_dict[k] for k in FIELDS if k in state_dict})
        result = fn(gs)
        return {k: getattr(result, k) for k in FIELDS}
    return wrapped


def build_graph():
    builder = StateGraph(GState)

    builder.add_node("supervisor",  _wrap(supervisor_node))
    builder.add_node("borrower",    _wrap(borrower_agent_node))
    builder.add_node("asset",       _wrap(asset_agent_node))
    builder.add_node("employment",  _wrap(employment_agent_node))
    builder.add_node("reo",         _wrap(reo_agent_node))
    builder.add_node("aggregator",  _wrap(aggregator_node))

    builder.set_entry_point("supervisor")
    builder.add_edge("supervisor",  "borrower")
    builder.add_edge("borrower",    "asset")
    builder.add_edge("asset",       "employment")
    builder.add_edge("employment",  "reo")
    builder.add_edge("reo",         "aggregator")
    builder.add_edge("aggregator",  END)

    return builder.compile()
