import asyncio
import json

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from web.document_routes import mutation_session, store_for
from web.documents import COOKIE_NAME, DocumentError
from web.ratelimit import SlidingWindowLimiter

router = APIRouter(prefix="/api/chat", tags=["answers"])


def expected_revision(request):
    value = request.headers.get("x-conversation-revision")
    if value is None:
        return None
    try:
        revision = int(value)
        if not 0 <= revision <= 2**53 - 1:
            raise ValueError
        return revision
    except ValueError:
        raise DocumentError("invalid_revision", "Invalid conversation revision. Reload history.", 400) from None


@router.get("")
def conversation_history(request: Request):
    store = store_for(request)
    session = store.get_session(request.cookies.get(COOKIE_NAME))
    with store.lock:
        doc = session.document
        if not session.busy and session.conversation.turns:
            key = doc.get("index", {}).get("cache_key") if doc else None
            if not key or doc.get("index", {}).get("status") != "ready" or session.conversation.base_key != f"{doc['id']}:{key}":
                session.conversation.clear()
        return session.conversation.snapshot(doc, session.busy)


@router.delete("")
def reset_conversation(request: Request):
    session = mutation_session(request)
    store = store_for(request)
    revision = expected_revision(request)
    with store.lock:
        if session.busy:
            raise DocumentError("busy", "Wait for processing to finish before resetting the conversation.", 409)
        doc = session.document
        if doc and request.headers.get("x-document-id") != doc["id"]:
            raise DocumentError("document_changed", "The document changed. Reload before resetting the conversation.", 409)
        if revision is not None and revision != session.conversation.revision:
            raise DocumentError("conversation_changed", "The conversation changed in another tab. Reload history before resetting.", 409)
        session.conversation.clear()
        return session.conversation.snapshot(doc, False)


@router.post("")
async def answer_question(request: Request):
    session = mutation_session(request)
    # Second layer after CSRF/origin: bound model pressure per session. Counted
    # before the body so a flood cannot even reach parsing; GET history is free.
    limiter: SlidingWindowLimiter | None = request.app.state.chat_rate_limiter
    if limiter is not None:
        allowed, retry_after = limiter.check(session.token)
        if not allowed:
            seconds = SlidingWindowLimiter.retry_after_header(retry_after)
            raise DocumentError("rate_limited",
                                f"Too many questions in one minute. Try again in {seconds} seconds.",
                                429, headers={"Retry-After": seconds})
    revision = expected_revision(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise DocumentError("invalid_type", "Questions must be submitted as JSON.", 415)
    body = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 8192:
                    raise DocumentError("question_too_large", "The question request is too large.", 413)
                body.extend(chunk)
        data = json.loads(body)
    except TimeoutError:
        raise DocumentError("question_timeout", "Question upload timed out.", 408) from None
    except (ValueError, UnicodeError):
        raise DocumentError("invalid_question", "Invalid question format.", 422) from None
    if not isinstance(data, dict) or "question" not in data or set(data) - {"question", "use_history"} or type(data.get("use_history", True)) is not bool or not isinstance(data["question"], str) or not 1 <= len(data["question"].strip()) <= 1500:
        raise DocumentError("invalid_question", "Submit one question of 1 to 1,500 characters. History, models, and URLs cannot be supplied.", 422)
    return await run_in_threadpool(request.app.state.answerer.answer, store_for(request), session,
                                   request.headers.get("x-document-id", ""), data["question"].strip(),
                                   use_history=data.get("use_history", True), expected_revision=revision)
