"""LangGraph multi-agent workflow with RAG, HITL, SSE and trace persistence."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import queue as thread_queue
import threading
import time
import uuid
from typing import TypedDict
try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired
from langgraph.graph import StateGraph, END
from openai import OpenAI
from app.agents.tools import (
    add_product,
    add_staff_member,
    add_store_metric,
    tool_result,
    analyze_sku_trends,
    check_external_context,
    compare_periods,
    create_anomaly_tasks,
    detect_business_anomalies,
    evaluate_strategy_risk,
    fetch_cost_anomalies,
    forecast_metric,
    generate_campaign_copy,
    generate_marketing_strategy,
    rank_stores,
    save_agent_memory,
    search_agent_memory,
    search_products,
    get_store_detail,
    get_daily_summary,
    calculate_roi,
    list_all_stores,
)
from app.core.config import get_settings
from app.database import SessionLocal
from app.models.models import AgentApproval, AgentMemory, AgentTrace
from app.services.rag_service import query_knowledge
from app.services.deepseek_client import chat as llm_chat, has_valid_api_key


class AgentState(TypedDict):
    user_query: str
    query: str
    trace_id: str
    store_id: NotRequired[int | None]
    date_range: NotRequired[dict]
    intent: NotRequired[str]
    metrics: NotRequired[dict]
    anomalies: NotRequired[list]
    external_context: str
    retrieved_docs: str
    rag_references: NotRequired[list]
    diagnosis: str
    data_analysis: str
    strategy: str
    risk_assessment: NotRequired[dict]
    approval_status: str
    approval_comment: str
    approval_id: NotRequired[int | None]
    hitl_proposal: str
    hitl_approved: bool
    campaign_copy: str
    copy: str
    execution_result: NotRequired[dict]
    final_report: str
    messages: list
    current_node: str


settings = get_settings()


def _append_message(state: AgentState, node: str, content: str) -> list:
    return [*state.get("messages", []), {"node": node, "content": content, "time": datetime.datetime.now().isoformat()}]


def intent_router_node(state: AgentState) -> dict:
    """Node 0: LLM-based intent classification with tool matching."""

    query = state["query"]

    system = """你是 AuraSaaS 智能助手的路由分析器。分析用户意图，严格返回 JSON：

{
  "intent": "general_chat|data_query|anomaly_diagnosis|knowledge_query|marketing_plan|data_management|report_generation",
  "tools_needed": ["tool_name"],
  "reasoning": "简短分析"
}

intent 说明：
- general_chat: 闲聊、问候、不需要数据/工具的对话
- data_query: 查询数据，如"今天营收"、"门店排行"、"搜索商品"、"日报"、"门店详情"
- anomaly_diagnosis: 分析异常，如"为什么下降"、"退款异常"、"毛利问题"
- knowledge_query: 知识查询，如"SOP"、"流程"、"怎么处理"、"规范"
- marketing_plan: 营销方案，如"营销"、"活动"、"文案"、"推广"、"方案"
- data_management: 数据录入，如"添加商品"、"新增员工"、"录入数据"、"修改"
- report_generation: 生成报告，如"战报"、"报表"、"总结"、"周报"

可用工具：
- get_daily_summary: 查询某天/某店的营收、订单、热卖商品
- get_store_detail: 查询门店详细信息(员工数、店长、评分、今日营收)
- search_products: 搜索商品(按名称/类别模糊搜索)
- rank_stores: 门店排行榜(按营收/利润/订单排名)
- forecast_metric: 营收/利润预测(未来N天)
- compare_periods: 周期环比对比(本周vs上周)
- calculate_roi: 营销ROI计算(投入vs产出)
- list_all_stores: 列出所有门店及近7天营收
- retrieve_knowledge: 搜索SOP知识库
- detect_anomalies: 异常检测(营收下滑、退款飙升)
- add_product/add_staff/add_metric: 数据录入

