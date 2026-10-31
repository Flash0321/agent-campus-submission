"""Conservative consistency checks against actual tool observations.

This module neither detects semantic conflicts nor reads evaluation labels.
It checks whether a model's declared terminal state has the minimum supporting
execution history. Structure and quotation validation remain separate concerns.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


# Only runtime failures that the current business-tool contract identifies as
# an actually dispatched query are allowed here. Unknown errors fail closed;
# parameter, whitelist, one-action and retry-budget rejections are not queries.
_DISPATCHED_SEARCH_ERRORS = frozenset({"TOOL_TIMEOUT"})


def _search_was_dispatched(event: Mapping[str, Any]) -> bool:
    if event.get("tool") != "search_documents":
        return False
    observation = event["observation"]
    if observation.get("ok") is True:
        return True
    error = observation.get("error")
    if observation.get("ok") is not False or not isinstance(error, Mapping):
        return False
    code = error.get("code")
    return isinstance(code, str) and code in _DISPATCHED_SEARCH_ERRORS


def validate_trajectory(output: Mapping[str, Any], events: list[dict[str, Any]]) -> list[str]:
    """Return inconsistencies between the declared result and its trajectory.

    ``events`` must contain this request's observed events in execution order.
    Planned calls and model-written decision summaries never establish that a
    tool ran. Only ``tool_result`` observations are considered.

    Deliberate limits:
    - A missing or differently named conflict reason is not inferred here.
    - A dispatched but timed-out follow-up proves an attempt, not sufficient
      verification. Pre-execution rejections do not establish a search attempt.
    - Any failed read with no successful read is conservatively treated as an
      unresolved verification failure for ``insufficient_evidence`` outputs.
    - A context-only clarification can legitimately finish without a search.
    """
    if not isinstance(output, Mapping):
        # The output-schema validator owns structural errors.
        return []
    observations = [
        event for event in events
        if isinstance(event, Mapping)
        and event.get("event") == "tool_result"
        and isinstance(event.get("observation"), Mapping)
    ]
    searches = [event for event in observations if event.get("tool") == "search_documents"]
    reads = [event for event in observations if event.get("tool") == "read_document"]
    successful_reads = [event for event in reads if event["observation"].get("ok") is True]
    errors: list[str] = []

    if output.get("status") == "insufficient_evidence":
        if not any(event["observation"].get("ok") is True for event in searches):
            errors.append("未成功检索，不能断言知识库没有资料。")
        if any(event["observation"].get("ok") is False for event in reads) and not successful_reads:
            errors.append("原文读取失败、未核实，应该返回 tool_error，而非把故障解释为无资料。")

    if output.get("status") == "needs_clarification" and output.get("reason_code") == "document_conflict":
        read_doc_ids: set[str] = set()
        acquired_two_at: int | None = None
        for index, event in enumerate(observations):
            observation = event["observation"]
            if event.get("tool") != "read_document" or observation.get("ok") is not True:
                continue
            doc_id = observation.get("doc_id")
            if isinstance(doc_id, str) and doc_id.strip():
                read_doc_ids.add(doc_id)
            if len(read_doc_ids) >= 2:
                acquired_two_at = index
                break
        if acquired_two_at is None:
            errors.append("已声明文档冲突，但本轮尚未成功读取至少两份不同文档。")
        elif not any(
            _search_was_dispatched(event)
            for event in observations[acquired_two_at + 1:]
        ):
            errors.append("已声明文档冲突，但读取双方后尚无实际执行的补充检索记录；参数或执行前校验拒绝不算查证，应修正后检索适用范围、替代关系或裁决依据。")

    return errors
