# Release review

Folio is a local prototype with a restricted-demo deployment option. Completing
implementation milestones does not establish production readiness.

## Dependencies and model licenses

The web application uses the pinned dependencies in `requirements.lock.txt`.
CI installs that file on Python 3.14 for Ubuntu and Windows, runs `pip check`,
executes the offline test suite, and checks server startup.

The selected embedding model is BGE-M3 (MIT); the selected answer model is
Qwen2.5 1.5B Instruct (Apache-2.0). Review the upstream model cards and license
terms before redistributing models. The Qwen2.5 3B variant has different,
research-only terms and is not a substitute for the configured 1.5B model.

Dependency and model licenses do not license Folio's own code. No project
`LICENSE` has been selected or included.

## Existing controls

- Local Ollama endpoint, with no automatic model download or cloud fallback.
- Bounded uploads, extracted text, chunk counts, history, sessions, and requests.
- Private document storage outside the static directory.
- Session-isolation tests, CSRF tokens, HttpOnly cookies, and mutation Origin checks.
- PDF parsing in a time-limited subprocess. This is not an OS sandbox or a
  reliable memory limit for a hostile PDF.
- One shared inference slot, explicit busy/capacity responses, and chat rate limits.
- Exact source-quote and numeric checks, extractive answer restrictions, and
  server-verified duration conversions for supported cases.

These checks reduce specific failure modes. Quote integrity alone does not prove
that a claim is relevant, complete, or semantically supported.

## Quality evidence

The evaluation tools use versioned synthetic English and Indonesian documents
and questions. Automatic proxies check expected status, selected evidence,
citations, and scenario-specific strings. They do not measure general answer
accuracy or replace independent human review.

Development and holdout datasets are part of the same project, not an independent
benchmark. Once a holdout has been inspected, it must not be represented as unseen
evidence for later tuning. New answer-policy changes require new validation.
See the [evaluation protocol](../evals/README.md).

## Open release gates

1. **Authentication and authorization:** no internal user accounts. A shared
   reverse-proxy password limits demo access but does not provide per-user access
   control, revocation, or identity auditing.
2. **Untrusted PDF isolation:** no OS-level parser sandbox or enforced subprocess
   memory quota.
3. **Session durability:** session state is process-local; multi-worker deployments
   are unsupported and server restarts discard conversation state.
4. **Independent quality validation:** no blinded, independent human assessment
   on representative real-world documents.
5. **Operations and capacity:** no SLA, watchdog, sustained-load guarantee, or
   verified minimum inference hardware requirement.
6. **Document coverage:** OCR and encrypted PDFs are unsupported.
7. **Project license:** the repository owner must select reuse terms for the code.

Keep these gates open until each has explicit acceptance evidence. An operational
tunnel or passing CI run does not close them.
