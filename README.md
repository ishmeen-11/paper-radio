# Paper Radio

A quiet workspace for thinking with research papers. Upload a PDF, ask a question, and follow the evidence back to the original page.

**Version 0.3:** a custom HTML/CSS/JavaScript interface served by FastAPI. No frontend build, Node installation, or separate UI server is required to run the app.

## Start on your Mac

**Unzip the project and double-click `Start-Paper-Radio.command`.** The launcher creates the environment, installs all dependencies, and opens the app in your browser. Keep the Terminal window open while using Paper Radio; press Ctrl+C to stop it.

Python 3.11+ must already be installed. The first launch needs an internet connection to install dependencies. Later launches reuse the environment and repair missing packages automatically. Existing `.env` settings and uploaded papers are preserved. If the default port is occupied, the launcher chooses another available local port.

For Terminal users, `python launch.py` performs the same setup and launch. `python launch.py --no-browser` starts without opening a browser.

### Manual setup

Use **Python 3.11+**. Unzip the project, open Terminal inside `paper-radio`, and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python run.py
```

Open **http://127.0.0.1:8000**. The custom UI and the RAG API run in one process. Press Ctrl+C to stop. To use another port, run `python run.py --port 8001`.

1. Click **Or try a demo**, or use **Add papers** to upload text-based PDFs.
2. Check the papers you want to search in the library.
3. Click a suggested question, or write your own in the question box.
4. Click a passage or citation to open the original PDF beside the conversation.
5. Use the **Passages / Paper reader** tabs and page arrows to inspect the evidence.

The demo is a clearly labeled synthetic test document. Its numerical values are invented, not research findings. Without an API key, the app provides real local passage search; it does not generate an AI answer.

## The interface

- Paper library with filename filtering, multi-paper selection, and direct PDF access.
- PDF uploads through a file picker or drag and drop; optional semantic indexing during upload.
- Conversation-style question history with independent questions and per-question paper scope.
- Clear **Search passages / Ask AI** modes. Passage results offer **Get a cited explanation** when configured, or **Set up AI explanations** when a key is missing. AI is an explicit opt-in choice.
- Clickable source cards, numbered AI citations, original PDF page links, and a side-by-side reader.
- New conversation action that clears visible history while preserving your paper collection.
- JSON exports through **Save result**, including the question and selected paper IDs.
- Responsive mobile library and reader panels, keyboard controls, upload progress, and actionable error states.
- All application assets are local. There are no third-party fonts, analytics scripts, or browser-side API keys.

The paper collection is stored on disk. Selection is remembered in browser local storage. Conversation history is kept in memory for the current page only; a reload clears it. Each question is independent and is not sent with prior chat history.

## Enable AI answers and semantic search

Edit `.env`:

```dotenv
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Restart the app, then choose **Ask AI** beside the question box. API usage has separate billing from ChatGPT subscriptions. You may select another model you can access that supports structured outputs.

For semantic retrieval, enable **semantic search** in the upload dialog and upload each PDF again. Once every selected paper is indexed, choose **Semantic + keyword** in the question box. Changing the embedding model requires re-indexing.

**What leaves your computer:** AI answers send your question and the retrieved passages to OpenAI. Semantic indexing sends extracted paper text to OpenAI for embeddings; hybrid queries also send the question for embedding. Local keyword search makes no model API calls. Keys remain on the Python server and are never returned to the browser. Never commit a real `.env` file.

## The RAG pipeline

