from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.courses import router as courses_router

app = FastAPI(title="CourseMate AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "CourseMate AI API"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
