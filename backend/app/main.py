from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.auth_router import router as auth_router

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

@app.get("/", tags=["Health"])
async def root():
    return {"message": "Welcome to Memory Companion API!", "docs": "/docs"}
