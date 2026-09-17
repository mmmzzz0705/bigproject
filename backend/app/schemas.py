"""请求 / 响应模型（Pydantic）：负责参数校验与序列化。"""
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SessionCreateResponse(BaseModel):
    """创建会话响应"""

    session_id: str = Field(..., description="会话唯一标识")


class ChatRequest(BaseModel):
    """问答请求"""

    session_id: str = Field(..., min_length=1, max_length=64, description="会话 ID")
    question: str = Field(..., min_length=1, max_length=1000, description="用户问题")

    @field_validator("question")
    @classmethod
    def strip_and_check(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("问题内容不能为空")
        return v


class SourceItem(BaseModel):
    """检索命中的文档片段（用于答案溯源）"""

    doc_name: str = ""
    section: str = ""
    snippet: str = ""
    score: float = 0.0


class MaterialItem(BaseModel):
    """单条材料"""

    name: str
    desc: str = ""
    count: str = ""


class MaterialList(BaseModel):
    """结构化办事材料清单"""

    title: str = ""
    department: str = ""
    legal_time: str = ""
    fee: str = ""
    channel: str = ""
    required: list[MaterialItem] = Field(default_factory=list)
    optional: list[MaterialItem] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """问答响应"""

    answer: str = Field(..., description="回答内容")
    material_list: MaterialList | None = Field(default=None, description="材料清单（可选）")
    sources: list[SourceItem] = Field(default_factory=list, description="参考依据")


class HistoryItem(BaseModel):
    """历史问答记录"""

    id: int = 0
    question: str
    answer: str
    create_time: str = ""


class HistoryResponse(BaseModel):
    """历史对话响应"""

    session_id: str
    total: int = 0
    records: list[HistoryItem] = Field(default_factory=list)


# ---------------- 工作台：语料管理 ----------------
class CorpusDoc(BaseModel):
    """单篇语料"""

    doc_id: str = ""
    doc_name: str = ""
    source: str = ""
    chunks: int = 0
    upload_time: str = ""
    # uploaded（用户上传，可删文件）| builtin（内置基准语料）| missing（源文件已丢失）
    origin: str = "builtin"
    in_index: bool = True            # False = 已被移出检索库（chunks=0）
    can_reingest: bool = False


class CorpusListResponse(BaseModel):
    """语料列表"""

    total: int = 0
    total_chunks: int = 0
    vector_store: str = ""
    degraded: bool = False          # True = 向量库降级，检索结果不可信
    docs: list[CorpusDoc] = Field(default_factory=list)


class CorpusTextRequest(BaseModel):
    """粘贴文本入库"""

    title: str = Field(..., min_length=2, max_length=120, description="语料标题")
    content: str = Field(..., min_length=20, description="语料正文")

    @field_validator("title", "content")
    @classmethod
    def strip_and_check(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("内容不能为空")
        return v


class CorpusDocResponse(BaseModel):
    """单篇语料操作结果"""

    doc_id: str = ""
    doc_name: str = ""
    source: str = ""
    chunks: int = 0
    status: str = "ok"


class CorpusChunk(BaseModel):
    """单个文本片段（切分预览）"""

    index: int = 0
    section: str = ""
    chars: int = 0
    text: str = ""


class CorpusChunksResponse(BaseModel):
    """某篇语料的片段列表"""

    doc_id: str = ""
    doc_name: str = ""
    shown: int = 0
    chunks: list[CorpusChunk] = Field(default_factory=list)


class CorpusDeleteResponse(BaseModel):
    """删除结果"""

    doc_id: str = ""
    doc_name: str = ""
    removed_chunks: int = 0
    file_removed: bool = False
    meta_removed: bool = False
    recoverable: bool = False       # True = 只清了向量，源文件还在，可重新导入
    status: str = "ok"


class HealthResponse(BaseModel):
    """健康检查"""

    status: str = "ok"
    database: str = ""
    vector_store: str = ""
    doc_count: int = 0
    llm_provider: str = ""
    embedding_provider: str = ""


def ok(data: Any) -> dict:
    """统一成功响应包装（保持与前端约定一致）"""
    return data if isinstance(data, dict) else {"data": data}
