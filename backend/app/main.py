from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from sqlalchemy import inspect, text
import os

from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import *  # noqa: F401, F403 — import all models to register them
from app.seed import seed_database
from app.routers import auth, programs, codes, lookup, transactions, payfiles, dashboard, settings as settings_router


def _ensure_rule_type_state_value() -> None:
    """
    Idempotent ALTER TYPE for the rule_type Postgres enum. The model
    declares 'state' as a valid rule_type but the enum was created
    earlier without it, so any program saved with a state-targeting
    rule failed at INSERT with InvalidTextRepresentation \u2014 surfaced
    as a 500 on PUT /api/programs/{id} which the SPA shows as a
    generic "Request failed" toast.

    Postgres supports ADD VALUE IF NOT EXISTS for enums (>=9.6), so
    this is a no-op on second boot. SQLite doesn't have a true enum
    \u2014 SQLAlchemy's Enum is implemented as a CHECK constraint at
    create_all time, and recreating the table to update it is
    overkill for dev. The model-level Enum tuple is the only check
    on SQLite, which already includes 'state' after the model edit.
    """
    if not settings.DATABASE_URL.startswith("postgres"):
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TYPE rule_type ADD VALUE IF NOT EXISTS 'state'"))


def _ensure_program_type_dealer_cash_value() -> None:
    """
    Same pattern as the rule_type fix above, for the program_type enum.
    'dealer_cash' was added to PROGRAM_TYPES so admins can create
    dealer-funded incentives that stack with everything; existing
    Postgres enums need the value appended explicitly or program saves
    fail with InvalidTextRepresentation.
    """
    if not settings.DATABASE_URL.startswith("postgres"):
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TYPE program_type ADD VALUE IF NOT EXISTS 'dealer_cash'"))


def _ensure_program_type_vin_specific_value() -> None:
    """
    Postgres enum migration for the vin_specific program type. Same
    rationale as the dealer_cash helper — the SQLAlchemy Enum value
    list is the model declaration, but the live Postgres enum has to
    be ALTER TYPE'd or program saves with the new type fail with
    InvalidTextRepresentation.
    """
    if not settings.DATABASE_URL.startswith("postgres"):
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TYPE program_type ADD VALUE IF NOT EXISTS 'vin_specific'"))


def _ensure_body_style_arcane_works_value() -> None:
    """
    Postgres enum migration for the arcane_works body style. Same
    pattern as the program_type migrations — Arcane Works is now its
    own body code (not station_wagon + special_edition), so the
    body_style_enum needs the new value or any matrix rebuild that
    inserts an arcane_works row blows up with InvalidTextRepresentation.
    """
    if not settings.DATABASE_URL.startswith("postgres"):
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TYPE body_style_enum ADD VALUE IF NOT EXISTS 'arcane_works'"))


def _ensure_dealer_cash_stacking_rules() -> None:
    """
    Idempotent backfill for the dealer_cash StackingRule rows. The
    seed only writes rows on a fresh DB, so existing deployments
    won't have any dealer_cash entries in stacking_rules \u2014 the
    matrix lookup would treat the program type as disallowed for
    every deal type. Insert allowed='Y' for cash/apr/lease (the
    user-stated default: stackable with everything retail) and
    allowed='N' for cvp/demo (where dealer cash typically isn't
    layered). Uses the ORM so SQLAlchemy generates the UUID id
    that the column expects via its Python-side default.
    """
    insp = inspect(engine)
    if "stacking_rules" not in insp.get_table_names():
        return
    from app.models.budget import StackingRule  # local import \u2014 model may not be ready at module import time
    rules = [
        ("cash", "Y"),
        ("apr", "Y"),
        ("lease", "Y"),
        ("cvp", "N"),
        ("demo", "N"),
    ]
    with SessionLocal() as session:
        for deal_type, allowed in rules:
            existing = session.query(StackingRule).filter(
                StackingRule.deal_type == deal_type,
                StackingRule.program_type == "dealer_cash",
            ).first()
            if existing:
                continue
            session.add(StackingRule(
                deal_type=deal_type, program_type="dealer_cash", allowed=allowed,
            ))
        session.commit()


def _ensure_vin_specific_stacking_rules() -> None:
    """
    Mirrors _ensure_dealer_cash_stacking_rules for the vin_specific
    program type. Default: stackable with all retail deal types
    (cash/apr/lease) since per-VIN MSRP rebates are intended as
    additive unit-level incentives. Excluded from cvp/demo channels.
    """
    insp = inspect(engine)
    if "stacking_rules" not in insp.get_table_names():
        return
    from app.models.budget import StackingRule
    rules = [
        ("cash", "Y"),
        ("apr", "Y"),
        ("lease", "Y"),
        ("cvp", "N"),
        ("demo", "N"),
    ]
    with SessionLocal() as session:
        for deal_type, allowed in rules:
            existing = session.query(StackingRule).filter(
                StackingRule.deal_type == deal_type,
                StackingRule.program_type == "vin_specific",
            ).first()
            if existing:
                continue
            session.add(StackingRule(
                deal_type=deal_type, program_type="vin_specific", allowed=allowed,
            ))
        session.commit()


