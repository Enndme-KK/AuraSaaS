"""Smart Import Agent — Excel/CSV upload with DeepSeek semantic mapping and SSE streaming."""

import csv
import datetime
import io
import json
import re

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Store, BusinessMetricsDaily, SkuPerformance, MarketingCampaign
from app.core.deps import get_current_user
from app.models.models import User
from app.services.deepseek_client import chat as llm_chat, has_valid_api_key

router = APIRouter(prefix="/api/agent", tags=["agent-import"])

# Known database fields with descriptions for AI semantic mapping
KNOWN_FIELDS = {
    # Store fields
    "门店名称": "store.name",
    "城市": "store.city",
    "地址": "store.address",
    "商圈": "store.area",
    "店长": "store.manager_name",
    "座位数": "store.seats",
    "员工数": "store.staff_count",
    "评分": "store.rating",
    # SKU fields
    "商品名称": "sku.sku_name",
    "品类": "sku.category",
    "分类": "sku.category",
    "单价": "sku.price",
    "售价": "sku.price",
    "成本": "sku.cost",
    "销量": "sku.sales_count",
    "营收": "sku.revenue",
    "销售额": "sku.revenue",
    "毛利率": "sku.gross_margin",
    "退单率": "sku.refund_rate",
    # Metrics fields
    "日期": "metrics.date",
    "门店ID": "metrics.store_id",
    "订单数": "metrics.order_count",
    "客单价": "metrics.avg_ticket",
    "净利润": "metrics.net_profit",
    "平台抽佣": "metrics.platform_commission",
    "外卖占比": "metrics.delivery_ratio",
    "堂食占比": "metrics.dine_in_ratio",
    "新客数": "metrics.new_customers",
    "回头客": "metrics.returning_customers",
    # Campaign fields
    "活动名称": "campaign.campaign_name",
    "渠道": "campaign.channel",
    "预算": "campaign.budget",
    "目标受众": "campaign.target_audience",
    "文案": "campaign.content_text",
}


def _parse_value(val, field_type="str"):
    """Parse a string value to the appropriate type."""
    if val is None or str(val).strip() == "":
        return None
    s = str(val).strip().replace(",", "").replace("¥", "").replace("%", "")
    try:
        if field_type == "int":
            return int(float(s))
        elif field_type == "float":
            return float(s)
        return s
    except (ValueError, TypeError):
        return s


def _read_file_content(file: UploadFile) -> tuple[list[str], list[list[str]], str]:
    """Read headers and rows from CSV or Excel file. Returns (headers, rows, file_type)."""
    content = file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".csv"):
        text = content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        lines = list(reader)
        if not lines:
            return [], [], "csv"
        headers = [h.strip() for h in lines[0]]
        rows = lines[1:]
        return headers, rows, "csv"

    elif filename.endswith((".xlsx", ".xls")):
        import pandas as pd
        df = pd.read_excel(io.BytesIO(content))
        headers = [str(h).strip() for h in df.columns.tolist()]
        rows = df.values.tolist()
        # Convert numpy types
        rows = [[str(v) if v is not None and not isinstance(v, (int, float)) else v for v in row] for row in rows]
        return headers, rows, "excel"

    else:
        raise ValueError(f"不支持的文件格式: {filename}，请上传 CSV 或 Excel 文件")


