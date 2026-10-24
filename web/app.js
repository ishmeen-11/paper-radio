/* Paper Radio custom UI. Same-origin requests; no API keys in the browser. */
"use strict";
const $ = id => document.getElementById(id);
const state = { papers: [], selected: new Set(), configured: false, busy: false, uploading: false, result: null, reader: null };
function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#i-" + name);
  svg.append(use);
  return svg;
}
function button(label, className, onClick, symbol) {
  const node = el("button", className);
  node.type = "button";
  if (symbol) node.append(icon(symbol));
  node.append(document.createTextNode(label));
  node.addEventListener("click", onClick);
  return node;
}
function toast(message, error = false) {
  const node = el("div", "toast" + (error ? " error" : ""), message);
  $("toastArea").append(node);
  setTimeout(() => node.remove(), error ? 9000 : 5000);
}
async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal });
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch (_) { /* An HTTP status is enough. */ }
      throw new Error(typeof detail === "string" ? detail : "Something went wrong. Check the file or your selected papers and try again.");
    }
    return response;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("This request took too long. Try again with fewer papers.");
    if (error instanceof TypeError) throw new Error("Can't reach Paper Radio. Check that the local server is running.");
    throw error;
  } finally { clearTimeout(timeout); }
}
function saveSelection() {
  try { localStorage.setItem("paper-radio-selection", JSON.stringify([...state.selected])); } catch (_) {}
}
function selectedPapers() { return state.papers.filter(p => state.selected.has(p.id)); }
function safeTitle(filename) { return filename.replace(/\.pdf$/i, "").replace(/[_-]+/g, " "); }
function syncControls() {
  const count = state.selected.size;
  const papers = selectedPapers();
  $("scopeLabel").textContent = count === 0 ? "No papers selected" : count === 1 ? "Reading " + safeTitle(papers[0].filename) : "Reading " + count + " selected papers";
  $("scopeLabel").title = papers.map(p => p.filename).join(", ");
  $("clearSelection").hidden = count === 0;
  const semanticReady = state.configured && papers.length > 0 && papers.every(p => p.semantic_indexed);
  $("retrievalMode").options[1].disabled = !semanticReady;
  if (!semanticReady) $("retrievalMode").value = "lexical";
  $("answerMode").options[1].disabled = !state.configured;
  $("answerMode").options[1].textContent = state.configured ? "Ask AI" : "Ask AI · setup needed";
  $("semanticUpload").disabled = !state.configured || state.uploading;
  $("fileInput").disabled = state.busy || state.uploading;
  $("sendButton").disabled = !count || !state.papers.length || !state.configured && $("answerMode").value === "answer" || state.busy || state.uploading || !$("question").value.trim();
  $("question").disabled = state.busy;
  $("answerMode").disabled = state.busy;
  $("retrievalMode").disabled = state.busy;
  $("newThread").disabled = state.busy;
  $("clearSelection").disabled = state.busy;
  document.querySelectorAll('[data-action="upload"]').forEach(n => n.disabled = state.busy || state.uploading);
  document.querySelectorAll(".paper-select input").forEach(n => n.disabled = state.busy || state.uploading);
  $("demoSide").disabled = state.busy || state.uploading;
  $("demoHero").disabled = state.busy || state.uploading;
  const external = $("answerMode").value === "answer" || $("retrievalMode").value === "hybrid";
  $("modeNote").textContent = external ? "This mode sends your question and relevant paper text to OpenAI." : "Every question stays within your selected papers.";
}
function renderPapers() {
  const container = $("paperList");
  container.replaceChildren();
  $("paperCount").textContent = state.papers.length;
  const filter = $("libraryFilter").value.trim().toLowerCase();
  const papers = state.papers.filter(p => p.filename.toLowerCase().includes(filter));
  if (!papers.length) {
    if (filter) container.append(el("p", "empty-filter", "No papers match that name."));
    else {
      const empty = el("div", "library-empty");
      empty.append(icon("book"), el("strong", "", "Room for your next idea."), el("p", "", "Add a paper to start building your reading list."));
      container.append(empty);
    }
  }
  for (const paper of papers) {
    const item = el("article", "paper-item" + (state.selected.has(paper.id) ? " selected" : ""));
    const label = el("label", "paper-select");
    const checkbox = el("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(paper.id);
    checkbox.setAttribute("aria-label", "Select " + paper.filename);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked && state.selected.size >= 20) {
        checkbox.checked = false;
        toast("You can read up to 20 papers at a time.", true);
        return;
      }
      if (checkbox.checked) state.selected.add(paper.id); else state.selected.delete(paper.id);
      saveSelection(); renderPapers(); syncControls();
    });
    const info = el("span", "paper-info");
    const meta = el("span", "paper-meta", paper.page_count + " pages");
    if (paper.filename === "demo_paper.pdf") meta.append(el("span", "", "· SYNTHETIC"));
    else meta.append(el("span", "", "· PDF"));
    if (paper.semantic_indexed) meta.append(el("span", "semantic-dot"));
    info.append(el("span", "paper-name", safeTitle(paper.filename)), meta);
    label.append(checkbox, info);
    const open = button("", "paper-open", () => openPaper(paper.id, 1), "out");
    open.setAttribute("aria-label", "Open " + paper.filename);
    open.title = "Open paper";
    item.append(label, open);
    container.append(item);
  }
  syncControls();
}
function setPanel(open) {
  $("sourcePanel").hidden = !open;
  $("app").classList.toggle("panel-open", open);
  $("app").classList.toggle("panel-closed", !open);
  $("sourceToggle").setAttribute("aria-expanded", String(open));
}
function setTab(tab) {
  const sources = tab === "sources";
  $("sourcesView").hidden = !sources;
  $("paperView").hidden = sources;
  $("sourcesTab").classList.toggle("active", sources);
  $("paperTab").classList.toggle("active", !sources);
  $("sourcesTab").setAttribute("aria-selected", String(sources));
  $("paperTab").setAttribute("aria-selected", String(!sources));
}
function openPaper(paperId, page = 1, quoteText = "") {
  const paper = state.papers.find(p => p.id === paperId);
  if (!paper) { toast("This paper is no longer in your library.", true); return; }
  page = Math.max(1, Math.min(paper.page_count, page));
  state.reader = { paperId, page, quoteText };
  const url = "/papers/" + encodeURIComponent(paperId) + "/pdf#page=" + page + "&view=FitH";
  $("pdfFrame").src = url;
  $("readerExternal").href = url;
  $("readerTitle").textContent = paper.filename;
  $("readerTitle").title = paper.filename;
  $("pageLabel").textContent = "PDF page " + page + " of " + paper.page_count;
  $("prevPage").disabled = page <= 1;
  $("nextPage").disabled = page >= paper.page_count;
  $("readerQuote").hidden = !quoteText;
  $("readerQuote").textContent = quoteText;
  $("readerEmpty").hidden = true;
  setPanel(true); setTab("paper"); setSidebar(false);
}
function sourcesFor(result) {
  return result.mode === "answer" ? result.sources : result.passages.map((p, i) => ({ ...p, number: i + 1 }));
}
function quotesFor(result, number) {
  return [...new Set(result.claims.flatMap(c => c.citations.filter(s => s.number === number).map(s => s.quote)))];
}
function showEvidence(result, open = true) {
  state.result = result;
  const sources = sourcesFor(result);
  $("sourceCount").textContent = sources.length;
  const container = $("sourceList");
  container.replaceChildren();
  if (!sources.length) {
    const empty = el("div", "panel-empty");
    empty.append(icon("book"), el("h3", "", "Every idea has a source."), el("p", "", "Ask a question to see the passages behind your answer."));
    container.append(empty);
  } else {
    container.append(el("p", "source-hint", "Original text from your selected papers. Page numbers refer to PDF pages."));
    for (const source of sources) {
      const card = el("article", "source-card");
      const head = el("div", "source-card-head");
      head.append(el("span", "citation-number", String(source.number)), el("span", "source-filename", source.filename));
      const footer = el("div", "source-card-footer");
      footer.append(el("span", "", "PDF page " + source.page), button("Read in paper", "", () => openPaper(source.paper_id, source.page, quotesFor(result, source.number)[0] || ""), "out"));
      card.append(head);
      for (const quoteText of quotesFor(result, source.number)) card.append(el("blockquote", "", quoteText));
      card.append(el("p", "source-text", source.text), footer);
      container.append(card);
    }
  }
  if (open) { setPanel(true); setTab("sources"); }
}
function newThread() {
  if (state.busy) return;
  $("messages").replaceChildren();
  $("welcome").hidden = false;
  $("question").value = "";
  state.result = null; state.reader = null;
  $("pdfFrame").removeAttribute("src");
  $("readerEmpty").hidden = false; $("readerQuote").hidden = true;
  showEvidence({ mode: "search", sources: [], passages: [], claims: [] }, false);
  setPanel(false); syncControls(); $("question").focus();
}
function messageShell(kind) {
  const message = el("article", "message message-" + kind);
  const body = el("div", "answer-body");
  if (kind !== "user") {
    const label = el("div", "message-label");
    const avatar = el("span", "message-avatar"); avatar.append(icon("wave"));
    label.append(avatar, el("span", "", "Paper Radio"));
    message.append(label);
  }
  message.append(body);
  return { message, body };
}
function addResult(result, question, paperIds) {
  const { message, body } = messageShell("assistant");
  const tag = el("span", "message-tag", result.mode === "answer" ? "CITED ANSWER" : "PASSAGE SEARCH");
  message.querySelector(".message-label").append(tag);
  if (result.mode === "answer") {
    const sources = sourcesFor(result);
    for (const claim of result.claims) {
      const p = el("p", "", claim.text);
      for (const number of new Set(claim.citations.map(c => c.number))) {
        const source = sources.find(s => s.number === number);
        if (!source) continue;
        const cite = button(String(number), "citation-button", () => { showEvidence(result, false); openPaper(source.paper_id, source.page, quotesFor(result, number)[0] || ""); });
        cite.setAttribute("aria-label", "Read citation " + number + " on PDF page " + source.page);
        p.append(cite);
      }
      body.append(p);
    }
    body.append(el("p", "answer-disclaimer", "Source IDs and exact quotes checked. Review whether the evidence supports each claim."));
  } else if (result.mode === "insufficient_evidence") {
    body.append(el("p", "answer-intro", "I couldn’t find enough supporting evidence in the retrieved passages."));
    body.append(el("p", "", "Try a more specific question, a different wording, or another paper selection."));
  } else {
    body.append(el("p", "answer-intro", result.intent === "overview" ? "Key passages for understanding the paper as a whole." : result.passages.length === 1 ? "One passage to help you get started." : result.passages.length + " passages to help you get started."));
    const hint = el("div", "explanation-hint");
    hint.append(el("span", "", "These are source excerpts. A plain-language explanation uses AI with citations."));
    hint.append(button(state.configured ? "Get a cited explanation" : "Set up AI explanations", "text-button", () => {
      if (state.busy || state.uploading) return;
      if (!state.configured) { $("settingsDialog").showModal(); return; }
      state.selected = new Set(paperIds.filter(id => state.papers.some(p => p.id === id)));
      if (!state.selected.size) { toast("The original papers are no longer available.", true); return; }
      saveSelection(); renderPapers();
      $("answerMode").value = "answer";
      $("question").value = question;
      syncControls(); $("askForm").requestSubmit();
    }, "spark"));
    body.append(hint);
    for (const source of sourcesFor(result)) {
      const card = button("", "result-passage", () => { showEvidence(result, false); openPaper(source.paper_id, source.page); });
      const head = el("span", "result-passage-head");
      head.append(el("span", "citation-number", String(source.number)), el("span", "filename", source.filename), el("span", "page", "p. " + source.page), icon("out"));
      card.append(head, el("span", "passage-excerpt", source.text));
      body.append(card);
    }
  }
  const footer = el("div", "answer-footer");
  footer.append(el("span", "", (result.elapsed_ms / 1000).toFixed(2) + "s"));
  if (result.passages.length) footer.append(button("View sources", "", () => showEvidence(result), "panel"));
  footer.append(button("Save result", "", () => {
    const blob = new Blob([JSON.stringify({ question, paper_ids: paperIds, ...result }, null, 2)], { type: "application/json" });
    const link = el("a");
    const url = URL.createObjectURL(blob);
    link.href = url; link.download = "paper-radio-result.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, "download"));
  body.append(footer);
  $("messages").append(message, el("div", "message-divider"));
  showEvidence(result, false);
  return message;
}
async function ask(event) {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question || !state.selected.size || state.busy || state.uploading) return;
  const paperIds = [...state.selected];
  const names = selectedPapers().map(p => p.filename).join(" · ");
  state.busy = true; syncControls();
  $("welcome").hidden = true;
  const user = el("article", "message message-user");
  user.append(el("div", "message-body", question), el("div", "message-meta", names));
  $("messages").append(user);
  const { message, body } = messageShell("pending");
  const dots = el("div", "busy-dots");
  dots.append(el("i"), el("i"), el("i"), el("span", "busy-text", "Following the paper trail…"));
  body.append(dots); $("messages").append(message);
  $("conversation").scrollTop = $("conversation").scrollHeight;
  try {
    const response = await request("/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, paper_ids: paperIds, retrieval: $("retrievalMode").value, generate_answer: $("answerMode").value === "answer", top_k: 6 })
    });
    const result = await response.json();
    message.remove();
    const answer = addResult(result, question, paperIds);
    $("question").value = "";
    answer.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    message.className = "message message-error"; body.replaceChildren(el("p", "error-message", error.message));
  } finally {
    state.busy = false; syncControls();
    $("question").focus();
  }
}
function openUpload() {
  if (state.busy || state.uploading) return;
  $("uploadStatus").hidden = true;
  $("uploadDialog").showModal();
}
function uploadStatus(text, error = false) {
  $("uploadStatus").hidden = false;
  $("uploadStatus").textContent = text;
  $("uploadStatus").classList.toggle("error", error);
}
async function uploadFiles(files, useSemantic = $("semanticUpload").checked) {
  if (state.busy || state.uploading || !files.length) return;
  state.uploading = true; syncControls();
  let success = 0; const errors = [];
  try {
    for (const [index, file] of [...files].slice(0, 20).entries()) {
      uploadStatus("Reading " + file.name + " · " + (index + 1) + " of " + Math.min(files.length, 20));
      try {
        if (!/\.pdf$/i.test(file.name)) throw new Error("Please choose a PDF file: " + file.name);
        if (file.size > 20 * 1024 * 1024) throw new Error(file.name + " exceeds the 20 MB limit.");
        const data = new FormData(); data.append("file", file); data.append("semantic", String(useSemantic));
        const paper = await (await request("/papers", { method: "POST", body: data })).json();
        state.papers = [paper, ...state.papers.filter(p => p.id !== paper.id)];
        if (state.selected.size < 20) state.selected.add(paper.id);
        saveSelection(); renderPapers(); success++;
        paper.warnings.forEach(w => toast(w, true));
      } catch (error) { errors.push(error.message); }
    }
    if (files.length > 20) errors.push("The first 20 files were processed. Add the remaining files in another upload.");
    if (success) {
      toast(success === 1 ? "Paper added. A good question comes next." : success + " papers added to your library.");
      if ($("uploadDialog").open && !errors.length) $("uploadDialog").close();
      setSidebar(false); $("question").focus();
    }
    if (errors.length) { uploadStatus(errors.join(" "), true); errors.forEach(error => toast(error, true)); }
  } finally {
    state.uploading = false; $("fileInput").value = ""; syncControls();
  }
}
async function demo() {
  if (state.busy || state.uploading) return;
  try {
    const data = await (await request("/demo.pdf")).blob();
    await uploadFiles([new File([data], "demo_paper.pdf", { type: "application/pdf" })], false);
    toast("Demo added: all content is synthetic, not published research.");
  } catch (error) { toast(error.message, true); }
}
function setSidebar(open) {
  $("app").classList.toggle("sidebar-open", open);
  $("sidebarShade").hidden = !open;
  $("menuButton").setAttribute("aria-expanded", String(open));
}
async function initialize() {
  try {
    const [healthResponse, papersResponse] = await Promise.all([request("/health"), request("/papers")]);
    const health = await healthResponse.json();
    state.configured = health.answers_configured;
    state.papers = await papersResponse.json();
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem("paper-radio-selection")); } catch (_) {}
    state.selected = new Set((Array.isArray(saved) ? saved : state.papers.map(p => p.id)).filter(id => state.papers.some(p => p.id === id)).slice(0, 20));
    $("healthDot").className = "health-dot ready"; $("healthLabel").textContent = "Reading room ready";
    if (state.configured) {
      $("aiSettingText").textContent = "Ready for cited answers. Choose Ask AI in the question box when you want to use it.";
      $("aiSettingStatus").textContent = "Ready"; $("aiSettingStatus").classList.remove("neutral");
    }
    renderPapers(); syncControls();
  } catch (error) {
    $("healthDot").className = "health-dot error"; $("healthLabel").textContent = "Connection unavailable";
    const empty = el("div", "library-empty");
    empty.append(el("strong", "", "Let’s reconnect."), el("p", "", error.message), button("Try again", "text-button", initialize));
    $("paperList").replaceChildren(empty); toast(error.message, true);
  }
}
$("askForm").addEventListener("submit", ask);
$("question").addEventListener("input", () => { $("question").style.height = "auto"; $("question").style.height = Math.min(130, $("question").scrollHeight) + "px"; syncControls(); });
$("question").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("askForm").requestSubmit(); } });
$("libraryFilter").addEventListener("input", renderPapers);
$("answerMode").addEventListener("change", syncControls);
$("retrievalMode").addEventListener("change", syncControls);
document.querySelectorAll('[data-action="upload"]').forEach(n => n.addEventListener("click", openUpload));
document.querySelectorAll("[data-close]").forEach(n => n.addEventListener("click", () => $(n.dataset.close).close()));
document.querySelectorAll(".starter-card").forEach(n => n.addEventListener("click", () => { $("question").value = n.dataset.question; $("question").focus(); syncControls(); if (!state.selected.size) toast("Add a paper or try the demo to explore this question."); }));
document.querySelectorAll("dialog").forEach(dialog => dialog.addEventListener("click", event => { if (event.target !== dialog) return; const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); }));
$("fileInput").addEventListener("change", event => uploadFiles(event.target.files));
$("demoSide").addEventListener("click", demo); $("demoHero").addEventListener("click", demo);
$("sourceToggle").addEventListener("click", () => setPanel($("sourcePanel").hidden));
$("closeSources").addEventListener("click", () => setPanel(false));
$("sourcesTab").addEventListener("click", () => setTab("sources"));
$("paperTab").addEventListener("click", () => setTab("paper"));
$("newThread").addEventListener("click", newThread);
$("settingsButton").addEventListener("click", () => $("settingsDialog").showModal());
$("clearSelection").addEventListener("click", () => { if (state.busy) return; state.selected.clear(); saveSelection(); renderPapers(); syncControls(); });
$("menuButton").addEventListener("click", () => setSidebar(!$("app").classList.contains("sidebar-open")));
$("sidebarShade").addEventListener("click", () => setSidebar(false));
$("prevPage").addEventListener("click", () => { if (state.reader) openPaper(state.reader.paperId, state.reader.page - 1); });
$("nextPage").addEventListener("click", () => { if (state.reader) openPaper(state.reader.paperId, state.reader.page + 1); });
document.addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "o") { event.preventDefault(); openUpload(); }
  if (event.key === "Escape") { setSidebar(false); if (!$("uploadDialog").open && !$("settingsDialog").open) setPanel(false); }
});
let dragDepth = 0;
document.addEventListener("dragenter", event => { if ([...event.dataTransfer.types].includes("Files")) { event.preventDefault(); dragDepth++; $("dragOverlay").hidden = false; } });
document.addEventListener("dragover", event => { if ([...event.dataTransfer.types].includes("Files")) event.preventDefault(); });
document.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("dragOverlay").hidden = true; });
document.addEventListener("drop", event => {
  if (!event.dataTransfer.files.length) return;
  event.preventDefault(); dragDepth = 0; $("dragOverlay").hidden = true;
  if (state.busy || state.uploading) { toast("Finish the current request before adding another paper."); return; }
  if (!$("uploadDialog").open) $("uploadDialog").showModal();
  uploadFiles(event.dataTransfer.files);
});
showEvidence({ mode: "search", passages: [], sources: [], claims: [] }, false);
initialize();
