/* DOM integration tests against the real local Python API. No paid model calls. */
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const { spawn } = require("node:child_process");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
let child, dom, base, dataDir;
let logs = "";
async function eventually(check, label) {
  for (let i = 0; i < 200; i++) {
    if (await check()) return;
    await new Promise(r => setTimeout(r, 25));
  }
  throw new Error("Timed out: " + label + "\n" + logs);
}
function click(selector) { dom.window.document.querySelector(selector).click(); }
function input(selector, value) {
  const n = dom.window.document.querySelector(selector);
  n.value = value;
  n.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
}
function submit() { dom.window.document.querySelector("#askForm").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })); }
before(async () => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "paper-radio-ui-"));
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  base = "http://127.0.0.1:" + port;
  const python = process.env.PAPER_RADIO_TEST_PYTHON || path.join(root, ".venv", "bin", "python");
  child = spawn(python, ["-m", "uvicorn", "paper_radio.api:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root, env: { ...process.env, OPENAI_API_KEY: "", PAPER_RADIO_DATA_DIR: dataDir }, stdio: ["ignore", "pipe", "pipe"]
  });
  child.stdout.on("data", b => logs += b.toString());
  child.stderr.on("data", b => logs += b.toString());
  await eventually(async () => { try { return (await fetch(base + "/health")).ok; } catch { return false; } }, "local API startup");
  dom = new JSDOM(fs.readFileSync(path.join(root, "web/index.html"), "utf8"), { runScripts: "outside-only", url: base, pretendToBeVisual: true });
  dom.window.fetch = (url, options) => fetch(new URL(url, base), options);
  // Use native multipart objects at the network boundary; no browser is launched.
  dom.window.FormData = FormData;
  dom.window.File = File;
  dom.window.Blob = Blob;
  dom.window.AbortController = AbortController;
  dom.window.HTMLElement.prototype.scrollIntoView = function () {};
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  dom.window.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  dom.window.eval(fs.readFileSync(path.join(root, "web/app.js"), "utf8"));
  await eventually(() => dom.window.document.querySelector("#healthLabel").textContent === "Reading room ready", "UI initialization");
});
after(async () => {
  if (dom) dom.window.close();
  if (child && child.exitCode === null) {
    child.kill("SIGTERM");
    await new Promise(resolve => child.once("exit", resolve));
  }
  if (dataDir) fs.rmSync(dataDir, { recursive: true, force: true });
});
test("welcome state and honest mode availability", () => {
  const d = dom.window.document;
  assert.equal(d.querySelector("#paperCount").textContent, "0");
  assert.match(d.querySelector(".library-empty").textContent, /Add a paper/);
  assert.ok(d.querySelector("#sendButton").disabled);
  assert.ok(d.querySelector("#answerMode").options[1].disabled);
  assert.ok(d.querySelector("#semanticUpload").disabled);
});
test("demo upload uses the real PDF parsing and persistence endpoints", async () => {
  click("#demoHero");
  await eventually(() => dom.window.document.querySelector("#paperCount").textContent === "1", "demo upload");
  await eventually(() => !dom.window.document.querySelector("#demoHero").disabled, "upload completion");
  const d = dom.window.document;
  assert.ok(d.querySelector(".paper-select input").checked);
  assert.match(d.querySelector(".paper-meta").textContent, /SYNTHETIC/);
  assert.match(d.querySelector("#scopeLabel").textContent, /demo paper/);
  const papers = await (await fetch(base + "/papers")).json();
  assert.equal(papers[0].page_count, 3);
});
test("question submission renders retrieved evidence and correct source page", async () => {
  click('[data-question="What are the limitations?"]');
  assert.equal(dom.window.document.querySelector("#question").value, "What are the limitations?");
  submit();
  await eventually(() => dom.window.document.querySelector(".message-assistant"), "question response");
  const d = dom.window.document;
  assert.equal(d.querySelector("#welcome").hidden, true);
  assert.match(d.querySelector(".message-tag").textContent, /PASSAGE SEARCH/);
  assert.match(d.querySelector(".passage-excerpt").textContent, /synthetic data only/);
  assert.match(d.querySelector(".result-passage-head .page").textContent, /3/);
  assert.equal(d.querySelector("#question").value, "");
});
test("source clicks, original PDF route, and page navigation work together", async () => {
  click(".result-passage");
  const d = dom.window.document;
  assert.equal(d.querySelector("#sourcePanel").hidden, false);
  assert.equal(d.querySelector("#paperView").hidden, false);
  assert.match(d.querySelector("#pdfFrame").getAttribute("src"), /#page=3/);
  assert.match(d.querySelector("#pageLabel").textContent, /3 of 3/);
  assert.ok(d.querySelector("#nextPage").disabled);
  const pdf = await fetch(base + d.querySelector("#pdfFrame").getAttribute("src"));
  assert.equal(pdf.headers.get("content-type"), "application/pdf");
  click("#prevPage");
  assert.match(d.querySelector("#pdfFrame").getAttribute("src"), /#page=2/);
  click("#sourcesTab");
  assert.equal(d.querySelector("#sourcesView").hidden, false);
  assert.match(d.querySelector(".source-text").textContent, /synthetic data only/);
  click("#closeSources");
  assert.equal(d.querySelector("#sourcePanel").hidden, true);
});
test("passage results offer AI setup rather than pretending to explain", () => {
  const d = dom.window.document;
  const action = d.querySelector(".explanation-hint button");
  assert.equal(action.textContent, "Set up AI explanations");
  action.click();
  assert.ok(d.querySelector("#settingsDialog").open);
  assert.match(d.querySelector("#aiSettingText").textContent, /API key/);
  click('[data-close="settingsDialog"]');
  assert.equal(d.querySelector("#settingsDialog").open, false);
});
test("selection, library filtering, and starter states remain in sync", async () => {
  const d = dom.window.document;
  click(".paper-select input");
  input("#question", "What are the limitations?");
  assert.ok(d.querySelector("#sendButton").disabled);
  assert.equal(d.querySelector("#scopeLabel").textContent, "No papers selected");
  click(".paper-select input");
  assert.equal(d.querySelector("#sendButton").disabled, false);
  input("#libraryFilter", "missing-name");
  assert.match(d.querySelector(".empty-filter").textContent, /No papers match/);
  input("#libraryFilter", "");
  assert.equal(d.querySelectorAll(".paper-item").length, 1);
  assert.ok(d.querySelector(".paper-select input").checked);
});
test("no-match query produces an evidence-aware empty response", async () => {
  input("#question", "moonstonebramble");
  submit();
  await eventually(() => dom.window.document.querySelectorAll(".message-assistant").length === 2, "no-match response");
  const answers = dom.window.document.querySelectorAll(".message-assistant");
  assert.match(answers[1].textContent, /couldn’t find enough supporting evidence/);
  assert.equal(answers[1].querySelectorAll(".result-passage").length, 0);
});
test("fresh conversation clears results without deleting papers", () => {
  click("#newThread");
  const d = dom.window.document;
  assert.equal(d.querySelectorAll(".message").length, 0);
  assert.equal(d.querySelector("#welcome").hidden, false);
  assert.equal(d.querySelector("#sourcePanel").hidden, true);
  assert.equal(d.querySelector("#paperCount").textContent, "1");
});
test("uploaded document names render as text rather than executable HTML", async () => {
  const blob = await (await fetch(base + "/demo.pdf")).blob();
  const bytes = Buffer.from(await blob.arrayBuffer());
  // Change PDF bytes harmlessly so the content-derived ID is distinct.
  const file = new File([bytes, "\n% isolated UI text-safety fixture\n"], "<img onerror=alert(1)>.pdf", { type: "application/pdf" });
  const inputNode = dom.window.document.querySelector("#fileInput");
  Object.defineProperty(inputNode, "files", { configurable: true, value: [file] });
  inputNode.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  await eventually(() => dom.window.document.querySelector("#paperCount").textContent === "2", "upload from custom file input");
  const names = [...dom.window.document.querySelectorAll(".paper-name")].map(n => n.textContent);
  assert.ok(names.includes("<img onerror=alert(1)>"));
  assert.equal(dom.window.document.querySelectorAll("#paperList img").length, 0);
});

test("AI answer citations open the matching quote and PDF page", async () => {
  const papers = await (await fetch(base + "/papers")).json();
  const evidence = await (await fetch(base + "/ask", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: "limitations", paper_ids: [papers[0].id] })
  })).json();
  const source = { ...evidence.passages[0], number: 1 };
  const quote = "The study uses synthetic data only.";
  const fixture = { ...evidence, mode: "answer", sources: [source], claims: [
    { text: "The study uses synthetic data only.", citations: [{ number: 1, quote }] }
  ] };
  const ai = new JSDOM(fs.readFileSync(path.join(root, "web/index.html"), "utf8"), { runScripts: "outside-only", url: base });
  try {
    ai.window.AbortController = AbortController;
    ai.window.HTMLElement.prototype.scrollIntoView = function () {};
    ai.window.fetch = async (url, options) => {
      if (url === "/health") return new Response(JSON.stringify({ status: "ok", answers_configured: true }));
      if (url === "/ask") {
        assert.equal(JSON.parse(options.body).generate_answer, true);
        return new Response(JSON.stringify(fixture));
      }
      return fetch(new URL(url, base), options);
    };
    ai.window.eval(fs.readFileSync(path.join(root, "web/app.js"), "utf8"));
    const d = ai.window.document;
    await eventually(() => d.querySelector("#healthLabel").textContent === "Reading room ready", "AI-mode UI initialization");
    assert.equal(d.querySelector("#answerMode").options[1].disabled, false);
    d.querySelector("#answerMode").value = "answer";
    d.querySelector("#question").value = "What kind of data was used?";
    d.querySelector("#askForm").dispatchEvent(new ai.window.Event("submit", { cancelable: true }));
    await eventually(() => d.querySelector(".citation-button"), "cited answer");
    assert.equal(d.querySelector(".message-tag").textContent, "CITED ANSWER");
    d.querySelector(".citation-button").click();
    assert.equal(d.querySelector("#readerQuote").textContent, quote);
    assert.equal(d.querySelector("#readerQuote").hidden, false);
    assert.match(d.querySelector("#pdfFrame").getAttribute("src"), /#page=3/);
    assert.match(d.querySelector("#modeNote").textContent, /OpenAI/);
  } finally { ai.window.close(); }
});

test("the reported overview question retrieves the opening context", async () => {
  input("#question", "what is this paper about? explain in ez lang");
  submit();
  await eventually(() => dom.window.document.querySelector(".message-assistant"), "overview retrieval");
  const d = dom.window.document;
  assert.match(d.querySelector(".answer-intro").textContent, /paper as a whole/);
  assert.match(d.querySelector(".result-passage-head .page").textContent, /1/);
  assert.match(d.querySelector(".passage-excerpt").textContent, /Abstract/);
});
