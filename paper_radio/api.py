"""Local-only API. Run from the project root with uvicorn paper_radio.api:app."""

from functools import lru_cache
import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from pydantic import BaseModel, Field, field_validator

from paper_radio.core import Store, parse_pdf, question_intent, retrieve, validate_claims
from paper_radio import provider

load_dotenv()
logger = logging.getLogger(__name__)
app = FastAPI(title="Paper Radio", version="0.3.0", description="A local, single-user research paper reader.")
MAX_BYTES = 20 * 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parent.parent
app.mount("/assets", StaticFiles(directory=PROJECT_ROOT / "web"), name="assets")


@app.get("/", include_in_schema=False)
def interface():
    return FileResponse(PROJECT_ROOT / "web" / "index.html")


@app.get("/demo.pdf", include_in_schema=False)
def demo_pdf():
    return FileResponse(PROJECT_ROOT / "examples" / "demo_paper.pdf", media_type="application/pdf")


@lru_cache
def get_store() -> Store:
    return Store(Path(os.getenv("PAPER_RADIO_DATA_DIR", ".data")))


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=3000)
    paper_ids: list[str] = Field(min_length=1, max_length=20)
    retrieval: Literal["lexical", "hybrid"] = "lexical"
    generate_answer: bool = False
    top_k: int = Field(default=6, ge=1, le=12)

    @field_validator("question")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Enter a question.")
        return value.strip()


@app.get("/health")
def health():
    return {"status": "ok", "answers_configured": provider.configured(), "version": "0.3.0"}


@app.get("/papers")
def papers():
    return get_store().list()


@app.post("/papers")
def upload(file: UploadFile = File(...), semantic: bool = Form(False)):
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "PDF exceeds the 20 MB limit.")
    filename = (file.filename or "paper.pdf").replace("\\", "/").rsplit("/", 1)[-1][:200]
    try:
        paper_id, page_count, chunks, warnings = parse_pdf(data, filename)
        existing = next((p for p in get_store().list() if p["id"] == paper_id), None)
        if existing and not semantic:
            return existing
        if semantic:
            vectors = provider.embed([chunk.text for chunk in chunks])
            if len(vectors) != len(chunks):
                raise ValueError("The embedding provider returned an incomplete result. Try again.")
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding = vector
                chunk.embedding_model = provider.embedding_model()
        get_store().put(paper_id, filename, page_count, chunks, warnings, data)
        return next(p for p in get_store().list() if p["id"] == paper_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OpenAIError as exc:
        logger.warning("Embedding request failed (%s)", type(exc).__name__)
        raise HTTPException(502, "Embedding request failed. Check the API key, model access, billing, and connection.") from exc


@app.get("/papers/{paper_id}/pdf")
def pdf(paper_id: str):
    try:
        return Response(get_store().pdf(paper_id), media_type="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="paper.pdf"'})
    except KeyError as exc:
        raise HTTPException(404, "Paper not found.") from exc


@app.delete("/papers/{paper_id}")
def delete(paper_id: str):
    if not get_store().delete(paper_id):
        raise HTTPException(404, "Paper not found.")
    return {"deleted": paper_id}


@app.post("/ask")
def ask(request: Ask):
    start = perf_counter()
    try:
        chunks = get_store().get_chunks(request.paper_ids)
        intent = question_intent(request.question)
        vector = None
        if request.retrieval == "hybrid" and intent != "overview":
            if any(c.embedding is None or c.embedding_model != provider.embedding_model() for c in chunks):
                raise ValueError("Re-upload all selected PDFs with semantic indexing enabled using the current embedding model.")
            vector = provider.embed([request.question])[0]
        budget = max(request.top_k, len(set(request.paper_ids))) if intent == "overview" else request.top_k
        passages = retrieve(request.question, chunks, budget, vector, provider.embedding_model())
        claims, sources = [], []
        mode = "search"
        message = "Retrieved passages only. No generated answer was requested."
        if not passages:
            mode = "insufficient_evidence"
            message = "No matching passages were found. Try another wording or semantic search."
        elif request.generate_answer:
            draft = provider.generate(request.question, passages)
            claims, sources = validate_claims(draft, passages)
            mode = "answer" if claims else "insufficient_evidence"
            message = ("Quotes and source IDs checked. Review whether the evidence supports each claim."
                       if claims else "I couldn't produce an answer supported by valid citations from the retrieved passages.")
        return {"mode": mode, "message": message, "claims": claims, "sources": sources,
                "passages": passages, "retrieval": request.retrieval,
                "intent": intent, "strategy": "overview" if intent == "overview" else request.retrieval,
                "elapsed_ms": round((perf_counter() - start) * 1000)}
    except KeyError as exc:
        raise HTTPException(404, "A selected paper was removed. Refresh and select your papers again.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OpenAIError as exc:
        logger.warning("Model request failed (%s)", type(exc).__name__)
        raise HTTPException(502, "Model request failed. Check your API key, model access, billing, and connection.") from exc
