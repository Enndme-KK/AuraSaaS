"""
Tool schemas in OpenAI Function Calling format + TOOL_MAP for the ReAct agent.

Each tool has:
  - name:        unique identifier the LLM sees
  - description: tells the LLM when and why to use this tool
  - parameters:  JSON Schema for arguments
  - map:         the actual Python function from tools.py
"""

from __future__ import annotations

from app.agents.tools import (
    add_product,
    add_staff_member,
    analyze_sku_trends,
    calculate_roi,
    check_external_context,
    compare_periods,
    create_anomaly_tasks,
    detect_business_anomalies,
    forecast_metric,
    generate_campaign_copy,
    generate_marketing_strategy,
    get_daily_summary,
    get_store_detail,
    list_all_stores,
    rank_stores,
    retrieve_sop_knowledge,
    save_agent_memory,
    search_agent_memory,
    search_products,
)

# ── Tool schemas (OpenAI function calling format) ──────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_daily_summary",
            "description": "查询某门店某天的经营日报，返回营收、订单量、客单价、热销SKU等指标。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID，必填",
                    },
                    "date": {
                        "type": "string",
                        "description": "日期，格式 YYYY-MM-DD，默认今天",
                    },
                },
                "required": ["store_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_anomalies",
            "description": "检测门店近N天的经营异常：营收骤降（环比下降超12%）、退单率飙升（环比翻1.8倍以上）、毛利恶化、外卖占比下滑等。返回异常列表含严重等级。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID，不传则检测全部门店",
                    },
                    "days": {
                        "type": "integer",
                        "description": "检测最近多少天，默认7天",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_sku_trends",
            "description": "分析近N天的SKU销售趋势，识别销量下跌超过20%、低毛利（<45%）、高退单率（>3%）、缺货的SKU。返回文本报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID，不传则查全部",
                    },
                    "date_range": {
                        "type": "integer",
                        "description": "天数范围，默认7天",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_external_factors",
            "description": "查询外部环境因素：天气、节假日、附近活动等，了解可能影响门店经营的外部条件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD，默认今天",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "从SOP知识库中检索相关文档，包括经营策略、营销手册、差评回复流程、雨天外卖方案、退单处理SOP、高毛利SKU策略、节假日营销方案、新店开业清单等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题描述，例如'退单率高怎么处理'、'雨天外卖方案'",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回文档数量，默认4篇",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_store_detail",
            "description": "查询单个门店的详细信息：店长姓名、城市商圈、评分、员工数、今日营收和订单数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                },
                "required": ["store_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_stores",
            "description": "列出全部门店及其基本信息：店名、城市、状态、店长、员工数、近7天营收。用于全局总览或选择门店。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forecast_metric",
            "description": "基于近30天历史数据用移动平均法预测未来N天的营收/利润/订单量趋势。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["revenue", "net_profit", "order_count"],
                        "description": "要预测的指标，revenue=营收, net_profit=净利润, order_count=订单量",
                    },
                    "forecast_days": {
                        "type": "integer",
                        "description": "预测未来几天，默认7天",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": "环比对比两个时间段的数据：本周 vs 上周，查看营收/利润/订单/毛利率的变化百分比和方向。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["revenue", "net_profit", "order_count", "gross_margin", "refund_rate", "avg_ticket"],
                        "description": "对比指标",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_stores",
            "description": "按指标（营收/利润/订单/毛利率等）对门店进行排名，返回TOP N榜单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["revenue", "net_profit", "order_count", "gross_margin", "refund_rate"],
                        "description": "排名指标",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回前N名，默认5",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_roi",
            "description": "计算营销活动的ROI回报率，可模拟不同转化率场景下的预期收益。",
            "parameters": {
                "type": "object",
                "properties": {
                    "budget": {
                        "type": "number",
                        "description": "营销预算金额，默认1000元",
                    },
                    "revenue_generated": {
                        "type": "number",
                        "description": "已产生的实际营收（如果有的话）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "按名称或分类模糊搜索商品/SKU，返回匹配的商品列表含价格和销量。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "商品名称或分类关键词",
                    },
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_marketing_strategy",
            "description": "根据诊断结果和预算限制，生成低预算营销方案，包含具体动作和预期效果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "目标门店ID",
                    },
                    "problem": {
                        "type": "string",
                        "description": "要解决的问题描述，如'退单率过高'",
                    },
                    "budget_limit": {
                        "type": "number",
                        "description": "预算上限，默认2000元",
                    },
                    "target": {
                        "type": "string",
                        "description": "目标，如'提升订单'、'降低退单率'",
                    },
                },
                "required": ["store_id", "problem"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_campaign_copy",
            "description": "根据营销策略生成具体文案：短信、小程序Push、公众号文章、外卖平台标题、员工话术。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                    "name": {
                        "type": "string",
                        "description": "活动名称",
                    },
                    "target": {
                        "type": "string",
                        "description": "活动目标",
                    },
                },
                "required": ["store_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_anomaly_tasks",
            "description": "根据检测到的异常自动创建待处理任务（如营收下降告警、退款异常工单），任务会出现在Dashboard。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_agent_memory",
            "description": "搜索Agent的历史记忆——之前分析过的结论、用户偏好、门店历史情况等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索词",
                    },
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_agent_memory",
            "description": "将本次分析的重要结论保存到长期记忆中，供未来对话参考。适合保存用户偏好、门店历史问题、已确认的策略方向等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "integer",
                        "description": "门店ID，没有则不传",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["diagnosis", "preference", "strategy", "fact"],
                        "description": "记忆类型：diagnosis=诊断发现, preference=用户偏好, strategy=策略决策, fact=事实信息",
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容，简洁概括关键信息，200字以内",
                    },
                },
                "required": ["memory_type", "content"],
            },
        },
    },
]

# ── Tool name → function map ──────────────────────────────────────────────

TOOL_MAP = {
    "get_daily_summary": get_daily_summary,
    "detect_anomalies": detect_business_anomalies,
    "analyze_sku_trends": analyze_sku_trends,
    "check_external_factors": check_external_context,
    "search_knowledge_base": retrieve_sop_knowledge,
    "get_store_detail": get_store_detail,
    "list_all_stores": list_all_stores,
    "forecast_metric": forecast_metric,
    "compare_periods": compare_periods,
    "rank_stores": rank_stores,
    "calculate_roi": calculate_roi,
    "search_products": search_products,
    "generate_marketing_strategy": generate_marketing_strategy,
    "generate_campaign_copy": generate_campaign_copy,
    "create_anomaly_tasks": create_anomaly_tasks,
    "search_agent_memory": search_agent_memory,
    "save_agent_memory": save_agent_memory,
}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name with given args. Returns JSON string for the LLM."""
    func = TOOL_MAP.get(name)
    if func is None:
        return _err(f"未知工具: {name}，请从可用工具列表中选择。可用: {', '.join(TOOL_MAP.keys())}")

    try:
        result = func(**args)
    except TypeError as e:
        return _err(f"参数错误: {e}。请检查参数名和类型是否正确。")
    except Exception as e:
        return _err(f"工具执行异常: {e}")

    if isinstance(result, dict):
        return _ok(result)
    return _ok({"result": str(result)})


def _ok(data: dict) -> str:
    import json
    return json.dumps({"success": True, "data": data}, ensure_ascii=False)


def _err(msg: str) -> str:
    import json
    return json.dumps({"success": False, "error": msg}, ensure_ascii=False)
