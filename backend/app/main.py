from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .scheduler import start as start_scheduler
from .routers import extraction, ledger, meetings, notifications, people, review


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    sched = start_scheduler() if settings.scheduler_enabled else None
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(
    title="Ledgerline API",
    description="Decisions that stick. Contradictions that don't slip through.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(meetings.router)
app.include_router(extraction.router)
app.include_router(ledger.router)
app.include_router(review.router)
app.include_router(notifications.router)
app.include_router(people.router)


@app.get("/api/health")
def health():
    return {"ok": True, "demo_mode": settings.use_mock_llm}
