from fastapi import APIRouter
from app.config import settings

router = APIRouter(tags=["saude"])


@router.get("/health")
def health():
    return {"status": "ok", "env": settings.app_env}