def _ensure_cvp_stacking_rules() -> None:
    """
    Idempotent fix-up for the cvp/bonus_cash StackingRule. The seed
    originally wrote allowed='Y' for that pair (matching the old
    DEFAULT_STACKING), so existing DBs keep stacking bonus_cash
    programs onto CVP codes even after the default flips. Force the
    row to allowed='N' if it exists. Runs every boot but no-ops once
    the row is already 'N'.
    """
    insp = inspect(engine)
    if "stacking_rules" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE stacking_rules SET allowed = 'N' "
            "WHERE deal_type = 'cvp' AND program_type = 'bonus_cash' AND allowed = 'Y'"
        ))


def _ensure_campaign_code_width() -> None:
    """
    Idempotent ALTER for the campaign_codes.code column width.
    Bumped 6 → 10 (APR/Lease MY suffix) → 12 (special-edition
    codes that need body+deal+flags suffixes). Postgres-only —
    SQLite doesn't enforce VARCHAR length so its CHECK constraint
    already accepts any length.
    """
    if not settings.DATABASE_URL.startswith("postgres"):
        return
    insp = inspect(engine)
    if "campaign_codes" not in insp.get_table_names():
        return
    cols = {c["name"]: c for c in insp.get_columns("campaign_codes")}
    code_col = cols.get("code")
    if not code_col:
        return
    # SQLAlchemy reports type as e.g. VARCHAR(10); read .length when
    # available. Skip if already >= 12.
    existing_len = getattr(getattr(code_col.get("type"), "length", None), "real", None) or getattr(code_col.get("type"), "length", None)
    try:
        if existing_len and int(existing_len) >= 12:
            return
    except (TypeError, ValueError):
        pass
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE campaign_codes ALTER COLUMN code TYPE VARCHAR(12)"))


def _ensure_program_not_stackable_column() -> None:
    """
    Idempotent ALTER for the per-program stacking exclusion list.
    Stored as JSON so we don't need a separate join table for what
    is conceptually a small per-program array of program ids.
    """
    insp = inspect(engine)
    if "programs" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("programs")}
    if "not_stackable_program_ids" in cols:
        return
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    add_sql = (
        "ALTER TABLE programs ADD COLUMN not_stackable_program_ids JSON"
        if not is_sqlite
        else "ALTER TABLE programs ADD COLUMN not_stackable_program_ids TEXT"
    )
    with engine.begin() as conn:
        conn.execute(text(add_sql))


def _ensure_program_public_facing_column() -> None:
    """
    Idempotent ALTER for the public_facing flag. Defaults TRUE so
    programs that existed before this column landed keep emitting
    customer disclaimers in their PDF bulletins — only newly-created
    or explicitly-marked-private programs skip the disclaimer block.
    """
    insp = inspect(engine)
    if "programs" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("programs")}
    if "public_facing" in cols:
        return
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    add_sql = (
        "ALTER TABLE programs ADD COLUMN public_facing BOOLEAN NOT NULL DEFAULT 1"
        if is_sqlite
        else "ALTER TABLE programs ADD COLUMN public_facing BOOLEAN NOT NULL DEFAULT true"
    )
    with engine.begin() as conn:
        conn.execute(text(add_sql))


def _ensure_program_published_column() -> None:
    """
    Idempotent ALTER for the production gate. The app uses
    Base.metadata.create_all (no Alembic), so a new column on an
    existing table never lands automatically. We inspect the live
    schema, add the column when it's missing, then backfill so
    every program currently in 'active' status stays publicly
    visible on the first deploy after the gate ships — without
    that backfill, every existing program would silently drop
    off the public /lookup/ page.
    """
    insp = inspect(engine)
    if "programs" not in insp.get_table_names():
        return  # create_all will handle a fresh DB
    cols = {c["name"] for c in insp.get_columns("programs")}
    if "published" in cols:
        return
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    add_sql = (
        "ALTER TABLE programs ADD COLUMN published BOOLEAN NOT NULL DEFAULT 0"
        if is_sqlite
        else "ALTER TABLE programs ADD COLUMN published BOOLEAN NOT NULL DEFAULT false"
    )
    backfill_sql = "UPDATE programs SET published = TRUE WHERE status = 'active'"
    with engine.begin() as conn:
        conn.execute(text(add_sql))
        conn.execute(text(backfill_sql))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    Base.metadata.create_all(bind=engine)
    # Run idempotent migrations that create_all can't do
    _ensure_rule_type_state_value()
    _ensure_program_type_dealer_cash_value()
    _ensure_program_type_vin_specific_value()
    _ensure_body_style_arcane_works_value()
    _ensure_program_published_column()
    _ensure_program_public_facing_column()
    _ensure_program_not_stackable_column()
    _ensure_campaign_code_width()
    _ensure_cvp_stacking_rules()
    _ensure_dealer_cash_stacking_rules()
    _ensure_vin_specific_stacking_rules()
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
