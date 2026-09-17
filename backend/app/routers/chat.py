"""智能问答接口（核心）。"""
from datetime import datetime


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import ChatHistory
from ..models import Session as SessionModel
from ..schemas import ChatRequest, ChatResponse, SourceItem
from ..services.context import get_recent_history
from ..services.pipeline import get_rag_service
from ..utils.text import sanitize_question

router = APIRouter(prefix="/api", tags=["智能问答"])


def _ensure_session(db: Session, session_id: str) -> None:
    """会话不存在时自动补建，避免前端历史会话失效导致 500。"""
    if not db.get(SessionModel, session_id):
        db.add(SessionModel(session_id=session_id, create_time=datetime.now()))
        db.commit()


@router.post("/chat", response_model=ChatResponse, summary="政务问答（RAG）")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """接收问题 -> 检索知识库 -> 调用大模型 -> 持久化本轮问答。"""
    question = sanitize_question(req.question, settings.MAX_QUESTION_LEN)
    if not question:
        raise HTTPException(status_code=400, detail="问题内容不能为空")

    _ensure_session(db, req.session_id)

    # 1. 读取并裁剪历史对话（多轮上下文）
    history = get_recent_history(db, req.session_id)

    # 2. RAG 检索 + 生成
    try:
        result = get_rag_service().answer(question, history)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail="大模型响应超时，请稍后重试") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"问答服务异常：{e}") from e

    answer = result["answer"]

    # 3. 本轮问答持久化
    try:
        db.add(
            ChatHistory(
                session_id=req.session_id,
                question=question,
                answer=answer,
                create_time=datetime.now(),
            )
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"对话记录保存失败：{e}") from e

    return ChatResponse(
        answer=answer,
        material_list=result.get("material_list"),
        sources=[SourceItem(**s) for s in result.get("sources", [])],
    )
