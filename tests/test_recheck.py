"""Offline reevaluation fixtures use Mock; no real model execution is performed."""
import hashlib
import json

import pytest

from src.evaluate import run_suite
from src.recheck import main, recheck


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file()}


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "original"
    run_suite("mock", "single", path, ["C01", "C02", "C05", "C08", "C09"])
    return path


def test_offline_recheck_preserves_original_and_recomputes_mutations(saved, tmp_path, monkeypatch):
    # Simulate a historical checker false negative, leaving the saved model
    # outputs/trace unchanged. Inquiry synonym semantics are tested separately.
    old_path = saved / "C02/checks.json"
    old = read(old_path)
    old["automated_passed"] = False
    for check in old["checks"]:
        if check["item"] == "conflict_followup_search_after_reading_sides":
            check["pass"] = False
    write(old_path, old)
    old_mutations = read(saved / "mutation-comparisons.json")
    old_mutations[1]["automated_passed"] = False
    old_mutations[1]["checks"]["both_runs_pass_automated_checks"] = False
    write(saved / "mutation-comparisons.json", old_mutations)
    before = hashes(saved)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline recheck must not run an Agent, load .env or use the network")

    monkeypatch.setattr("src.agent.Agent.run", forbidden)
    monkeypatch.setattr("dotenv.load_dotenv", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    out = tmp_path / "rechecked"
    report = recheck(saved, out)
    assert hashes(saved) == before
    assert report["model_api_calls"] == 0
    assert report["counts"]["mock"]["requests"] == 6
    assert report["counts"]["real"]["requests"] == 0
    assert report["counts"]["all"]["original_request_passed"] == 5
    assert report["counts"]["all"]["revised_request_passed"] == 6
    assert report["counts"]["all"]["original_scenario_passed"] == 4
    assert report["counts"]["all"]["revised_scenario_passed"] == 5
    assert report["mutations"][1]["original_automated_passed"] is False
    assert all(row["automated_passed"] for row in report["mutations"])
    new = read(out / "C02/recheck.json")
    assert new["changed_checks"] == [{"item": "conflict_followup_search_after_reading_sides", "original": False, "revised": True}]
    assert new["original_artifact_sha256"]["checks.json"] == before["C02/checks.json"]
    assert new["original_source_hash"] == read(saved / "C02/metadata.json")["source_hash"]
    assert new["evaluator_hashes"]["src/checks.py"]
    assert new["cases_sha256"]
    assert read(out / "C02/checks.json")["human_review"]["status"] == "pending"


def test_follow_up_recheck_uses_saved_actual_history(saved, tmp_path):
    report = recheck(saved, tmp_path / "out")
    follow = next(row for row in report["cases"] if row["case_id"] == "C05-follow-up")
    assert follow["actual_input"] == read(saved / "C05/turn2/input.json")
    assert follow["actual_input"]["history"][-1]["content"] == read(saved / "C05/turn1/output.json")["answer"]
    checked = read(tmp_path / "out/C05/turn2/checks.json")
    assert checked["automated_passed"]
    assert checked["evidence_coverage"]["required"] == 1
    assert checked["expectations_for_review"]["expected_claims"] == ["专业版", "支持", "PDF"]


@pytest.mark.parametrize("damage", ["missing_output", "empty_trace", "bad_output", "corpus_tamper", "unknown_case"])
def test_invalid_saved_evidence_does_not_create_output(saved, tmp_path, damage):
    if damage == "missing_output":
        (saved / "C01/output.json").unlink()
    elif damage == "empty_trace":
        (saved / "C01/trace.jsonl").write_text("", encoding="utf-8")
    elif damage == "bad_output":
        write(saved / "C01/output.json", {})
    elif damage == "corpus_tamper":
        docs = read(saved / "C01/corpus_snapshot.json")
        docs[0]["chunks"][0]["text"] += " changed"
        write(saved / "C01/corpus_snapshot.json", docs)
    else:
        data = read(saved / "C01/checks.json")
        data["case_id"] = "unknown"
        write(saved / "C01/checks.json", data)
    before = hashes(saved)
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        recheck(saved, out)
    assert not out.exists()
    assert hashes(saved) == before


def test_recheck_rejects_overwrite_nested_output_and_empty_input(saved, tmp_path):
    existing = tmp_path / "exists"
    existing.mkdir()
    for out in (existing, saved, saved / "nested"):
        with pytest.raises(ValueError):
            recheck(saved, out)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="No saved acceptance checks"):
        recheck(empty, tmp_path / "unused")
    assert not (saved / "nested").exists()
    assert not (tmp_path / "unused").exists()


def test_recheck_cli_and_immutable_second_run(saved, tmp_path, capsys):
    out = tmp_path / "cli"
    assert main(["--input-dir", str(saved), "--output-dir", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["model_api_calls"] == 0
    before = hashes(out)
    with pytest.raises(SystemExit) as error:
        main(["--input-dir", str(saved), "--output-dir", str(out)])
    assert error.value.code == 2
    assert hashes(out) == before
