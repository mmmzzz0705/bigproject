"""历史对话查询接口。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChatHistory
from ..schemas import HistoryItem

router = APIRouter(prefix="/api/chat", tags=["对话历史"])


@router.get("/history", response_model=list[HistoryItem], summary="查询会话历史")
def get_history(
    session_id: str = Query(..., min_length=1, max_length=64, description="会话 ID"),
    limit: int = Query(200, ge=1, le=1000, description="返回条数上限"),
    db: Session = Depends(get_db),
):
    """按 session_id 查询该会话全部历史问答记录。"""
    try:
        rows = (
            db.execute(
                select(ChatHistory)
                .where(ChatHistory.session_id == session_id)
                .order_by(ChatHistory.id.asc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            HistoryItem(
                id=r.id,
                question=r.question,
                answer=r.answer,
                create_time=str(r.create_time),
            )
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"查询历史失败：{e}") from e
