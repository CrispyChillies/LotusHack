from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.auth_router import router as auth_router
from app.routers.graph_router import router as graph_router
from app.routers.relation_router import router as relation_router
from app.routers.media_crud_router import router as media_crud_router
from app.routers.user_crud_router import router as user_crud_router

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
app.include_router(graph_router, prefix="/api/v1/graph", tags=["Memory Graph"])
app.include_router(relation_router, prefix="/api/relations", tags=["Relations"])
app.include_router(user_crud_router, prefix="/api/v1", tags=["User CRUD"])
app.include_router(media_crud_router, prefix="/api/v1", tags=["Media CRUD"])

@app.get("/", tags=["Health"])
async def root():
    return {"message": "Welcome to Memory Companion API!", "docs": "/docs"}
