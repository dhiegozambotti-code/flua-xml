"""Worker de polling: thread de background que executa varridas periódicas."""

import logging
import threading
import time
from typing import Optional

from app.config import settings
from app.db import SessionLocal
from app.services.orquestrador import run_sweep

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_thread: Optional[threading.Thread] = None


def _loop() -> None:
    logger.info("Worker de polling iniciado (interval=%ds)", settings.polling_interval_seconds)
    while not _stop_event.is_set():
        db = SessionLocal()
        try:
            run_sweep(db)
        except Exception:
            logger.exception("Erro na varredura do orquestrador")
        finally:
            db.close()
        _stop_event.wait(timeout=settings.polling_interval_seconds)
    logger.info("Worker de polling encerrado")


def start() -> None:
    global _thread
    if not settings.polling_enabled:
        logger.info("Polling desabilitado (POLLING_ENABLED=false)")
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, name="polling-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop_event.set()
    if _thread:
        _thread.join(timeout=10)
