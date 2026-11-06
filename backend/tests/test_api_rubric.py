from collections.abc import Callable

from fastapi.testclient import TestClient

from services.llm.base import LLMProvider, LLMUnavailableError
from tests.conftest import ScriptedProvider, make_pdf
from tests.test_rubric import GOOD_DRAFT

ClientFactory = Callable[[LLMProvider], TestClient]


def test_rubric_from_text(client_with: ClientFactory) -> None:
    client = client_with(ScriptedProvider([GOOD_DRAFT]))
    r = client.post("/api/rubric", data={"jd_text": "We need a backend engineer", "model": "fake:1b"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "fake:1b"
    assert sum(c["weight"] for c in body["rubric"]["criteria"]) == 100


def test_rubric_from_pdf_file(client_with: ClientFactory) -> None:
    client = client_with(ScriptedProvider([GOOD_DRAFT]))
    pdf = make_pdf(["Backend Engineer", "Must have 5+ years of Python and REST APIs."])
    r = client.post("/api/rubric", files={"jd_file": ("jd.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert "5+ years of Python" in r.json()["jd_text"]


def test_rubric_combines_file_and_typed_criteria(client_with: ClientFactory) -> None:
    client = client_with(ScriptedProvider([GOOD_DRAFT]))
    pdf = make_pdf(["Backend Engineer", "Must have 5+ years of Python and REST APIs."])
    r = client.post("/api/rubric", data={"jd_text": "Must have Kubernetes"},
                    files={"jd_file": ("jd.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    jd = r.json()["jd_text"]
    assert "5+ years of Python" in jd and "Must have Kubernetes" in jd


def test_rubric_scanned_pdf_error(client_with: ClientFactory) -> None:
    client = client_with(ScriptedProvider([]))
    r = client.post("/api/rubric", files={"jd_file": ("jd.pdf", make_pdf([]), "application/pdf")})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "scanned_pdf_ocr_needed"


def test_rubric_missing_jd(client_with: ClientFactory) -> None:
    r = client_with(ScriptedProvider([])).post("/api/rubric", data={"jd_text": "   "})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "jd_missing"


def test_llm_unavailable_maps_to_503(client_with: ClientFactory) -> None:
    class Down(ScriptedProvider):
        async def chat_json(self, *a: object, **k: object) -> str:
            raise LLMUnavailableError("Cannot reach Ollama")

    r = client_with(Down([])).post("/api/rubric", data={"jd_text": "JD"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "llm_unavailable"


def test_models_endpoint(client_with: ClientFactory) -> None:
    r = client_with(ScriptedProvider([])).get("/api/models")
    assert r.status_code == 200
    assert r.json()["models"][0]["name"] == "fake:1b"


def test_config_endpoint_exposes_no_secrets(client_with: ClientFactory) -> None:
    body = client_with(ScriptedProvider([])).get("/api/config").json()
    assert body["max_file_mb"] > 0 and body["persist_resume_text"] is False
    assert "ollama_host" not in body and "database_url" not in body
