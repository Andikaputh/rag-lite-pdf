# Folio

[![CI](https://github.com/Andikaputh/rag-lite-pdf/actions/workflows/ci.yml/badge.svg)](https://github.com/Andikaputh/rag-lite-pdf/actions/workflows/ci.yml)

Ask questions about a PDF and inspect the passages behind each answer.
Folio runs document embeddings and answer generation on your own machine
through Ollama. No model API key or paid inference service is required.

**Status:** a self-hosted prototype for local use and restricted demos.
Answer quality has been tested on small synthetic datasets, not independently
validated for production use. See [limitations](#limitations).

## Features

- Upload one PDF per session and build a local search index.
- Read text-based PDFs out of the box, or enable optional local OCR for scanned pages.
- Ask follow-up questions with bounded conversation history.
- Inspect source quotes and page references alongside answers.
- Receive an explicit refusal when retrieved evidence is insufficient.
- Replace or delete a document and its associated text and index.

Text-based PDFs need no extra tools. Scanned PDFs need the optional OCR extra
described in [Installation](#installation). Encrypted documents are not supported.

## Requirements

- Git and Python 3.14, the version used in CI.
- [Ollama](https://ollama.com/) running at `http://127.0.0.1:11434`.
- Disk space for dependencies, documents, and both models. The measured model
  downloads total approximately 2.2 GB. A minimum inference RAM requirement
  has not been established.

## Installation

The following commands use PowerShell. On Linux or macOS, replace
`.venv\Scripts\python` with `.venv/bin/python`.

```powershell
git clone https://github.com/Andikaputh/rag-lite-pdf.git
cd rag-lite-pdf
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
.venv\Scripts\python -m pip check
```

### Optional local OCR

Text-based PDFs work with the core install. To read scanned or image-only
pages, install the pinned OCR extra. RapidOCR and pypdfium2 run locally on the
CPU, need no external OCR binary, and do not send documents to a service.

```powershell
.venv\Scripts\python -m pip install -r requirements-ocr.lock.txt
.venv\Scripts\python -m pip check
```

The first OCR upload initializes the local OCR engine and may take a few
seconds. The application OCRs up to 25 image pages per document and applies a
separate 180-second OCR timeout. Tesseract is an optional alternative when
RapidOCR is not installed: install `pytesseract` and the Tesseract binary, then
set `TESSERACT_CMD` if the binary is not on `PATH`.

With Ollama running, download the models:

```powershell
ollama pull bge-m3
ollama pull qwen2.5:1.5b-instruct
ollama list
```

| Model | Purpose | Model license |
| --- | --- | --- |
| `bge-m3` | Document and question embeddings | MIT |
| `qwen2.5:1.5b-instruct` | Answer generation | Apache-2.0 |

The application does not download models automatically or fall back to cloud
inference. The 3B Qwen2.5 variant is not used because its model license differs
from the 1.5B variant. See the [release review](docs/RELEASE-REVIEW.md).

## Running locally

```powershell
.venv\Scripts\python -m uvicorn web.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Use **one worker**: session state and conversation
history live in process memory and are lost when the server restarts.

Check the web process with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

`status: ok` indicates that the web server is running, not that the models
are ready. Model availability is checked when an operation needs them.

## Usage

1. Upload a PDF. Scanned PDFs need the OCR extra.
2. Build its index and wait for completion.
3. Ask a question about the document.
4. Open a citation number to inspect the source passage.

If the application declines to answer, check whether the requested information
is actually stated in the PDF. Passing automatic checks does not make an
answer correct; review the sources before relying on it.

| Resource | Limit |
| --- | --- |
| Upload | 10 MiB, 100 pages, 1 million text characters |
| OCR | Up to 25 image pages per document, 180-second timeout |
| Question | 1 to 1,500 characters |
| Chat requests | 30 per 60 seconds per session |
| Conversation history | Up to 6 turns and 48 KiB per session |
| Model operations | One shared slot for indexing and answers |

## Architecture

FastAPI serves Jinja2 templates and plain JavaScript/CSS. Text is extracted
per page; image-only pages can use optional local OCR in the bounded parser
subprocess. Text is split into chunks and embedded with BGE-M3. Each document
has a SQLite vector index. Questions retrieve relevant passages before
generation; the resulting claims and citations are checked against retrieved
evidence.

| Path | Contents |
| --- | --- |
| `web/` | Server, PDF ingestion, retrieval, and answer validation |
| `web/templates/`, `web/static/` | Web interface |
| `web/answer-policy.json` | Active answer strategy |
| `tests/` | Offline, browser, and local integration tests |
| `evals/` | Synthetic fixtures and evaluation tools |
| `docs/` | Deployment and release documentation |
| `.data/` | Private runtime data, excluded from Git |

## Testing

Offline tests do not require Ollama, model downloads, or an API key:

```powershell
.venv\Scripts\python -m unittest discover -s tests -q
```

[CI](.github/workflows/ci.yml) installs the lockfile, checks dependencies,
runs offline tests, and verifies server startup on Ubuntu and Windows with
Python 3.14. Browser and live-model tests run separately.
See [testing](docs/TESTING.md) for browser setup and synthetic fixture generation.

With both models available locally:

```powershell
.venv\Scripts\python -m tests.live_embeddings
.venv\Scripts\python -m tests.live_answers
.venv\Scripts\python -m tests.live_conversations
```

See [evaluation](evals/README.md) for the dataset protocol and interpretation
of scores. Multilingual fixture text is retained to test document-language
handling; it is not interface copy.

## Limitations

- No built-in user accounts or authentication. Do not expose the application
  port directly to a public network.
- No OS-level sandbox for PDF parsing or OCR, and no durable multi-worker
  sessions.
- OCR can misread characters, especially numbers, handwriting, and low-quality
  scans. Review the cited page before relying on an answer.
- No independent human validation of answer quality. Synthetic test results
  are not general accuracy guarantees.
- No uptime or multi-user capacity guarantee. Model operations share one slot.

In local mode, PDF processing and inference stay on the host machine. Uploads
are stored outside the static directory. Sessions use HttpOnly cookies, CSRF
tokens, and Origin checks for mutations. These controls do not establish that
the application is suitable for sensitive documents or unrestricted public use.

Restricted publication through a Cloudflare tunnel and an authenticated reverse
proxy is described in [deployment](docs/DEPLOYMENT.md). In that mode, traffic
including uploads passes through Cloudflare. Free software does not remove
hardware, electricity, or connectivity costs.

## Contributing

For bug reports, include reproduction steps, Python/Ollama versions, and
redacted error messages. Do not attach sensitive PDFs, credentials, or the
contents of `.data/`. Changes should include relevant tests and explain any
effect on document isolation or answer validation.

## License

This repository does not currently include a `LICENSE` file. Model and
dependency licenses do not determine the license of Folio's own code.
Contact the repository owner before reusing project code.
