"""Unit tests for LangGraph agent nodes and routing logic."""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

test_db = Path(tempfile.mkdtemp()) / "aurasaas_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{test_db.as_posix()}"
os.environ["SEED_DEMO_ON_STARTUP"] = "false"
os.environ["DEEPSEEK_API_KEY"] = "sk-placeholder"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["ENVIRONMENT"] = "test"

from app.models.models import AgentApproval, AgentTrace, Store  # noqa: E402
from app.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)


# --- Intent Router Tests -----------------------------------------------------

def test_intent_router_classifies_report_generation():
    from app.agents.graph import intent_router_node, AgentState
    state: AgentState = {"user_query": "生成上周战报", "query": "生成上周战报", "trace_id": "t1", "messages": []}
    result = intent_router_node(state)
    assert result["intent"] == "report_generation"


def test_intent_router_classifies_knowledge_query():
    from app.agents.graph import intent_router_node, AgentState
    state: AgentState = {"user_query": "雨天怎么处理外卖", "query": "雨天怎么处理外卖", "trace_id": "t2", "messages": []}
    result = intent_router_node(state)
    assert result["intent"] == "knowledge_query"


def test_intent_router_classifies_marketing_plan():
    from app.agents.graph import intent_router_node, AgentState
    state: AgentState = {"user_query": "帮我写个营销文案", "query": "帮我写个营销文案", "trace_id": "t3", "messages": []}
    result = intent_router_node(state)
    assert result["intent"] == "marketing_plan"


def test_intent_router_classifies_anomaly_diagnosis():
    from app.agents.graph import intent_router_node, AgentState
    state: AgentState = {"user_query": "为什么退单率上升了", "query": "为什么退单率上升了", "trace_id": "t4", "messages": []}
    result = intent_router_node(state)
    assert result["intent"] == "anomaly_diagnosis"


def test_intent_router_defaults_to_general_chat():
    from app.agents.graph import intent_router_node, AgentState
    state: AgentState = {"user_query": "今天天气不错", "query": "今天天气不错", "trace_id": "t5", "messages": []}
    result = intent_router_node(state)
    assert result["intent"] == "general_chat"


def test_intent_router_routes_sop_campaign_to_marketing_plan():
    from app.agents.graph import intent_router_node, AgentState
    state: AgentState = {
        "user_query": "用我们的 SOP 为最弱门店设计低预算活动",
        "query": "用我们的 SOP 为最弱门店设计低预算活动",
        "trace_id": "t6",
        "messages": [],
    }
    result = intent_router_node(state)
    assert result["intent"] == "marketing_plan"


# --- Graph Routing Tests -----------------------------------------------------

def test_build_graph_has_all_nodes():
    from app.agents.graph import build_graph
    graph = build_graph()
    nodes = list(graph.nodes.keys())
    expected = {"__start__", "intent_router", "data_analyst", "data_editor",
                "fetch_context", "rag_strategist", "risk_controller",
                "human_approval", "copywriter", "general_chat", "report_generator"}
    assert set(nodes) == expected


def test_knowledge_query_skips_data_and_risk():
    from app.agents.graph import build_graph, AgentState
    state: AgentState = {"user_query": "查SOP", "query": "查SOP", "trace_id": "tk",
                         "messages": [], "intent": "knowledge_query"}
    graph = build_graph()
    for output in graph.stream(state):
        node_names = list(output.keys())
        assert "risk_controller" not in node_names
        assert "human_approval" not in node_names
        assert "copywriter" not in node_names


def test_dashboard_query_skips_to_report():
    from app.agents.graph import build_graph, AgentState
    state: AgentState = {"user_query": "看数据", "query": "看数据", "trace_id": "td",
                         "messages": [], "intent": "dashboard_query"}
    graph = build_graph()
    for output in graph.stream(state):
        node_names = list(output.keys())
        assert "fetch_context" not in node_names
        assert "risk_controller" not in node_names
        assert "human_approval" not in node_names


def test_anomaly_diagnosis_runs_full_pipeline():
    from app.agents.graph import build_graph, AgentState
    state: AgentState = {"user_query": "为什么营收下降", "query": "为什么营收下降", "trace_id": "ta",
                         "messages": [], "intent": "anomaly_diagnosis"}
    graph = build_graph()
    nodes_seen = set()
    for output in graph.stream(state):
        nodes_seen.update(output.keys())
    assert "intent_router" in nodes_seen
    assert "report_generator" in nodes_seen


# --- AgentState Tests --------------------------------------------------------

def test_agent_state_default_values():
    from app.agents.graph import AgentState
    state: AgentState = {
        "user_query": "test", "query": "test", "trace_id": "s1", "messages": [],
        "external_context": "", "retrieved_docs": "", "diagnosis": "",
        "data_analysis": "", "strategy": "", "approval_status": "",
        "approval_comment": "", "hitl_proposal": "", "hitl_approved": False,
        "campaign_copy": "", "copy": "", "final_report": "", "current_node": "",
    }
    assert state["external_context"] == ""
    assert state["strategy"] == ""
    assert state["approval_status"] == ""
    assert state["hitl_approved"] is False
    assert state["final_report"] == ""


# --- SSE Streaming Test -----------------------------------------------------

def test_run_agent_stream_yields_events():
    import asyncio
    from app.agents.graph import run_agent_stream

    async def _collect():
        events = []
        async for raw in run_agent_stream("查看经营数据概况"):
            events.append(raw)
            if len(events) >= 3:
                break
        return events

    events = asyncio.run(_collect())
    assert len(events) >= 1
    first = json.loads(events[0])
    assert first["type"] == "agent_start"
    assert "trace_id" in first
