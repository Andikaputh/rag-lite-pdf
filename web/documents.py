"""Bounded, local single-process document gateway. No external model calls."""
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from web.conversations import Conversation

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 100
MAX_CHARS = 1_000_000
COOKIE_NAME = "folio_session"


class DocumentError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, *, headers: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.headers = headers or {}


@dataclass
class Session:
    token: str
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = field(default_factory=time.monotonic)
    document: dict | None = None
    busy: bool = False
    conversation: Conversation = field(default_factory=Conversation)


class DocumentStore:
    """One active PDF/session; temporary files live outside the public static tree.

    Use ONE server worker. Session state is intentionally ephemeral and not auth.
    A hard process kill can leave private run directories; see deployment notes.
    """
    def __init__(self, data_dir: Path, *, max_bytes=MAX_BYTES, max_pages=MAX_PAGES,
                 max_chars=MAX_CHARS, ttl=3600, max_sessions=50, max_parsers=2,
                 parse_timeout=20):
        data_dir.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(prefix="folio-", dir=data_dir)
        self.root = Path(self._temporary.name)
        self.max_bytes, self.max_pages, self.max_chars = max_bytes, max_pages, max_chars
        self.ttl, self.max_sessions, self.parse_timeout = ttl, max_sessions, parse_timeout
        self.sessions: dict[str, Session] = {}
        self.lock = threading.RLock()
        self.parsers = threading.BoundedSemaphore(max_parsers)

    def close(self):
        with self.lock:
            self.sessions.clear()
            self._temporary.cleanup()

    def cleanup_expired(self):
        with self.lock:
            now = time.monotonic()
            for token, session in list(self.sessions.items()):
                if not session.busy and now - session.touched >= self.ttl:
                    shutil.rmtree(self.root / token)
                    del self.sessions[token]

    def get_session(self, token: str | None, *, create=False):
        with self.lock:
            self.cleanup_expired()
            session = self.sessions.get(token or "")
            if session:
                session.touched = time.monotonic()
                return session
            if not create:
                raise DocumentError("session_expired", "Session expired. Reload the page and try again.", 403)
            if len(self.sessions) >= self.max_sessions:
                raise DocumentError("capacity", "The server has reached its session limit. Try again later.", 503)
            session = Session(token=secrets.token_urlsafe(32))
            (self.root / session.token).mkdir(mode=0o700)
            self.sessions[session.token] = session
            return session

    def begin_upload(self, session: Session):
        with self.lock:
            if session.busy:
                raise DocumentError("busy", "This session is processing a document. Wait for completion.", 409)
            if not self.parsers.acquire(blocking=False):
                raise DocumentError("capacity", "All PDF parsers are busy. Try again shortly.", 503)
            session.busy = True

    def end_upload(self, session: Session):
        with self.lock:
            session.busy = False
            session.touched = time.monotonic()
            self.parsers.release()

    def validate(self, path: Path) -> dict:
        """Subprocess bounds wall time and isolates parser failures, not OS memory.

        Only a server-generated path and numeric limits reach the worker. Never
        feed uploaded filenames to a shell, command line, or filesystem path.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "web.pdf_worker", str(path.resolve()),
                 str(self.max_pages), str(self.max_chars)],
                cwd=Path(__file__).resolve().parent.parent, capture_output=True,
                timeout=self.parse_timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise DocumentError("parse_timeout", "PDF parsing timed out. Try a simpler PDF.", 422) from None
        if result.returncode != 0:
            raise DocumentError("parser_failed", "The PDF could not be processed safely. Try another file.")
        try:
            data = json.loads(result.stdout)
            if "error" in data:
                raise DocumentError(data["error"]["code"], data["error"]["message"])
            return data
        except (json.JSONDecodeError, KeyError, TypeError):
            raise DocumentError("parser_failed", "The PDF parser returned invalid output. Try another file.") from None

    def commit(self, session: Session, path: Path, name: str, size: int, parsed: dict):
        with self.lock:
            pdf_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            if session.document and session.document["sha256"] == pdf_sha256:
                # Identical bytes in this session keep the document ID and its
                # index. No cross-session cache or existence side-channel.
                if session.document["name"] != name:
                    session.conversation.clear()
                session.document = {**session.document, "name": name}
                return session.document
            document_id = secrets.token_hex(16)
            directory = self.root / session.token / document_id
            directory.mkdir(mode=0o700)
            try:
                path.replace(directory / "document.pdf")
                (directory / "pages.json").write_text(json.dumps(parsed["pages"], ensure_ascii=False), encoding="utf-8")
                metadata = {
                    "id": document_id, "name": name, "size_bytes": size,
                    "page_count": parsed["page_count"], "text_characters": parsed["text_characters"],
                    "empty_pages": parsed["empty_pages"], "status": "validated",
                    "sha256": pdf_sha256,
                }
                old = session.document
                if old:
                    shutil.rmtree(self.root / session.token / old["id"])
                session.document = metadata
                session.conversation.clear()
                return metadata
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise

    def delete(self, session: Session):
        with self.lock:
            if session.busy:
                raise DocumentError("busy", "Wait for processing to finish before deleting the document.", 409)
            if session.document:
                shutil.rmtree(self.root / session.token / session.document["id"])
                session.document = None
            session.conversation.clear()


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f<>\"'&]", "", name).strip()
    if not name.lower().endswith(".pdf") or len(name) > 180:
        raise DocumentError("invalid_filename", "Choose a .pdf file with a filename of at most 180 characters.", 415)
    return name
