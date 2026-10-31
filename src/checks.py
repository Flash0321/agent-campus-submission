"""Offline acceptance checks. Gold data is never an input to the online Agent.

Deterministic checks are a screening layer, not a claim of semantic correctness.
Human citation/claim review remains pending unless a reviewer supplies it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _key(item: dict[str, Any]) -> tuple[str, str]:
    return (item.get("doc_id", ""), item.get("chunk_id", ""))


def _search_queries(event: dict[str, Any]) -> list[str]:
    """Prefer the tool's actual retrieval input over the model's proposal."""
    observation = event.get("observation", {})
    if "effective_queries" in observation:
        queries = observation["effective_queries"]
    else:
        arguments = event.get("arguments", {})
        queries = arguments.get("queries", []) if isinstance(arguments, dict) else []
    return queries if isinstance(queries, list) and all(isinstance(q, str) for q in queries) else []


def _conflict_inquiry(queries: list[str], required: set[tuple[str, str]]) -> bool:
    """Recognize bounded adjudication paraphrases, not any search after reading.

    This lexical screening still needs semantic review. Relevance and inquiry
    intent must occur in the same query so unrelated searches cannot be joined.
    """
    doc_ids = {doc_id for doc_id, _ in required}
    for query in queries:
        relevant = bool(re.search(r"报销|费用|制度|规定|政策|条款|文档|FAQ", query, re.I)) or any(
            re.search(rf"(?<![A-Za-z0-9]){re.escape(doc_id)}(?![A-Za-z0-9])", query, re.I)
            for doc_id in doc_ids)
        intent = re.search(
            r"范围|适用|优先|替代|废止|裁决|公告|"
            r"冲突.{0,8}(?:解决|处理|依据)|(?:以|按).{0,12}为准|哪个.{0,6}为准", query)
        if relevant and intent:
            return True
    return False


def successful_reads(trace: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    evidence = {}
    for event in trace:
        obs = event.get("observation", {})
        if event.get("event") == "tool_result" and event.get("tool") == "read_document" and obs.get("ok"):
            for chunk in obs.get("chunks", []):
                item = {**obs, **chunk}
                evidence[(obs.get("doc_id", ""), chunk.get("chunk_id", ""))] = item
    return evidence


def observation_links(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prove that actual tool observations occurred in subsequent P4 requests."""
    links = []
    for index, event in enumerate(trace):
        if event.get("event") != "tool_result":
            continue
        observation = event.get("observation")
        next_request = next((e for e in trace[index + 1:]
                             if e.get("event") == "model_request" and e.get("stage") == "P4"), None)
        forwarded = False
        if next_request:
            messages = next_request.get("messages", next_request.get("payload", {}).get("messages", []))
            for message in messages:
                if message.get("role") != "tool":
                    continue
                try:
                    value = json.loads(message.get("content", ""))
                except (TypeError, json.JSONDecodeError):
                    continue
                if value == observation:
                    forwarded = True
                    break
        links.append({"trace_index": index, "tool": event.get("tool"),
                      "has_later_model_request": next_request is not None,
                      "observation_forwarded": forwarded})
    return links


