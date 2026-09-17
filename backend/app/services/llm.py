"""大模型封装：extractive（离线兜底）/ OpenAI / 通义千问（OpenAI 兼容协议）。"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from ..config import settings
from ..schemas import MaterialList
from .material import body_of, extract_material
from .prompts import (
    NO_HIT_ANSWER,
    QA_TEMPLATE,
    SYSTEM_PROMPT,
    build_context,
    build_history,
)
from .vectorstore import Hit

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
# 兜底：JSON 被截断 / 含未转义换行时，直接把 answer 字段抠出来
_ANSWER_FIELD = re.compile(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)
_ANSWER_START = re.compile(r'"answer"\s*:\s*"')
# answer 真正的结束引号：后面紧跟「, 换行 下一个键」或「换行 } / ]」。
# 大模型常在答案正文里写英文双引号（如：进入"社会保障卡申领"栏目），
# 这些引号后面跟的是中文而不是结构符，不会被误判成结尾。
_ANSWER_END = re.compile(r'(?<!\\)"(?=\s*(?:,\s*\n\s*"|\s*\n\s*[}\]]))')


def _rescue_answer(text: str) -> str:
    """从（可能被截断 / 含非法裸引号的）JSON 文本中抢救出 answer 字段。

    实测 qwen3.8 会在 answer 正文里写未转义的英文双引号，导致 json.loads 失败；
    旧实现的正则遇到第一个裸引号就收尾，答案被砍掉一半（146/1199 字符）。
    这里改为按**结构边界**定位结尾，正文里的裸引号不影响。
    """
    m = _ANSWER_START.search(text)
    if not m:
        return ""
    rest = text[m.end() :]
    # 取**第一个**结构边界：answer 结束引号后面就是下一个顶层键。
    # 取最后一个会把 material_list 内部的字符串结尾也算进来（实测血案）。
    end = _ANSWER_END.search(rest)
    if end:
        raw = rest[: end.start()]
    else:
        m2 = _ANSWER_FIELD.search(text)
        raw = m2.group(1) if m2 else ""
    if not raw:
        return ""
    try:
        return json.loads('"' + raw + '"')
    except Exception:  # noqa: BLE001
        return raw.replace("\\n", "\n").replace('\\"', '"')


def _is_thinking_param_error(e: Exception) -> bool:
    """判断是否为「enable_thinking 参数不被接受」的服务端报错。

    实测 DashScope qwen3.8-2.4t-a95b 返回：
    400 InternalError.Algo.InvalidParameter:
    The value of the enable_thinking parameter is restricted to True.
    """
    return "enable_thinking" in str(e).lower()


class BaseLLM(ABC):
    """统一的大模型接口：输入问题与检索结果，输出结构化结果。"""

    name = "base"

    def build_prompt(self, question: str, history, hits: list[Hit]) -> str:
        return QA_TEMPLATE.format(
            context=build_context(hits),
            history=build_history(history),
            question=question,
            no_hit=NO_HIT_ANSWER.replace("\n", "\\n"),
        )

    def answer(self, question: str, history, hits: list[Hit]) -> dict:
        """默认实现：调用 generate 得到文本，再解析 JSON。"""
        raw = self.generate(self.build_prompt(question, history, hits))
        return self.parse(raw, hits)

    @abstractmethod
    def generate(self, prompt: str) -> str: ...

    @staticmethod
    def parse(raw: str, hits: list[Hit]) -> dict:
        """解析大模型输出，容错处理代码块、前后缀文本。"""
        text = (raw or "").strip()
        m = _JSON_BLOCK.search(text)
        if m:
            text = m.group(1).strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            # 未按要求返回 JSON：直接作为自然语言回答
            return {"answer": text or NO_HIT_ANSWER, "material_list": None}

        try:
            data = json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            # JSON 被截断 / 含非法换行：抢救 answer，避免把原始 JSON 直接甩给前端
            rescued = _rescue_answer(text)
            if rescued:
                return {"answer": rescued, "material_list": extract_material(hits)}
            return {"answer": text, "material_list": None}

        answer = str(data.get("answer") or "").strip()
        material = data.get("material_list")
        if material is not None and not isinstance(material, dict):
            material = None
        if material is not None:
            try:
                MaterialList(**material)  # 结构校验
            except Exception:  # noqa: BLE001
                material = extract_material(hits)  # 结构不合规则用规则兜底
        return {"answer": answer or NO_HIT_ANSWER, "material_list": material}


class ExtractiveLLM(BaseLLM):
    """离线抽取式：不调用 API，直接依据检索片段组织答案（零成本、零幻觉风险）。"""

    name = "extractive"

    # 优先纳入答案的章节
    _PRIORITY = ("适用", "条件", "渠道", "时限", "收费", "流程", "标准", "对象", "依据")

    def generate(self, prompt: str) -> str:
        raise NotImplementedError("抽取式模式不调用大模型")

    def answer(self, question: str, history, hits: list[Hit]) -> dict:
        if not hits:
            return {"answer": NO_HIT_ANSWER, "material_list": None}

        primary = hits[0]
        picked: list[Hit] = []
        seen_sections: set[str] = set()
        for h in hits:
            if h.doc_name != primary.doc_name:
                continue
            if h.section in seen_sections:
                continue
            seen_sections.add(h.section)
            picked.append(h)

        picked.sort(
            key=lambda h: min(
                [i for i, k in enumerate(self._PRIORITY) if k in (h.section or "")] or [len(self._PRIORITY)]
            )
        )

        lines = [f"根据《{primary.doc_name}》，为您整理如下：", ""]
        used = 0
        for h in picked:
            if not h.section:
                continue
            if any(k in h.section for k in ("材料",)):  # 材料走结构化卡片
                continue
            body = body_of(h).strip()
            if len(body) > 320:
                body = body[:320] + "…"
            lines.append(f"**{h.section}**")
            lines.append(body)
            lines.append("")
            used += 1
            if used >= 4:
                break

        if used == 0:
            lines.append(primary.text.strip()[:400])

        lines.append(f"> 本回答依据《{primary.doc_name}》生成，具体以窗口最新政策为准。")
        return {"answer": "\n".join(lines).strip(), "material_list": extract_material(hits)}


class OpenAICompatLLM(BaseLLM):
    """OpenAI / 通义千问（兼容模式）聊天接口。"""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        name: str | None = None,
    ):
        from openai import OpenAI  # 延迟导入

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=settings.LLM_TIMEOUT)
        self.model = model
        self.temperature = temperature
        # 服务端强制思考链时置 True，之后不再尝试关闭（见 generate）
        self._thinking_forced = False
        if name:
            self.name = name

    #: 服务端强制开启思考链时，自动重试所用的 max_tokens 下限
    #: （思考 token 会计入 max_tokens，沿用 4096 会把答案挤没）
    THINKING_MIN_TOKENS = 8192

    def _create(self, kwargs: dict) -> str:
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def generate(self, prompt: str) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }
        max_tokens = settings.LLM_MAX_TOKENS or 0
        # 推理类模型（qwen3.x）默认做深度思考，政务问答场景关闭可显著降低延迟
        if settings.LLM_ENABLE_THINKING or self._thinking_forced:
            # 思考 token 计入 max_tokens：沿用 4096 会把正式答案挤没（实测只剩半句）
            max_tokens = max(max_tokens, self.THINKING_MIN_TOKENS)
            kwargs["max_tokens"] = max_tokens
            kwargs["extra_body"] = self._thinking_body()
            return self._create(kwargs)
        if max_tokens:
            # 显式放开输出长度，避免材料清单较长时被截断（截断会导致 JSON 不完整）
            kwargs["max_tokens"] = max_tokens
        kwargs["extra_body"] = {"enable_thinking": False}
        try:
            return self._create(kwargs)
        except Exception as e:  # noqa: BLE001
            # 部分模型（实测 qwen3.8-2.4t-a95b）服务端把 enable_thinking 锁死为 True，
            # 传 False 直接 400 InvalidParameter。这里翻转重试，并记住结果，
            # 避免后续每次请求都先白吃一次 400。
            if not _is_thinking_param_error(e):
                raise
            print(
                f"[warn] 模型 {self.model} 要求 enable_thinking=True"
                "（服务端限制），已自动切换为思考模式重试"
            )
            self._thinking_forced = True
            kwargs["extra_body"] = self._thinking_body()
            kwargs["max_tokens"] = max(
                settings.LLM_MAX_TOKENS or 0, self.THINKING_MIN_TOKENS
            )
            return self._create(kwargs)

    def _thinking_body(self) -> dict:
        """开启思考模式的 extra_body；同时限制思考预算，避免单轮跑满 100s+。

        注：`thinking_budget` 是 qwen3 专有参数。deepseek-v4.1-flash 服务端会忽略它
        （实测传了仍返回 200），且该模型恒思考、enable_thinking=false 也关不掉，
        所以只对 qwen 系模型下发预算，避免对 deepseek 产生"限流生效"的错觉。
        """
        body: dict = {"enable_thinking": True}
        if settings.LLM_THINKING_BUDGET > 0 and self.model.lower().startswith("qwen"):
            body["thinking_budget"] = settings.LLM_THINKING_BUDGET
        return body


def build_llm() -> BaseLLM:
    """按配置创建大模型实例，缺失密钥时自动降级为抽取式模式。"""
    provider = (settings.LLM_PROVIDER or "extractive").lower()
    try:
        if provider == "openai" and settings.OPENAI_API_KEY:
            return OpenAICompatLLM(
                settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL,
                settings.OPENAI_MODEL, settings.TEMPERATURE,
            )
        if provider == "dashscope" and settings.DASHSCOPE_API_KEY:
            return OpenAICompatLLM(
                settings.DASHSCOPE_API_KEY, settings.DASHSCOPE_BASE_URL,
                settings.DASHSCOPE_MODEL, settings.TEMPERATURE,
                name=f"dashscope:{settings.DASHSCOPE_MODEL}",
            )
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 大模型初始化失败，降级为抽取式模式：{e}")

    if provider != "extractive":
        print(f"[warn] LLM_PROVIDER={provider} 未配置密钥，使用抽取式模式")
    return ExtractiveLLM()
