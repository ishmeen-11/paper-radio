from io import BytesIO
from fastapi.testclient import TestClient
import pytest
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas

from paper_radio import api, provider
from paper_radio.core import Chunk, Store, parse_pdf, retrieve, validate_claims


def pdf_bytes(pages):
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for text in pages:
        for i, line in enumerate(text.split("\n")):
            canvas.drawString(40, 760 - i * 16, line)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(api, "get_store", lambda: store)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return TestClient(api.app)


def upload(client, pages, name="paper.pdf", semantic=False):
    response = client.post("/papers", files={"file": (name, pdf_bytes(pages), "application/pdf")},
                           data={"semantic": str(semantic).lower()})
    assert response.status_code == 200, response.text
    return response.json()


def test_page_aware_chunks_cover_text_without_crossing_pages():
    data = pdf_bytes([" ".join(f"token{i}" for i in range(470)), "Limitations: Synthetic data only."])
    _, count, chunks, warnings = parse_pdf(data, "study.pdf")
    assert count == 2 and not warnings
    assert [c.page for c in chunks] == [1, 1, 1, 2]
    assert "token469" in chunks[2].text
    assert set(chunks[0].text.split()) & set(chunks[1].text.split())
    assert "Limitations" not in chunks[2].text


def test_invalid_and_scanned_pdf_are_actionable(client):
    response = client.post("/papers", files={"file": ("bad.pdf", b"not PDF", "application/pdf")})
    assert response.status_code == 422 and "not a PDF" in response.text
    response = client.post("/papers", files={"file": ("scan.pdf", pdf_bytes([""]), "application/pdf")})
    assert response.status_code == 422 and "OCR" in response.text


def test_encrypted_and_too_many_pages_are_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    data = BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="Password-protected"):
        parse_pdf(data.getvalue(), "secret.pdf")
    writer = PdfWriter()
    for _ in range(81):
        writer.add_blank_page(width=100, height=100)
    data = BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="1–80"):
        parse_pdf(data.getvalue(), "long.pdf")


def test_upload_deduplication_persistence_and_deletion(client):
    data = pdf_bytes(["Forecasting uses rolling evaluation."])
    first = client.post("/papers", files={"file": ("../study.pdf", data)}).json()
    second = client.post("/papers", files={"file": ("again.pdf", data)}).json()
    assert first["id"] == second["id"]
    assert first["filename"] == "study.pdf"
    assert len(Store(api.get_store().path.parent).list()) == 1
    assert client.get(f"/papers/{first['id']}/pdf").content == data
    assert client.delete(f"/papers/{first['id']}").status_code == 200
    assert client.get(f"/papers/{first['id']}/pdf").status_code == 404
    assert client.get("/papers").json() == []


def test_selection_scope_never_searches_other_papers(client, monkeypatch):
    first = upload(client, ["Forecasting used rolling backtesting."], "a.pdf")
    upload(client, ["The secret moonstone experiment measured lunar radiation."], "b.pdf")
    def forbidden(*args, **kwargs):
        pytest.fail("Local search must not call external models.")
    monkeypatch.setattr(provider, "embed", forbidden)
    monkeypatch.setattr(provider, "generate", forbidden)
    result = client.post("/ask", json={"question": "moonstone", "paper_ids": [first["id"]]}).json()
    assert result["mode"] == "insufficient_evidence" and not result["passages"]
    result = client.post("/ask", json={"question": "rolling", "paper_ids": [first["id"]]}).json()
    assert result["mode"] == "search"
    assert {p["paper_id"] for p in result["passages"]} == {first["id"]}


@pytest.mark.parametrize("body", [
    {"question": "test", "paper_ids": []},
    {"question": "  ", "paper_ids": ["x"]},
    {"question": "test", "paper_ids": ["x"], "top_k": 50},
])
def test_question_validation(client, body):
    assert client.post("/ask", json=body).status_code == 422


def test_missing_selected_paper_fails_instead_of_widening_scope(client):
    assert client.post("/ask", json={"question": "methods", "paper_ids": ["missing"]}).status_code == 404


def test_no_api_key_returns_clear_error_for_generated_answers(client):
    paper = upload(client, ["Methods used chronological backtesting."])
    response = client.post("/ask", json={"question": "methods", "paper_ids": [paper["id"]], "generate_answer": True})
    assert response.status_code == 422 and "OPENAI_API_KEY" in response.text


def test_cited_answer_uses_real_page_and_exact_quote(client, monkeypatch):
    paper = upload(client, ["Abstract: This is a synthetic study.", "Limitations: The study uses synthetic data only."])
    def generated(question, passages):
        source = next(p for p in passages if p["page"] == 2)
        return {"insufficient_evidence": False, "claims": [{"text": "The study uses synthetic data only.",
                "citations": [{"chunk_id": source["chunk_id"], "quote": "The study uses synthetic data only."}]}]}
    monkeypatch.setattr(provider, "generate", generated)
    result = client.post("/ask", json={"question": "limitations", "paper_ids": [paper["id"]], "generate_answer": True}).json()
    assert result["mode"] == "answer"
    assert result["sources"][0]["page"] == 2
    assert result["claims"][0]["citations"][0]["number"] == 1


