"""
LangGraph pipeline for mortgage document verification.
Integrates with DB persistence via session_id in GraphState.
"""
from langgraph.graph import StateGraph, END
from agents.state import GraphState
from agents.supervisor import supervisor_node
from agents.borrower_agent import borrower_agent_node
from agents.asset_agent import asset_agent_node
from agents.employment_agent import employment_agent_node
from agents.reo_agent import reo_agent_node
from agents.aggregator import aggregator_node


def build_graph() -> StateGraph:
    builder = StateGraph(dict)  # Use dict as underlying state type

    builder.add_node("supervisor", lambda s: vars(supervisor_node(_dict_to_state(s))))
    builder.add_node("borrower", lambda s: vars(borrower_agent_node(_dict_to_state(s))))
    builder.add_node("asset", lambda s: vars(asset_agent_node(_dict_to_state(s))))
    builder.add_node("employment", lambda s: vars(employment_agent_node(_dict_to_state(s))))
    builder.add_node("reo", lambda s: vars(reo_agent_node(_dict_to_state(s))))
    builder.add_node("aggregator", lambda s: vars(aggregator_node(_dict_to_state(s))))

    builder.set_entry_point("supervisor")
    builder.add_edge("supervisor", "borrower")
    builder.add_edge("borrower", "asset")
    builder.add_edge("asset", "employment")
    builder.add_edge("employment", "reo")
    builder.add_edge("reo", "aggregator")
    builder.add_edge("aggregator", END)

    return builder.compile()


def _dict_to_state(d: dict) -> GraphState:
    """Convert dict state to GraphState dataclass."""
    state = GraphState()
    for key, val in d.items():
        if hasattr(state, key):
            setattr(state, key, val)
    return state
