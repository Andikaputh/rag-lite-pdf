"""Same-origin, CSRF-protected raw PDF upload. No multipart spool surprises."""
import asyncio
import secrets
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from web.documents import COOKIE_NAME, DocumentError, DocumentStore, safe_filename

router = APIRouter(prefix="/api/documents", tags=["documents"])


def store_for(request: Request) -> DocumentStore:
    return request.app.state.documents


def mutation_session(request: Request):
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin is not None and origin != str(request.base_url).rstrip("/")
    ):
        raise DocumentError("origin_rejected", "Cross-site requests are not allowed.", 403)
    session = store_for(request).get_session(request.cookies.get(COOKIE_NAME))
    if not secrets.compare_digest(request.headers.get("x-csrf-token", "").encode("utf-8"), session.csrf.encode("utf-8")):
        raise DocumentError("csrf_rejected", "Invalid security token. Reload the page.", 403)
    return session


@router.get("")
def current_document(request: Request):
    store = store_for(request)
    session = store.get_session(request.cookies.get(COOKIE_NAME), create=True)
    response = JSONResponse({
        "document": session.document, "processing": session.busy, "csrf_token": session.csrf,
        "limits": {"max_bytes": store.max_bytes, "max_pages": store.max_pages,
                   "max_ocr_pages": store.max_ocr_pages, "session_ttl_seconds": store.ttl},
    })
    response.set_cookie(COOKIE_NAME, session.token, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=store.ttl)
    return response


@router.post("", status_code=201)
async def upload_document(request: Request):
    store = store_for(request)
    session = mutation_session(request)
    name = safe_filename(unquote(request.headers.get("x-file-name", "")))
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in (
        "application/pdf", "application/octet-stream",
    ):
        raise DocumentError("invalid_type", "Uploads must use the PDF content type.", 415)
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared_length = int(length)
        except ValueError:
            raise DocumentError("invalid_length", "Invalid upload size.", 400) from None
        if declared_length < 0:
            raise DocumentError("invalid_length", "Invalid upload size.", 400)
        if declared_length > store.max_bytes:
            raise DocumentError("too_large", f"PDFs may be up to {store.max_bytes // (1024 * 1024)} MiB.", 413)
    store.begin_upload(session)
    path = store.root / session.token / "incoming.pdf"
    try:
        size = 0
        async with asyncio.timeout(30):
            with path.open("wb") as target:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > store.max_bytes:
                        raise DocumentError("too_large", "The PDF exceeds the upload size limit.", 413)
                    await run_in_threadpool(target.write, chunk)
        if not size:
            raise DocumentError("empty_file", "The file is empty. Choose a PDF with content.")
        parsed = await run_in_threadpool(store.validate, path)
        document = await run_in_threadpool(store.commit, session, path, name, size, parsed)
        return {"document": document}
    except TimeoutError:
        raise DocumentError("upload_timeout", "Upload timed out. Retry with a more stable connection.", 408) from None
    except OSError:
        raise DocumentError("storage_unavailable", "Server storage is unavailable. Try again later.", 503) from None
    finally:
        try:
            path.unlink(missing_ok=True)
        finally:
            store.end_upload(session)


@router.delete("", status_code=204)
def delete_document(request: Request):
    session = mutation_session(request)
    store_for(request).delete(session)
    return Response(status_code=204)


@router.post("/index")
def index_document(request: Request):
    session = mutation_session(request)
    document_id = request.headers.get("x-document-id", "")
    return request.app.state.indexer.ensure(store_for(request), session, document_id)
