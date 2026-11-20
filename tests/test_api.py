import pytest
from fastapi.testclient import TestClient

from fedsight.agent import AgentResult, Step
from fedsight.api import create_app
from fedsight.ops import RateLimiter


class FakeIndex:
    chunks = [1, 2, 3]


class FakeDB:
    loaded = {"fema_declarations": ["state"]}


class FakeAgent:
    model = "claude-sonnet-5-5"
    index, db = FakeIndex(), FakeDB()

    def __init__(self):
        self.asked = []

    def ask(self, question, sources=None):
        self.asked.append((question, sources))
        if "boom" in question:
            raise RuntimeError("upstream exploded")
        return AgentResult(
            "req123", question, [{"text": "An answer.", "citations": []}], [], [Step("search_documents", {}, "ok")],
            {"status": "verified"}, {"cost_usd": 0.01, "latency_ms": 5})


@pytest.fixture
def client():
    agent = FakeAgent()
    with TestClient(create_app(agent, RateLimiter(3, 100))) as c:
        c.agent = agent
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body == {"status": "ok", "chunks": 3, "tables": ["fema_declarations"], "model": "claude-sonnet-5-5"}


def test_ask_returns_answer_and_audit_fields(client):
    r = client.post("/api/ask", json={"question": "What did GAO find?", "sources": ["gao"]})
    assert r.status_code == 200
    assert r.json()["answer"] == "An answer." and r.json()["guardrails"]["status"] == "verified"
    assert client.agent.asked == [("What did GAO find?", ["gao"])]


def test_validation_rejects_short_long_and_unknown_sources(client):
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 601}).status_code == 422
    assert client.post("/api/ask", json={"question": "valid question", "sources": ["reddit"]}).status_code == 422


def test_rate_limit_returns_429(client):
    codes = [client.post("/api/ask", json={"question": "valid question"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_model_failure_is_a_clean_502_without_details(client):
    r = client.post("/api/ask", json={"question": "please boom now"})
    assert r.status_code == 502 and "exploded" not in r.text


def test_index_page_and_static_files(client):
    page = client.get("/")
    assert page.status_code == 200 and "FedSight" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_evals_endpoint_404_until_a_run_exists(client, monkeypatch, tmp_path):
    import fedsight.api as api
    monkeypatch.setattr(api, "ROOT", tmp_path)
    assert client.get("/api/evals").status_code == 404