1. Extract PDF text page by page and split into 220-word chunks with 40-word overlap, keeping physical page numbers.
2. Persist PDFs, chunks, metadata, and optional embeddings in `.data/papers.sqlite3`. Identical bytes share a content-derived paper ID.
3. Retrieve only from selected papers. Broad overview questions prioritize opening context, an abstract when detected, and conclusions before methods/results. Specific questions use BM25 by default, or combine BM25 with FAISS cosine rankings using reciprocal rank fusion. Generic request words such as paper, about, and explain do not drive keyword rankings.
4. Optionally send retrieved chunks to the model and request structured claims with citation IDs and exact supporting quotes. Overview prompts request a clear main idea, approach, takeaway, and caveat in everyday language. The usual budget is six chunks; a multi-paper overview may use up to 20 to include at least one passage per selected paper.
5. Reject the full generated answer if any claim lacks citations, a source ID is unknown, or a quote fails to match its chunk after whitespace normalization.
6. Display the evidence, original PDF page, retrieval mode, and elapsed time.

Citation checks verify source identity and quote integrity. They **do not prove that a quote logically supports the entire claim**. The model may still introduce unsupported reasoning; review the sources. Empty retrieval does not prove the full paper lacks an answer. See `EVALUATION.md` for the next real-paper benchmark.

## Files

| File | Purpose |
| --- | --- |
| `web/index.html` | Custom app layout and accessible controls |
| `web/style.css` | Responsive visual design |
| `web/app.js` | Uploads, paper selection, questions, citations, and PDF reader |
| `paper_radio/api.py` | API endpoints and same-origin frontend serving |
| `paper_radio/core.py` | PDF parsing, SQLite, retrieval, and citation validation |
| `paper_radio/provider.py` | Optional external model calls |
| `run.py` | One-command startup |
| `launch.py` | First-run setup, dependency checks, browser launch, and server shutdown |
| `Start-Paper-Radio.command` | Double-click launcher for macOS |
| `examples/demo_paper.pdf` | Synthetic demo document |
| `tests/` | Backend and optional JavaScript DOM integration checks |

API documentation is available at **http://127.0.0.1:8000/docs** while the app runs. An existing paper can be removed with `DELETE /papers/{paper_id}` through the API documentation. The UI does not delete papers.

## Checks

Backend:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Optional interface integration checks require Node 22+:

```bash
npm install
npm test
```

The UI tests start a temporary real Python API, exercise the custom JavaScript through a simulated DOM, and clean up the temporary collection. They make no paid API calls. A generated-answer UI fixture tests citation rendering separately from real model behavior. See `VALIDATION.md` for the exact validation scope.

## Scope

Local, single-user prototype; keep the server bound to `127.0.0.1`. Shared hosting needs authentication, collection ownership, upload isolation, and rate limits before deployment.

Limits: 20 MB, 80 pages, and 1,000 text chunks per PDF; up to 20 selected papers per question. Text-based PDFs only. Scans need OCR before upload. Figures, tables, equations, and multi-column layouts may not extract reliably. Empty pages generate warnings, but not every missing fragment can be detected.

Not yet included: paper URL ingestion, audio, follow-up conversation memory, automatic paper discovery, reranking, and Eve orchestration. The FAISS index is rebuilt in memory for each hybrid question, which suits a small reading collection.

## References

- https://fastapi.tiangolo.com/tutorial/request-files/
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/embeddings
- https://pypdf.readthedocs.io/en/stable/user/extract-text.html

## Updating an existing installation

Stop the app with Ctrl+C. Merge the new source files into your existing `paper-radio` folder, preserving `.env`, `.venv`, and `.data`. The SQLite format is unchanged; existing uploaded papers work without re-uploading.

For the standard Downloads location, use Terminal extraction rather than replacing the entire folder in Finder:

```bash
unzip -o "/full/path/to/the/new/paper-radio-starter.zip" -d ~/Downloads
cd ~/Downloads/paper-radio
source .venv/bin/activate
python run.py
```

Replace the quoted ZIP path with your actual newly downloaded file. This source archive contains no `.env`, `.venv`, or `.data`, so `unzip -o` preserves those existing files and directories. No additional Python dependencies were added in version 0.3.

For a generated explanation, choose **Ask AI** or **Get a cited explanation**. If it is unavailable, put your own `OPENAI_API_KEY` into `.env` and restart the server. Passage search remains available without an API key.
