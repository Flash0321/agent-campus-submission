"""Recheck saved evidence offline without editing it or instantiating a model."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.checks import evaluate_case, read_trace

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ("input.json", "output.json", "trace.jsonl", "corpus_snapshot.json", "metadata.json", "checks.json")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _corpus_hash(documents: list[dict[str, Any]]) -> str:
    # Same canonical representation as Corpus, without rebuilding a retrieval index.
    canonical = sorted(copy.deepcopy(documents), key=lambda d: d["doc_id"])
    for doc in canonical:
        doc["chunks"] = sorted(doc["chunks"], key=lambda c: c["chunk_id"])
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _prepare_run(check_path: Path, input_dir: Path, cases: dict[str, Any]) -> dict[str, Any]:
    directory = check_path.parent
    missing = [name for name in ARTIFACTS if not (directory / name).is_file() or not (directory / name).stat().st_size]
    if missing:
        raise ValueError(f"Incomplete evidence in {directory}: {', '.join(missing)}")
    original = _read(check_path)
    cid = original.get("case_id") if isinstance(original, dict) else None
    follow_up = isinstance(cid, str) and cid.endswith("-follow-up")
    base_id = cid.removesuffix("-follow-up") if follow_up else cid
    if base_id not in cases or not isinstance(original.get("automated_passed"), bool):
        raise ValueError(f"Not an acceptance check or unknown case ID in {check_path}")
    case = copy.deepcopy(cases[base_id])
    if follow_up:
        if not isinstance(case.get("follow_up_expected"), dict):
            raise ValueError(f"Missing follow-up expectations for {cid}")
        case.update(copy.deepcopy(case["follow_up_expected"]))
    actual_input = _read(directory / "input.json")
    if not isinstance(actual_input, dict) or not isinstance(actual_input.get("question"), str) or not actual_input["question"].strip():
        raise ValueError(f"Invalid actual input in {directory}")
    # Preserve actual history, including controlled comparison history; never
    # reconstruct it from a gold answer or from another profile's current data.
    case.update(case_id=cid, input=actual_input)
    output, metadata = _read(directory / "output.json"), _read(directory / "metadata.json")
    documents, trace = _read(directory / "corpus_snapshot.json"), read_trace(directory / "trace.jsonl")
    if (not isinstance(output, dict) or not isinstance(output.get("answer"), str)
        or not isinstance(output.get("status"), str) or not isinstance(output.get("citations"), list)
        or not isinstance(output.get("gaps"), list)):
        raise ValueError(f"Invalid saved output in {directory}")
    if (not isinstance(metadata, dict) or metadata.get("model_mode") not in {"real", "mock"}
        or not metadata.get("source_hash") or not metadata.get("corpus_hash")):
        raise ValueError(f"Invalid saved metadata in {directory}")
    if not isinstance(documents, list) or not documents or not trace or not all(isinstance(e, dict) for e in trace):
        raise ValueError(f"Empty or invalid corpus/trace in {directory}")
    if _corpus_hash(documents) != metadata["corpus_hash"]:
        raise ValueError(f"Corpus snapshot hash mismatch in {directory}")
    revised = evaluate_case(case, output, trace, documents, metadata)
    original_gates = {c["item"]: c["pass"] for c in original.get("checks", [])}
    changes = [{"item": c["item"], "original": original_gates.get(c["item"]), "revised": c["pass"]}
               for c in revised["checks"] if original_gates.get(c["item"]) != c["pass"]]
    relative = directory.relative_to(input_dir)
    scenario = relative.parent if (follow_up or case.get("follow_up")) and directory.name in {"turn1", "turn2"} else relative
    return {"relative": relative, "directory": directory, "case_id": cid, "base_case_id": base_id,
            "scenario_id": str(scenario), "original": original, "revised": revised, "changes": changes,
            "output": output, "metadata": metadata, "actual_input": actual_input,
            "artifact_hashes": {name: _hash(directory / name) for name in ARTIFACTS}}


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        scenarios.setdefault(row["scenario_id"], []).append(row)
    complete = [group for group in scenarios.values()
                if group[0]["base_case_id"] != "C05" or {r["case_id"] for r in group} == {"C05", "C05-follow-up"}]
    return {"requests": len(rows),
            "original_request_passed": sum(r["original_automated_passed"] for r in rows),
            "revised_request_passed": sum(r["revised_automated_passed"] for r in rows),
            "complete_scenarios": len(complete), "partial_scenarios": len(scenarios) - len(complete),
            "original_scenario_passed": sum(all(r["original_automated_passed"] for r in group) for group in complete),
            "revised_scenario_passed": sum(all(r["revised_automated_passed"] for r in group) for group in complete)}


def _mutations(prepared: list[dict[str, Any]], input_dir: Path) -> list[dict[str, Any]]:
    """Recompute pair gates from the same saved answers and revised case checks."""
    groups: dict[Path, dict[str, Any]] = {}
    for run in prepared:
        if run["case_id"] in {"C01", "C02", "C08", "C09"}:
            groups.setdefault(run["directory"].parent, {})[run["case_id"]] = run
    result = []
    for directory, runs in sorted(groups.items()):
        old_path = directory / "mutation-comparisons.json"
        old = _read(old_path) if old_path.exists() else []
        for baseline, changed, kind in (("C01", "C08", "value_changed"), ("C02", "C09", "conflict_removed")):
            row = {"group": str(directory.relative_to(input_dir)), "baseline": baseline, "changed": changed, "kind": kind}
            if baseline not in runs or changed not in runs:
                result.append({**row, "status": "not_run", "reason": "Missing paired saved run"})
                continue
            a, b = runs[baseline], runs[changed]
            ao, bo = a["output"], b["output"]
            gates = {"corpus_hash_changed": a["metadata"]["corpus_hash"] != b["metadata"]["corpus_hash"],
                     "answer_changed": ao["answer"] != bo["answer"],
                     "both_runs_pass_automated_checks": a["revised"]["automated_passed"] and b["revised"]["automated_passed"]}
            if kind == "value_changed":
                gates["new_value_quoted"] = any("20天" in c.get("quote", "") for c in bo["citations"])
                gates["old_value_not_quoted"] = all("30天" not in c.get("quote", "") for c in bo["citations"])
            else:
                gates["decision_changed"] = ao["status"] == "needs_clarification" and bo["status"] == "answered"
            previous = next((item for item in old if item.get("baseline") == baseline and item.get("changed") == changed), None)
            result.append({**row, "status": "completed", "checks": gates, "automated_passed": all(gates.values()),
                           "original_automated_passed": previous.get("automated_passed") if previous else None,
                           "original_artifact": str(old_path) if old_path.exists() else None,
                           "original_artifact_sha256": _hash(old_path) if old_path.exists() else None,
                           "model_mode": a["metadata"]["model_mode"], "human_review": "pending"})
    return result


def recheck(input_dir: str | Path, output_dir: str | Path, cases_path: str | Path | None = None) -> dict[str, Any]:
    input_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    cases_path = Path(cases_path).resolve() if cases_path else ROOT / "data/cases.json"
    if not input_dir.is_dir():
        raise ValueError("Input directory does not exist")
    if output_dir.exists():
        raise ValueError("Output directory already exists; choose a new directory to preserve evidence")
    if input_dir == output_dir or input_dir in output_dir.parents or output_dir in input_dir.parents:
        raise ValueError("Input and output directories must be separate trees")
    paths = sorted(input_dir.rglob("checks.json"))
    if not paths:
        raise ValueError("No saved acceptance checks found; no artifacts written")
    cases_raw = _read(cases_path)
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ValueError("Cases must be a nonempty array")
    cases = {case["case_id"]: case for case in cases_raw}
    evaluator_paths = [ROOT / "src/checks.py", Path(__file__).resolve()]
    provenance = {"evaluator_hashes": {str(p.relative_to(ROOT)): _hash(p) for p in evaluator_paths},
                  "cases_path": str(cases_path), "cases_sha256": _hash(cases_path)}
    # Validate and evaluate every run before creating output, so malformed input
    # never leaves an empty or deceptively partial successful report.
    prepared = [_prepare_run(path, input_dir, cases) for path in paths]
    mutations = _mutations(prepared, input_dir)
    for run in prepared:
        if any(_hash(run["directory"] / name) != digest for name, digest in run["artifact_hashes"].items()):
            raise ValueError("Input evidence changed during recheck")
    if any(_hash(p) != provenance["evaluator_hashes"][str(p.relative_to(ROOT))] for p in evaluator_paths) or _hash(cases_path) != provenance["cases_sha256"]:
        raise ValueError("Evaluator or cases changed during recheck")
    rows = []
    for run in prepared:
        meta = run["metadata"]
        row = {"request_id": str(run["relative"]), "case_id": run["case_id"], "base_case_id": run["base_case_id"],
               "scenario_id": run["scenario_id"], "model_mode": meta["model_mode"],
               "configured_profile": meta.get("configured_profile", "unknown"), "status": run["output"]["status"],
               "original_automated_passed": run["original"]["automated_passed"],
               "revised_automated_passed": run["revised"]["automated_passed"], "changed_checks": run["changes"],
               "original_artifact_dir": str(run["directory"]), "original_artifact_sha256": run["artifact_hashes"],
               "original_source_hash": meta["source_hash"], "original_prompt_hashes": meta.get("prompt_hashes", {}),
               "original_corpus_hash": meta["corpus_hash"], "actual_input": run["actual_input"],
               "acceptance_status": run["revised"]["acceptance_status"]}
        rows.append(row)
        _write(output_dir / run["relative"] / "checks.json", run["revised"])
        _write(output_dir / run["relative"] / "recheck.json", {**row, **provenance})
    real = [r for r in rows if r["model_mode"] == "real"]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "operation": "offline_recheck",
              "input_dir": str(input_dir), "output_dir": str(output_dir), **provenance,
              "model_api_calls": 0, "original_artifacts_modified": False,
              "counts": {"all": _counts(rows), "real": _counts(real),
                         "mock": _counts([r for r in rows if r["model_mode"] == "mock"])},
              "real_profiles": {profile: _counts([r for r in real if r["configured_profile"] == profile])
                                for profile in sorted({r["configured_profile"] for r in real})},
              "cases": rows, "mutations": mutations, "human_review": "pending",
              "limitation": "离线复核只改变评测口径，不是新的模型运行；自动初筛不替代答案/引用语义与用户验收。"}
    _write(output_dir / "cases-snapshot.json", cases_raw)
    _write(output_dir / "mutation-comparisons.json", mutations)
    _write(output_dir / "summary.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cases-path")
    args = parser.parse_args(argv)
    try:
        report = recheck(args.input_dir, args.output_dir, args.cases_path)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output_dir": report["output_dir"], "counts": report["counts"], "model_api_calls": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