def _ai_semantic_map(headers: list[str], sample_rows: list[list[str]]) -> dict:
    """Use DeepSeek to semantically map CSV headers to database fields."""
    fields_desc = "\n".join([f"- {cn}: {fn}" for cn, fn in KNOWN_FIELDS.items()])

    sample_text = ""
    for i, row in enumerate(sample_rows[:3]):
        sample_text += f"  第{i+1}行: {dict(zip(headers, [str(v)[:30] for v in row]))}\n"

    prompt = f"""你是一个数据导入专家。请根据以下文件表头和示例数据，将每个列名映射到最合适的数据库字段。

可用数据库字段:
{fields_desc}

文件表头: {json.dumps(headers, ensure_ascii=False)}
示例数据:
{sample_text}

请返回 JSON 格式: {{"mapping": {{"原始列名": "数据库字段路径"}}, "target_table": "store|sku|metrics|campaign", "confidence": "high|medium|low"}}
如果某个列没有合适的映射，映射值设为 null。
target_table 表示这张表应该导入哪种数据（store/sku/metrics/campaign）。
只返回 JSON，不要加任何解释文字。"""

    try:
        if has_valid_api_key():
            result = llm_chat(
                "你是精确的数据导入专家，只返回 JSON。",
                prompt,
                json.dumps({"mapping": {}, "target_table": "sku", "confidence": "low"}, ensure_ascii=False),
                temperature=0.1,
                max_tokens=600,
            )
            # Extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", result)
            if json_match:
                return json.loads(json_match.group())
    except Exception:
        pass

    # Fallback: simple keyword matching
    mapping = {}
    for h in headers:
        h_clean = h.strip()
        matched = None
        for cn, fn in KNOWN_FIELDS.items():
            if cn in h_clean or h_clean in cn:
                matched = fn
                break
        mapping[h_clean] = matched

    # Guess target table
    fields_str = " ".join([v or "" for v in mapping.values()])
    if "store" in fields_str and "sku" not in fields_str:
        target = "store"
    elif "metrics" in fields_str:
        target = "metrics"
    elif "campaign" in fields_str:
        target = "campaign"
    else:
        target = "sku"

    return {"mapping": mapping, "target_table": target, "confidence": "low"}


