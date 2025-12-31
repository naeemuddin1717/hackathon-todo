from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db
from app.api import api_router

app = FastAPI(title="Todo App (FastAPI + Neon + JWT + Gemini)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000",
        "http://127.0.0.1:3000",],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/")
def health():
    return {"message": "OK"}

app.include_router(api_router)