def evaluate_case(case: dict[str, Any], output: dict[str, Any], trace: list[dict[str, Any]],
                  documents: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    checks = []

    def check(item: str, passed: bool, detail: Any = None, critical: bool = False) -> None:
        checks.append({"item": item, "pass": bool(passed), "detail": detail,
                       "critical_failure": bool(critical and not passed)})

    expected_status = case.get("expected_status")
    statuses = expected_status if isinstance(expected_status, list) else [expected_status]
    check("expected_status", output.get("status") in statuses,
          {"expected": statuses, "actual": output.get("status")})
    check("nonempty_answer", isinstance(output.get("answer"), str) and bool(output["answer"].strip()))
    check("trace_present", bool(trace))
    if metadata.get("normalization"):
        check("normalization_preserves_original_question",
              metadata["normalization"].get("original_question") == case.get("input", {}).get("question"))
    reads = successful_reads(trace)
    source = {(doc["doc_id"], chunk["chunk_id"]): {**doc, **chunk}
              for doc in documents for chunk in doc["chunks"]}
    citations = output.get("citations", [])
    citation_errors = []
    for cite in citations:
        if not isinstance(cite, dict):
            citation_errors.append("citation is not an object")
            continue
        key = _key(cite)
        doc = source.get(key)
        read = reads.get(key)
        quote = cite.get("quote")
        if not doc or not read:
            citation_errors.append({"key": key, "reason": "unknown or not read in this run"})
        elif (not isinstance(quote, str) or not quote.strip() or quote not in doc["text"]
              or quote not in read["text"] or cite.get("version_date") != doc["version_date"]
              or cite.get("version_date") != read.get("version_date")
              or read.get("corpus_hash") != metadata.get("corpus_hash")):
            citation_errors.append({"key": key, "reason": "quote, version or corpus mismatch"})
    check("citation_existence_and_read_provenance", not citation_errors, citation_errors, critical=True)
    required = {_key(item) for item in case.get("required_evidence", [])}
    cited = {_key(item) for item in citations if isinstance(item, dict)}
    # Required evidence remains the coverage denominator. Equivalent supporting
    # sources may instead declare complete acceptable groups for the pass gate.
    raw_groups = case.get("acceptable_evidence_sets")
    if raw_groups is None:
        groups = [required]
        group_schema_valid = True
    else:
        group_schema_valid = isinstance(raw_groups, list) and bool(raw_groups)
        groups = []
        if group_schema_valid:
            for group in raw_groups:
                if (not isinstance(group, list) or not group
                    or any(not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k]
                           for k in ("doc_id", "chunk_id")) for item in group)):
                    group_schema_valid = False
                    break
                keys = {_key(item) for item in group}
                if not keys <= required:
                    group_schema_valid = False
                    break
                groups.append(keys)
        check("acceptable_evidence_sets_valid", group_schema_valid,
              "每个可接受组必须非空，且所有片段均来自已标注证据集合")
    check("required_evidence_read", group_schema_valid and any(group <= set(reads) for group in groups),
          {"rule": "any_complete_group" if raw_groups is not None else "all_required",
           "missing_by_group": [sorted(group - set(reads)) for group in groups]})
    check("required_evidence_cited", group_schema_valid and any(group <= cited for group in groups),
          {"rule": "any_complete_group" if raw_groups is not None else "all_required",
           "missing_by_group": [sorted(group - cited) for group in groups]})
    if output.get("status") == "answered":
        check("answered_has_evidence", bool(citations), critical=True)
    if output.get("status") != "answered":
        check("incomplete_or_uncertain_has_gaps", bool(output.get("gaps")))
    if output.get("status") == "needs_clarification":
        check("clarification_question_present", bool(output.get("follow_up_question", "").strip()))

    links = observation_links(trace)
    # step_limit may legitimately prevent any further model call after the last tool.
    applicable = [link for link in links if link["has_later_model_request"]]
    check("observations_forwarded_to_next_model", all(link["observation_forwarded"] for link in applicable), links)
    if output.get("status") != "step_limit":
        check("model_observed_tool_result", any(link["observation_forwarded"] for link in links))

    cid = case.get("case_id", "")
    answer = output.get("answer", "")
    if cid in {"C01", "C04", "C06", "C08", "C09"}:
        # Narrow numeric/condition assertions complement, but do not replace, human review.
        expected_text = " ".join(item.get("quote", "") for item in case.get("required_evidence", []))
        days = set(re.findall(r"(\d+)\s*天", expected_text))
        check("deadline_value_present", bool(days) and all(re.search(rf"{re.escape(day)}\s*天", answer) for day in days),
              {"expected_days": sorted(days)})
        check("deadline_start_and_submission_present", "费用发生" in answer and "提交" in answer)
    if cid == "C02":
        check("both_conflicting_values_disclosed", bool(re.search(r"30\s*天", answer)) and bool(re.search(r"15\s*天", answer)))
        check("conflict_disclosed", "冲突" in answer or "不一致" in answer or "矛盾" in answer)
        read_keys: set[tuple[str, str]] = set()
        inquiry = False
        for event in trace:
            if event.get("event") != "tool_result":
                continue
            obs = event.get("observation", {})
            if event.get("tool") == "read_document" and obs.get("ok"):
                read_keys.update((obs.get("doc_id", ""), c.get("chunk_id", "")) for c in obs.get("chunks", []))
            if event.get("tool") == "search_documents" and obs.get("ok") is True and required <= read_keys:
                if _conflict_inquiry(_search_queries(event), required):
                    inquiry = True
        check("conflict_followup_search_after_reading_sides", inquiry)
        check("unresolved_conflict_not_marked_answered", output.get("status") != "answered", critical=True)
    if cid in {"C06", "C07"}:
        errors = [i for i, event in enumerate(trace) if event.get("event") == "tool_result"
                  and not event.get("observation", {}).get("ok", True)]
        check("tool_failure_actually_observed", bool(errors))
        check("tool_failure_returned_to_model", any(link["trace_index"] in errors and link["observation_forwarded"] for link in links))
        if cid == "C06":
            recovered = any(event.get("event") == "tool_result" and event.get("tool") == "read_document"
                            and event.get("observation", {}).get("ok")
                            for event in trace[(errors[0] + 1 if errors else len(trace)):])
            check("successful_read_after_failure", recovered)
    if cid == "C05":
        check("standard_edition_and_pdf_present", "标准版" in answer and "PDF" in answer.upper())
        check("standard_pdf_negation_present", bool(re.search(r"(?:不支持|不能|无法|不可以).{0,12}PDF", answer, re.I)))
    if cid == "C05-follow-up":
        check("professional_edition_and_pdf_present", "专业版" in answer and "PDF" in answer.upper())
        check("professional_pdf_not_negated", not re.search(r"专业版.{0,12}(?:不支持|不能|无法).{0,12}PDF", answer, re.I))
    model_calls = metadata.get("model_calls", sum(e.get("event") == "model_request" for e in trace))
    tool_calls = metadata.get("tool_calls", sum(e.get("event") == "tool_result" for e in trace))
    budget = case.get("budget", {})
    limits = metadata.get("config", metadata.get("limits", {}))
    check("model_budget_respected", model_calls <= budget.get("max_model_calls", limits.get("max_model_calls", 8)), model_calls)
    check("tool_budget_respected", tool_calls <= budget.get("max_tool_calls", limits.get("max_tool_calls", 6)), tool_calls)
    model_mode = metadata.get("model_mode", "unknown")
    first_search = next((e for e in trace if e.get("event") == "tool_result"
                         and e.get("tool") == "search_documents" and e.get("observation", {}).get("ok") is True), None)
    effective_queries = _search_queries(first_search) if first_search else []
    first_preserved = (bool(effective_queries) and effective_queries[0] == case.get("input", {}).get("question")) if first_search else None
    return {
        "case_id": cid, "model_mode": model_mode, "tool_mode": metadata.get("tool_mode", "unknown"),
        "automated_passed": all(c["pass"] for c in checks),
        "detected_critical_failure": any(c["critical_failure"] for c in checks),
        "acceptance_status": "pending_human_review" if all(c["pass"] for c in checks) else "failed_automated_checks",
        "human_review": {"status": "pending", "required": ["答案与引用的语义支持性", "预期事实与禁止断言", "动作是否合理"]},
        "checks": checks,
        "expectations_for_review": {key: case.get(key) for key in ("expected_claims", "forbidden_claims", "behavior_checks", "acceptable_evidence_sets")},
        "real_dynamic_path_candidate": model_mode == "real" and any(link["observation_forwarded"] for link in links),
        "evidence_coverage": {"read": len(required & set(reads)), "cited": len(required & cited), "required": len(required)},
        "diagnostics": {"first_search_preserved_original": first_preserved,
                        "first_successful_search_queries": effective_queries,
                        "query_source": ("observation.effective_queries" if "effective_queries" in first_search.get("observation", {})
                                         else "arguments.queries") if first_search else None,
                        "note": "仅诊断首次成功检索的queries[0]是否逐字保留原问题，不计入自动通过门槛。无成功检索记null。"},
        "limitation": "自动检查只是初筛；Mock 不证明模型决策效果。最终业务与引用支持性仍需人工对照原文。",
    }