选择规则：如果用户问题不需要工具(intent=general_chat)，tools_needed 为空数组。
如果不是 general_chat，根据问题选择最相关的 1-3 个工具。只返回 JSON，不要其他文字。"""

    if has_valid_api_key():
        try:
            raw = llm_chat(
                system,
                f"用户输入: {query}",
                "",  # no fallback — if LLM fails, fall through to keyword
                temperature=0.1,
                max_tokens=300,
            )
            if raw:
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                    if raw.endswith("```"):
                        raw = raw[:-3]
                parsed = json.loads(raw.strip())
            else:
                raise ValueError("empty response")
        except (json.JSONDecodeError, ValueError, Exception):
            parsed = _keyword_intent(query)
    else:
        parsed = _keyword_intent(query)

    intent = parsed.get("intent", "general_chat")
    tools = parsed.get("tools_needed", [])
    reasoning = parsed.get("reasoning", "")

    return {
        "intent": intent,
        "tools_needed": tools,
        "current_node": "intent_router",
        "messages": _append_message(state, "intent_router",
            f"意图：{intent} | 工具：{', '.join(tools) or '无'} | {reasoning}"),
    }


def _keyword_intent(query: str) -> dict:
    """Fallback keyword-based intent classification when LLM is unavailable."""
    q = query.lower()
    if any(w in q for w in ["添加", "增加", "新增", "录入", "删除", "修改"]):
        return {"intent": "data_management", "tools_needed": [], "reasoning": "keyword:data"}
    if any(w in q for w in ["报表", "战报", "总结", "报告"]):
        return {"intent": "report_generation", "tools_needed": [], "reasoning": "keyword:report"}
    if any(w in q for w in ["营销", "活动", "文案", "推广", "方案"]):
        return {"intent": "marketing_plan", "tools_needed": [], "reasoning": "keyword:marketing"}
    if any(w in q for w in ["下降", "异常", "退单", "退款", "毛利", "为什么"]):
        return {"intent": "anomaly_diagnosis", "tools_needed": ["detect_anomalies", "compare_periods"], "reasoning": "keyword:anomaly"}
    if any(w in q for w in ["sop", "知识", "流程", "怎么处理", "规范"]):
        return {"intent": "knowledge_query", "tools_needed": ["retrieve_knowledge"], "reasoning": "keyword:knowledge"}
    if any(w in q for w in ["排行", "排名", "门店", "详情", "日报", "搜索", "商品", "营收", "订单", "概况"]):
        return {"intent": "data_query", "tools_needed": [], "reasoning": "keyword:data"}
    return {"intent": "general_chat", "tools_needed": [], "reasoning": "keyword:chat"}


def data_analyst_node(state: AgentState) -> dict:
    """Node 1: Analyze metrics, anomalies, forecasts, comparisons, and auto-create tasks."""

    store_id = state.get("store_id")
    sku_report = analyze_sku_trends(7, store_id=store_id)
    cost_report = fetch_cost_anomalies(store_id=store_id)
    anomaly_result = detect_business_anomalies(store_id=store_id, days=7)
    anomaly_text = json.dumps(anomaly_result.get("data", []), ensure_ascii=False, indent=2)

    # --- new: forecast, comparison, ranking, anomaly-to-task ---
    forecast = forecast_metric("revenue", store_id=store_id)
    comparison = compare_periods(store_id=store_id, metric="revenue")
    ranking = rank_stores("revenue", top_n=3)
    tasks_created = create_anomaly_tasks(store_id=store_id)

    forecast_text = json.dumps(forecast.get("data", {}), ensure_ascii=False, indent=2)
    comparison_text = json.dumps(comparison.get("data", {}), ensure_ascii=False, indent=2)
    ranking_text = json.dumps(ranking.get("data", []), ensure_ascii=False, indent=2)
    tasks_text = json.dumps(tasks_created.get("data", {}), ensure_ascii=False, indent=2)

    fallback = (
        "数据诊断：近 7 天发现以下重点信号：\n"
        f"{anomaly_text}\n\n"
        "SKU 趋势与成本异常已获取，供后续策略节点参考。"
    )
    analysis = llm_chat(
        "你是经营分析师。根据 BI 数据，简洁总结关键发现（参数变化、退款趋势、高退款 SKU、毛利变化、外卖占比变化），150字内。",
        f"近7天数据分析：\n异常：{anomaly_text}\nSKU报告：{json.dumps(sku_report, ensure_ascii=False, indent=2)}\n成本异常：{json.dumps(cost_report, ensure_ascii=False, indent=2)}",
        fallback,
        temperature=0.3,
        max_tokens=500,
    )
    return {
        "data_analysis": analysis,
        "diagnosis": analysis,
        "anomalies": anomaly_result.get("data", []),
        "metrics": {
            "forecast": forecast.get("data"),
            "comparison": comparison.get("data"),
            "ranking": ranking.get("data"),
            "tasks_created": tasks_created.get("data"),
        },
        "current_node": "data_analyst",
        "messages": _append_message(state, "data_analyst", analysis),
    }


def fetch_external_context_node(state: AgentState) -> dict:
    """Node 2: Collect external factors."""

    store_id = state.get("store_id")
    context = check_external_context(store_id=store_id)
    return {
        "external_context": context,
        "current_node": "fetch_context",
        "messages": _append_message(state, "fetch_context", context),
    }


def rag_strategist_node(state: AgentState) -> dict:
    """Node 3: RAG lookup and strategic recommendation."""

    docs = query_knowledge(state["query"] + " " + state.get("data_analysis", ""))
    references = [
        {
            "title": doc.get("title", "Untitled"),
            "source": doc.get("source", ""),
            "snippet": doc.get("snippet", "")[:220],
            "score": doc.get("score"),
        }
        for doc in docs
    ]
    snippets = "\n".join(
        f"- {doc.get('title', 'Untitled')}: {doc.get('snippet', '')[:280]}"
        for doc in docs
    ) or "未找到相关 SOP 文档。"
    strategy = llm_chat(
        "你是经营策略专家。根据数据诊断和 SOP 知识，给出1-3条可执行策略建议（含量化预期）。",
        f"问题: {state['query']}\n诊断: {state.get('data_analysis', '')}\nSOP参考:\n{snippets}",
        "策略建议：基于诊断数据和 SOP 知识，建议执行低门槛定向营销并结合高毛利套餐推广。",
        temperature=0.3,
        max_tokens=500,
    )
    risk_result = evaluate_strategy_risk({"budget": 2000})
    return {
        "strategy": strategy,
        "retrieved_docs": snippets,
        "rag_references": references,
        "risk_assessment": risk_result.get("data", {}),
        "current_node": "rag_strategist",
        "messages": _append_message(state, "rag_strategist", strategy),
    }


def risk_controller_node(state: AgentState) -> dict:
    """Node 4: Mark approval requirement."""

    risk = state.get("risk_assessment") or {"risk_level": "medium", "requires_approval": True}
    summary = f"风险等级：{risk.get('risk_level', 'medium')}；是否需要审批：{risk.get('requires_approval', True)}"
    return {
        "risk_assessment": risk,
        "current_node": "risk_controller",
        "messages": _append_message(state, "risk_controller", summary),
    }


def hitl_node(state: AgentState) -> dict:
    """Node 5: Human-in-the-loop approval task creation."""

    proposal = llm_chat(
        "根据策略方案，生成一个简洁审批提案。包含策略摘要、预估成本、预期收益，100字以内。",
        f"策略方案:\n{state['strategy']}",
        "审批提案：建议上线低预算定向券和高毛利套餐，预估成本 2000 元内，目标提升订单 8%-15%，需店长确认后执行。",
        temperature=0.3,
        max_tokens=220,
    )

    db = SessionLocal()
    approval_id = None
    try:
        approval = AgentApproval(
            session_id=f"session_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
            trace_id=state["trace_id"],
            node_name="human_approval",
            proposal=proposal,
            estimated_cost=2000,
            status="pending",
        )
        db.add(approval)
        db.commit()
        approval_id = approval.id
    finally:
        db.close()

    content = json.dumps({"approval_id": approval_id, "proposal": proposal}, ensure_ascii=False)
    return {
        "hitl_proposal": proposal,
        "approval_status": "pending",
        "approval_id": approval_id,
        "hitl_approved": False,
        "current_node": "human_approval",
        "messages": _append_message(state, "human_approval", content),
    }


def copywriter_node(state: AgentState) -> dict:
    """Node 6: Generate campaign copy."""

    strategy_payload = {"name": "AI 经营改善活动", "target": "提升订单并控制毛利风险", "budget": 2000, "store_id": state.get("store_id") or 1}
    copy_payload = generate_campaign_copy(strategy_payload, tone="friendly").get("data", {})
    fallback = json.dumps(copy_payload, ensure_ascii=False, indent=2)
    copy = llm_chat(
        "你是门店营销文案专家。根据策略生成短信、小程序 Push、公众号、外卖平台标题、员工话术，输出 JSON。",
        f"策略:\n{state['strategy']}\n\n问题: {state['query']}",
        fallback,
        temperature=0.6,
        max_tokens=800,
    )
    return {
        "campaign_copy": copy,
        "copy": copy,
        "current_node": "copywriter",
        "messages": _append_message(state, "copywriter", copy),
    }


def report_generator_node(state: AgentState) -> dict:
    """Node 7: Final report with quantified insights and actionable next steps."""

    references = "\n".join(
        f"- {doc.get('title', 'Untitled')} ({doc.get('source', '')})"
        for doc in state.get("rag_references", [])
    ) or state.get("retrieved_docs", "")[:1200]

    # --- enrich with forecast, comparison, ranking ---
    metrics = state.get("metrics", {})
    forecast_block = ""
    if metrics.get("forecast"):
        f = metrics["forecast"]
        forecast_block = (
            f"\n## 营收预测\n"
            f"近30天历史均值：{f.get('historical_avg', 'N/A')} 元\n"
            f"近7天均值：{f.get('recent_avg', 'N/A')} 元\n"
            f"趋势：{f.get('trend_pct', 0):.1f}%\n"
            f"未来7天预测：{json.dumps(f.get('forecast', []), ensure_ascii=False)}\n"
        )

    comparison_block = ""
    if metrics.get("comparison"):
        c = metrics["comparison"]
        comparison_block = (
            f"\n## 周期对比（本周 vs 上周）\n"
            f"本周：{c.get('current_value', 'N/A')} | 上周：{c.get('previous_value', 'N/A')}\n"
            f"变化：{c.get('change_pct', 0):+.1f}% ({c.get('direction', 'flat')})\n"
        )

    ranking_block = ""
    if metrics.get("ranking"):
        ranking_block = "\n## 门店排行 TOP3\n" + "\n".join(
            f"{r.get('rank')}. {r.get('name')} ({r.get('city')}): {r.get('value')} 元"
            for r in metrics["ranking"]
        )

    tasks_block = ""
    tasks = metrics.get("tasks_created") or {}
    if tasks.get("tasks_created", 0) > 0:
        tasks_block = f"\n## 自动告警\n已生成 {tasks['tasks_created']} 条待处理任务，请前往 Dashboard 查看。\n"

    report = (
        "# AuraSaaS 经营诊断报告\n\n"
        f"## 用户问题\n{state['query']}\n\n"
        f"## 数据诊断\n{state.get('diagnosis', '')}\n"
        f"## 外部因素\n{state.get('external_context', '')}\n"
        f"## SOP 引用\n{references}\n"
        f"{forecast_block}"
        f"{comparison_block}"
        f"{ranking_block}"
        f"{tasks_block}"
        f"## 策略建议\n{state.get('strategy', '')}\n\n"
        f"## 风险与审批\n{json.dumps(state.get('risk_assessment', {}), ensure_ascii=False)}\n\n"
        f"## 可执行下一步\n"
        f"1. 审批通过后，系统将自动创建营销活动草稿\n"
        f"2. 将策略任务分配给对应门店店长\n"
        f"3. 每2小时复盘订单、退单和毛利表现\n"
        f"4. 3天后复诊，对比策略效果数据\n\n"
        f"## 营销文案\n{state.get('campaign_copy', '')}\n"
    )

    return {
        "final_report": report,
        "current_node": "report_generator",
        "messages": _append_message(state, "report_generator", report),
    }



def data_editor_node(state: AgentState) -> dict:
    """Node for data CRUD: parse natural language, call tools, return result."""
    query = state["query"]
    store_id = state.get("store_id") or 1

    # Use LLM to extract structured data from natural language
    system = """你是一个数据录入助手。从用户输入中提取结构化数据，返回JSON。
