"""Local, immutable-per-run corpus and Chinese BM25 retrieval.

Only document files are loaded here. Evaluation labels are never read. Scores
indicate lexical relevance, not authority or factual confidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import jieba
from rank_bm25 import BM25Okapi


jieba.setLogLevel(logging.ERROR)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_WORD = re.compile(r"[\w\u3400-\u9fff]", re.UNICODE)
# Query/document preprocessing is identical. Negation, numbers and product
# editions deliberately remain in the index.
_STOP_WORDS = frozenset({
    "的", "了", "吗", "呢", "啊", "呀", "吧", "我", "我们", "你", "您",
    "请", "问", "一下", "什么", "怎么", "如何", "是否", "能", "可以", "多久",
    "多少", "几", "在", "是", "和", "及", "与", "后", "应", "须", "时",
    "有", "其", "该", "它", "这个", "那个", "最", "得", "要", "一个", "哪些",
    "什么时候",
})


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def tokenize(text: str) -> list[str]:
    """Normalize index text only; stored source text is never modified."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return [
        token for token in jieba.lcut(normalized, cut_all=False)
        if token not in _STOP_WORDS and _WORD.search(token)
    ]


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_search(queries: Any, top_k: Any) -> None:
    if not isinstance(queries, list) or not 1 <= len(queries) <= 2:
        raise ValueError("queries 必须是含 1—2 个非空字符串的数组")
    if not all(_nonempty_string(q) for q in queries):
        raise ValueError("queries 必须是含 1—2 个非空字符串的数组")
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("top_k 必须为 1—5 的整数")


def validate_read(doc_id: Any, chunk_ids: Any) -> None:
    if not valid_id(doc_id):
        raise ValueError("doc_id 必须为文档 ID，不能是文件路径")
    if not isinstance(chunk_ids, list) or not 1 <= len(chunk_ids) <= 3:
        raise ValueError("chunk_ids 必须包含 1—3 个片段 ID")
    if not all(valid_id(cid) for cid in chunk_ids):
        raise ValueError("chunk_ids 含无效片段 ID")
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("chunk_ids 不能包含重复 ID")


