# Evaluation

Local diagnostic tools for the PDF question-answering pipeline. The datasets
contain synthetic documents and questions, including English and Indonesian cases.
They are not a representative production corpus or an independent benchmark.

## Running an evaluation

Install the web lockfile as described in the main README. Start local Ollama
with BGE-M3 and Qwen2.5 1.5B Instruct available. No paid judge, cloud API, private
PDF directory, or automatic model download is used.

```powershell
.venv\Scripts\python -m evals.run --split dev --min-score 0.45 --out evals/results/local-dev
```

On Linux/macOS, use `.venv/bin/python`. Output directories must be new; previous
runs are not overwritten. Generated reports stay local and are excluded from Git.

The runner follows `web/answer-policy.json` unless `--answer-strategy` is specified.
Use `--dataset` to select an explicitly reviewed synthetic JSON dataset. See
`python -m evals.run --help` for options. Do not use personal data as a fixture.

`datasets/rag-v5.json` adds general-domain English and Indonesian handbook cases,
including a punctuation-free table page. It is a regression set for evidence-unit
filtering, not a broader accuracy claim.

For a controlled comparison, run baseline and candidate with the same dataset,
case IDs, model digests, code fingerprint, seeds, and environment. Change only
the parameter under study, then compare the two JSON reports:

```powershell
.venv\Scripts\python -m evals.compare evals/results/baseline/report.json evals/results/candidate/report.json --out evals/results/comparison
```

Use development cases for tuning. Run a previously unseen holdout only with the
chosen configuration fixed. A holdout inspected during development is no longer
unseen validation data. Fixed seeds do not guarantee identical model output;
repeat runs are needed to assess stability and timing variance.

## Metrics and interpretation

- `retrieval_recall_at_3`: gold evidence found in the actual retrieved chunks.
- `gold_cited_evidence_recall`: gold excerpts literally covered by cited quotes.
- `quote_integrity`: quotes occur in the extracted page and retrieved chunk.
  This does not establish semantic entailment.
- Answer and abstention rates: expected versus actual status. HTTP errors are
  failures, not safe abstentions.
- `scenario_proxy_pass`: expected status, literal aliases/forbidden strings,
  evidence, citation, and history checks. It is not an accuracy score.
- `followup_proxy_pass`: the same scenario checks for follow-up questions.
- Latency p50/p95: answer-request time, including rewriting when used. Setup,
  parsing, and indexing are recorded separately. This is not throughput testing.

Empty denominators are not treated as perfect scores. Faithfulness and semantic
citation correctness remain null until a separate review supplies labels.
Canary-string matching is a narrow injection diagnostic, not a security proof.

## Semantic review

Copy the generated `review-template.json`, supply the reviewer name and type,
and inspect each answer against the question, document, and cited sources.
Label relevance, support, and completeness separately; leave unknown values null.

```powershell
.venv\Scripts\python -m evals.review evals/results/local-dev/report.json reviewed-labels.json --out review-summary.json
```

Reviewer type is self-reported, not authenticated. Automated review is not
independent human validation. The tool rejects stale hashes, duplicate or missing
case IDs, and invalid labels; partial reviews do not imply unrated cases passed.

## Data handling

The runner generates text PDFs in memory from the selected synthetic corpus and
exercises the application in-process. Temporary PDFs, indexes, and sessions are
cleaned up after the run. Normal user chats are not evaluated or exported.
Reports include synthetic responses and evidence, environment details, hashes,
and model digests. Inspect them before sharing and do not publish private inputs.
