"""Single source of truth for the migration campaign; no fake RAG metrics."""

CHECKPOINTS = (
    {
        "id": "01", "title": "Base camp", "subtitle": "Web application foundation",
        "status": "done", "description": "FastAPI, a responsive workspace, implementation status, and HTTP tests without an API key.",
        "criteria": ["FastAPI serves pages and assets", "Workspace and status navigation", "Health API and foundation tests"],
    },
    {
        "id": "02", "title": "Document gateway", "subtitle": "PDF upload and validation",
        "status": "done", "description": "Uploads up to 10 MiB/100 pages, PDF validation, session isolation, atomic replacement, and document deletion.",
        "criteria": ["Explicit upload limits", "Actionable PDF errors", "Valid and invalid PDF tests"],
    },
    {
        "id": "03", "title": "Knowledge engine", "subtitle": "Indexing & lifecycle",
        "status": "done", "description": "Page-aware chunks, local BGE-M3, isolated SQLite indexes, hash/config/model-based reuse, and lifecycle cleanup.",
        "criteria": ["Reusable per-document index", "Session and index isolation", "Reset and failure recovery tests"],
    },
    {
        "id": "04", "title": "Grounded answers", "subtitle": "Retrieval, answers, and citations",
        "status": "done", "description": "Dense retrieval without re-indexing, local Ollama generation, quote/page checks, abstention, and explicit errors.",
        "criteria": ["Retrieval connected to local Ollama", "Verifiable citations", "Model errors and injection requests handled"],
    },
    {
        "id": "05", "title": "Conversation flow", "subtitle": "History and follow-up questions",
        "status": "done", "description": "Temporary history up to 6 turns/48 KiB, question-topic follow-ups, reset, and cross-tab revisions. Evidence is retrieved afresh.",
        "criteria": ["Context-aware follow-ups", "Bounded and isolated history", "Conversation reset tests"],
    },
    {
        "id": "06", "title": "Quality arena", "subtitle": "RAG evaluation and validation",
        "status": "done", "description": "Versioned synthetic evaluation, extractive evidence checks, exact server-side conversions, and question-language handling. Production quality validation remains incomplete.",
        "criteria": ["Versioned datasets and results", "Automatic metrics separated from semantic review", "Candidate comparisons and known limitations"],
    },
    {
        "id": "07", "title": "Polish pass", "subtitle": "Interaction and accessibility",
        "status": "done", "description": "Loading, error, and empty states, health retries, Escape handling, keyboard focus, and mobile touch targets. Not a WCAG certification.",
        "criteria": ["Browser workflow tests", "Mobile and keyboard checks", "Loading, empty, and error states"],
    },
    {
        "id": "08", "title": "Launch gate", "subtitle": "Reproducibility & release",
        "status": "done", "description": "Pinned dependencies, CI, resource limits, health monitoring, and a deployment review. Continuous hosting requires an available host and network.",
        "criteria": ["Clean installation and CI checks", "Self-hosting and capacity checks", "Model license and security review"],
    },
)


def campaign_summary():
    """Count milestones, not RAG accuracy or equal-weight product completion."""
    completed = sum(item["status"] == "done" for item in CHECKPOINTS)
    return {"completed": completed, "total": len(CHECKPOINTS), "next_id": next(
        (item["id"] for item in CHECKPOINTS if item["status"] == "next"), None
    )}