def _import_rows(target_table: str, mapping: dict, headers: list[str], rows: list[list[str]], db: Session) -> dict:
    """Import rows into the appropriate table. Returns stats."""
    valid_store_ids = {s.id for s in db.query(Store).all()}
    default_store_id = next(iter(valid_store_ids)) if valid_store_ids else 1
    today = datetime.date.today()
    imported = 0
    skipped = 0
    errors = []

    # Build header index map
    header_idx = {h: i for i, h in enumerate(headers)}
    # Build reverse mapping: field_path -> header name
    field_to_header = {}
    for header, field in mapping.items():
        if field:
            field_to_header[field] = header

    for row_idx, row in enumerate(rows):
        try:
            if target_table == "store":
                name = str(row[header_idx.get(field_to_header.get("store.name", ""), 0)] or "").strip() if field_to_header.get("store.name") in header_idx else ""
                if not name:
                    skipped += 1
                    continue
                store = Store(
                    name=name,
                    city=str(row[header_idx[field_to_header["store.city"]]] or "") if field_to_header.get("store.city") in header_idx else "",
                    address=str(row[header_idx[field_to_header["store.address"]]] or "") if field_to_header.get("store.address") in header_idx else "",
                    area=str(row[header_idx[field_to_header["store.area"]]] or "") if field_to_header.get("store.area") in header_idx else "",
                    manager_name=str(row[header_idx[field_to_header["store.manager_name"]]] or "") if field_to_header.get("store.manager_name") in header_idx else "",
                    seats=_parse_value(row[header_idx[field_to_header["store.seats"]]], "int") or 0 if field_to_header.get("store.seats") in header_idx else 0,
                    staff_count=_parse_value(row[header_idx[field_to_header["store.staff_count"]]], "int") or 0 if field_to_header.get("store.staff_count") in header_idx else 0,
                )
                db.add(store)
                imported += 1

            elif target_table == "sku":
                name = str(row[header_idx.get(field_to_header.get("sku.sku_name", ""), 0)] or "").strip() if field_to_header.get("sku.sku_name") in header_idx else ""
                if not name:
                    skipped += 1
                    continue
                price = _parse_value(row[header_idx[field_to_header["sku.price"]]], "float") if field_to_header.get("sku.price") in header_idx else None
                cost = _parse_value(row[header_idx[field_to_header["sku.cost"]]], "float") if field_to_header.get("sku.cost") in header_idx else None
                price = price or 0
                cost = cost or 0
                margin = round((price - cost) / price, 4) if price > 0 else 0

                sku = SkuPerformance(
                    store_id=default_store_id,
                    date=today,
                    sku_name=name,
                    category=str(row[header_idx[field_to_header["sku.category"]]] or "") if field_to_header.get("sku.category") in header_idx else "未分类",
                    price=price,
                    cost=cost,
                    sales_count=_parse_value(row[header_idx[field_to_header["sku.sales_count"]]], "int") if field_to_header.get("sku.sales_count") in header_idx else None,
                    revenue=_parse_value(row[header_idx[field_to_header["sku.revenue"]]], "float") if field_to_header.get("sku.revenue") in header_idx else None,
                    gross_margin=margin,
                    refund_rate=(_parse_value(row[header_idx[field_to_header["sku.refund_rate"]]], "float") or 0) / 100 if field_to_header.get("sku.refund_rate") in header_idx else 0,
                )
                if sku.sales_count is None:
                    sku.sales_count = 0
                if sku.revenue is None:
                    sku.revenue = price * sku.sales_count
                sku.sales_volume = sku.sales_count
                db.add(sku)
                imported += 1

            elif target_table == "metrics":
                date_str = str(row[header_idx.get(field_to_header.get("metrics.date", ""), 0)] or "").strip() if field_to_header.get("metrics.date") in header_idx else ""
                if not date_str:
                    skipped += 1
                    continue
                d = None
                for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y%m%d"]:
                    try:
                        d = datetime.datetime.strptime(date_str, fmt).date()
                        break
                    except (ValueError, TypeError):
                        continue
                if not d:
                    skipped += 1
                    continue

                store_id = _parse_value(row[header_idx[field_to_header["metrics.store_id"]]], "int") if field_to_header.get("metrics.store_id") in header_idx else None
                store_id = store_id if store_id in valid_store_ids else default_store_id

                revenue = _parse_value(row[header_idx[field_to_header["metrics.revenue"]]], "float") if field_to_header.get("metrics.revenue") in header_idx else None
                orders = _parse_value(row[header_idx[field_to_header["metrics.order_count"]]], "int") if field_to_header.get("metrics.order_count") in header_idx else None
                avg_ticket = _parse_value(row[header_idx[field_to_header["metrics.avg_ticket"]]], "float") if field_to_header.get("metrics.avg_ticket") in header_idx else None

                metric = BusinessMetricsDaily(
                    store_id=store_id,
                    date=d,
                    revenue=revenue or 0,
                    total_revenue=revenue or 0,
                    order_count=orders or 0,
                    avg_ticket=avg_ticket or 0,
                    avg_order_value=avg_ticket or 0,
                    gross_margin=(_parse_value(row[header_idx[field_to_header["metrics.gross_margin"]]], "float") or 0) / 100 if field_to_header.get("metrics.gross_margin") in header_idx else 0,
                    refund_rate=(_parse_value(row[header_idx[field_to_header["metrics.refund_rate"]]], "float") or 0) / 100 if field_to_header.get("metrics.refund_rate") in header_idx else 0,
                    net_profit=_parse_value(row[header_idx[field_to_header["metrics.net_profit"]]], "float") if field_to_header.get("metrics.net_profit") in header_idx else None,
                    platform_commission=_parse_value(row[header_idx[field_to_header["metrics.platform_commission"]]], "float") if field_to_header.get("metrics.platform_commission") in header_idx else None,
                    delivery_ratio=(_parse_value(row[header_idx[field_to_header["metrics.delivery_ratio"]]], "float") or 0) / 100 if field_to_header.get("metrics.delivery_ratio") in header_idx else 0,
                    dine_in_ratio=(_parse_value(row[header_idx[field_to_header["metrics.dine_in_ratio"]]], "float") or 0) / 100 if field_to_header.get("metrics.dine_in_ratio") in header_idx else 0,
                    new_customers=_parse_value(row[header_idx[field_to_header["metrics.new_customers"]]], "int") if field_to_header.get("metrics.new_customers") in header_idx else None,
                    returning_customers=_parse_value(row[header_idx[field_to_header["metrics.returning_customers"]]], "int") if field_to_header.get("metrics.returning_customers") in header_idx else None,
                )
                db.add(metric)
                imported += 1

            elif target_table == "campaign":
                name = str(row[header_idx.get(field_to_header.get("campaign.campaign_name", ""), 0)] or "").strip() if field_to_header.get("campaign.campaign_name") in header_idx else ""
                if not name:
                    skipped += 1
                    continue
                campaign = MarketingCampaign(
                    campaign_name=name,
                    channel=str(row[header_idx[field_to_header["campaign.channel"]]] or "") if field_to_header.get("campaign.channel") in header_idx else "全渠道",
                    budget=_parse_value(row[header_idx[field_to_header["campaign.budget"]]], "float") if field_to_header.get("campaign.budget") in header_idx else None,
                    target_audience=str(row[header_idx[field_to_header["campaign.target_audience"]]] or "") if field_to_header.get("campaign.target_audience") in header_idx else "",
                    content_text=str(row[header_idx[field_to_header["campaign.content_text"]]] or "") if field_to_header.get("campaign.content_text") in header_idx else "",
                )
                db.add(campaign)
                imported += 1

        except Exception as exc:
            errors.append(f"第{row_idx + 1}行: {str(exc)}")

    db.commit()
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10],  # Limit error messages
        "target_table": target_table,
    }


