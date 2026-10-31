"""Trajectory provenance checks use observations, never labels or case IDs."""
import pytest

from src.provenance import validate_trajectory


def search(ok=True, error_code="TOOL_TIMEOUT"):
    return {"event": "tool_result", "tool": "search_documents", "observation": {
        "ok": ok, "results": [],
        "error": None if ok else {"code": error_code, "message": "测试工具错误", "retryable": error_code == "TOOL_TIMEOUT"},
    }}


def read(doc_id="D01", ok=True):
    return {"event": "tool_result", "tool": "read_document", "observation": {"ok": ok, "doc_id": doc_id}}


INSUFFICIENT = {"status": "insufficient_evidence", "reason_code": "no_supporting_evidence"}
CONFLICT = {"status": "needs_clarification", "reason_code": "document_conflict"}


def test_successful_empty_search_supports_honest_no_evidence_result():
    assert validate_trajectory(INSUFFICIENT, [search()]) == []


@pytest.mark.parametrize("events", [[], [search(False)], [read()], [
    {"event": "model_response", "tool": "search_documents", "observation": {"ok": True}},
]])
def test_absence_of_successful_search_cannot_be_replaced_by_claimed_search(events):
    errors = validate_trajectory(INSUFFICIENT, events)
    assert errors == ["未成功检索，不能断言知识库没有资料。"]


def test_failed_read_without_recovery_requires_tool_error():
    errors = validate_trajectory(INSUFFICIENT, [search(), read(ok=False), read(ok=False)])
    assert len(errors) == 1 and "tool_error" in errors[0]


def test_both_missing_search_and_failed_read_are_reported():
    errors = validate_trajectory(INSUFFICIENT, [search(False), read(ok=False)])
    assert len(errors) == 2


def test_successful_read_recovery_does_not_force_error_state():
    assert validate_trajectory(INSUFFICIENT, [search(), read(ok=False), read()]) == []


def test_failure_can_end_as_tool_error_without_search():
    assert validate_trajectory({"status": "tool_error", "reason_code": "service_failed"}, [read(ok=False)]) == []


def test_declared_conflict_requires_successful_reads_of_two_distinct_documents():
    errors = validate_trajectory(CONFLICT, [search(), read("A"), read("A"), search()])
    assert len(errors) == 1 and "两份不同文档" in errors[0]
    assert validate_trajectory(CONFLICT, [search(), read("A"), read("B", ok=False), search()])


def test_conflict_needs_followup_after_second_document_not_before():
    errors = validate_trajectory(CONFLICT, [search(), read("A"), search(), read("B")])
    assert len(errors) == 1 and "读取双方后" in errors[0]


def test_followup_after_both_reads_satisfies_minimum_trajectory():
    assert validate_trajectory(CONFLICT, [search(), read("A"), read("B"), search()]) == []


def test_dispatched_but_timed_out_followup_is_an_attempt_not_success():
    assert validate_trajectory(CONFLICT, [read("A"), read("B"), search(False)]) == []
    # A timeout alone is still insufficient to claim the corpus lacks evidence.
    assert validate_trajectory(INSUFFICIENT, [search(False)])


@pytest.mark.parametrize("code", [
    "INVALID_ARGUMENTS", "UNKNOWN_TOOL", "ONE_ACTION_REQUIRED", "RETRY_LIMIT",
    "UNRECOGNIZED_ERROR", None, [],
])
def test_pre_execution_or_unrecognized_errors_do_not_count_as_conflict_investigation(code):
    errors = validate_trajectory(CONFLICT, [read("A"), read("B"), search(False, code)])
    assert len(errors) == 1 and "尚无实际执行" in errors[0]


def test_rejected_query_can_be_corrected_then_executed():
    events = [read("A"), read("B"), search(False, "INVALID_ARGUMENTS"), search()]
    assert validate_trajectory(CONFLICT, events) == []


def test_failure_without_identifiable_runtime_error_is_not_an_executed_query():
    unknown = {"event": "tool_result", "tool": "search_documents", "observation": {"ok": False}}
    assert validate_trajectory(CONFLICT, [read("A"), read("B"), unknown])


def test_extra_reads_after_followup_do_not_reset_requirement():
    assert validate_trajectory(CONFLICT, [read("A"), read("B"), search(), read("C")]) == []


def test_context_clarification_without_history_needs_no_tools():
    output = {"status": "needs_clarification", "reason_code": "missing_product_context", "follow_up_question": "请问哪个产品？"}
    assert validate_trajectory(output, []) == []


def test_validator_does_not_infer_or_reclassify_conflicts():
    assert validate_trajectory({"status": "answered", "reason_code": "document_conflict"}, []) == []
    assert validate_trajectory({"status": "needs_clarification", "reason_code": "other_reason"}, []) == []


def test_non_observation_events_and_malformed_records_do_not_prove_execution():
    events = [None, {}, {"event": "tool_result", "observation": "not structured"},
              {"event": "model_request", "tool": "search_documents", "observation": {"ok": True}}]
    assert validate_trajectory(INSUFFICIENT, events)


def test_structure_validation_is_owned_by_separate_validator():
    assert validate_trajectory(None, []) == []
