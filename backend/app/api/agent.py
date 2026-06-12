"""Agent API — SSE streaming, HITL approval, trace and replay."""

import datetime
import json
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Query, Body, Depends
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.core.response import api_response
from app.database import get_db
from app.models.models import AgentApproval, AgentTrace, MarketingCampaign, User
from app.agents.graph import run_agent_stream
from app.agents.react_agent import run_react_agent_stream


class ReactRequest(BaseModel):
    query: str
    store_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    history: Optional[list[dict]] = None


router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/stream-diagnose")
async def stream_diagnose(
    query: str = Query(..., min_length=1, max_length=500),
    store_id: int = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    """Stream LangGraph multi-agent diagnosis via SSE."""
    return EventSourceResponse(run_agent_stream(query, store_id=store_id, start_date=start_date, end_date=end_date))


@router.post("/stream-react")
async def stream_react(body: ReactRequest):
    """Stream ReAct Agent (autonomous tool selection) via SSE.

    Accepts POST with JSON body: {query, store_id?, start_date?, end_date?, history?}
    history is a list of {role, content} from previous turns, enabling multi-turn conversation.
    """
    return EventSourceResponse(run_react_agent_stream(
        body.query,
        store_id=body.store_id,
        start_date=body.start_date,
        end_date=body.end_date,
        history=body.history,
    ))


@router.get("/approvals")
def list_approvals(status: str = Query("pending"), db: Session = Depends(get_db)):
    """List HITL approval requests."""
    q = db.query(AgentApproval)
    if status != "all":
        q = q.filter(AgentApproval.status == status)
    rows = q.order_by(AgentApproval.created_at.desc()).limit(20).all()
    return {
        "code": 0,
        "data": [
            {
                "id": r.id,
                "session_id": r.session_id,
                "trace_id": r.trace_id,
                "node_name": r.node_name,
                "proposal": r.proposal,
                "estimated_cost": r.estimated_cost,
                "status": r.status,
                "reviewer_comment": r.reviewer_comment,
                "created_at": str(r.created_at),
                "reviewed_at": str(r.reviewed_at) if r.reviewed_at else None,
            }
            for r in rows
        ],
        "message": "ok",
    }


@router.post("/approve")
def approve_proposal(
    approval_id: int = Body(...),
    action: str = Body(...),  # approve / reject / revise
    comment: str = Body(""),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Approve, reject, or request revision for a HITL proposal."""
    if action not in {"approve", "reject", "revise"}:
        return api_response(code=-1, message="action must be approve, reject, or revise")

    approval = db.query(AgentApproval).filter(AgentApproval.id == approval_id).first()
    if not approval:
        return api_response(code=-1, message="Approval not found")
    if approval.status != "pending":
        return api_response(code=-1, message="Already reviewed")

    approval.status = {"approve": "approved", "reject": "rejected", "revise": "revise"}[action]
    approval.reviewer_comment = comment
    approval.reviewed_at = datetime.datetime.now()
    campaign_id = None
    if action == "approve":
        campaign = MarketingCampaign(
            campaign_name="AI 审批通过活动草稿",
            channel="全渠道",
            status="draft",
            target_audience="门店会员与高潜客群",
            budget=approval.estimated_cost or 0,
            content_text=approval.proposal,
        )
        db.add(campaign)
        db.flush()
        campaign_id = campaign.id

    trace = db.query(AgentTrace).filter(AgentTrace.trace_id == approval.trace_id).first()
    if trace:
        steps = json.loads(trace.steps_json or "[]")
        steps.append({
            "node": "human_approval",
            "time": datetime.datetime.now().isoformat(),
            "duration_ms": 0,
            "input_summary": approval.proposal[:180],
            "event": {
                "type": "approval_update",
                "title": "审批已更新",
                "content": f"Proposal {approval.status}",
                "trace_id": approval.trace_id,
                "node": "human_approval",
                "approval_id": approval.id,
                "campaign_id": campaign_id,
                "done": True,
            },
        })
        trace.steps_json = json.dumps(steps, ensure_ascii=False)
        trace.updated_at = datetime.datetime.now()
    db.commit()

    return {
        "code": 0,
        "data": {"id": approval.id, "status": approval.status, "trace_id": approval.trace_id, "campaign_id": campaign_id},
        "message": f"Proposal {approval.status}",
    }


@router.get("/traces")
def list_traces(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Return recent agent traces for timeline browsing."""
    rows = db.query(AgentTrace).order_by(AgentTrace.created_at.desc()).limit(limit).all()
    return {
        "code": 0,
        "data": [
            {
                "trace_id": r.trace_id,
                "user_query": r.user_query,
                "store_id": r.store_id,
                "status": r.status,
                "created_at": str(r.created_at),
                "updated_at": str(r.updated_at),
                "step_count": len(json.loads(r.steps_json or "[]")),
            }
            for r in rows
        ],
        "message": "ok",
    }


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db)):
    """Return one trace with timeline steps."""
    trace = db.query(AgentTrace).filter(AgentTrace.trace_id == trace_id).first()
    if not trace:
        return api_response(code=-1, message="Trace not found")
    return {
        "code": 0,
        "data": {
            "trace_id": trace.trace_id,
            "user_query": trace.user_query,
            "store_id": trace.store_id,
            "status": trace.status,
            "steps": json.loads(trace.steps_json or "[]"),
            "final_answer": trace.final_answer,
            "created_at": str(trace.created_at),
            "updated_at": str(trace.updated_at),
        },
        "message": "ok",
    }


@router.post("/replay/{trace_id}")
def replay_trace(trace_id: str, db: Session = Depends(get_db)):
    """MVP replay: return saved trace steps for frontend re-display."""
    trace = db.query(AgentTrace).filter(AgentTrace.trace_id == trace_id).first()
    if not trace:
        return api_response(code=-1, message="Trace not found")
    return {
        "code": 0,
        "data": {
            "trace_id": trace.trace_id,
            "mode": "saved_trace_replay",
            "steps": json.loads(trace.steps_json or "[]"),
            "final_answer": trace.final_answer,
        },
        "message": "ok",
    }
@router.delete("/traces/{trace_id}")
def delete_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Delete a single agent trace."""
    trace = db.query(AgentTrace).filter(AgentTrace.trace_id == trace_id).first()
    if not trace:
        return api_response(code=-1, message="Trace not found")
    db.delete(trace)
    db.commit()
    return api_response(message="Trace deleted")


@router.delete("/traces")
def clear_all_traces(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Delete all agent traces."""
    count = db.query(AgentTrace).delete()
    db.commit()
    return api_response(data={"deleted": count}, message=f"Deletd {count} traces")

