"""Shared test helpers. The LLM is always faked; tests never need Ollama."""
import io
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from typing import Any

# Must happen before the app (and its settings) are imported: isolate tests from backend/.env.
_TMP = tempfile.mkdtemp(prefix='shortlister-test-')
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["PERSIST_RESUME_TEXT"] = "false"
# Tests share one database; the cache would leak results between them. Cache tests turn it on explicitly.
os.environ["LLM_CACHE_ENABLED"] = "false"
# API tests call routes directly; test_auth.py turns sign-in tokens back on.
os.environ["AUTH_REQUIRED"] = "false"

import pytest
from docx import Document
from fastapi.testclient import TestClient

from models.schemas import ModelInfo
from services.llm.base import ChatMessage, LLMProvider


def make_pdf(lines: list[str]) -> bytes:
    """Build a minimal valid single-page PDF; an empty list gives a blank (scanned-like) page."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = "".join(f"({esc(line)}) Tj T* " for line in lines)
    stream = f"BT /F1 11 Tf 14 TL 72 740 Td {ops}ET".encode() if lines else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    if table:
        t = doc.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, val in enumerate(row):
                t.cell(r, c).text = val
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class ScriptedProvider(LLMProvider):
    """Fake provider returning queued raw responses (or computing them from the request)."""

    name = "scripted"

    def __init__(self, responses: list[str | dict[str, Any] | Callable[[list[ChatMessage]], str]]) -> None:
        self.responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    async def chat_json(self, messages: list[ChatMessage], json_schema: dict[str, Any], *, model: str,
                        temperature: float = 0.0, num_ctx: int | None = None) -> str:
        self.calls.append(messages)
        r = self.responses.pop(0)
        if callable(r):
            return r(messages)
        return r if isinstance(r, str) else json.dumps(r)

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="fake:1b")]


@pytest.fixture
def client_with() -> Iterator[Callable[[LLMProvider], TestClient]]:
    """Yield a factory producing a TestClient whose app uses the given provider."""
    from app.main import app

    clients: list[TestClient] = []

    def factory(provider: LLMProvider) -> TestClient:
        c = TestClient(app)
        c.__enter__()  # run lifespan, then swap in the fake provider
        app.state.provider = provider
        app.state.jobs._provider = provider
        clients.append(c)
        return c

    yield factory
    for c in clients:
        c.__exit__(None, None, None)
