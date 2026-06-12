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

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from app.models.models import AgentApproval, AgentTrace, Store


Base.metadata.create_all(bind=engine)
client = TestClient(app)


def auth_headers():
    email = "tester@example.com"
    password = "secret123"
    client.post("/api/auth/register", json={"username": "tester", "email": email, "password": password})
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def ensure_store():
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        store = db.query(Store).first()
        if store:
            return store.id
        store = Store(name="Test Store", city="Shanghai", status="open")
        db.add(store)
        db.commit()
        return store.id
    finally:
        db.close()


def test_health_and_auth_flow():
    assert client.get("/api/health").status_code == 200
    headers = auth_headers()
    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["email"] == "tester@example.com"


def test_write_endpoints_require_auth():
    store_id = ensure_store()
    assert client.post("/api/admin/regenerate-mock").status_code == 401
    assert client.post("/api/import/manual", json={"type": "store", "name": "Nope"}).status_code == 401
    assert client.post("/api/dashboard/campaigns", json={"name": "Nope"}).status_code == 401
    response = client.post(
        "/api/sku/add",
        data={"store_id": store_id, "sku_name": "Latte", "category": "Drink", "price": 28},
    )
    assert response.status_code == 401


def test_logged_in_user_can_create_campaign_and_sku():
    headers = auth_headers()
    store_id = ensure_store()
    campaign = client.post("/api/dashboard/campaigns", headers=headers, json={"name": "Demo Campaign", "channel": "SMS"})
    assert campaign.status_code == 200
    assert campaign.json()["data"]["name"] == "Demo Campaign"
    sku = client.post(
        "/api/sku/add",
        headers=headers,
        data={"store_id": store_id, "sku_name": "Americano", "category": "Drink", "price": 22, "cost": 6},
    )
    assert sku.status_code == 200
    assert sku.json()["data"]["sku_name"] == "Americano"


def test_rag_search_and_agent_stream_fallback():
    rag = client.post("/api/rag/search", data={"query": "雨天 外卖", "top_k": "2"})
    assert rag.status_code == 200
    assert isinstance(rag.json()["data"], list)

    with client.stream("GET", "/api/agent/stream-diagnose?query=昨天营收为什么下降") as response:
        assert response.status_code == 200
        payload = "".join(response.iter_text())
    assert "agent_start" in payload
    assert "rag_reference" in payload
    assert "end" in payload


def test_agent_stream_routes_sop_campaign_to_approval_flow():
    with client.stream(
        "GET",
        "/api/agent/stream-diagnose",
        params={"query": "用我们的 SOP 为最弱门店设计低预算活动"},
    ) as response:
        assert response.status_code == 200
        payload = "".join(response.iter_text())
    assert "marketing_plan" in payload
    assert "approval_required" in payload
    assert "NoneType" not in payload
    assert "error" not in payload.lower()


def test_approval_approve_creates_campaign_draft_and_updates_trace():
    headers = auth_headers()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        trace = AgentTrace(trace_id="trace-test", user_query="create campaign", status="completed", steps_json="[]")
        db.add(trace)
        approval = AgentApproval(
            session_id="session-test",
            trace_id="trace-test",
            node_name="human_approval",
            proposal="上线低预算会员召回活动",
            estimated_cost=1200,
            status="pending",
        )
        db.add(approval)
        db.commit()
        approval_id = approval.id
    finally:
        db.close()

    response = client.post(
        "/api/agent/approve",
        headers=headers,
        json={"approval_id": approval_id, "action": "approve", "comment": ""},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "approved"
    assert data["campaign_id"]

    trace_response = client.get("/api/agent/traces/trace-test")
    assert "approval_update" in str(trace_response.json()["data"]["steps"])
