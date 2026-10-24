# Validation of version 0.3

Validated on October 24, 2026, with Python 3.12.14 and Node 24.19.0 on Linux.

## Backend

`python -m pytest -q`: **43 passed**.

Coverage includes page-aware chunks and overlap; invalid, scanned, password-protected, oversized, and partially blank PDFs; content-based deduplication; SQLite persistence; original PDF delivery and deletion; selected-paper isolation; question validation; missing API keys; valid cited answers; rejection of invented quotes, unknown source IDs, and uncited claims; model abstention; real FAISS ranking with controlled vectors; persisted semantic vectors and embedding-model mismatch; credential-free health responses; current OpenAI SDK structured parsing through mocked HTTP; and delivery of the custom UI, JavaScript, CSS, and synthetic demo.

Additional version 0.3 checks cover the reported questions `what is this paper about.` and `what is this paper about? explain in ez lang`; broad versus topic-specific routing; abstract and IEEE-style conclusion priority over generic paper-word distractors; reference exclusion; selected-paper fairness; overview retrieval from existing stored chunks without an embedding call; and plain-language overview instructions through the mocked SDK. These are synthetic regression checks, not measurements on the user's real quantum paper.

## Custom interface

`npm test`: **11 passed** using jsdom against a temporary real Python API, with no paid model calls:

1. Empty collection, disabled send button, and accurate AI setup state.
2. Demo upload through real PDF extraction and SQLite persistence.
3. Question submission and display of the actual limitations passage from PDF page 3.
4. Source clicks, original PDF response, paper reader URLs, and page navigation.
5. Selected-paper controls, query availability, and library filtering.
6. Clear behavior when no matching evidence is found.
7. New conversation clears messages while preserving papers.
8. Untrusted uploaded filenames render as text, without HTML execution.
9. AI setup is offered directly from passage results without pretending local search is generation.
10. The reported overview question retrieves the opening abstract context.
11. A controlled generated-answer fixture renders numbered citations and opens the matching quote and PDF page. This fixture does not call a live model.

The UI JavaScript also passes `node --check`.

## Startup and visual checks

- `python run.py --port 18379`: the custom UI, assets, and API health endpoint respond from one server; shutdown completes.
- Fresh-copy `python launch.py --no-browser`: created a new virtual environment, installed the complete requirements file, created the local config, and served the UI and API successfully. The startup process shut down cleanly.
- Desktop layout reviewed in the browser at approximately 1364 × 937.
- Responsive layout reviewed inside a 390 × 844 browser frame, including the mobile composer controls.
- Upload and settings dialogs opened and inspected.

The browser's visual preview used an empty-collection static fixture because its sandbox could not start the local Python virtual environment. Upload/query integration was verified separately by the DOM tests against the real API. Native PDF bytes and page URLs were checked; the browser's built-in PDF rendering was not exercised with a live Python backend in that visual preview.

## Remaining validation

Six launcher regressions cover full requirements installation, reuse of a healthy environment, repair of missing imports, preserving existing settings, failure handling, virtual-environment creation, and occupied-port selection. The macOS `.command` wrapper passes `bash -n`. The wrapper was not double-clicked on an actual Mac in this environment.

No live model or embedding API call was made. Credentials, model access, and live answer quality need a local end-to-end check. No real-paper accuracy or citation-entailment benchmark has been run; see `EVALUATION.md`. Installation has not been executed on the user's Mac.

These checks establish a working prototype and specific regression protections. They do not establish that generated answers are always supported by the paper.

## Version 0.3 quality limit

The original `Quantum_Entanglement_IEEE.pdf` was not supplied in this workspace. Its copied search results established the failure mode, but do not provide the abstract or complete paper. Overview routing was tested with synthetic documents and the user's exact question wording. No live generated answer, real-paper recall improvement, or two-column extraction fix has been verified. The existing PDF parser was not changed in this update.
