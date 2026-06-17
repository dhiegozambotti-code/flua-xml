from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.routes import distribuicao, empresas, organizacoes, saude
from app.workers import polling

_ADMIN_HTML = Path(__file__).parent / "static" / "admin.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    polling.start()
    yield
    polling.stop()


app = FastAPI(title="Flua XML", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(saude.router)
app.include_router(empresas.router)
app.include_router(distribuicao.router)
app.include_router(organizacoes.router)


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_panel():
    return HTMLResponse(_ADMIN_HTML.read_text(encoding="utf-8"))
