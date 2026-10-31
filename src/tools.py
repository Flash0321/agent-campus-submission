"""Whitelisted business tools and deterministic fault injection for tests."""
from __future__ import annotations

import copy
from typing import Any

from .retrieval import Corpus, validate_read, validate_search


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "检索本地合成制度和产品 FAQ，返回候选 ID、版本、片段位置和短摘录。原问题及改写均可用于检索，也可补查适用范围或替代关系。最终引用前必须读取原文。",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "queries": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 2},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 5},
                    "reason": {"type": "string", "minLength": 1, "description": "一句简要动作依据，无需内部思维过程"},
                },
                "required": ["queries", "top_k", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "读取一个文档的完整原文片段以及版本、范围、优先级。使用已有文档和片段 ID，不接受文件路径。只有本轮成功读取的原文才可作为最终引用。",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "doc_id": {"type": "string", "minLength": 1},
                    "chunk_ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 3, "uniqueItems": True},
                    "reason": {"type": "string", "minLength": 1, "description": "一句简要动作依据，无需内部思维过程"},
                },
                "required": ["doc_id", "chunk_ids", "reason"],
            },
        },
    },
]


class Toolbox:
    """Tools contain no model policy, answer keys, or automatic retries.

    Budget enforcement and the one-retry policy belong to the Agent loop. A
    failure here is returned as an observation, never converted to an empty hit.
    """

    def __init__(self, corpus: Corpus, retrieval_mode: str = "dual", fault: dict | None = None):
        if retrieval_mode not in {"original", "dual"}:
            raise ValueError("retrieval_mode 必须为 original 或 dual")
        self.corpus = corpus
        self.retrieval_mode = retrieval_mode
        self.fault = copy.deepcopy(fault)
        self._fault_count = 0
        self.original_question: str | None = None
        self._first_search_succeeded = False
        self._validate_fault()
        self.tool_mode = "fault_injected" if self.fault is not None else "local"
        self.read_evidence: dict[tuple[str, str], dict[str, Any]] = {}

    def _validate_fault(self) -> None:
        if self.fault is None:
            return
        if not isinstance(self.fault, dict) or not {"tool", "times"}.issubset(self.fault):
            raise ValueError("fault 必须包含 tool 和 times")
        if set(self.fault) - {"tool", "times", "doc_id"}:
            raise ValueError("fault 包含未知字段")
        if self.fault["tool"] not in {"search_documents", "read_document"}:
            raise ValueError("fault.tool 必须是已知工具")
        times = self.fault["times"]
        if times != "always" and (type(times) is not int or times < 1):
            raise ValueError("fault.times 必须是正整数或 always")
        if "doc_id" in self.fault and not isinstance(self.fault["doc_id"], str):
            raise ValueError("fault.doc_id 必须是字符串")

    def execute(self, name: str, arguments: dict) -> dict[str, Any]:
        if name not in {"search_documents", "read_document"}:
            return self._error("UNKNOWN_TOOL", "工具不在允许清单中")
        try:
            self._validate_arguments(name, arguments)
        except ValueError as exc:
            return self._error("INVALID_ARGUMENTS", str(exc))
        if name == "search_documents":
            if self._should_fail(name, arguments):
                return self._error("TOOL_TIMEOUT", "工具调用超时，尚未取得本次证据", retryable=True)
            requested_queries = list(arguments["queries"])
            effective_queries = list(requested_queries)
            preserve_original = bool(self.original_question and not self._first_search_succeeded)
            if preserve_original:
                # Deterministic retrieval invariant, not an action/answer policy.
                # Keep the user's original wording alongside a model-selected query.
                alternatives = [q for q in requested_queries if q != self.original_question]
                effective_queries = [self.original_question] + alternatives[-1:]
            results = self.corpus.search(effective_queries, arguments["top_k"], mode=self.retrieval_mode)
            self._first_search_succeeded = True
            return {
                "ok": True, "results": results,
                "requested_queries": requested_queries,
                "effective_queries": effective_queries[:1] if self.retrieval_mode == "original" else effective_queries,
                "query_policy": "first_search_preserves_original" if preserve_original else "model_selected",
                "error": None, "corpus_hash": self.corpus.corpus_hash,
            }
        result = self.corpus.read(arguments["doc_id"], arguments["chunk_ids"])
        if not result["ok"]:
            return result
        if self._should_fail(name, arguments):
            return self._error("TOOL_TIMEOUT", "工具调用超时，尚未取得本次证据", retryable=True)
        if result["ok"]:
            for chunk in result["chunks"]:
                self.read_evidence[(result["doc_id"], chunk["chunk_id"])] = {
                    "doc_id": result["doc_id"], "version_date": result["version_date"],
                    "chunk_id": chunk["chunk_id"], "text": chunk["text"],
                    "chunk_hash": chunk["chunk_hash"], "corpus_hash": result["corpus_hash"],
                }
        return result

    @staticmethod
    def _validate_arguments(name: str, arguments: Any) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须是 JSON 对象")
        expected = {"queries", "top_k", "reason"} if name == "search_documents" else {"doc_id", "chunk_ids", "reason"}
        if set(arguments) != expected:
            raise ValueError("工具参数缺少必填字段或包含未知字段")
        if not isinstance(arguments["reason"], str) or not arguments["reason"].strip():
            raise ValueError("reason 必须为非空字符串")
        if name == "search_documents":
            validate_search(arguments["queries"], arguments["top_k"])
        else:
            validate_read(arguments["doc_id"], arguments["chunk_ids"])

    def _should_fail(self, name: str, arguments: dict) -> bool:
        if not self.fault or self.fault["tool"] != name:
            return False
        if self.fault.get("doc_id") and self.fault["doc_id"] != arguments.get("doc_id"):
            return False
        times = self.fault["times"]
        if times == "always" or self._fault_count < times:
            self._fault_count += 1
            return True
        return False

    def _error(self, code: str, message: str, retryable: bool = False) -> dict[str, Any]:
        return {
            "ok": False, "results": [], "chunks": [],
            "error": {"code": code, "message": message, "retryable": retryable},
            "corpus_hash": self.corpus.corpus_hash,
        }