支持的操作：add_product, add_staff, add_store_metric

add_product 需要: {"action":"add_product","data":{"sku_name":"...","category":"...","price":...,"cost":...,"store_id":...}}
add_staff 需要: {"action":"add_staff","data":{"name":"...","phone":"...","role":"...","store_id":...}}
add_store_metric 需要: {"action":"add_store_metric","data":{"store_id":...,"date":"...","revenue":...,"order_count":...}}

只返回JSON，不要其他文字。"""
    
    result_json = llm_chat(
        system,
        f"用户输入: {query}\n门店ID: {store_id}",
        json.dumps({"action": "unknown", "data": {}, "message": "无法解析，请用'添加商品 名称 XX 价格 XX'的格式"}),
        temperature=0.1,
        max_tokens=500,
    )

    try:
        parsed = json.loads(result_json)
    except json.JSONDecodeError:
        parsed = {"action": "unknown", "data": {}, "message": result_json[:200]}

    action = parsed.get("action", "unknown")
    data = parsed.get("data", {})

    result = tool_result(False, error="不支持的操作")
    if action == "add_product":
        result = add_product(data)
    elif action == "add_staff":
        result = add_staff_member(data)
    elif action == "add_store_metric":
        result = add_store_metric(data)

    success = result.get("success", False)
    content = json.dumps(result, ensure_ascii=False)
    if success:
        summary = f"✅ 已{action}: {json.dumps(result.get('data', {}), ensure_ascii=False)}"
    else:
        summary = f"❌ 操作失败: {result.get('error', '未知错误')}"

    return {
        "current_node": "data_editor",
        "final_report": summary,
        "messages": _append_message(state, "data_editor", summary),
    }



def general_chat_node(state: AgentState) -> dict:
    """Node for general conversation — direct LLM answer without tools."""
    query = state["query"]
    answer = llm_chat(
        "你是AuraSaaS的AI经营助手。友好简洁地回答用户问题。如果用户问你是谁，介绍自己是AuraSaaS的智能经营助手。",
        query,
        f"你好！我是 AuraSaaS 的 AI 经营助手，可以帮你分析门店数据、诊断异常、制定营销策略、查询 SOP 知识库。有什么可以帮你的？",
        temperature=0.7,
        max_tokens=400,
    )
    return {
        "final_report": answer,
        "current_node": "general_chat",
        "messages": _append_message(state, "general_chat", answer),
    }


def build_graph():
    """Build the LangGraph StateGraph with conditional routing based on intent."""

    graph = StateGraph(AgentState)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("data_analyst", data_analyst_node)
    graph.add_node("fetch_context", fetch_external_context_node)
    graph.add_node("rag_strategist", rag_strategist_node)
    graph.add_node("risk_controller", risk_controller_node)
    graph.add_node("human_approval", hitl_node)
    graph.add_node("copywriter", copywriter_node)
    graph.add_node("data_editor", data_editor_node)
    graph.add_node("general_chat", general_chat_node)
    graph.add_node("report_generator", report_generator_node)

    graph.set_entry_point("intent_router")

    def route_after_intent(state: AgentState) -> str:
        """Route based on intent: knowledge->RAG, data_mgmt->editor, else->data."""
        intent = state.get("intent")
        if intent == "knowledge_query":
            return "rag_strategist"
        if intent == "data_management":
            return "data_editor"
        if intent == "general_chat":
            return "general_chat"
        return "data_analyst"

    def route_after_data(state: AgentState) -> str:
        """dashboard_query skips to report; anomaly/marketing/report continue full pipeline."""
        return "report_generator" if state.get("intent") == "dashboard_query" else "fetch_context"

    def route_after_rag(state: AgentState) -> str:
        """knowledge_query done after RAG; others need risk review."""
        return "report_generator" if state.get("intent") == "knowledge_query" else "risk_controller"

    def route_after_risk(state: AgentState) -> str:
        """Lightweight intents skip HITL approval."""
        if state.get("intent") in ("knowledge_query", "dashboard_query"):
            return "report_generator"
        return "human_approval"

    graph.add_conditional_edges("intent_router", route_after_intent, {
        "data_analyst": "data_analyst",
        "data_editor": "data_editor",
        "rag_strategist": "rag_strategist",
        "general_chat": "general_chat",
    })
    graph.add_conditional_edges("data_analyst", route_after_data, {
        "fetch_context": "fetch_context",
        "report_generator": "report_generator",
    })
    graph.add_edge("fetch_context", "rag_strategist")
    graph.add_conditional_edges("rag_strategist", route_after_rag, {
        "risk_controller": "risk_controller",
        "report_generator": "report_generator",
    })
    graph.add_conditional_edges("risk_controller", route_after_risk, {
        "human_approval": "human_approval",
        "report_generator": "report_generator",
    })
    graph.add_edge("human_approval", "copywriter")
    graph.add_edge("copywriter", "report_generator")
    graph.add_edge("data_editor", END)
    graph.add_edge("general_chat", END)
    graph.add_edge("report_generator", END)
    return graph.compile()


def _create_trace(trace_id: str, query: str, store_id: int | None):
    db = SessionLocal()
    try:
        trace = AgentTrace(trace_id=trace_id, user_query=query, store_id=store_id, status="running", steps_json="[]")
        db.add(trace)
        db.commit()
    finally:
        db.close()


def _finish_trace(trace_id: str, steps: list[dict], final_answer: str, status: str = "completed"):
    db = SessionLocal()
    try:
        trace = db.query(AgentTrace).filter(AgentTrace.trace_id == trace_id).first()
        if trace:
            trace.steps_json = json.dumps(steps, ensure_ascii=False)
            trace.final_answer = final_answer
            trace.status = status
            trace.updated_at = datetime.datetime.now()
            db.commit()
    finally:
        db.close()


def _sse(data: dict) -> str:
    """Return JSON string — EventSourceResponse adds the 'data:' prefix automatically."""
    return json.dumps(data, ensure_ascii=False)


async def run_agent_stream(query: str, store_id: int | None = None, start_date: str | None = None, end_date: str | None = None):
    """Yield SSE events as the graph executes each node — true streaming via async queue."""

    trace_id = str(uuid.uuid4())
    _create_trace(trace_id, query, store_id)
    yield _sse({"type": "agent_start", "trace_id": trace_id, "node": "agent", "title": "Agent 启动", "content": query, "done": False})

    app_graph = build_graph()
    initial_state: AgentState = {
        "user_query": query,
        "query": query,
        "trace_id": trace_id,
        "store_id": store_id,
        "date_range": {"start_date": start_date, "end_date": end_date},
        "intent": "",
        "metrics": {},
        "anomalies": [],
        "external_context": "",
        "retrieved_docs": "",
        "rag_references": [],
        "diagnosis": "",
        "data_analysis": "",
        "strategy": "",
        "risk_assessment": {},
        "approval_status": "",
        "approval_comment": "",
        "approval_id": None,
        "hitl_proposal": "",
        "hitl_approved": False,
        "campaign_copy": "",
        "copy": "",
        "execution_result": {},
        "final_report": "",
        "messages": [],
        "current_node": "",
    }

    queue = thread_queue.Queue()

    def _run_graph():
        """Run LangGraph stream in a thread, pushing each node result to the queue."""
        try:
            for output in app_graph.stream(initial_state):
                for node_name, node_output in output.items():
                    queue.put((node_name, node_output))
        except Exception as exc:
            queue.put(("__error__", {"error": str(exc)}))
        finally:
            queue.put(None)

    thread = threading.Thread(target=_run_graph, daemon=True)
    thread.start()

    trace_steps = []
    final_state = initial_state

    try:
        while True:
            item = await asyncio.to_thread(queue.get)
            if item is None:
                break

            if isinstance(item, tuple) and item[0] == "__error__":
                error_msg = item[1].get("error", "Unknown error")
                _finish_trace(trace_id, trace_steps, str(error_msg), status="failed")
                yield _sse({"type": "error", "trace_id": trace_id, "node": "error", "done": True, "content": error_msg})
                thread.join(timeout=5)
                return

            node_name, node_output = item
            if not isinstance(node_output, dict):
                node_output = {}
            final_state = {**final_state, **node_output}
            node_started = time.perf_counter()
            yield _sse({"type": "node_start", "trace_id": trace_id, "node": node_name, "title": f"开始：{node_name}", "content": "", "done": False})

            if node_name == "intent_router":
                event = {"type": "thinking", "title": "🧭 意图识别", "content": f"识别为：{node_output.get('intent', '')}"}
            elif node_name == "data_analyst":
                event = {"type": "tool_result", "title": "📊 数据分析", "content": node_output.get("data_analysis", ""), "anomalies": node_output.get("anomalies", [])}
            elif node_name == "fetch_context":
                event = {"type": "tool_result", "title": "🌦 外部环境", "content": node_output.get("external_context", "")}
            elif node_name == "rag_strategist":
                # Single combined event instead of two separate yields
                event = {
                    "type": "rag_reference",
                    "title": "📚 SOP 引用 & 🎯 策略规划",
                    "content": node_output.get("strategy", ""),
                    "strategy": node_output.get("strategy", ""),
                    "retrieved_docs": node_output.get("retrieved_docs", ""),
                    "references": node_output.get("rag_references", []),
                }
            elif node_name == "risk_controller":
                event = {"type": "thinking", "title": "🛡 风险评估", "content": json.dumps(node_output.get("risk_assessment", {}), ensure_ascii=False)}
            elif node_name == "human_approval":
                event = {"type": "approval_required", "title": "⏸ 等待审批", "content": node_output.get("hitl_proposal", ""), "approval_needed": True, "approval_id": node_output.get("approval_id"), "estimated_cost": 2000}
            elif node_name == "copywriter":
                event = {"type": "thinking", "title": "✍️ 营销文案", "content": node_output.get("copy", "")}
            elif node_name == "data_editor":
                event = {"type": "tool_result", "title": "📝 数据操作", "content": node_output.get("final_report", ""), "done": True}
            elif node_name == "report_generator":
                event = {"type": "final_answer", "title": "✅ 最终报告", "content": node_output.get("final_report", ""), "done": True}
            elif node_name == "general_chat":
                event = {"type": "final_answer", "title": "直接回答", "content": node_output.get("final_report", ""), "done": True}
            else:
                event = {"type": "thinking", "title": node_name, "content": json.dumps(node_output, ensure_ascii=False)}

            event.update({"trace_id": trace_id, "node": node_name, "done": event.get("done", False)})
            event["duration_ms"] = round((time.perf_counter() - node_started) * 1000, 2)
            trace_steps.append({
                "node": node_name,
                "event": event,
                "input_summary": query[:180],
                "time": datetime.datetime.now().isoformat(),
                "duration_ms": event["duration_ms"],
            })
            yield _sse(event)

        thread.join(timeout=10)

        final_answer = final_state.get("final_report") or final_state.get("copy") or final_state.get("strategy") or ""
        _finish_trace(trace_id, trace_steps, final_answer)
        yield _sse({"type": "end", "trace_id": trace_id, "node": "end", "done": True, "content": ""})
    except Exception as exc:
        _finish_trace(trace_id, trace_steps, str(exc), status="failed")
        yield _sse({"type": "error", "trace_id": trace_id, "node": "error", "done": True, "content": str(exc)})
