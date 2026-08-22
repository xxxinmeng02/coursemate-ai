from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.courses import router as courses_router
from app.routers.documents import router as documents_router

app = FastAPI(title="CourseMate AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses_router)
app.include_router(documents_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "CourseMate AI API"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