@pytest.mark.parametrize("bad_quote,bad_id", [("Invented accuracy was 99 percent.", False), ("The sample is synthetic.", True)])
def test_invalid_citations_fail_closed(bad_quote, bad_id):
    passages = [{"chunk_id": "real", "text": "The sample is synthetic.", "page": 1}]
    draft = {"insufficient_evidence": False, "claims": [{"text": "Claim", "citations": [
        {"chunk_id": "invented" if bad_id else "real", "quote": bad_quote}]}]}
    assert validate_claims(draft, passages) == ([], [])


def test_any_uncited_claim_rejects_the_whole_answer():
    draft = {"insufficient_evidence": False, "claims": [{"text": "An unsupported statement", "citations": []}]}
    assert validate_claims(draft, []) == ([], [])


def test_model_abstention_is_preserved(client, monkeypatch):
    paper = upload(client, ["Methods: Forecasting uses chronological folds."])
    monkeypatch.setattr(provider, "generate", lambda *args: {"insufficient_evidence": True, "claims": []})
    result = client.post("/ask", json={"question": "methods cost", "paper_ids": [paper["id"]], "generate_answer": True}).json()
    assert result["mode"] == "insufficient_evidence"
    assert not result["claims"]


def test_hybrid_retrieves_synonym_with_faiss():
    chunks = [Chunk("a", "p", "paper.pdf", 1, "The automobile moved.", [1., 0.], "test"),
              Chunk("b", "p", "paper.pdf", 2, "Flowers bloom in spring.", [0., 1.], "test")]
    assert retrieve("car", chunks) == []
    result = retrieve("car", chunks, top_k=1, query_vector=[1., 0.], embedding_model="test")
    assert result[0]["chunk_id"] == "a"


def test_hybrid_api_indexes_and_reuses_persisted_vectors(client, monkeypatch):
    calls = []
    def embedded(texts):
        calls.append(texts)
        return [[1., 0.] for _ in texts]
    monkeypatch.setattr(provider, "embed", embedded)
    monkeypatch.setattr(provider, "embedding_model", lambda: "test-model")
    paper = upload(client, ["Methods use chronological forecasting."], semantic=True)
    assert paper["semantic_indexed"]
    result = client.post("/ask", json={"question": "prediction", "paper_ids": [paper["id"]], "retrieval": "hybrid"})
    assert result.status_code == 200
    assert result.json()["passages"][0]["paper_id"] == paper["id"]
    assert len(calls) == 2
    monkeypatch.setattr(provider, "embedding_model", lambda: "new-model")
    response = client.post("/ask", json={"question": "prediction", "paper_ids": [paper["id"]], "retrieval": "hybrid"})
    assert response.status_code == 422 and len(calls) == 2


def test_hybrid_does_not_silently_use_unembedded_papers(client):
    paper = upload(client, ["Methods use chronological forecasting."])
    response = client.post("/ask", json={"question": "prediction", "paper_ids": [paper["id"]], "retrieval": "hybrid"})
    assert response.status_code == 422 and "semantic indexing" in response.text


def test_health_does_not_return_credentials(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-value")
    response = client.get("/health")
    assert response.json()["answers_configured"] is True
    assert "secret-test-value" not in response.text


def test_custom_ui_and_assets_are_served_without_streamlit(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Paper Radio" in response.text
    assert 'id="askForm"' in response.text
    assert "streamlit" not in response.text.lower()
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/style.css").headers["content-type"].startswith("text/css")
    demo = client.get("/demo.pdf")
    assert demo.status_code == 200 and demo.content.startswith(b"%PDF-")


def test_upload_size_limit_before_parsing(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_BYTES", 10)
    response = client.post("/papers", files={"file": ("large.pdf", b"%PDF-" + b"x" * 20)})
    assert response.status_code == 413
    assert client.get("/papers").json() == []


def test_partially_blank_pdf_preserves_physical_page_numbers():
    _, count, chunks, warnings = parse_pdf(pdf_bytes(["", "Methods use rolling evaluation."]), "partial.pdf")
    assert count == 2 and chunks[0].page == 2
    assert warnings and "pages: 1" in warnings[0]


@pytest.mark.parametrize("question", ["What kind of data?", "what is this paper about? explain in ez lang"])
def test_provider_uses_current_sdk_structured_parsing_without_live_calls(monkeypatch, question):
    import json
    import httpx2
    from openai import OpenAI
    payload = {"insufficient_evidence": False, "claims": [{"text": "The data are synthetic.",
               "citations": [{"chunk_id": "chunk1", "quote": "The data are synthetic."}]}]}
    seen = []
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body["response_format"]["type"] == "json_schema"
        assert body["store"] is False
        assert "untrusted" in body["messages"][0]["content"]
        assert "Write in clear everyday language" in body["messages"][0]["content"]
        if "paper about" in question:
            assert "paper overview" in body["messages"][0]["content"]
            assert "main idea first" in body["messages"][0]["content"]
        return httpx2.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
            "model": "gpt-4.1-mini", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload)}, "finish_reason": "stop"}],
        })
    with OpenAI(api_key="test-key", http_client=httpx2.Client(transport=httpx2.MockTransport(handler), trust_env=False)) as sdk:
        monkeypatch.setattr(provider, "client", lambda: sdk)
        result = provider.generate(question, [{"chunk_id": "chunk1", "text": "The data are synthetic."}])
    assert result == payload and len(seen) == 1


