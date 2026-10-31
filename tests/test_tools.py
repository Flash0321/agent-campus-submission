"""Offline contract tests; these do not measure model decision quality."""
import copy
import json

import pytest

from src.retrieval import Corpus, tokenize
from src.tools import Toolbox


def document(doc_id, text, title="费用报销规定"):
    return {
        "doc_id": doc_id, "title": title, "version_date": "2026-09-01",
        "scope": None, "priority": None, "synthetic": True,
        "chunks": [{"chunk_id": doc_id + "-C01", "text": text}],
    }


@pytest.fixture
def corpus_file(tmp_path):
    path = tmp_path / "documents.json"
    docs = [
        document("D01", "员工报销应在费用发生后30天内提交申请。"),
        document("D02", "员工报销应在费用发生后15天内提交申请。", "费用报销FAQ"),
        document("D03", "门禁卡遗失后，应联系行政人员办理挂失。", "门禁卡挂失FAQ"),
    ]
    path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return path


def test_search_finds_both_conflicting_documents(corpus_file):
    corpus = Corpus(corpus_file)
    results = corpus.search(["报销期限多久？", "费用报销申请提交期限"])
    assert {r["doc_id"] for r in results} == {"D01", "D02"}
    assert all(set(("doc_id", "version_date", "chunk_id", "snippet", "score")) <= set(r) for r in results)


def test_no_overlap_is_successful_empty_result(corpus_file):
    tools = Toolbox(Corpus(corpus_file))
    output = tools.execute("search_documents", {"queries": ["quantumxyz"], "top_k": 5, "reason": "查找资料"})
    assert output["ok"] is True and output["results"] == [] and output["error"] is None
    assert tools.read_evidence == {}


def test_single_document_negative_bm25_still_retrievable(tmp_path):
    path = tmp_path / "one.json"
    path.write_text(json.dumps([document("X01", "员工报销期限30天。")], ensure_ascii=False), encoding="utf-8")
    assert Corpus(path).search(["报销"], mode="original")[0]["doc_id"] == "X01"


def test_dual_query_retains_original_and_adds_rewrite(corpus_file):
    corpus = Corpus(corpus_file)
    assert corpus.search(["quantumxyz", "费用报销"], mode="original") == []
    assert {r["doc_id"] for r in corpus.search(["quantumxyz", "费用报销"], mode="dual")} == {"D01", "D02"}
    assert corpus.search(["报销", "报销"]) == corpus.search(["报销"])


def test_document_diversity_prevents_one_source_occupying_top_two(corpus_file):
    docs = json.loads(corpus_file.read_text(encoding="utf-8"))
    docs[0]["chunks"].extend([
        {"chunk_id": "D01-C02", "text": "费用报销期限与费用报销规则。"},
        {"chunk_id": "D01-C03", "text": "费用报销的提交期限。"},
    ])
    corpus_file.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    results = Corpus(corpus_file).search(["费用报销期限"], top_k=2)
    assert {r["doc_id"] for r in results} == {"D01", "D02"}


def test_read_returns_exact_text_and_only_successful_reads_are_evidence(corpus_file):
    tools = Toolbox(Corpus(corpus_file))
    result = tools.execute("read_document", {"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": "核对原文"})
    assert result["ok"] and result["scope"] is None and result["priority"] is None
    evidence = tools.read_evidence[("D01", "D01-C01")]
    assert evidence["text"] == "员工报销应在费用发生后30天内提交申请。"
    assert evidence["corpus_hash"] == tools.corpus.corpus_hash
    assert evidence["chunk_hash"] == result["chunks"][0]["chunk_hash"]
    result["chunks"][0]["text"] = "篡改返回对象"
    assert tools.corpus.read("D01", ["D01-C01"])["chunks"][0]["text"] == evidence["text"]


@pytest.mark.parametrize("args", [
    {"doc_id": "../secret", "chunk_ids": ["D01-C01"], "reason": "读取"},
    {"doc_id": "D01", "chunk_ids": [], "reason": "读取"},
    {"doc_id": "D01", "chunk_ids": ["D01-C01", "D01-C01"], "reason": "读取"},
    {"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": " "},
    {"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": "读取", "path": "/etc/passwd"},
    {"doc_id": "D01", "chunk_ids": ["D01-C01"]},
    [],
])
def test_invalid_read_does_not_pollute_evidence(corpus_file, args):
    tools = Toolbox(Corpus(corpus_file))
    result = tools.execute("read_document", args)
    assert result["ok"] is False and result["error"]["code"] == "INVALID_ARGUMENTS"
    assert tools.read_evidence == {}


@pytest.mark.parametrize("args", [
    {"queries": ["报销"], "top_k": True, "reason": "检索"},
    {"queries": ["报销"], "top_k": 6, "reason": "检索"},
    {"queries": ["报销", "报销", "报销"], "top_k": 5, "reason": "检索"},
    {"queries": [" "], "top_k": 5, "reason": "检索"},
    {"queries": "报销", "top_k": 5, "reason": "检索"},
])
def test_search_arguments_reject_invalid_schema(corpus_file, args):
    assert Toolbox(Corpus(corpus_file)).execute("search_documents", args)["error"]["code"] == "INVALID_ARGUMENTS"


