from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import *  # noqa: F401, F403 — import all models to register them
from app.seed import seed_database
from app.routers import auth, programs, codes, lookup, transactions, payfiles, dashboard, settings as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    Base.metadata.create_all(bind=engine)
    # Seed data
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    # Create output directory
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(programs.router)
app.include_router(codes.router)
app.include_router(lookup.router)
app.include_router(transactions.router)
app.include_router(payfiles.router)
app.include_router(dashboard.router)
app.include_router(settings_router.router)


# Health check
@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}


# Serve static frontend (Next.js export) if the directory exists
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
