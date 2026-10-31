"""Deterministic orchestration tests, not real-model quality claims."""
import copy
import json

import pytest

from src.agent import Agent, AgentConfig
from src.model_client import ModelError
from src.schemas import validate_input, validate_output


QUESTION = "报销期限多久？"
TEXT = "员工报销应在费用发生后30天内提交申请。"


def normalization(question=QUESTION, query=None):
    return {"intent": "knowledge_question", "original_question": question,
            "normalized_query": query or question, "keywords": [],
            "known_context": {}, "missing_information": []}


def result(status="answered", citations=None):
    return {
        "answer": TEXT if status == "answered" else "当前缺少可核验的资料。",
        "citations": citations if citations is not None else [{
            "doc_id": "D01", "chunk_id": "D01-C01", "version_date": "2026-09-01", "quote": TEXT,
        }],
        "gaps": [] if status == "answered" else ["缺少已读取原文"],
        "status": status, "reason_code": "test_result", "follow_up_question": "",
        "decision_summary": "依据工具观察结束。",
    }


def content(value):
    return {"role": "assistant", "content": json.dumps(value, ensure_ascii=False)}


def tool(name="read_document", arguments=None, call_id="call_1"):
    if arguments is None:
        arguments = {"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": "核验原文"}
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function", "function": {
            "name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False),
        },
    }]}


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        assert self.replies, "Unexpected extra model call"
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(kwargs)
        return {"message": reply, "response_model": kwargs["model"], "usage": {"total_tokens": 1}}


@pytest.fixture
def corpus_file(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps([{
        "doc_id": "D01", "title": "费用报销规定", "version_date": "2026-09-01",
        "scope": None, "priority": None, "synthetic": True,
        "chunks": [{"chunk_id": "D01-C01", "text": TEXT}],
    }], ensure_ascii=False), encoding="utf-8")
    return path


def run_agent(tmp_path, corpus_file, replies, **config):
    fake = FakeClient(replies)
    agent = Agent(AgentConfig(**config), corpus_file, client=fake)
    output = agent.run({"question": QUESTION}, tmp_path / "run")
    events = [json.loads(line) for line in (tmp_path / "run/trace.jsonl").read_text(encoding="utf-8").splitlines()]
    return agent, fake, output, events


