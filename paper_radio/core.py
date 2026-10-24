"""Page-aware PDF parsing, lexical/hybrid retrieval, and citation checks."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
import json
import math
import re
import sqlite3
from pathlib import Path

import numpy as np
from pypdf import PdfReader

STOPWORDS = set("a an and are as at be by do does for from how i in is it of on or that the this to was were what which with you your about paper papers explain simple simply easy ez language lang please pls tell give summarize summary overview".split())


def question_intent(question: str) -> str:
    """Recognize broad paper overviews without swallowing topic-specific questions."""
    text = re.sub(r"[^a-z0-9'\s]", " ", question.lower())
    text = re.sub(r"\b(?:explain\s+)?(?:it\s+)?in\s+(?:simple|easy|ez|plain)\s+(?:language|lang|terms|words|english)\b", " ", text)
    text = re.sub(r"\b(?:please|pls)\b", " ", text)
    text = normalize(text)
    paper = r"(?:(?:this|the|that|selected|uploaded)\s+)?(?:paper|papers|article|study)"
    patterns = [
        rf"(?:what is|what's|whats|what are)\s+{paper}\s+about",
        rf"what does\s+{paper}\s+(?:do|discuss|cover|study|investigate|contribute)",
        rf"(?:explain|describe|summari[sz]e)\s+{paper}(?:\s+simply)?",
        rf"(?:give me\s+)?(?:a |an )?(?:summary|overview)(?:\s+of\s+{paper})?",
        rf"(?:what (?:is|are)\s+)?(?:the )?(?:main|key|central)\s+(?:idea|ideas|contribution|contributions|takeaway|takeaways|purpose|message)(?:\s+of\s+{paper})?",
    ]
    return "overview" if any(re.fullmatch(pattern, text) for pattern in patterns) else "specific"


def section_hint(text: str) -> str | None:
    """Recover common section labels, including IEEE's spaced initial capitals.

    This operates on existing stored chunks, so old collections need no re-upload.
    It is a heuristic; prose references to a section can still be ambiguous.
    """
    names = {"abstract": r"a\s*bstract", "introduction": r"i\s*ntroduction",
             "conclusion": r"c\s*onclusions?", "discussion": r"d\s*iscussion",
             "methods": r"m\s*ethod(?:s|ology)?", "results": r"r\s*esults",
             "references": r"r\s*eferences"}
    matches = []
    for name, pattern in names.items():
        numbered = rf"\b(?:[ivx]+|\d+)[.)]\s*{pattern}\b"
        leading = rf"^\s*{pattern}\b"
        for match in re.finditer(rf"{numbered}|{leading}", text, re.I):
            matches.append((match.start(), name))
    abstract = re.search(r"\ba\s*bstract\b", text[:1200], re.I)
    if abstract:
        matches.append((abstract.start(), "abstract"))
    return min(matches)[1] if matches else None


def overview_passages(chunks: list[Chunk], top_k: int) -> list[dict]:
    """Cover the beginning, main takeaway, and approach instead of generic BM25 hits."""
    grouped = {}
    for chunk in chunks:
        grouped.setdefault(chunk.paper_id, []).append(chunk)
    queues = []
    reasons = {}
    for paper_chunks in grouped.values():
        ordered = sorted(paper_chunks, key=lambda c: (c.page, int(c.id.rsplit(":c", 1)[-1]) if ":c" in c.id else 0))
        hints = {c.id: section_hint(c.text) for c in ordered}
        candidates = []
        def add(chunk, reason):
            if chunk.id not in reasons:
                candidates.append(chunk)
                reasons[chunk.id] = reason
        abstracts = [c for c in ordered if hints[c.id] == "abstract" and c.page <= ordered[0].page + 1]
        for chunk in abstracts[:1]:
            add(chunk, "abstract")
        add(ordered[0], "first page")
        # A numbered conclusion beats a generic match to the word 'paper'.
        for chunk in ordered:
            if hints[chunk.id] == "conclusion":
                add(chunk, "conclusion")
        # Give an abstract that crosses a chunk boundary its immediate continuation.
        if abstracts:
            pos = ordered.index(abstracts[0])
            if pos + 1 < len(ordered) and ordered[pos + 1].page == abstracts[0].page:
                add(ordered[pos + 1], "abstract continuation")
        for heading in ("introduction", "methods", "results", "discussion"):
            match = next((c for c in ordered if hints[c.id] == heading), None)
            if match:
                add(match, heading)
        content = [c for c in ordered if hints[c.id] != "references"]
        if content:
            add(content[-1], "closing content")
        for chunk in content:
            add(chunk, "supporting context")
        queues.append(candidates)
    selected = []
    # Round-robin selection prevents one paper from occupying every overview slot.
    while len(selected) < top_k and any(queues):
        for queue in queues:
            if queue and len(selected) < top_k:
                selected.append(queue.pop(0))
    return [{"chunk_id": c.id, "paper_id": c.paper_id, "filename": c.filename,
             "page": c.page, "text": c.text, "score": round(1 / (rank + 1), 5),
             "selection_reason": reasons[c.id]} for rank, c in enumerate(selected)]


def tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOPWORDS]


def normalize(text: str) -> str:
    return " ".join(text.split())


@dataclass
class Chunk:
    id: str
    paper_id: str
    filename: str
    page: int
    text: str
    embedding: list[float] | None = None
    embedding_model: str | None = None


def parse_pdf(data: bytes, filename: str) -> tuple[str, int, list[Chunk], list[str]]:
    if not data.startswith(b"%PDF-"):
        raise ValueError("This file is not a PDF. Upload the original PDF file.")
    paper_id = sha256(data).hexdigest()[:24]
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("Password-protected PDFs are not supported. Upload an unlocked copy.")
        page_count = len(reader.pages)
        if not 1 <= page_count <= 80:
            raise ValueError("Upload a PDF with 1–80 pages for this first version.")
        chunks, skipped = [], []
        for page_number, page in enumerate(reader.pages, 1):
            words = (page.extract_text() or "").split()
            if not words:
                skipped.append(page_number)
                continue
            # Every chunk belongs to one physical PDF page; page numbers never drift.
            for start in range(0, len(words), 180):
                text = " ".join(words[start:start + 220])
                chunks.append(Chunk(f"{paper_id}:p{page_number}:c{start // 180}", paper_id,
                                    filename, page_number, text))
                if len(chunks) > 1000:
                    raise ValueError("This PDF has too much text for the first version (1,000 chunks max).")
                if start + 220 >= len(words):
                    break
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Could not read this PDF. Try an unlocked, text-based PDF.") from exc
    if not chunks:
        raise ValueError("No text was found. Scanned PDFs need OCR before upload; OCR is not included yet.")
    warnings = []
    if skipped:
        warnings.append(f"No extractable text on PDF pages: {', '.join(map(str, skipped))}. These pages were skipped.")
    return paper_id, page_count, chunks, warnings


class Store:
    """One local collection. PDFs and chunks are committed in the same transaction."""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "papers.sqlite3"
        with self.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, page_count INTEGER NOT NULL,
                chunks_json TEXT NOT NULL, warnings_json TEXT NOT NULL, pdf BLOB NOT NULL)""")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def metadata(row) -> dict:
        chunks = json.loads(row["chunks_json"])
        return {"id": row["id"], "filename": row["filename"], "page_count": row["page_count"],
                "chunk_count": len(chunks), "semantic_indexed": bool(chunks) and all(c["embedding"] is not None for c in chunks),
                "warnings": json.loads(row["warnings_json"])}

    def list(self) -> list[dict]:
        with self.connect() as conn:
            return [self.metadata(row) for row in conn.execute(
                "SELECT id, filename, page_count, chunks_json, warnings_json FROM papers ORDER BY rowid DESC")]

    def put(self, paper_id, filename, page_count, chunks, warnings, data):
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO papers VALUES (?, ?, ?, ?, ?, ?)",
                         (paper_id, filename, page_count, json.dumps([asdict(c) for c in chunks]), json.dumps(warnings), data))

    def get_chunks(self, paper_ids: list[str]) -> list[Chunk]:
        if not paper_ids:
            raise ValueError("Select at least one paper.")
        chunks = []
        with self.connect() as conn:
            for paper_id in dict.fromkeys(paper_ids):
                row = conn.execute("SELECT chunks_json FROM papers WHERE id = ?", (paper_id,)).fetchone()
                if row is None:
                    raise KeyError(paper_id)
                chunks.extend(Chunk(**item) for item in json.loads(row["chunks_json"]))
        return chunks

    def pdf(self, paper_id: str) -> bytes:
        with self.connect() as conn:
            row = conn.execute("SELECT pdf FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise KeyError(paper_id)
        return row["pdf"]

    def delete(self, paper_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,)).rowcount > 0