class Corpus:
    """Read one explicit corpus snapshot and build a fresh index.

    A run holds its initial snapshot, even if the file changes underneath it.
    Instantiate a new Corpus for the next run to see updated content. The hash
    is stable across document ordering, and changes with source/metadata edits.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._validate_documents(raw)
        self.documents = copy.deepcopy(raw)
        self._docs = {d["doc_id"]: copy.deepcopy(d) for d in raw}
        canonical = sorted(copy.deepcopy(raw), key=lambda d: d["doc_id"])
        for doc in canonical:
            doc["chunks"] = sorted(doc["chunks"], key=lambda c: c["chunk_id"])
        self.corpus_hash = text_hash(json.dumps(
            canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        self._rows: list[dict[str, Any]] = []
        self._tokens: list[list[str]] = []
        for doc in canonical:
            for chunk in doc["chunks"]:
                self._rows.append({
                    "doc_id": doc["doc_id"], "title": doc["title"],
                    "version_date": doc["version_date"], "scope": doc["scope"],
                    "chunk_id": chunk["chunk_id"], "text": chunk["text"],
                    "chunk_hash": text_hash(chunk["text"]),
                })
                searchable = " ".join([
                    doc["title"], chunk["text"], doc["scope"] or "",
                    doc["version_date"], doc["priority"] or "",
                ])
                self._tokens.append(tokenize(searchable))
        self._token_sets = [set(tokens) for tokens in self._tokens]
        self._index = BM25Okapi(self._tokens) if self._tokens else None

    @staticmethod
    def _validate_documents(documents: Any) -> None:
        if not isinstance(documents, list):
            raise ValueError("知识资料必须是文档数组")
        doc_ids: set[str] = set()
        chunk_ids: set[str] = set()
        for doc in documents:
            if not isinstance(doc, dict):
                raise ValueError("每份文档必须为对象")
            required = {"doc_id", "title", "version_date", "scope", "priority", "synthetic", "chunks"}
            if not required.issubset(doc):
                raise ValueError("文档缺少必要元数据")
            if not valid_id(doc["doc_id"]) or doc["doc_id"] in doc_ids:
                raise ValueError("文档 ID 无效或重复")
            doc_ids.add(doc["doc_id"])
            if not _nonempty_string(doc["title"]) or doc["synthetic"] is not True:
                raise ValueError("文档标题须非空，且 synthetic 必须为 true")
            if not isinstance(doc["version_date"], str):
                raise ValueError("version_date 必须是 ISO 日期字符串")
            try:
                parsed_date = date.fromisoformat(doc["version_date"])
            except ValueError as exc:
                raise ValueError("version_date 必须是 ISO 日期字符串") from exc
            if parsed_date.isoformat() != doc["version_date"]:
                raise ValueError("version_date 必须使用 YYYY-MM-DD 格式")
            for field in ("scope", "priority"):
                if doc[field] is not None and not _nonempty_string(doc[field]):
                    raise ValueError(f"{field} 必须为非空字符串或 null")
            if not isinstance(doc["chunks"], list) or not doc["chunks"]:
                raise ValueError("文档必须包含至少一个原文片段")
            for chunk in doc["chunks"]:
                if not isinstance(chunk, dict) or not {"chunk_id", "text"}.issubset(chunk):
                    raise ValueError("片段必须包含 chunk_id 和 text")
                if not valid_id(chunk["chunk_id"]) or chunk["chunk_id"] in chunk_ids:
                    raise ValueError("片段 ID 无效或重复")
                if not _nonempty_string(chunk["text"]):
                    raise ValueError("片段原文不能为空")
                chunk_ids.add(chunk["chunk_id"])

    def search(self, queries: list[str], top_k: int = 5, mode: str = "dual") -> list[dict[str, Any]]:
        validate_search(queries, top_k)
        if mode not in {"original", "dual"}:
            raise ValueError("retrieval mode 必须为 original 或 dual")
        if self._index is None:
            return []
        routes = queries[:1] if mode == "original" else queries
        scores: dict[int, float] = {}
        seen_queries: set[tuple[str, ...]] = set()
        all_query_tokens: set[str] = set()
        for query in routes:
            query_tokens = tokenize(query)
            key = tuple(query_tokens)
            if not query_tokens or key in seen_queries:
                continue
            seen_queries.add(key)
            terms = set(query_tokens)
            all_query_tokens.update(terms)
            bm25_scores = self._index.get_scores(query_tokens)
            # BM25 can be zero or negative in tiny corpora. Lexical overlap,
            # rather than score > 0, distinguishes candidates from no match.
            candidates = [i for i, tokens in enumerate(self._token_sets) if terms & tokens]
            candidates.sort(key=lambda i: (
                -float(bm25_scores[i]), self._rows[i]["doc_id"], self._rows[i]["chunk_id"]
            ))
            for rank, index in enumerate(candidates, start=1):
                contribution = float(bm25_scores[index]) if mode == "original" else 1.0 / (60 + rank)
                scores[index] = scores.get(index, 0.0) + contribution
        ranked = sorted(scores, key=lambda i: (
            -scores[i], self._rows[i]["doc_id"], self._rows[i]["chunk_id"]
        ))
        # One best passage per document first, then fill remaining positions.
        # This prevents one long document from hiding a contradictory source.
        primary, secondary, seen_docs = [], [], set()
        for index in ranked:
            doc_id = self._rows[index]["doc_id"]
            if doc_id in seen_docs:
                secondary.append(index)
            else:
                primary.append(index)
                seen_docs.add(doc_id)
        results = []
        for index in (primary + secondary)[:top_k]:
            row = self._rows[index]
            result = {k: row[k] for k in ("doc_id", "title", "version_date", "scope", "chunk_id")}
            result.update(snippet=self._snippet(row["text"], all_query_tokens), score=scores[index])
            results.append(result)
        return results

    @staticmethod
    def _snippet(text: str, query_tokens: set[str], width: int = 120) -> str:
        if len(text) <= width:
            return text
        positions = [text.lower().find(term) for term in query_tokens]
        positions = [position for position in positions if position >= 0]
        start = max(0, min(positions) - 25) if positions else 0
        return text[start:start + width]

    def read(self, doc_id: str, chunk_ids: list[str]) -> dict[str, Any]:
        try:
            validate_read(doc_id, chunk_ids)
        except ValueError as exc:
            return self._read_error("INVALID_ARGUMENTS", str(exc))
        doc = self._docs.get(doc_id)
        if doc is None:
            return self._read_error("DOCUMENT_NOT_FOUND", "指定文档 ID 不存在", doc_id)
        by_id = {chunk["chunk_id"]: chunk for chunk in doc["chunks"]}
        if any(cid not in by_id for cid in chunk_ids):
            return self._read_error("CHUNK_NOT_FOUND", "指定片段不属于该文档或不存在", doc_id)
        chunks = [dict(copy.deepcopy(by_id[cid]), chunk_hash=text_hash(by_id[cid]["text"])) for cid in chunk_ids]
        return {
            "ok": True, "doc_id": doc_id, "title": doc["title"],
            "version_date": doc["version_date"], "scope": doc["scope"],
            "priority": doc["priority"], "chunks": chunks, "error": None,
            "corpus_hash": self.corpus_hash,
        }

    def _read_error(self, code: str, message: str, doc_id: str | None = None) -> dict[str, Any]:
        return {
            "ok": False, "doc_id": doc_id, "version_date": None,
            "scope": None, "priority": None, "chunks": [],
            "error": {"code": code, "message": message, "retryable": False},
            "corpus_hash": self.corpus_hash,
        }
