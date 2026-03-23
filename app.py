"""
MLB Betting System — Web Dashboard
FastAPI application serving the browser-based UI.

Run:
    uvicorn app:app --reload --port 8000
Then open:  http://localhost:8000
"""

from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager

from web.routers import predictions, bets, health, config_router, scheduler_api, logs_router, teams_router

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    (BASE_DIR / "output_data").mkdir(exist_ok=True)
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    # Initialise SQLite schema (CREATE TABLE IF NOT EXISTS — always safe)
    from db.schema import init_db
    init_db()
    # Seed the team registry with all 30 canonical teams (INSERT OR IGNORE)
    from db.team_registry import seed_from_config
    seed_from_config()
    # Load any user-confirmed team aliases from DB into the runtime resolver map
    from mlb.team_resolver import _load_db_aliases
    _load_db_aliases()
    # Hot-load registry source names into the resolver (in case of locked rows)
    from db.team_registry import _reload_resolver
    _reload_resolver()
    # Configure logging first (sets up file + console handlers)
    from web.state import load_config_overrides
    from utils.logger import configure_logging
    cfg = load_config_overrides()
    saved_level = cfg.get("log_level", "INFO")
    configure_logging(saved_level)
    yield


app = FastAPI(
    title="MLB Betting System",
    description="MLB moneyline prediction dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files + templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/help", StaticFiles(directory=str(BASE_DIR / "help"), html=True), name="help")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# API routers
app.include_router(predictions.router)
app.include_router(bets.router)
app.include_router(health.router)
app.include_router(config_router.router)
app.include_router(scheduler_api.router)
app.include_router(logs_router.router)
app.include_router(teams_router.router)


# ── Page routes ──────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/predictions")
def predictions_page(request: Request):
    return templates.TemplateResponse("predictions.html", {"request": request})


@app.get("/bets")
def bets_page(request: Request):
    return templates.TemplateResponse("bets.html", {"request": request})


@app.get("/analytics")
def analytics_page(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request})


@app.get("/model")
def model_page(request: Request):
    return templates.TemplateResponse("model.html", {"request": request})


@app.get("/config")
def config_page(request: Request):
    return templates.TemplateResponse("config.html", {"request": request})


@app.get("/logs")
def logs_page(request: Request):
    return templates.TemplateResponse("logs.html", {"request": request})


@app.get("/teams")
def teams_page(request: Request):
    return templates.TemplateResponse("teams.html", {"request": request})
