"""Creative Brief API — application entry point.

Run from the backend/ folder:   python -m uvicorn app.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST, settings
from .database import init_db
from .errors import AppError
from .routers import auth, contents, governance, knowledge, workflow


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Creative Brief API", version="2.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"])


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


for module in (auth, knowledge, contents, workflow, governance):
    app.include_router(module.router)

if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


@app.get("/", include_in_schema=False)
def index():
    built = FRONTEND_DIST / "index.html"
    if built.is_file():
        return FileResponse(built)
    return {"service": "Creative Brief API", "status": "running", "docs": "/docs",
            "frontend": "Run the Vite frontend on http://localhost:5173"}
