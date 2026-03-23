from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from web.state import load_config_overrides, save_config_overrides, get_default_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config():
    return load_config_overrides()


@router.get("/defaults")
def get_defaults():
    return get_default_config()


@router.put("")
def update_config(payload: dict):
    """Replace the full config override document."""
    save_config_overrides(payload)
    return {"success": True, "config": payload}


@router.post("/reset")
def reset_config():
    defaults = get_default_config()
    save_config_overrides(defaults)
    return {"success": True, "config": defaults}
