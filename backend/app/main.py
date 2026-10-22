import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import SessionLocal
from app.routers import admin, auth, github, repos
from app.security import csrf_ok
from app.services import get_or_create_org

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as db:
        get_or_create_org(db)
    yield


app = FastAPI(title="Rino API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if not csrf_ok(request):
        return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(github.router)
app.include_router(repos.router)