def test_unknown_ids_do_not_allow_partial_reads(corpus_file):
    tools = Toolbox(Corpus(corpus_file))
    bad_doc = tools.execute("read_document", {"doc_id": "ABSENT", "chunk_ids": ["D01-C01"], "reason": "核对"})
    bad_chunk = tools.execute("read_document", {"doc_id": "D01", "chunk_ids": ["D01-C01", "D02-C01"], "reason": "核对"})
    assert bad_doc["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert bad_chunk["error"]["code"] == "CHUNK_NOT_FOUND"
    assert bad_chunk["chunks"] == [] and tools.read_evidence == {}
    assert tools.execute("shell", {})["error"]["code"] == "UNKNOWN_TOOL"


def test_fault_injection_recovers_without_automatic_retry(corpus_file):
    tools = Toolbox(Corpus(corpus_file), fault={"tool": "read_document", "doc_id": "D01", "times": 1})
    args = {"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": "读原文"}
    first = tools.execute("read_document", args)
    assert tools.tool_mode == "fault_injected"
    assert first["error"]["code"] == "TOOL_TIMEOUT" and first["error"]["retryable"] is True
    assert tools.read_evidence == {}
    assert tools.execute("read_document", args)["ok"] is True


def test_invalid_attempt_does_not_consume_fault_injection(corpus_file):
    tools = Toolbox(Corpus(corpus_file), fault={"tool": "read_document", "doc_id": "D01", "times": 1})
    tools.execute("read_document", {"doc_id": "D01"})
    args = {"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": "读原文"}
    assert tools.execute("read_document", args)["error"]["code"] == "TOOL_TIMEOUT"


def test_missing_ids_are_not_masked_by_fault_injection(corpus_file):
    tools = Toolbox(Corpus(corpus_file), fault={"tool": "read_document", "times": "always"})
    result = tools.execute("read_document", {"doc_id": "ABSENT", "chunk_ids": ["ABSENT-C01"], "reason": "核实"})
    assert result["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert tools.read_evidence == {}


def test_persistent_failure_stays_distinct_from_absent_documents(corpus_file):
    tools = Toolbox(Corpus(corpus_file), fault={"tool": "read_document", "times": "always"})
    for _ in range(3):
        result = tools.execute("read_document", {"doc_id": "D01", "chunk_ids": ["D01-C01"], "reason": "重试"})
        assert result["ok"] is False and result["error"]["code"] == "TOOL_TIMEOUT"
    assert tools.read_evidence == {}


def test_same_id_date_content_replacement_changes_hash_and_fresh_answer_evidence(corpus_file):
    old = Corpus(corpus_file)
    docs = json.loads(corpus_file.read_text(encoding="utf-8"))
    docs[0]["chunks"][0]["text"] = "员工报销应在费用发生后20天内提交申请。"
    corpus_file.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    new = Corpus(corpus_file)
    assert old.corpus_hash != new.corpus_hash
    assert "30天" in old.read("D01", ["D01-C01"])["chunks"][0]["text"]
    assert "20天" in new.read("D01", ["D01-C01"])["chunks"][0]["text"]
    assert "20天" in new.search(["报销"])[0]["snippet"]


def test_order_change_keeps_content_hash_and_ranking(corpus_file):
    old = Corpus(corpus_file)
    docs = json.loads(corpus_file.read_text(encoding="utf-8"))
    corpus_file.write_text(json.dumps(list(reversed(docs)), ensure_ascii=False), encoding="utf-8")
    new = Corpus(corpus_file)
    assert old.corpus_hash == new.corpus_hash
    assert old.search(["报销"]) == new.search(["报销"])


def test_negation_numbers_and_product_editions_are_not_discarded():
    tokens = tokenize("星影协作标准版不支持PDF，30天；专业版支持CSV。")
    assert "不" in tokens and "30" in tokens and "pdf" in tokens
    assert "标准版" in tokens and "专业版" in tokens


def test_empty_corpus_is_valid_but_duplicate_ids_fail(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    assert Corpus(path).search(["报销"]) == []
    doc = document("X", "测试原文")
    path.write_text(json.dumps([doc, copy.deepcopy(doc)], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="ID"):
        Corpus(path)


def test_first_search_preserves_original_and_reports_effective_queries(tmp_path):
    import json
    from src.retrieval import Corpus
    from src.tools import Toolbox
    path=tmp_path/'documents.json'
    path.write_text(json.dumps([{'doc_id':'D1','title':'星影协作标准版','version_date':'2026-09-01',
        'scope':None,'priority':None,'synthetic':True,'chunks':[{'chunk_id':'C1','text':'星影协作标准版不支持PDF。'}]}],ensure_ascii=False))
    box=Toolbox(Corpus(path));box.original_question='它能导出PDF吗？'
    args={'queries':['星影协作标准版导出能力','标准版PDF支持'],'top_k':5,'reason':'定位用户产品'}
    result=box.execute('search_documents',args)
    assert result['requested_queries']==args['queries']
    assert result['effective_queries']==['它能导出PDF吗？','标准版PDF支持']
    assert args['queries'][0]=='星影协作标准版导出能力'
    result2=box.execute('search_documents',{'queries':['产品支持范围'],'top_k':5,'reason':'补充核验'})
    assert result2['effective_queries']==['产品支持范围']
