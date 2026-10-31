"""Evaluation-unit fixtures are synthetic; these are not real-model run records."""
import copy
import json
import pytest

from src.checks import evaluate_case, observation_links
from src.evaluate import follow_up_input, online_input, run_metrics, run_suite, main


def fixture():
    doc = {"doc_id": "D01", "version_date": "2026-09-01", "title": "规定", "scope": None,
           "chunks": [{"chunk_id": "D01-C01", "text": "员工报销应在费用发生后30天内提交申请。"}]}
    citation = {"doc_id": "D01", "version_date": "2026-09-01", "chunk_id": "D01-C01",
                "quote": doc["chunks"][0]["text"]}
    case = {"case_id": "C01", "input": {"question": "报销期限多久？"}, "expected_status": "answered",
            "required_evidence": [citation], "expected_claims": ["30天"], "forbidden_claims": ["15天"]}
    observation = {"ok": True, "doc_id": "D01", "version_date": "2026-09-01", "corpus_hash": "test-hash",
                   "chunks": [{"chunk_id": "D01-C01", "text": citation["quote"], "chunk_hash": "test-chunk"}]}
    trace = [{"event": "tool_result", "tool": "read_document", "observation": observation},
             {"event": "model_request", "stage": "P4", "messages": [
                 {"role": "tool", "tool_call_id": "call1", "content": json.dumps(observation)}]}]
    output = {"status": "answered", "answer": citation["quote"], "citations": [citation], "gaps": [],
              "reason_code": "evidence_found", "follow_up_question": "", "decision_summary": "依据原文回答"}
    metadata = {"model_mode": "mock", "tool_mode": "local", "corpus_hash": "test-hash", "model_calls": 3, "tool_calls": 2}
    return case, output, trace, [doc], metadata


def test_gold_allowlist_and_follow_up_uses_actual_answer():
    case = {"input": {"question": "它支持吗", "history": [{"role": "user", "content": "标准版", "expected": "secret"}],
                      "expected": "secret"}, "expected_status": "answered", "fault_injection": {"times": "always"}}
    actual = online_input(case)
    assert actual == {"question": "它支持吗", "history": [{"role": "user", "content": "标准版"}]}
    second = follow_up_input(actual, {"answer": "实际答案而非预期答案"}, {"question": "专业版呢？"})
    assert second["history"][-1] == {"role": "assistant", "content": "实际答案而非预期答案"}
    assert len(actual["history"]) == 1


def test_automatic_pass_never_claims_human_or_real_model_acceptance():
    report = evaluate_case(*fixture())
    assert report["automated_passed"]
    assert report["acceptance_status"] == "pending_human_review"
    assert report["human_review"]["status"] == "pending"
    assert not report["real_dynamic_path_candidate"]


def test_citation_that_exists_but_was_not_read_fails():
    case, output, trace, docs, metadata = fixture()
    trace[0]["tool"] = "search_documents"
    report = evaluate_case(case, output, trace, docs, metadata)
    assert not report["automated_passed"]
    assert report["detected_critical_failure"]


def test_wrong_quote_and_stale_hash_fail():
    case, output, trace, docs, metadata = fixture()
    output["citations"][0]["quote"] = "员工报销应在费用发生后15天内提交申请。"
    assert evaluate_case(case, output, trace, docs, metadata)["detected_critical_failure"]
    case, output, trace, docs, metadata = fixture()
    metadata["corpus_hash"] = "new-hash"
    assert evaluate_case(case, output, trace, docs, metadata)["detected_critical_failure"]


def test_correct_number_alone_is_not_a_passing_answer():
    case, output, trace, docs, metadata = fixture()
    output["answer"] = "30天"
    report = evaluate_case(case, output, trace, docs, metadata)
    assert not report["automated_passed"]
    assert any(c["item"] == "deadline_start_and_submission_present" and not c["pass"] for c in report["checks"])


def test_unforwarded_observation_is_not_dynamic_evidence():
    case, output, trace, docs, metadata = fixture()
    trace[-1]["messages"] = []
    metadata["model_mode"] = "real"
    assert not observation_links(trace)[0]["observation_forwarded"]
    report = evaluate_case(case, output, trace, docs, metadata)
    assert not report["automated_passed"]
    assert not report["real_dynamic_path_candidate"]


