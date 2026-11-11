# Deployment

Folio is designed for one process on a self-hosted machine. It has no built-in
authentication, durable session store, or production availability guarantee.

## Install and start

Use Python 3.14 and the pinned lockfile. See the [README](../README.md) for
installation commands. Start Ollama separately and install `bge-m3` and
`qwen2.5:1.5b-instruct` before indexing or asking questions.

```powershell
.venv\Scripts\python -m uvicorn web.main:app --host 127.0.0.1 --port 8000
```

On Linux/macOS, use `.venv/bin/python`. Keep a single worker. Sessions,
conversation revisions, rate limits, and inference coordination are process-local.
Adding workers does not provide supported horizontal scaling.

### Optional local OCR

Text-based PDFs need only the core lockfile. For scanned or image-only pages,
install the pinned OCR extra:

```powershell
.venv\Scripts\python -m pip install -r requirements-ocr.lock.txt
.venv\Scripts\python -m pip check
```

RapidOCR and pypdfium2 run locally on the CPU and need no external OCR binary.
The parser subprocess OCRs up to 25 image pages per document and uses a separate
180-second timeout. Text PDFs keep the 20-second parse timeout. Pages render at
4x by default, up to 5x for higher-resolution scans, with a 4000-pixel side cap.
OCR only runs on pages that contain an image and have little or no extractable
text. Higher-resolution rendering increases CPU and memory use; keep parser
concurrency bounded. Tesseract is an optional fallback when RapidOCR is
unavailable or cannot start: install `pytesseract` and the Tesseract binary,
then set `TESSERACT_CMD` if the binary is not on `PATH`. The application never
sends documents to an OCR service. On headless Linux, OpenCV may require the
system `libGL` package.

## Health and model readiness

`GET /api/health` returns process status and `uptime_s`. It deliberately does
not contact Ollama. `rag_ready: null` and `models_checked: false` are not
readiness claims. Verify models by running the opt-in integration tests or
performing an upload, index, and question workflow with a synthetic PDF.

```powershell
.venv\Scripts\python -m tests.live_embeddings
.venv\Scripts\python -m tests.live_answers
.venv\Scripts\python -m tests.live_conversations
```

Missing models produce actionable errors. The application does not pull models
or use a remote inference fallback. Changing a model digest invalidates relevant
cached state; rebuild the index when instructed.

## Resource limits

- One active document per session, up to 10 MiB, 100 pages, and 1 million
  extracted characters.
- OCR is optional and limited to 25 image pages per document with a 180-second
  timeout. Larger scans must be split.
- At most 50 sessions and two PDF parser subprocesses.
- One shared local-inference slot. A busy session returns HTTP 409; exhausted
  model capacity returns HTTP 503 rather than queuing unbounded work.
- Chat is limited to 30 requests per 60 seconds per session. HTTP 429 includes
  `Retry-After`.
- Conversation history is bounded to six turns and 48 KiB.

These are application limits, not measured throughput guarantees. Actual latency
depends on the host, model loading, PDF content, and competing Ollama work.
Minimum inference RAM, sustained concurrency, and uptime have not been certified.

## Data lifecycle

Runtime data is stored beneath `.data/`, outside the static directory and excluded
from Git. Documents, extracted text including OCR output, and indexes are
session-private. Deleting or replacing a document removes its associated stored data.

Sessions expire after one hour of inactivity and are not restored after a server
restart. Expiry cleanup is request-driven, not a background deletion deadline.
A hard kill can leave private run directories. Stop the server before inspecting
or removing stale runtime data, and do not publish that data as a bug attachment.
There is no supported session backup/restore workflow.

## Restricted public demos

Do not bind the unauthenticated application directly to a public interface.
For a restricted demo, keep the application and proxy listeners on loopback,
add authentication at the proxy, and terminate public HTTPS at a trusted entry
point. A shared proxy password is not a per-user account system.

One tested topology is:

```text
Browser (HTTPS) -> Cloudflare tunnel -> Caddy (loopback) -> Uvicorn (loopback)
```

Uploads pass through Cloudflare in this mode. Do not describe it as a deployment
where documents never leave the browser-to-host network path or reach a third party.

An example Caddy configuration for a listener used only by a local tunnel:

```caddyfile
:8090 {
    bind 127.0.0.1
    basic_auth {
        demo REPLACE_WITH_CADDY_PASSWORD_HASH
    }
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto {http.request.header.X-Forwarded-Proto}
    }
}
```

Replace the password-hash placeholder before starting Caddy. Generate the hash
with `caddy hash-password`; do not commit plaintext passwords or local secrets.
Preserving this header is appropriate only for the loopback listener behind the
trusted tunnel. Do not trust arbitrary client-supplied forwarded headers on a
public listener. Uvicorn should trust proxy headers only from the local proxy.

Without scheme preservation, Caddy sees the tunnel connection as HTTP and may
overwrite `X-Forwarded-Proto`. The application then rejects browser HTTPS Origins.
Static assets use root-relative paths to avoid mixed-content URLs independently.
The Caddy site address must be `:8090` with `bind 127.0.0.1`; matching only a
loopback Host can fail when the tunnel supplies its public hostname.

After configuring the proxy, verify all of the following from the public URL:

- Unauthenticated requests return HTTP 401, including static assets and APIs.
- Authenticated pages and CSS return HTTP 200 with the expected content types.
- HTTPS sessions receive Secure cookies.
- Same-origin HTTPS uploads succeed; mismatched Origins are rejected.
- Deletion and session isolation still work.

Cloudflare quick-tunnel URLs change when the tunnel restarts. The host must remain
powered on and connected. There is no bundled watchdog, alerting, or SLA.

## Release requirements

Public access is not a substitute for a security review. OS-level PDF sandboxing,
per-user authentication, durable sessions, independent quality validation, and
capacity testing remain open. See [release review](RELEASE-REVIEW.md).
