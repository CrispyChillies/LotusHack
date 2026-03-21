import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from app.routers.auth_router import router as auth_router
from app.routers.agentic_router import router as agentic_router
from app.routers.graph_router import router as graph_router
from app.routers.relation_router import router as relation_router
from app.routers.media_crud_router import router as media_crud_router
from app.routers.user_crud_router import router as user_crud_router

_FRONTEND_FILE = Path(__file__).resolve().parents[1] / "manual_test" / "index.html"
_GRAPH_VISUALIZE_FILE = Path(__file__).resolve().parents[1] / "manual_test" / "graph_visualize.html"
_ngrok_tunnel = None

load_dotenv()


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(
    title="Memory Companion API",
    description="Backend API cho ứng dụng Memory Companion hỗ trợ người mất trí nhớ.",
    version="1.0.0"
)

# Cấu hình CORS (Cho phép frontend gọi API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Trong production nên sửa lại domain cụ thể
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount các Router
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(agentic_router, prefix="/api/v1/agentic", tags=["Agentic"])
app.include_router(graph_router, prefix="/api/v1/graph", tags=["Memory Graph"])
app.include_router(relation_router, prefix="/api/relations", tags=["Relations"])
app.include_router(user_crud_router, prefix="/api/v1", tags=["User CRUD"])
app.include_router(media_crud_router, prefix="/api/v1", tags=["Media CRUD"])

@app.get("/", tags=["Health"])
async def root():
    return {"message": "Welcome to Memory Companion API!", "docs": "/docs"}


@app.get("/frontend", tags=["Frontend"])
async def frontend_page():
    return FileResponse(_FRONTEND_FILE)


@app.get("/graph_visualize", tags=["Frontend"])
async def graph_visualize_page():
    return FileResponse(_GRAPH_VISUALIZE_FILE)


@app.on_event("startup")
async def startup_ngrok() -> None:
    global _ngrok_tunnel

    if os.getenv("PYTEST_CURRENT_TEST"):
        return

    if not _is_truthy(os.getenv("NGROK_ENABLED", "false")):
        return

    ngrok_token = os.getenv("NGROK_AUTHTOKEN")
    if not ngrok_token:
        print("[ngrok] NGROK_ENABLED is true but NGROK_AUTHTOKEN is missing.")
        return

    try:
        from pyngrok import ngrok
    except Exception as exc:
        print(f"[ngrok] pyngrok unavailable: {exc}")
        return

    try:
        ngrok.set_auth_token(ngrok_token)
        port = int(os.getenv("NGROK_PORT", "8000"))
        domain = os.getenv("NGROK_DOMAIN")

        for tunnel in ngrok.get_tunnels():
            if str(tunnel.config.get("addr", "")).endswith(f":{port}"):
                _ngrok_tunnel = tunnel
                print(f"[ngrok] Reusing tunnel: {tunnel.public_url}")
                return

        if domain:
            _ngrok_tunnel = ngrok.connect(addr=port, proto="http", domain=domain)
        else:
            _ngrok_tunnel = ngrok.connect(addr=port, proto="http")

        print(f"[ngrok] Public URL: {_ngrok_tunnel.public_url}")
    except Exception as exc:
        print(f"[ngrok] Failed to start tunnel: {exc}")


@app.on_event("shutdown")
async def shutdown_ngrok() -> None:
    global _ngrok_tunnel
    if _ngrok_tunnel is None:
        return

    try:
        from pyngrok import ngrok

        ngrok.disconnect(_ngrok_tunnel.public_url)
        print(f"[ngrok] Disconnected tunnel: {_ngrok_tunnel.public_url}")
    except Exception:
        pass
    finally:
        _ngrok_tunnel = None
