import json
import time
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from services.llm.base import LLMProvider, LLMTimeoutError
from services.llm.mock import MockProvider
from tests.conftest import ScriptedProvider, make_pdf

ClientFactory = Callable[[LLMProvider], TestClient]

RUBRIC = {
    "job_title": "Backend Engineer",
    "criteria": [
        {"name": "Python", "description": "Python FastAPI APIs", "weight": 60, "must_have": True},
        {"name": "Kubernetes", "description": "Kubernetes EKS clusters", "weight": 40, "must_have": False},
    ],
}
STRONG = "Alex Strong\nBuilt Python FastAPI APIs for six years.\nOperated Kubernetes EKS clusters in production."
WEAK = "Sam Weak\nRetail store supervisor.\nExcellent customer service and cash handling."


def wait_for(client: TestClient, job_id: str, timeout: float = 10) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {job}")


def files(*items: tuple[str, bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("resumes", (name, data, "application/octet-stream")) for name, data in items]


def test_score_job_end_to_end_with_mock(client_with: ClientFactory) -> None:
    client = client_with(MockProvider())
    r = client.post(
        "/api/score",
        data={"rubric": json.dumps(RUBRIC)},
        files=files(("weak.txt", WEAK.encode()), ("strong.pdf", make_pdf(STRONG.splitlines())),
                    ("scan.pdf", make_pdf([]))),
    )
    assert r.status_code == 202, r.text
    created = r.json()
    assert [c["status"] for c in created["candidates"]] == ["pending", "pending", "error"]
    assert "OCR needed" in created["candidates"][2]["error"]

    job = wait_for(client, created["job_id"])
    assert job["status"] == "completed"
    assert job["progress"] == {"total": 3, "done": 2, "failed": 1, "percent": 100.0}
    first, second, third = job["candidates"]
    assert first["candidate_name"] == "Alex Strong" and first["rank"] == 1 and first["must_have_ok"] is True
    assert second["candidate_name"] == "Sam Weak" and second["must_have_missing"] == ["Python"]
    assert first["total_score"] > second["total_score"]
    assert all(c["evidence_status"] == "verified" for c in first["criteria"])
    assert third["status"] == "error" and third["rank"] is None


def test_score_generates_rubric_from_jd_when_missing(client_with: ClientFactory) -> None:
    client = client_with(MockProvider())
    jd = "Backend Engineer\n- Must have Python FastAPI APIs\n- Kubernetes EKS clusters"
    r = client.post("/api/score", data={"jd_text": jd}, files=files(("s.txt", STRONG.encode())))
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "completed"
    assert job["rubric"]["job_title"] == "Backend Engineer"
    assert job["candidates"][0]["status"] == "done"


def test_invalid_rubric_rejected(client_with: ClientFactory) -> None:
    bad = {**RUBRIC, "criteria": [{**RUBRIC["criteria"][0], "weight": 10}]}
    r = client_with(MockProvider()).post("/api/score", data={"rubric": json.dumps(bad)},
                                         files=files(("s.txt", STRONG.encode())))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_rubric"
    assert "sum to 100" in r.json()["detail"]["detail"]


def test_candidate_llm_failure_is_isolated(client_with: ClientFactory) -> None:
    client = client_with(ScriptedProvider(["garbage"] * 3 + [valid_score_reply(STRONG)]))
    r = client.post("/api/score", data={"rubric": json.dumps(RUBRIC)},
                    files=files(("a.txt", WEAK.encode()), ("b.txt", STRONG.encode())))
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "completed"
    statuses = {c["filename"]: c["status"] for c in job["candidates"]}
    assert statuses == {"a.txt": "error", "b.txt": "done"}


def valid_score_reply(resume: str) -> str:
    return json.dumps({
        "candidate_name": resume.splitlines()[0],
        "criteria": [
            {"criterion_id": "C1", "score": 8, "evidence": resume.splitlines()[1], "reasoning": "ok"},
            {"criterion_id": "C2", "score": 6, "evidence": resume.splitlines()[2], "reasoning": "ok"},
        ],
        "strengths": [], "gaps": [], "summary": "ok",
    })


def test_decision_update_and_delete(client_with: ClientFactory) -> None:
    client = client_with(MockProvider())
    r = client.post("/api/score", data={"rubric": json.dumps(RUBRIC)}, files=files(("s.txt", STRONG.encode())))
    job = wait_for(client, r.json()["job_id"])
    cid = job["candidates"][0]["id"]

    r = client.patch(f"/api/jobs/{job['job_id']}/candidates/{cid}", json={"decision": "shortlisted"})
    assert r.status_code == 200 and r.json()["decision"] == "shortlisted"
    assert client.get(f"/api/jobs/{job['job_id']}").json()["candidates"][0]["decision"] == "shortlisted"
    assert client.patch(f"/api/jobs/{job['job_id']}/candidates/{cid}", json={"decision": "maybe"}).status_code == 422

    # Notes update alone leaves the decision untouched.
    r = client.patch(f"/api/jobs/{job['job_id']}/candidates/{cid}", json={"notes": "Strong infra; ask about AWS."})
    assert r.json()["notes"] == "Strong infra; ask about AWS." and r.json()["decision"] == "shortlisted"

    assert any(j["job_id"] == job["job_id"] for j in client.get("/api/jobs").json())
    assert client.delete(f"/api/jobs/{job['job_id']}").status_code == 204
    assert client.get(f"/api/jobs/{job['job_id']}").status_code == 404
    assert client.delete(f"/api/jobs/{job['job_id']}").status_code == 404


def test_resume_text_not_persisted_by_default(client_with: ClientFactory) -> None:
    from app.main import app
    from models.db import CandidateRow

    client = client_with(MockProvider())
    r = client.post("/api/score", data={"rubric": json.dumps(RUBRIC)}, files=files(("s.txt", STRONG.encode())))
    wait_for(client, r.json()["job_id"])
    with app.state.db.session() as s:
        rows = s.query(CandidateRow).filter_by(job_id=r.json()["job_id"]).all()
        assert rows and all(row.resume_text is None for row in rows)


def test_rerun_reuses_cached_rubric_and_scores(client_with: ClientFactory, monkeypatch: Any) -> None:
    from app.main import settings

    monkeypatch.setattr(settings, "llm_cache_enabled", True)
    jd = "Cache Test Engineer\n- Must have Python FastAPI APIs\n- Kubernetes EKS clusters"
    first_provider = MockProvider()
    client = client_with(first_provider)
    first = wait_for(client, client.post("/api/score", data={"jd_text": jd},
                                         files=files(("s.txt", STRONG.encode()))).json()["job_id"])
    assert first["candidates"][0]["cached"] is False
    assert first["candidates"][0]["best_fit_role"]

    # Same JD and resume again: no LLM call at all (the provider would fail if called).
    client = client_with(ScriptedProvider([]))
    r = client.post("/api/score", data={"jd_text": jd}, files=files(("renamed.txt", STRONG.encode())))
    second = wait_for(client, r.json()["job_id"])
    assert second["status"] == "completed" and second["rubric"] == first["rubric"]
    reused = second["candidates"][0]
    assert reused["cached"] is True and reused["status"] == "done" and reused["filename"] == "renamed.txt"
    assert reused["total_score"] == first["candidates"][0]["total_score"]
    assert reused["id"] != first["candidates"][0]["id"]


PY_DEV = ("Priya Backend\nSenior Python developer, 7 years of professional Python development.\n"
          "Building REST APIs with FastAPI or Django for SaaS products.\n"
          "PostgreSQL schema design and query optimisation. Hands-on AWS experience.\n"
          "Running containers and Kubernetes in production.")


def test_score_without_jd_is_rejected(client_with: ClientFactory) -> None:
    client = client_with(MockProvider())
    r = client.post("/api/score", files=files(("dev.txt", PY_DEV.encode())))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "jd_missing"
    assert "default_jd" not in client.get("/api/config").json()


class _SlowOnWeakProvider(MockProvider):
    async def chat_json(self, messages: list[Any], json_schema: dict[str, Any], **kw: Any) -> str:
        if any("Sam Weak" in m.content for m in messages):
            raise LLMTimeoutError("Ollama took longer than 900s. Try a smaller model or raise LLM_TIMEOUT_S.")
        return await super().chat_json(messages, json_schema, **kw)


def test_timeout_fails_only_that_resume(client_with: ClientFactory) -> None:
    client = client_with(_SlowOnWeakProvider())
    r = client.post("/api/score", data={"rubric": json.dumps(RUBRIC)},
                    files=files(("weak.txt", WEAK.encode()), ("strong.txt", STRONG.encode())))
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "completed"
    by_name = {c["filename"]: c for c in job["candidates"]}
    assert by_name["weak.txt"]["status"] == "error" and "900s" in by_name["weak.txt"]["error"]
    assert by_name["strong.txt"]["status"] == "done"


def test_priority_prompt_is_a_25_percent_criterion(client_with: ClientFactory) -> None:
    client = client_with(MockProvider())
    r = client.post("/api/score", data={"rubric": json.dumps(RUBRIC), "priority": "Operated Kubernetes EKS clusters"},
                    files=files(("strong.txt", STRONG.encode())))
    assert r.status_code == 202
    job = wait_for(client, r.json()["job_id"])
    weights = {c["name"]: c["weight"] for c in job["rubric"]["criteria"]}
    assert weights == {"Python": 45, "Kubernetes": 30, "Recruiter priority": 25}
    assert job["status"] == "completed"
    crit = {c["criterion"]: c for c in job["candidates"][0]["criteria"]}
    assert crit["Recruiter priority"]["weight"] == 25
