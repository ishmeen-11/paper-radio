# Measure before adding an agent

No real-paper accuracy results have been measured yet. Synthetic regression tests verify plumbing and source checks; they are not a benchmark of research understanding.

## First real benchmark

Choose three publicly shareable papers you know well. Label **15 questions** before inspecting the system output:

| Type | Count | Required annotation |
| --- | --- | --- |
| Direct fact or method | 6 | Expected answer + exact supporting page and quote |
| Several passages required | 3 | All necessary pages + expected reasoning |
| Comparison across selected papers | 3 | Expected answer + separate evidence for each paper |
| Unsupported in the selected collection | 3 | Why it is unsupported, checked by a human |

Do not upload private or unpublished research to an external API without authorization.

Use fixed paper bytes, the same questions, top_k=6, and the same answer model. Compare BM25 against hybrid retrieval. Save each result with the interface's JSON export; record question, selected paper IDs, retrieval mode, model names, and the labels separately.

## Metrics

- **Evidence recall@6:** fraction of labeled supporting evidence passages found within the six retrieved chunks. For multi-evidence questions, score each required passage separately.
- **Answer correctness:** human review against the labeled answer, counting unsupported extra statements as errors.
- **Citation integrity:** correct source IDs and exact quotes; this is a programmatic check, not an entailment score.
- **Citation support:** human judgment of whether each quote supports the entire associated claim.
- **Abstention:** correct refusal rate on the three unsupported questions, plus false refusal rate on answerable questions.
- **Latency:** median and slowest end-to-end question latency from `elapsed_ms`. Report indexing time separately.
- **Cost:** record provider token usage or dashboard charges for indexing and answering separately. The current UI does not report token cost.

Record failures by cause: extraction, chunk boundaries, retrieval, synthesis, wrong citation, or a weak reference answer. Choose the next improvement based on the largest observed failure category.

## Follow-up work

1. Section-aware extraction and improved table handling if evidence is missing before retrieval.
2. A reranker if relevant evidence is retrieved too low.
3. Evidence-checking or query refinement if questions need multiple passages.
4. Eve orchestration for a comparison task only after the baseline and an agent version can be compared on the same questions, latency, and cost.
