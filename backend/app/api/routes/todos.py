from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime, timezone

from app.core.database import get_session
from app.api.deps import get_current_user
from app.models import Todo, User
from app.schemas.todo import TodoCreate, TodoUpdate

router = APIRouter(prefix="/todos", tags=["todos"])

@router.get("")
def list_todos(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    todos = session.exec(select(Todo).where(Todo.user_id == user.id).order_by(Todo.id.desc())).all()
    return todos

@router.post("", status_code=201)
def create_todo(data: TodoCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    todo = Todo(user_id=user.id, title=data.title, description=data.description)
    session.add(todo)
    session.commit()
    session.refresh(todo)
    return todo

@router.get("/{todo_id}")
def get_todo(todo_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    todo = session.get(Todo, todo_id)
    if not todo or todo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo

@router.patch("/{todo_id}")
def update_todo(todo_id: int, data: TodoUpdate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    todo = session.get(Todo, todo_id)
    if not todo or todo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Todo not found")

    if data.title is not None:
        todo.title = data.title
    if data.description is not None:
        todo.description = data.description
    if data.completed is not None:
        todo.completed = data.completed

    todo.updated_at = datetime.now(timezone.utc)
    session.add(todo)
    session.commit()
    session.refresh(todo)
    return todo

@router.delete("/{todo_id}", status_code=204)
def delete_todo(todo_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    todo = session.get(Todo, todo_id)
    if not todo or todo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Todo not found")
    session.delete(todo)
    session.commit()
    return None
