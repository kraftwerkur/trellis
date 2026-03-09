"""FastAPI application entry point."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from trellis.database import Base, async_session, engine
from trellis.models import Agent, ModelRoute
from trellis.schemas import Envelope


# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    import os

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from trellis.api import seed_default_routes
    async with async_session() as db:
        await seed_default_routes(db)

    # Warn if management/ingestion API keys are not configured
    _log = logging.getLogger("trellis")
    if not os.environ.get("TRELLIS_MANAGEMENT_API_KEY"):
        _log.warning(
            "TRELLIS_MANAGEMENT_API_KEY is not set — management API is unprotected (dev mode). "
            "Set this env var in production!"
        )
    if not os.environ.get("TRELLIS_INGESTION_API_KEY"):
        _log.warning(
            "TRELLIS_INGESTION_API_KEY is not set — ingestion API is unprotected (dev mode). "
            "Set this env var in production!"
        )

    from trellis.agents.health_auditor import health_auditor_loop
    auditor_task = asyncio.create_task(health_auditor_loop())

    from trellis.agents.audit_compactor import compactor_loop
    compactor_task = asyncio.create_task(compactor_loop())

    from trellis.agents.rule_optimizer import rule_optimizer_loop
    optimizer_task = asyncio.create_task(rule_optimizer_loop())

    from trellis.agents.schema_drift import schema_drift_loop
    schema_drift_task = asyncio.create_task(schema_drift_loop())

    from trellis.agents.cost_optimizer import cost_optimizer_loop
    cost_optimizer_task = asyncio.create_task(cost_optimizer_loop())

    yield

    for t in (auditor_task, compactor_task, optimizer_task, schema_drift_task, cost_optimizer_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Trellis",
    description="Enterprise AI Agent Orchestration Platform",
    version="0.3.0",
    lifespan=lifespan,
)

_cors_env = os.environ.get("TRELLIS_CORS_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else ["http://localhost:8100", "http://localhost:3000"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ── Mock agent (built-in for demo) ────────────────────────────────────────

mock_router = APIRouter(prefix="/mock-agent", tags=["mock"])


@mock_router.post("/envelope")
async def mock_agent_envelope(envelope: Envelope):
    text = envelope.payload.text or "(no text)"
    return {
        "status": "completed",
        "result": {"text": f"I received your message: {text}", "data": {}, "attachments": []},
        "delegations": [],
        "cost_report": {"inference_calls": 0, "total_tokens": 0, "estimated_cost_usd": 0.0, "model": "mock"},
    }


@mock_router.get("/health")
async def mock_agent_health():
    return {"status": "healthy"}


@mock_router.get("/manifest")
async def mock_agent_manifest():
    return {
        "name": "Mock Echo Agent", "tools": ["echo"], "channels": ["api"],
        "maturity": "autonomous", "framework": "mock", "department": "IT",
    }


# ── Mount routers ──────────────────────────────────────────────────────────

from trellis.api import (
    agents_router, audit_router, costs_router, event_router,
    finops_router, gateway_mgmt_router, health_router, keys_router, rules_router,
    phi_router, tools_router,
)
from trellis.intelligent_router import intelligent_router as intelligent_routing_router
from trellis.gateway import router as gateway_llm_router
from trellis.observatory import observatory_router
from trellis.agents.health_auditor import health_auditor_router
from trellis.bot_service import bot_router

api = APIRouter(prefix="/api")
api.include_router(health_router)
api.include_router(health_auditor_router)
api.include_router(agents_router)
api.include_router(rules_router)
api.include_router(event_router)
api.include_router(keys_router)
api.include_router(costs_router)
api.include_router(audit_router)
api.include_router(finops_router)
api.include_router(gateway_mgmt_router)
api.include_router(phi_router)
api.include_router(tools_router)
api.include_router(observatory_router)
api.include_router(intelligent_routing_router)

app.include_router(api)
app.include_router(gateway_llm_router)
app.include_router(mock_router)
app.include_router(bot_router)


@app.get("/health")
async def root_health():
    return {"status": "healthy", "service": "trellis"}


# ── Static dashboard (served from /app/static in Docker) ──────────────────

import os
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
# Docker: /app/static (copied from dashboard/out)
# Local dev: prefer dashboard/out (always fresh), fall back to static/
_static_dir = _project_root / "static"
_dashboard_out = _project_root / "dashboard" / "out"
if _dashboard_out.is_dir():
    _static_dir = _dashboard_out
if _static_dir.is_dir():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    def _resolve_static(path: str = "") -> Path:
        """Resolve a URL path to a static file."""
        if not path:
            return _static_dir / "index.html"
        file = _static_dir / path
        if file.is_file():
            return file
        html_file = _static_dir / f"{path}.html"
        if html_file.is_file():
            return html_file
        # Check for directory with index.html (Next.js trailingSlash)
        idx = _static_dir / path.rstrip("/") / "index.html"
        if idx.is_file():
            return idx
        return _static_dir / "index.html"

    # Mount _next/ as static files (JS/CSS chunks must be served with correct MIME types)
    _next_dir = _static_dir / "_next"
    if _next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=str(_next_dir)), name="next-static")

    @app.get("/")
    async def dashboard_index():
        return FileResponse(_resolve_static())

    @app.head("/")
    async def dashboard_index_head():
        return FileResponse(_resolve_static())

    # Catch-all: serve static dashboard files (GET/HEAD + POST for Next.js RSC prefetch)
    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST"])
    async def dashboard_catchall(path: str, request: Request):
        # Don't intercept API routes
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(_resolve_static(path))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("trellis.main:app", host="0.0.0.0", port=8100, reload=True)