def _sse(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


@router.post("/import-data")
async def agent_import_data(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """
    Smart import: upload Excel/CSV, AI semantic mapping, SSE streaming progress.

    Streams: [识别表头] → [语义映射] → [清洗导入] → [完成]
    """
    async def event_stream():
        # Phase 1: Read file headers
        yield _sse({
            "type": "phase",
            "phase": "header_detect",
            "title": "🔍 识别表头",
            "content": f"正在读取文件: {file.filename}",
            "done": False,
        })

        try:
            headers, rows, file_type = _read_file_content(file)
        except Exception as e:
            yield _sse({"type": "error", "content": str(e), "done": True})
            return

        if not headers:
            yield _sse({"type": "error", "content": "文件为空或无法解析表头", "done": True})
            return

        yield _sse({
            "type": "progress",
            "phase": "header_detect",
            "title": "🔍 识别表头",
            "content": f"检测到 {len(headers)} 个列: {', '.join(headers)}",
            "headers": headers,
            "row_count": len(rows),
            "file_type": file_type,
            "done": True,
        })

        # Phase 2: Semantic mapping
        yield _sse({
            "type": "phase",
            "phase": "semantic_map",
            "title": "🧠 语义映射",
            "content": "正在使用 AI 进行字段语义映射...",
            "done": False,
        })

        sample_rows = rows[:5] if len(rows) >= 5 else rows
        mapping_result = _ai_semantic_map(headers, sample_rows)

        yield _sse({
            "type": "progress",
            "phase": "semantic_map",
            "title": "🧠 语义映射",
            "content": f"映射完成 (置信度: {mapping_result.get('confidence', 'low')})",
            "mapping": mapping_result.get("mapping", {}),
            "target_table": mapping_result.get("target_table", "sku"),
            "done": True,
        })

        # Phase 3: Clean and import
        yield _sse({
            "type": "phase",
            "phase": "import",
            "title": "📥 清洗导入",
            "content": f"正在导入 {len(rows)} 行数据到 {mapping_result.get('target_table', 'sku')} 表...",
            "done": False,
        })

        stats = _import_rows(
            mapping_result.get("target_table", "sku"),
            mapping_result.get("mapping", {}),
            headers,
            rows,
            db,
        )

        yield _sse({
            "type": "progress",
            "phase": "import",
            "title": "📥 清洗导入",
            "content": f"成功导入 {stats['imported']} 条, 跳过 {stats['skipped']} 条, 错误 {len(stats['errors'])} 条",
            "stats": stats,
            "done": True,
        })

        # Phase 4: Complete
        yield _sse({
            "type": "done",
            "phase": "complete",
            "title": "✅ 导入完成",
            "content": f"共导入 {stats['imported']} 条数据到 {stats['target_table']} 表",
            "stats": stats,
            "done": True,
        })

    return EventSourceResponse(event_stream())