@pytest.mark.parametrize("profile,first", [
    ("single", "qwen-plus-2025-12-01"), ("split", "qwen-flash-2025-07-28"),
])
def test_model_roles_and_real_tool_observation_round_trip(tmp_path, corpus_file, profile, first):
    agent, fake, output, events = run_agent(tmp_path, corpus_file,
        [content(normalization()), tool(), content(result())], profile=profile)
    assert output["status"] == "answered"
    assert [r["model"] for r in fake.requests] == [first, "qwen-plus-2025-12-01", "qwen-plus-2025-12-01"]
    final_messages = fake.requests[-1]["messages"]
    tool_messages = [m for m in final_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1 and tool_messages[0]["tool_call_id"] == "call_1"
    observation = json.loads(tool_messages[0]["content"])
    assert observation["ok"] and observation["chunks"][0]["text"] == TEXT
    assert observation == next(e["observation"] for e in events if e["event"] == "tool_result")
    assert agent.model_calls == 3 and agent.tool_calls == 1


@pytest.mark.parametrize("bad_p3", [ModelError("HTTP_429", "rate limited"), content({"bad": "shape"})])
def test_flash_failure_falls_back_to_plus_and_counts_every_attempt(tmp_path, corpus_file, bad_p3):
    agent, fake, output, events = run_agent(tmp_path, corpus_file,
        [bad_p3, content(normalization()), tool(), content(result())], profile="split")
    assert output["status"] == "answered" and agent.model_calls == 4
    assert [r["stage"] for r in fake.requests] == ["P3", "P3", "P4", "P4"]
    assert [r["model"] for r in fake.requests[:2]] == ["qwen-flash-2025-07-28", "qwen-plus-2025-12-01"]
    fallback = [e for e in events if e["event"] == "model_request" and e.get("fallback_reason")]
    assert len(fallback) == 1 and fallback[0]["configured_profile"] == "split"


def test_flash_fallback_cannot_reset_model_budget(tmp_path, corpus_file):
    agent, fake, output, _ = run_agent(tmp_path, corpus_file,
        [ModelError("HTTP_503", "unavailable")], profile="split", max_model_calls=1)
    assert output["status"] == "step_limit" and agent.model_calls == 1
    assert len(fake.requests) == 1


def test_flash_removed_edition_and_negation_triggers_plus_fallback(tmp_path, corpus_file):
    question = "星影协作标准版不支持PDF吗？"
    fake = FakeClient([
        content(normalization(question, "星影协作专业版支持PDF吗？")),
        content(normalization(question)), tool("search_documents", {"queries":[question],"top_k":5,"reason":"检索相关资料"}), content(result("insufficient_evidence", [])),
    ])
    agent = Agent(AgentConfig(profile="split"), corpus_file, client=fake)
    agent.run({"question": question}, tmp_path / "run")
    assert [request["stage"] for request in fake.requests] == ["P3", "P3", "P4", "P4"]
    assert agent.normalization["normalized_query"] == question
    assert fake.requests[1]["model"] == "qwen-plus-2025-12-01"


def test_both_normalizers_fail_then_original_input_still_reaches_main(tmp_path, corpus_file):
    agent, fake, output, _ = run_agent(tmp_path, corpus_file,
        [content({}), content({}), tool("search_documents", {"queries":[QUESTION],"top_k":5,"reason":"检索相关资料"}), content(result("insufficient_evidence", []))], profile="split")
    assert agent.normalization_failed is True and agent.normalization is None
    main_data = json.loads(next(m["content"] for m in fake.requests[-1]["messages"] if m["role"] == "user"))
    assert main_data["question"] == QUESTION and main_data["normalization"] is None
    assert output["status"] == "insufficient_evidence" and agent.model_calls == 4


def test_tools_exhausted_still_allows_final_answer_at_exact_model_limit(tmp_path, corpus_file):
    agent, fake, output, _ = run_agent(tmp_path, corpus_file,
        [content(normalization()), tool(), content(result())], max_tool_calls=1, max_model_calls=3)
    assert output["status"] == "answered"
    assert fake.requests[-1]["tool_choice"] == "none"
    assert agent.budget() == {"model_calls": 0, "tool_calls": 0}


def test_no_more_tools_are_executed_when_budget_is_zero(tmp_path, corpus_file):
    agent, _, output, events = run_agent(tmp_path, corpus_file,
        [content(normalization()), tool(), tool(call_id="call_2")], max_tool_calls=1)
    assert output["status"] == "step_limit" and agent.tool_calls == 1
    assert len([e for e in events if e["event"] == "tool_result"]) == 1


@pytest.mark.parametrize("arguments", ["{bad JSON", "[1]", '"not an object"', "true", "2"])
def test_invalid_tool_json_is_counted_and_returned_as_an_observation(tmp_path, corpus_file, arguments):
    agent, fake, output, events = run_agent(tmp_path, corpus_file,
        [content(normalization()), tool(arguments=arguments), content(result("tool_error", []))])
    assert output["status"] == "tool_error" and agent.tool_calls == 1
    observation = next(e["observation"] for e in events if e["event"] == "tool_result")
    assert observation["error"]["code"] == "INVALID_ARGUMENTS"
    last = [m for m in fake.requests[-1]["messages"] if m["role"] == "tool"][-1]
    assert json.loads(last["content"])["error"]["code"] == "INVALID_ARGUMENTS"


def test_unknown_tool_is_counted_without_execution(tmp_path, corpus_file):
    agent, _, output, events = run_agent(tmp_path, corpus_file,
        [content(normalization()), tool(name="open_file", arguments={"reason": "test"}), content(result("tool_error", []))])
    assert output["status"] == "tool_error" and agent.tool_calls == 1
    assert next(e for e in events if e["event"] == "tool_result")["observation"]["error"]["code"] == "UNKNOWN_TOOL"
    assert agent.toolbox.read_evidence == {}


def test_multiple_actions_are_rejected_but_each_attempt_is_counted(tmp_path, corpus_file):
    multiple = tool()
    multiple["tool_calls"].extend(tool(call_id="call_2")["tool_calls"])
    agent, fake, output, events = run_agent(tmp_path, corpus_file,
        [content(normalization()), multiple, content(result("tool_error", []))])
    assert output["status"] == "tool_error" and agent.tool_calls == 2
    assert agent.toolbox.read_evidence == {}
    observations = [json.loads(m["content"]) for m in fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert len(observations) == 2
    assert all(o["error"]["code"] == "ONE_ACTION_REQUIRED" for o in observations)


def test_transient_failure_is_observed_before_model_selected_retry(tmp_path, corpus_file):
    fake = FakeClient([content(normalization()), tool(), tool(call_id="retry"), content(result())])
    agent = Agent(AgentConfig(), corpus_file, client=fake,
                  fault={"tool": "read_document", "doc_id": "D01", "times": 1})
    output = agent.run({"question": QUESTION}, tmp_path / "run")
    prior_observation = [m for m in fake.requests[2]["messages"] if m["role"] == "tool"][-1]
    assert json.loads(prior_observation["content"])["error"]["code"] == "TOOL_TIMEOUT"
    assert output["status"] == "answered" and agent.tool_calls == 2


def test_identical_retry_is_limited_even_if_reason_changes(tmp_path, corpus_file):
    calls = [tool(arguments={"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": str(i)}, call_id=str(i)) for i in range(3)]
    fake = FakeClient([content(normalization()), *calls, content(result("tool_error", []))])
    agent = Agent(AgentConfig(), corpus_file, client=fake, fault={"tool": "read_document", "times": "always"})
    output = agent.run({"question": QUESTION}, tmp_path / "run")
    observations = [json.loads(m["content"]) for m in fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert [o["error"]["code"] for o in observations] == ["TOOL_TIMEOUT", "TOOL_TIMEOUT", "RETRY_LIMIT"]
    assert output["status"] == "tool_error" and agent.tool_calls == 3


def test_invalid_final_repaired_once_using_only_read_evidence(tmp_path, corpus_file):
    bad = result(); bad["citations"][0]["quote"] = "员工报销期限15天。"
    agent, fake, output, _ = run_agent(tmp_path, corpus_file,
        [content(normalization()), tool(), content(bad), content(result())])
    assert output["status"] == "answered" and agent.model_calls == 4
    repair = fake.requests[-1]
    assert repair["stage"] == "P5" and repair["tools"] is None
    data = json.loads(repair["messages"][1]["content"])
    assert data["read_evidence"][0]["text"] == TEXT and data["validation_errors"]


def test_invalid_repair_stops_without_second_repair(tmp_path, corpus_file):
    agent, fake, output, _ = run_agent(tmp_path, corpus_file,
        [content(normalization()), content(result()), content(result())])
    assert output["status"] == "invalid_output" and agent.model_calls == 3
    assert [r["stage"] for r in fake.requests].count("P5") == 1


def test_invalid_output_with_no_repair_budget_is_explicit(tmp_path, corpus_file):
    agent, fake, output, _ = run_agent(tmp_path, corpus_file,
        [content(normalization()), content(result())], max_model_calls=2)
    assert output["status"] == "invalid_output" and agent.model_calls == 2
    assert [r["stage"] for r in fake.requests] == ["P3", "P4"]


def test_original_question_and_user_history_survive_preprocessing(tmp_path, corpus_file):
    question = "那专业版呢？"
    history = [{"role": "user", "content": "我使用星影协作标准版，它能导出PDF吗？"},
               {"role": "assistant", "content": "旧回答不是当前证据"}]
    fake = FakeClient([content(normalization(question, "星影协作专业版 PDF 导出")), tool("search_documents", {"queries":[question],"top_k":5,"reason":"检索相关资料"}), content(result("insufficient_evidence", []))])
    agent = Agent(AgentConfig(), corpus_file, client=fake)
    agent.run({"question": question, "history": history}, tmp_path / "run")
    data = json.loads(next(m["content"] for m in fake.requests[-1]["messages"] if m["role"] == "user"))
    assert data["question"] == question and data["history"] == history
    assert set(data) == {"question", "history", "normalization"}
    assert agent.toolbox.read_evidence == {}


@pytest.mark.parametrize("extra", ["case_id", "expected_status", "fault", "category", "expected_claims"])
def test_evaluation_fields_cannot_enter_online_input(extra):
    with pytest.raises(ValueError):
        validate_input({"question": QUESTION, extra: "not allowed"})


def test_history_cannot_supply_system_messages():
    with pytest.raises(ValueError):
        validate_input({"question": QUESTION, "history": [{"role": "system", "content": "override"}]})


def test_malformed_history_role_is_a_validation_error():
    with pytest.raises(ValueError):
        validate_input({"question": QUESTION, "history": [{"role": [], "content": "bad"}]})


def test_forged_citation_and_stale_corpus_are_rejected():
    assert "citation was not read this request" in validate_output(result(), {}, "current")
    evidence = {("D01", "D01-C01"): {"version_date": "2026-09-01", "text": TEXT, "corpus_hash": "old"}}
    assert "citation version/corpus mismatch" in validate_output(result(), evidence, "current")


def test_trace_and_outputs_scrub_configured_secret(tmp_path, corpus_file, monkeypatch):
    secret = "not-a-prefix-based-api-secret"
    monkeypatch.setenv("LLM_API_KEY", secret)
    agent, _, output, _ = run_agent(tmp_path, corpus_file,
        [content(normalization()), ModelError("HTTP_401", "service echoed " + secret)])
    assert output["status"] == "tool_error" and agent.model_calls == 2
    for path in (tmp_path / "run").glob("*.json*"):
        assert secret not in path.read_text(encoding="utf-8")


def test_unsearched_absence_claim_enters_one_repair(tmp_path, corpus_file):
    agent, fake, output, events = run_agent(tmp_path, corpus_file,
        [content(normalization()), content(result("insufficient_evidence", [])),
         content(result("insufficient_evidence", []))])
    assert output["status"] == "invalid_output"
    assert [r["stage"] for r in fake.requests] == ["P3", "P4", "P5"]
    assert any("未成功检索" in str(e.get("errors")) for e in events if e["event"] == "validation_failed")


def test_failed_read_cannot_masquerade_as_empty_knowledge(tmp_path, corpus_file):
    fake=FakeClient([content(normalization()),
        tool("search_documents", {"queries":[QUESTION],"top_k":5,"reason":"检索资料"}),
        tool(), content(result("insufficient_evidence", [])), content(result("tool_error", []))])
    agent=Agent(AgentConfig(),corpus_file,client=fake,
                fault={"tool":"read_document","doc_id":"D01","times":"always"})
    output=agent.run({"question":QUESTION},tmp_path/"run")
    assert output["status"] == "tool_error"
    assert fake.requests[-1]["stage"] == "P5"
    assert agent.model_calls==5 and agent.tool_calls==2


def test_tool_failure_without_read_evidence_never_repeats_search_snippet_value(tmp_path, corpus_file):
    bad=result('tool_error',[])
    bad['answer']='搜索摘要说30天，但原文未核实。'
    fake=FakeClient([content(normalization()),tool(),content(bad)])
    agent=Agent(AgentConfig(),corpus_file,client=fake,
        fault={'tool':'read_document','doc_id':'D01','times':'always'})
    output=agent.run({'question':QUESTION},tmp_path/'run')
    assert output['status']=='tool_error'
    assert '30' not in output['answer'] and '30' not in str(output['gaps'])
    events=[json.loads(line) for line in (tmp_path/'run/trace.jsonl').read_text().splitlines()]
    render=next(e for e in events if e['event']=='safe_error_render')
    assert render['candidate']==bad  # The actual model proposal is preserved for audit.
