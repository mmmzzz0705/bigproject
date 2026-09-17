"""会话管理接口。"""
from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Session as SessionModel
from ..schemas import SessionCreateResponse

router = APIRouter(prefix="/api/session", tags=["会话管理"])


@router.post("/create", response_model=SessionCreateResponse, summary="创建会话")
def create_session(db: Session = Depends(get_db)):
    """生成唯一 session_id 并写入 session 表。"""
    try:
        session_id = uuid.uuid4().hex
        db.add(SessionModel(session_id=session_id, create_time=datetime.now()))
        db.commit()
        return SessionCreateResponse(session_id=session_id)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建会话失败：{e}") from e


@router.get("/list", summary="会话列表（调试用）")
def list_sessions(limit: int = 20, db: Session = Depends(get_db)):
    rows = (
        db.query(SessionModel).order_by(SessionModel.create_time.desc()).limit(min(limit, 100)).all()
    )
    return {
        "total": len(rows),
        "records": [
            {"session_id": r.session_id, "create_time": str(r.create_time)} for r in rows
        ],
    }
