"""工作台：语料管理接口（上传 / 粘贴 / 列表 / 删除 / 重新导入）。

只做三件事：参数校验、调用 ``services.corpus``、把业务异常映射成 HTTP 状态码。
所有入库/删除逻辑都在 service 层，便于脱离 FastAPI 直接单测。
"""
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile

from ..config import settings
from ..schemas import (
    CorpusChunksResponse,
    CorpusDeleteResponse,
    CorpusDocResponse,
    CorpusListResponse,
    CorpusTextRequest,
)
from ..services import corpus as svc


def verify_token(x_workbench_token: str | None = Header(default=None)) -> None:
    """工作台访问凭证校验（未配置 CORPUS_WRITE_TOKEN 时直接放行）。

    做成"可开关"而不是强制鉴权：内网演示/课程作业场景不该被登录流程挡住，
    但只要部署到能被外人访问的地址，配一个值就立刻生效，不用改代码。
    """
    need = (settings.CORPUS_WRITE_TOKEN or "").strip()
    if not need:
        return
    if (x_workbench_token or "").strip() != need:
        raise HTTPException(status_code=403, detail="工作台访问凭证无效")


router = APIRouter(
    prefix="/api/corpus",
    tags=["语料管理"],
    dependencies=[Depends(verify_token)],
)


def _bad_request(e: Exception) -> HTTPException:
    """调用方造成的错误（文件类型不对、内容为空、语料不存在）统一 400/404。"""
    return HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=CorpusListResponse, summary="语料列表")
def list_corpus():
    """文档元数据 + 向量库实际片段数。"""
    try:
        return svc.list_documents()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"语料列表查询失败：{e}") from e


@router.post("/upload", response_model=CorpusDocResponse, summary="上传语料文件")
def upload_corpus(
    file: UploadFile = File(..., description="txt / md / pdf / docx"),
    title: str = Form("", max_length=120, description="语料名称（可选，文件名无语义时建议填写）"),
):
    # 同步路由（不用 async def）：入库要调 Embedding 接口，是阻塞调用。
    # 写成 async 又不 await 到别处，会把整段阻塞留在事件循环里，
    # 期间所有请求一起排队。同步路由由 FastAPI 丢进线程池，不会互相拖死。
    try:
        data = file.file.read()
        r = svc.add_document(file.filename or "", data, title=title or "")
    except (ValueError, TypeError) as e:
        raise _bad_request(e) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"语料入库失败：{e}") from e
    finally:
        file.file.close()
    return CorpusDocResponse(**r)


@router.post("/text", response_model=CorpusDocResponse, summary="粘贴文本入库")
def add_corpus_text(req: CorpusTextRequest):
    try:
        r = svc.add_text(req.title, req.content)
    except ValueError as e:
        raise _bad_request(e) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"语料入库失败：{e}") from e
    return CorpusDocResponse(**r)


@router.get(
    "/{doc_id}/chunks",
    response_model=CorpusChunksResponse,
    summary="查看语料被切成的片段",
)
def list_corpus_chunks(doc_id: str, limit: int = Query(50, ge=1, le=200)):
    """切分预览：看这篇语料实际被切成了哪些块、每块属于哪个章节。"""
    try:
        return svc.list_chunks(doc_id, limit=limit)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取片段失败：{e}") from e


@router.delete("/{doc_id}", response_model=CorpusDeleteResponse, summary="删除语料")
def delete_corpus(doc_id: str):
    try:
        r = svc.delete_document(doc_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        # 向量库不支持按文档删除 —— 属于部署问题，不是调用方问题
        raise HTTPException(status_code=501, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"语料删除失败：{e}") from e
    return CorpusDeleteResponse(**r)


@router.post("/{doc_id}/reingest", response_model=CorpusDocResponse, summary="重新导入内置语料")
def reingest_corpus(doc_id: str):
    """内置语料删掉向量后用它恢复（源文件仍在 DOCS_DIR）。"""
    try:
        r = svc.reingest_document(doc_id)
    except (KeyError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise _bad_request(e) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"重新导入失败：{e}") from e
    return CorpusDocResponse(**r)
