"""ORM 模型：与《系统设计》第四章表结构严格一致。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def _now() -> datetime:
    return datetime.now()


class Session(Base):
    """会话表 session"""

    __tablename__ = "session"

    session_id = Column(String(64), primary_key=True, comment="会话唯一标识")
    create_time = Column(DateTime, nullable=False, default=_now, comment="会话创建时间")

    histories = relationship(
        "ChatHistory", back_populates="session", cascade="all, delete-orphan"
    )


class ChatHistory(Base):
    """对话历史表 chat_history"""

    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    session_id = Column(
        String(64),
        ForeignKey("session.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联 session 会话",
    )
    question = Column(Text, nullable=False, comment="用户提问内容")
    answer = Column(Text, nullable=False, comment="AI 返回回答内容")
    create_time = Column(DateTime, nullable=False, default=_now, comment="消息记录时间")

    session = relationship("Session", back_populates="histories")


class DocMeta(Base):
    """文档元数据表 doc_meta"""

    __tablename__ = "doc_meta"

    doc_id = Column(String(64), primary_key=True, comment="文档唯一编号")
    doc_name = Column(String(255), nullable=False, comment="文档名称")
    source = Column(String(255), nullable=False, default="", comment="文档来源")
    upload_time = Column(DateTime, nullable=False, default=_now, comment="文档入库时间")


__all__ = ["Session", "ChatHistory", "DocMeta"]