def test_budget_limit_without_a_later_model_request_is_valid():
    case, output, trace, docs, metadata = fixture()
    case.update(case_id="C10", expected_status="step_limit", required_evidence=[], budget={"max_model_calls": 3, "max_tool_calls": 1})
    output.update(status="step_limit", citations=[], answer="调用额度用完，任务未完成。", gaps=["未完成读取"])
    metadata.update(model_calls=3, tool_calls=1)
    trace.pop()
    assert evaluate_case(case, output, trace, docs, metadata)["automated_passed"]
    metadata["model_calls"] = 4
    assert not evaluate_case(case, output, trace, docs, metadata)["automated_passed"]


def test_usage_and_fallback_are_not_dropped():
    trace = [{"event": "model_request", "stage": "P3", "requested_model": "flash"},
             {"event": "model_error", "stage": "P3", "elapsed_ms": 8},
             {"event": "model_request", "stage": "P3", "requested_model": "plus", "fallback_reason": "P3_failed"},
             {"event": "model_response", "stage": "P3", "elapsed_ms": 12, "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}]
    metrics = run_metrics(trace, {"elapsed_ms": 25})
    assert metrics["p3_ms"] == 20
    assert metrics["fallback_calls"] == 1
    assert metrics["model_calls"] == 2
    assert metrics["usage"]["total_tokens"] == 25


def test_conflict_requires_both_sources_and_actual_followup_search():
    case, output, trace, docs, metadata = fixture()
    second_doc = copy.deepcopy(docs[0])
    second_doc.update(doc_id="D02", version_date="2026-10-01")
    second_doc["chunks"] = [{"chunk_id": "D02-C01", "text": "员工报销应在费用发生后15天内提交申请。"}]
    second_citation = {"doc_id": "D02", "version_date": "2026-10-01", "chunk_id": "D02-C01", "quote": second_doc["chunks"][0]["text"]}
    docs.append(second_doc)
    case.update(case_id="C02", expected_status="needs_clarification")
    case["required_evidence"].append(second_citation)
    output.update(status="needs_clarification", answer="D01规定30天，D02规定15天，存在冲突。", gaps=["缺少适用范围"], follow_up_question="请确认适用制度")
    output["citations"].append(second_citation)
    second_obs = {"ok": True, "doc_id": "D02", "version_date": "2026-10-01", "corpus_hash": "test-hash", "chunks": second_doc["chunks"]}
    trace.insert(1, {"event": "tool_result", "tool": "read_document", "observation": second_obs})
    trace[-1]["messages"].append({"role": "tool", "tool_call_id": "call2", "content": json.dumps(second_obs)})
    report = evaluate_case(case, output, trace, docs, metadata)
    assert not report["automated_passed"]
    invalid_obs = {"ok": False, "error": {"code": "INVALID_ARGUMENTS", "retryable": False}, "corpus_hash": "test-hash"}
    trace.insert(-1, {"event": "tool_result", "tool": "search_documents", "arguments": {"queries": ["报销适用范围", "制度优先级", "替代公告"]}, "observation": invalid_obs})
    trace[-1]["messages"].append({"role": "tool", "tool_call_id": "invalid-call", "content": json.dumps(invalid_obs)})
    report = evaluate_case(case, output, trace, docs, metadata)
    assert not report["automated_passed"]
    assert not next(c for c in report["checks"] if c["item"] == "conflict_followup_search_after_reading_sides")["pass"]
    # Only the subsequent corrected and successfully executed inquiry counts.
    obs = {"ok": True, "results": [], "corpus_hash": "test-hash"}
    trace.insert(-1, {"event": "tool_result", "tool": "search_documents", "arguments": {"queries": ["报销适用范围优先级"]}, "observation": obs})
    trace[-1]["messages"].append({"role": "tool", "tool_call_id": "call3", "content": json.dumps(obs)})
    assert evaluate_case(case, output, trace, docs, metadata)["automated_passed"]


@pytest.mark.parametrize("queries,ok,read_both,expected", [
    (["费用报销规定 D01 与 费用报销FAQ D02 冲突解决依据"], True, True, True),
    (["D01 和 D02 发生冲突如何处理"], True, True, True),
    (["费用报销规定与FAQ冲突时以哪个为准"], True, True, True),
    (["报销制度应按什么为准"], True, True, True),
    (["制度优先级和替代公告"], True, True, True),
    (["D01、D02的适用范围"], True, True, True),
    (["费用报销规定 D01 与费用报销FAQ D02 冲突解决依据"], False, True, False),
    (["费用报销规定 D01 与费用报销FAQ D02 冲突解决依据"], True, False, False),
    (["报销期限多久"], True, True, False),
    (["产品适用范围"], True, True, False),
    (["Git合并冲突解决依据"], True, True, False),
    (["报销期限", "Git合并冲突解决依据"], True, True, False),
])
def test_conflict_inquiry_synonyms_keep_success_and_relevance_gates(queries, ok, read_both, expected):
    case, output, trace, docs, metadata = fixture()
    case.update(case_id="C02", expected_status="needs_clarification")
    second_doc = {"doc_id": "D02", "version_date": "2026-10-01", "title": "FAQ", "scope": None,
                  "chunks": [{"chunk_id": "D02-C01", "text": "员工报销应在费用发生后15天内提交申请。"}]}
    docs.append(second_doc)
    cite = {"doc_id": "D02", "version_date": "2026-10-01", "chunk_id": "D02-C01", "quote": second_doc["chunks"][0]["text"]}
    case["required_evidence"].append(cite)
    output.update(status="needs_clarification", answer="D01规定30天，D02规定15天，存在冲突。",
                  gaps=["缺少裁决依据"], follow_up_question="请确认适用制度")
    output["citations"].append(cite)
    if read_both:
        observation = {"ok": True, "doc_id": "D02", "version_date": "2026-10-01",
                       "corpus_hash": "test-hash", "chunks": second_doc["chunks"]}
        trace.insert(-1, {"event": "tool_result", "tool": "read_document", "observation": observation})
        trace[-1]["messages"].append({"role": "tool", "content": json.dumps(observation)})
    observation = {"ok": ok, "results": [], "effective_queries": queries, "corpus_hash": "test-hash"}
    if not ok:
        observation["error"] = {"code": "INVALID_ARGUMENTS"}
    trace.insert(-1, {"event": "tool_result", "tool": "search_documents", "observation": observation})
    trace[-1]["messages"].append({"role": "tool", "content": json.dumps(observation)})
    report = evaluate_case(case, output, trace, docs, metadata)
    assert next(c for c in report["checks"] if c["item"] == "conflict_followup_search_after_reading_sides")["pass"] is expected
    assert report["automated_passed"] is expected


def test_real_suite_without_credentials_is_not_run_not_mock(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    report = run_suite("real", "single", tmp_path / "runs", ["C01"])
    assert report["counts"]["not_run"] == 1
    assert report["counts"]["mock_runs"] == 0
    assert report["counts"]["real_runs"] == 0
    assert report["cases"][0]["automated_passed"] is None
    assert not (tmp_path / "runs/C01/trace.jsonl").exists()


def test_existing_suite_evidence_is_not_overwritten(tmp_path):
    (tmp_path / "summary.json").write_text('{"preserve":true}')
    with pytest.raises(ValueError, match="preserve evidence"):
        run_suite("mock", "single", tmp_path, ["C01"])
    assert json.loads((tmp_path / "summary.json").read_text()) == {"preserve": True}


def test_profile_comparison_freezes_actual_follow_up_history(tmp_path, monkeypatch):
    # Test comparison logic without reading a developer's local credentials.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    assert main(["--mode", "mock", "--compare-models", "--case", "C05", "--output-dir", str(tmp_path)]) == 0
    a = json.loads((tmp_path / "single/C05/turn2/input.json").read_text())
    b = json.loads((tmp_path / "split/C05/turn2/input.json").read_text())
    actual = json.loads((tmp_path / "single/C05/turn1/output.json").read_text())
    assert a == b
    assert a["history"][-1]["content"] == actual["answer"]
    report = json.loads((tmp_path / "comparison.json").read_text())
    assert report["input_pairs"][0]["same_follow_up_input"]
    assert report["profiles"]["single"]["mean_elapsed_ms"] is None
    assert report["profiles"]["split"]["real_request_count"] == 0
    assert report["selected_profile"] is None


@pytest.mark.parametrize("selected_doc", ["D01", "D02"])
def test_consistent_case_accepts_either_complete_evidence_group(selected_doc):
    case, output, trace, docs, metadata = fixture()
    case.update(case_id="C09", acceptable_evidence_sets=[
        [{"doc_id": "D01", "chunk_id": "D01-C01"}],
        [{"doc_id": "D02", "chunk_id": "D02-C01"}],
    ])
    second_doc = copy.deepcopy(docs[0])
    second_doc.update(doc_id="D02", version_date="2026-10-01")
    second_doc["chunks"][0]["chunk_id"] = "D02-C01"
    docs.append(second_doc)
    second_citation = {"doc_id": "D02", "chunk_id": "D02-C01", "version_date": "2026-10-01",
                       "quote": second_doc["chunks"][0]["text"]}
    case["required_evidence"].append(second_citation)
    if selected_doc == "D02":
        output["citations"] = [second_citation]
        obs = trace[0]["observation"]
        obs.update(doc_id="D02", version_date="2026-10-01", chunks=second_doc["chunks"])
        trace[-1]["messages"][0]["content"] = json.dumps(obs)
    report = evaluate_case(case, output, trace, docs, metadata)
    assert report["automated_passed"]
    assert report["evidence_coverage"] == {"read": 1, "cited": 1, "required": 2}
    assert report["human_review"]["status"] == "pending"


def test_conflict_without_alternative_groups_still_requires_every_source():
    case, output, trace, docs, metadata = fixture()
    case.update(case_id="C02", expected_status="needs_clarification")
    second_doc = copy.deepcopy(docs[0])
    second_doc.update(doc_id="D02", version_date="2026-10-01")
    second_doc["chunks"] = [{"chunk_id": "D02-C01", "text": "员工报销应在费用发生后15天内提交申请。"}]
    docs.append(second_doc)
    case["required_evidence"].append({"doc_id": "D02", "chunk_id": "D02-C01", "quote": second_doc["chunks"][0]["text"]})
    output.update(status="needs_clarification", answer="D01规定30天，D02规定15天，存在冲突。",
                  gaps=["缺少裁决依据"], follow_up_question="请确认适用制度")
    report = evaluate_case(case, output, trace, docs, metadata)
    gates = {check["item"]: check["pass"] for check in report["checks"]}
    assert not report["automated_passed"]
    assert not gates["required_evidence_read"]
    assert not gates["required_evidence_cited"]


def test_alternative_group_must_be_complete_and_nonempty():
    case, output, trace, docs, metadata = fixture()
    # An empty alternative would otherwise vacuously pass every evidence gate.
    case["acceptable_evidence_sets"] = [[]]
    report = evaluate_case(case, output, trace, docs, metadata)
    assert not report["automated_passed"]
    assert not next(c for c in report["checks"] if c["item"] == "acceptable_evidence_sets_valid")["pass"]
    case["acceptable_evidence_sets"] = [[{"doc_id": "D01", "chunk_id": "D01-C01"},
                                        {"doc_id": "D02", "chunk_id": "D02-C01"}]]
    case["required_evidence"].append({"doc_id": "D02", "chunk_id": "D02-C01"})
    report = evaluate_case(case, output, trace, docs, metadata)
    assert not report["automated_passed"]
    assert not next(c for c in report["checks"] if c["item"] == "required_evidence_read")["pass"]


@pytest.mark.parametrize("effective,expected", [(["报销期限多久？", "改写"], True), (["改写"], False)])
def test_first_search_diagnostic_prefers_actual_effective_queries(effective, expected):
    case, output, trace, docs, metadata = fixture()
    obs = {"ok": True, "results": [], "effective_queries": effective, "corpus_hash": "test-hash"}
    # The model's proposal deliberately disagrees with effective retrieval input.
    proposed = ["改写"] if expected else ["报销期限多久？"]
    trace.insert(0, {"event": "tool_result", "tool": "search_documents", "arguments": {"queries": proposed}, "observation": obs})
    trace[-1]["messages"].append({"role": "tool", "tool_call_id": "search", "content": json.dumps(obs)})
    report = evaluate_case(case, output, trace, docs, metadata)
    assert report["diagnostics"]["first_search_preserved_original"] is expected
    assert report["diagnostics"]["query_source"] == "observation.effective_queries"
    assert report["automated_passed"]  # Diagnostics do not change the pass gate.


def test_first_search_diagnostic_skips_failure_and_supports_old_traces():
    case, output, trace, docs, metadata = fixture()
    failure = {"ok": False, "error": {"code": "INVALID_ARGUMENTS"}}
    success = {"ok": True, "results": [], "corpus_hash": "test-hash"}
    trace[:0] = [
        {"event": "tool_result", "tool": "search_documents", "arguments": {"queries": ["错误改写"]}, "observation": failure},
        {"event": "tool_result", "tool": "search_documents", "arguments": {"queries": ["报销期限多久？"]}, "observation": success},
    ]
    for index, obs in enumerate((failure, success)):
        trace[-1]["messages"].append({"role": "tool", "tool_call_id": f"search{index}", "content": json.dumps(obs)})
    report = evaluate_case(case, output, trace, docs, metadata)
    assert report["diagnostics"]["first_search_preserved_original"] is True
    assert report["diagnostics"]["query_source"] == "arguments.queries"
    assert evaluate_case(*fixture())["diagnostics"]["first_search_preserved_original"] is None
