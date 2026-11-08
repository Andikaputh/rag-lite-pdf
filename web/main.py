"""Small application factory: starts without Streamlit, ML downloads or secrets."""
import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.checkpoints import CHECKPOINTS, campaign_summary
from web.document_routes import router as document_router
from web.documents import DocumentError, DocumentStore
from web.indexing import IndexService
from web.answer_routes import router as answer_router
from web.answering import AnswerService
from web.policies import configured_strategy, generator_for
from web.ratelimit import CHAT_RATE_LIMIT, CHAT_RATE_WINDOW_SECONDS, SlidingWindowLimiter

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("folio")


def _surface_startup_log_under_uvicorn() -> None:
    """Attach our own handler only when uvicorn configured logging (real server).

    Under plain TestClient runs the "folio" logger has no handler and INFO is
    dropped by logging's default, keeping test output clean.
    """
    if logger.handlers:
        return
    if not logging.getLogger("uvicorn").handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_app(*, document_store: DocumentStore | None = None, index_service: IndexService | None = None,
               answer_service: AnswerService | None = None, chat_rate_limit: int | None = CHAT_RATE_LIMIT) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        store = document_store or DocumentStore(BASE_DIR.parent / ".data" / "uploads")
        application.state.documents = store
        application.state.indexer = index_service or IndexService()
        application.state.answerer = answer_service or AnswerService(application.state.indexer, generator=generator_for(configured_strategy()))
        _surface_startup_log_under_uvicorn()
        logger.info(
            "folio-web configured: chat rate limit %s, one shared inference slot, "
            "ollama http://127.0.0.1:11434, policy %s, single worker expected",
            f"{CHAT_RATE_LIMIT}/{int(CHAT_RATE_WINDOW_SECONDS)}s per session" if application.state.chat_rate_limiter else "disabled (local harness)",
            configured_strategy(),
        )

        async def sweep():
            while True:
                await asyncio.sleep(60)
                await asyncio.to_thread(store.cleanup_expired)

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await asyncio.to_thread(store.close)

    application = FastAPI(title="Folio · Document Workspace", version="0.8.0", lifespan=lifespan)
    application.include_router(document_router)
    application.include_router(answer_router)
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    started_at = time.monotonic()
    application.state.chat_rate_limiter = None if chat_rate_limit is None else SlidingWindowLimiter(
        chat_rate_limit, CHAT_RATE_WINDOW_SECONDS)

    @application.exception_handler(DocumentError)
    async def document_error(request: Request, error: DocumentError):
        return JSONResponse({"error": {"code": error.code, "message": error.message}},
                            status_code=error.status, headers=error.headers or None)

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def workspace(request: Request):
        return templates.TemplateResponse(
            request=request, name="workspace.html",
            context={"checkpoints": CHECKPOINTS, "campaign": campaign_summary()},
        )

    @application.get("/api/health")
    def health():
        # uptime_s is process-local monitoring metadata, not an availability claim.
        return {"status": "ok", "service": "folio-web", "rag_available": True, "rag_ready": None,
                "models_checked": False, "uptime_s": max(0, int(time.monotonic() - started_at))}

    @application.get("/api/checkpoints")
    def checkpoints():
        return {"summary": campaign_summary(), "checkpoints": CHECKPOINTS}

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    return application


app = create_app()