@pytest.mark.parametrize("question", [
    "what is this paper about.",
    "what is this paper about? explain in ez lang",
    "Explain this paper in simple words",
    "Summarize the paper",
    "What are the main contributions of this paper?",
])
def test_overview_questions_route_to_document_context(question):
    from paper_radio.core import question_intent
    assert question_intent(question) == "overview"


@pytest.mark.parametrize("question", [
    "What does the paper say about amplitude noise?",
    "Explain the three-tangle equation in easy language",
    "What is this paper's sample size?",
    "How was the model evaluated?",
])
def test_specific_questions_do_not_become_generic_summaries(question):
    from paper_radio.core import question_intent
    assert question_intent(question) == "specific"


def test_overview_prioritizes_abstract_and_conclusion_over_generic_word_matches():
    from paper_radio.core import section_hint
    chunks = [
        Chunk("p:p1:c0", "p", "synthetic.pdf", 1,
              "SYNTHETIC TEST. Abstract—We compare a small summary of a toy state with its full representation."),
        Chunk("p:p2:c0", "p", "synthetic.pdf", 2,
              "I. I NTRODUCTION This toy study asks whether simpler features preserve classification quality."),
        Chunk("p:p3:c0", "p", "synthetic.pdf", 3,
              "III. M ETHODOLOGY We compare the two feature sets on controlled synthetic examples."),
        Chunk("p:p5:c0", "p", "synthetic.pdf", 5,
              " ".join(["This paper about a paper is a paper."] * 60)),
        Chunk("p:p6:c0", "p", "synthetic.pdf", 6,
              "VII. C ONCLUSION The smaller representation loses information about one state family."),
        Chunk("p:p7:c0", "p", "synthetic.pdf", 7,
              "REFERENCES [1] Abstract Algebra. [2] A paper about a paper."),
    ]
    results = retrieve("what is this paper about? explain in ez lang", chunks, top_k=4)
    assert results[0]["page"] == 1
    assert results[1]["page"] == 6
    assert {p["selection_reason"] for p in results} >= {"abstract", "conclusion"}
    assert all(p["page"] not in (5, 7) for p in results)
    assert section_hint(chunks[-1].text) == "references"


def test_overview_api_works_on_existing_collection_without_embeddings(client, monkeypatch):
    paper = upload(client, [
        "Abstract: This synthetic study compares two toy forecasting representations.",
        "Methods: We use chronological holdout evaluation.",
        "VII. Conclusion: The smaller representation misses a synthetic seasonal pattern.",
    ])
    def forbidden(*args, **kwargs):
        pytest.fail("A broad overview must not require an embedding API call.")
    monkeypatch.setattr(provider, "embed", forbidden)
    result = client.post("/ask", json={"question": "what is this paper about? explain in ez lang",
                        "paper_ids": [paper["id"]], "retrieval": "hybrid"}).json()
    assert result["intent"] == "overview"
    assert result["strategy"] == "overview"
    assert result["passages"][0]["page"] == 1
    assert result["passages"][1]["page"] == 3
    assert result["mode"] == "search"  # Retrieval must not masquerade as generation.


def test_overview_retrieval_keeps_one_paper_from_crowding_out_another():
    chunks = [
        Chunk("a:p1:c0", "a", "a.pdf", 1, "Abstract: Synthetic topic A."),
        Chunk("a:p2:c0", "a", "a.pdf", 2, "VII. Conclusion: Topic A has a limitation."),
        Chunk("b:p1:c0", "b", "b.pdf", 1, "Abstract: Synthetic topic B."),
        Chunk("b:p2:c0", "b", "b.pdf", 2, "VII. Conclusion: Topic B has another limitation."),
    ]
    results = retrieve("summarize the papers", chunks, top_k=2)
    assert {p["paper_id"] for p in results} == {"a", "b"}


def test_generic_paper_word_does_not_drive_specific_keyword_ranking():
    chunks = [
        Chunk("a", "p", "p.pdf", 1, "paper paper paper paper paper"),
        Chunk("b", "p", "p.pdf", 2, "Noise affects calibration of a measured state."),
    ]
    assert retrieve("What does this paper say about noise?", chunks)[0]["chunk_id"] == "b"
    assert len(retrieve("What does this paper say about noise?", chunks)) == 1
