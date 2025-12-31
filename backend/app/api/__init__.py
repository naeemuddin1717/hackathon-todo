from fastapi import APIRouter
from app.api.routes import auth_router, todos_router, chat_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(todos_router)
api_router.include_router(chat_router)
