# Testing

## Offline suite

Install `requirements.lock.txt`, then run from the repository root:

```powershell
.venv\Scripts\python -m unittest discover -s tests -q
```

The suite uses temporary synthetic PDFs and test doubles for model calls.
It does not need Ollama or an external inference service. On Linux/macOS,
replace `.venv\Scripts\python` with `.venv/bin/python`.

The OCR tests are opt-in by dependency. Install `requirements-ocr.lock.txt` to
run the real image-only PDF checks; without it, those tests are skipped. The
focused OCR suite is:

```powershell
.venv\Scripts\python -m unittest tests.test_ocr -v
```

## Local model checks

Start Ollama and install both models from the main README. Each module below
creates its own temporary data directory and cleans it on exit:

```powershell
.venv\Scripts\python -m tests.live_embeddings
.venv\Scripts\python -m tests.live_answers
.venv\Scripts\python -m tests.live_conversations
```

## Browser suites

Browser tests are opt-in and run against `http://127.0.0.1:8000`. They upload
synthetic PDFs, may trigger model inference, and delete their test documents
on successful completion. A failing run can leave its session until expiry.
Do not run them against a shared production instance.

1. Start the application with the command in the main README.
2. Generate the synthetic fixtures:

   ```powershell
   .venv\Scripts\python -m tests.prepare_browser
   ```

3. Install `@playwright/cli`, Chromium, and, for the accessibility audit,
   `axe-core`. Copy `axe.min.js` from that package to `.tools/axe.min.js`.
   These are development tools, not application dependencies.
4. Open a browser session and run a suite:

   ```powershell
   playwright-cli -s=folio-check open http://127.0.0.1:8000
   playwright-cli -s=folio-check --raw run-code --filename=tests/browser_smoke.js
   playwright-cli -s=folio-check --raw run-code --filename=tests/browser_documents.js
   playwright-cli -s=folio-check close
   ```

`browser_smoke.js` and `browser_documents.js` cover navigation, responsive
layout, upload errors, deletion, and reconnection without model inference.
The indexing, answers, conversations, grounding, precision, polish, and audit
suites require both local models. Use the same command with their filenames.

Screenshots and generated fixtures stay in `.tools/`, which is excluded from
Git. Existing fixture files are not overwritten. Use a fresh checkout when
checking fixture reproducibility; do not replace personal files with test data.

English UI assertions and multilingual document fixtures serve different
purposes. Keep the original language of a fixture when testing language-aware
retrieval, follow-up questions, or exact source quotes.
