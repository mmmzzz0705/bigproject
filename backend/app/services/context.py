"""多轮对话上下文管理：读取历史 + 超长裁剪 / 摘要。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ChatHistory


def get_recent_history(
    db: Session,
    session_id: str,
    turns: int | None = None,
    max_chars: int | None = None,
) -> list[tuple[str, str]]:
    """取最近 N 轮问答，并在字符超限时做截断式裁剪。

    返回按时间正序的 [(question, answer)]，可直接拼进 Prompt。
    """
    turns = turns or settings.MAX_HISTORY_TURNS
    max_chars = max_chars or settings.MAX_CONTEXT_CHARS

    rows = (
        db.execute(
            select(ChatHistory)
            .where(ChatHistory.session_id == session_id)
            .order_by(ChatHistory.id.desc())
            .limit(max(turns, 1))
        )
        .scalars()
        .all()
    )
    rows = list(reversed(rows))  # 还原为正序

    history: list[tuple[str, str]] = [(r.question or "", r.answer or "") for r in rows]

    # 上下文裁剪：从最早的一轮开始丢弃，直到满足长度限制
    total = sum(len(q) + len(a) for q, a in history)
    while history and total > max_chars:
        q, a = history.pop(0)
        total -= len(q) + len(a)
    return history