def lexical_scores(question: str, chunks: list[Chunk]) -> np.ndarray:
    """BM25 baseline. No model, key, network, or corpus download required."""
    docs = [Counter(tokens(chunk.text)) for chunk in chunks]
    scores = np.zeros(len(docs), dtype=np.float32)
    lengths = [sum(doc.values()) for doc in docs]
    average = sum(lengths) / max(len(lengths), 1) or 1
    for term in set(tokens(question)):
        document_frequency = sum(term in doc for doc in docs)
        idf = math.log(1 + (len(docs) - document_frequency + 0.5) / (document_frequency + 0.5))
        for i, doc in enumerate(docs):
            frequency = doc[term]
            denominator = frequency + 1.5 * (0.25 + 0.75 * lengths[i] / average)
            scores[i] += idf * frequency * 2.5 / denominator
    return scores


def retrieve(question: str, chunks: list[Chunk], top_k: int = 6,
             query_vector: list[float] | None = None, embedding_model: str | None = None) -> list[dict]:
    if question_intent(question) == "overview":
        return overview_passages(chunks, top_k)
    scores = lexical_scores(question, chunks)
    lexical_order = sorted((i for i, score in enumerate(scores) if score > 0),
                           key=lambda i: float(scores[i]), reverse=True)
    if query_vector is None:
        order = lexical_order[:top_k]
        rank_scores = {i: float(scores[i]) for i in order}
    else:
        if not chunks or any(c.embedding is None or c.embedding_model != embedding_model for c in chunks):
            raise ValueError("Re-upload all selected PDFs with semantic indexing enabled using the current embedding model.")
        import faiss
        vectors = np.ascontiguousarray([c.embedding for c in chunks], dtype=np.float32)
        query = np.ascontiguousarray([query_vector], dtype=np.float32)
        if vectors.shape[1] != query.shape[1]:
            raise ValueError("Embedding dimensions changed. Re-upload these PDFs with semantic indexing enabled.")
        faiss.normalize_L2(vectors)
        faiss.normalize_L2(query)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        _, indices = index.search(query, min(20, len(chunks)))
        # Reciprocal rank fusion avoids comparing BM25 values with cosine values.
        rank_scores = {}
        for ranking in (lexical_order[:20], indices[0].tolist()):
            for rank, i in enumerate(ranking, 1):
                rank_scores[i] = rank_scores.get(i, 0.0) + 1 / (60 + rank)
        order = sorted(rank_scores, key=rank_scores.get, reverse=True)[:top_k]
    return [{"chunk_id": chunks[i].id, "paper_id": chunks[i].paper_id,
             "filename": chunks[i].filename, "page": chunks[i].page,
             "text": chunks[i].text, "score": round(rank_scores[i], 5)} for i in order]


def validate_claims(draft: dict, passages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Fail closed if any claim lacks a real chunk and an exact supporting quote.

    This checks citation integrity, not whether the quote logically proves a claim.
    That distinction is deliberately documented and exposed in the interface.
    """
    if draft.get("insufficient_evidence") or not draft.get("claims"):
        return [], []
    known = {passage["chunk_id"]: passage for passage in passages}
    claims, sources = [], {}
    for claim in draft["claims"]:
        citations = claim.get("citations", [])
        if not claim.get("text", "").strip() or not citations:
            return [], []
        checked = []
        for citation in citations:
            source = known.get(citation["chunk_id"])
            quote = normalize(citation["quote"])
            if source is None or len(quote) < 12 or quote not in normalize(source["text"]):
                return [], []
            source_id = citation["chunk_id"]
            if source_id not in sources:
                sources[source_id] = {**source, "number": len(sources) + 1}
            checked.append({"number": sources[source_id]["number"], "quote": quote})
        claims.append({"text": claim["text"], "citations": checked})
    return claims, list(sources.values())
