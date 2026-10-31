"""Run the acceptance suite and controlled comparisons, with gold kept offline."""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.checks import evaluate_case, read_trace

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def online_input(case: dict[str, Any]) -> dict[str, Any]:
    """Allowlist the only case fields the online system may receive."""
    raw = case["input"]
    result = {"question": raw["question"]}
    if "history" in raw:
        # Do not accidentally pass fields such as expected_answer embedded in turns.
        result["history"] = [{"role": m["role"], "content": m["content"]} for m in raw["history"]]
    return result


def follow_up_input(first_input: dict[str, Any], first_output: dict[str, Any],
                    follow_up: dict[str, Any]) -> dict[str, Any]:
    history = copy.deepcopy(first_input.get("history", []))
    history.extend([{"role": "user", "content": first_input["question"]},
                    {"role": "assistant", "content": first_output["answer"]}])
    return {"question": follow_up["question"], "history": history}


def run_metrics(trace: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    responses = [e for e in trace if e.get("event") in {"model_response", "model_error"}]
    p3 = sum(float(e.get("elapsed_ms", 0)) for e in responses if e.get("stage") == "P3")
    main = sum(float(e.get("elapsed_ms", 0)) for e in responses if e.get("stage") in {"P4", "P5"})
    usage_events = [e["usage"] for e in responses if isinstance(e.get("usage"), dict) and e["usage"]]
    usage = {key: sum(int(u.get(key) or 0) for u in usage_events)
             for key in ("prompt_tokens", "completion_tokens", "total_tokens")} if usage_events else None
    calls = [e for e in trace if e.get("event") == "model_request"]
    return {"elapsed_ms": metadata.get("elapsed_ms"), "p3_ms": p3, "main_ms": main,
            "model_calls": metadata.get("model_calls", len(calls)),
            "tool_calls": metadata.get("tool_calls", sum(e.get("event") == "tool_result" for e in trace)),
            "fallback_calls": sum(bool(e.get("fallback_reason")) for e in calls),
            "normalization_failed": metadata.get("normalization_failed", False),
            "normalization": metadata.get("normalization"), "usage": usage,
            "requested_models": [e.get("requested_model") for e in calls]}


def _turn(case: dict[str, Any], input_data: dict[str, Any], corpus_path: Path,
          out_dir: Path, mode: str, profile: str, retrieval_mode: str,
          agent_factory: Any = None) -> dict[str, Any]:
    from src.agent import Agent, AgentConfig
    factory = agent_factory or Agent
    budget = case.get("budget", {})
    config = AgentConfig(mode=mode, profile=profile, retrieval_mode=retrieval_mode,
                         max_model_calls=budget.get("max_model_calls", 8),
                         max_tool_calls=budget.get("max_tool_calls", 6),
                         main_model=os.getenv("LLM_MAIN_MODEL", os.getenv("LLM_MODEL", "qwen-plus-2025-12-01")),
                         fast_model=os.getenv("LLM_FAST_MODEL", "qwen-flash-2025-07-28"))
    agent = factory(config, corpus_path, fault=case.get("fault_injection"),
                    mock_behavior=case.get("mock_behavior") if mode == "mock" else None)
    output = agent.run(input_data, out_dir)
    trace = read_trace(out_dir / "trace.jsonl")
    metadata = _read(out_dir / "metadata.json", {})
    docs = _read(out_dir / "corpus_snapshot.json", _read(corpus_path))
    checks = evaluate_case(case, output, trace, docs, metadata)
    # Keep runtime validation and offline gold checks as distinct artifacts.
    runtime_checks = _read(out_dir / "checks.json")
    if runtime_checks is not None:
        _write(out_dir / "runtime-checks.json", runtime_checks)
    _write(out_dir / "checks.json", checks)
    return {"case_id": case["case_id"], "run_state": "completed", "model_mode": mode,
            "configured_profile": profile, "status": output.get("status"),
            "automated_passed": checks["automated_passed"],
            "detected_critical_failure": checks["detected_critical_failure"],
            "acceptance_status": checks["acceptance_status"],
            "real_dynamic_path_candidate": checks["real_dynamic_path_candidate"],
            "artifact_dir": str(out_dir), "metrics": run_metrics(trace, metadata)}


def mutation_comparisons(rows: list[dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    """Check pairs only if both actual runs exist; never invent an earlier result."""
    by_id = {r["case_id"]: r for r in rows if r.get("run_state") == "completed"}
    comparisons = []
    for baseline, changed, kind in (("C01", "C08", "value_changed"), ("C02", "C09", "conflict_removed")):
        if baseline not in by_id or changed not in by_id:
            comparisons.append({"baseline": baseline, "changed": changed, "kind": kind,
                                "status": "not_run", "reason": "缺少成对的实际运行"})
            continue
        a_dir, b_dir = Path(by_id[baseline]["artifact_dir"]), Path(by_id[changed]["artifact_dir"])
        a, b = _read(a_dir / "output.json"), _read(b_dir / "output.json")
        am, bm = _read(a_dir / "metadata.json", {}), _read(b_dir / "metadata.json", {})
        corpus_changed = bool(am.get("corpus_hash")) and am.get("corpus_hash") != bm.get("corpus_hash")
        checks = {"corpus_hash_changed": corpus_changed, "answer_changed": a.get("answer") != b.get("answer"),
                  "both_runs_pass_automated_checks": by_id[baseline]["automated_passed"] and by_id[changed]["automated_passed"]}
        if kind == "value_changed":
            checks["new_value_quoted"] = any("20天" in c.get("quote", "") for c in b.get("citations", []))
            checks["old_value_not_quoted"] = all("30天" not in c.get("quote", "") for c in b.get("citations", []))
        else:
            checks["decision_changed"] = a.get("status") == "needs_clarification" and b.get("status") == "answered"
        comparisons.append({"baseline": baseline, "changed": changed, "kind": kind,
                            "status": "completed", "automated_passed": all(checks.values()), "checks": checks,
                            "model_mode": by_id[baseline]["model_mode"], "human_review": "pending",
                            "note": "数值替换不强制工具路径变化；冲突消失要求终止决定变化。"})
    _write(output_dir / "mutation-comparisons.json", comparisons)
    return comparisons


def dynamic_path_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paths = []
    for row in rows:
        if row.get("run_state") != "completed":
            continue
        trace = read_trace(Path(row["artifact_dir"]) / "trace.jsonl")
        actions = []
        for event in trace:
            if event.get("event") == "tool_result":
                observation = event.get("observation", {})
                outcome = "ok" if observation.get("ok") else (observation.get("error") or {}).get("code", "error")
                actions.append(f"{event.get('tool')}:{outcome}")
        actions.append("finish:" + str(row.get("status")))
        paths.append({"case_id": row["case_id"], "repeat": row["repeat"], "model_mode": row["model_mode"],
                      "actions": actions, "observations_linked": row.get("real_dynamic_path_candidate", False),
                      "artifact_dir": row["artifact_dir"]})
    patterns = {tuple(p["actions"]) for p in paths if p["model_mode"] == "real" and p["observations_linked"]}
    return {"paths": paths, "distinct_observation_linked_real_patterns": len(patterns),
            "at_least_two_real_patterns": len(patterns) >= 2,
            "review_status": "pending_user_review", "note": "仅真实模型记录计入；模式差异仍需结合工具参数、原文和后续响应人工审阅。"}


def run_suite(mode: str, profile: str, output_dir: str | Path, case_ids: list[str] | None = None,
              repeat: int = 1, retrieval_mode: str = "dual", cases_path: str | Path | None = None,
              agent_factory: Any = None, fixed_followups: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("repeat must be positive")
    output_dir = Path(output_dir)
    if (output_dir / "summary.json").exists():
        raise ValueError("output directory already contains a suite; choose a new directory to preserve evidence")
    cases = _read(Path(cases_path) if cases_path else ROOT / "data/cases.json")
    if case_ids:
        known = {c["case_id"] for c in cases}
        if set(case_ids) - known:
            raise ValueError("Unknown case IDs: " + ", ".join(sorted(set(case_ids) - known)))
        cases = [c for c in cases if c["case_id"] in case_ids]
    # dotenv is loaded by main, callers may supply environment themselves.
    has_credentials = bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_BASE_URL"))
    rows = []
    repetitions = []
    started = time.perf_counter()
    for index in range(repeat):
        current_root = output_dir if repeat == 1 else output_dir / f"repeat-{index + 1}"
        current_rows = []
        for case in cases:
            cid = case["case_id"]
            effective_mode = "mock" if cid == "C10" else mode
            # Never write a Mock run under the real evidence directory.
            case_root = current_root / ("mock-only" if mode == "real" and effective_mode == "mock" else "") / cid
            if effective_mode == "real" and not has_credentials and agent_factory is None:
                row = {"case_id": cid, "run_state": "not_run", "model_mode": "real",
                       "configured_profile": profile, "reason": "缺少 LLM_API_KEY 或 LLM_BASE_URL，未请求模型服务",
                       "artifact_dir": str(case_root), "automated_passed": None, "acceptance_status": "not_run"}
                _write(case_root / "not-run.json", row)
            else:
                corpus_path = ROOT / "data/variants" / (case["corpus_variant"] + ".json")
                first_input = online_input(case)
                turn_dir = case_root / "turn1" if case.get("follow_up") else case_root
                try:
                    row = _turn(case, first_input, corpus_path, turn_dir, effective_mode, profile, retrieval_mode, agent_factory)
                    if case.get("follow_up"):
                        first_output = _read(turn_dir / "output.json")
                        comparison_key = f"{index + 1}:{cid}"
                        fixed = (fixed_followups or {}).get(comparison_key)
                        second_input = copy.deepcopy(fixed) if fixed else follow_up_input(first_input, first_output, case["follow_up"])
                        second_case = {**case, **case["follow_up_expected"], "case_id": cid + "-follow-up", "input": second_input}
                        second = _turn(second_case, second_input, corpus_path, case_root / "turn2",
                                       effective_mode, profile, retrieval_mode, agent_factory)
                        _write(case_root / "conversation.json", {"turn1_input": first_input, "turn1_output": first_output,
                               "turn2_input": second_input, "turn2_output": _read(case_root / "turn2/output.json"),
                               "history_source": "single配置实际首轮回答固定为两配置共有历史" if fixed else "本轮实际首轮回答",
                               "conversation_mode": "controlled_history_comparison" if fixed else "own_actual_conversation"})
                        row["follow_up"] = second
                        row["automated_passed"] = row["automated_passed"] and second["automated_passed"]
                        row["detected_critical_failure"] |= second["detected_critical_failure"]
                        row["acceptance_status"] = "pending_human_review" if row["automated_passed"] else "failed_automated_checks"
                except Exception as exc:
                    # Do not persist exception strings that might contain service credentials.
                    row = {"case_id": cid, "run_state": "runner_error", "model_mode": effective_mode,
                           "configured_profile": profile, "error_type": type(exc).__name__,
                           "artifact_dir": str(case_root), "automated_passed": False,
                           "acceptance_status": "runner_error"}
                    _write(case_root / "runner-error.json", row)
            row["repeat"] = index + 1
            current_rows.append(row)
            rows.append(row)
        repetitions.append({"repeat": index + 1, "mutations": mutation_comparisons(current_rows, current_root)})
    completed = [r for r in rows if r.get("run_state") == "completed"]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "requested_mode": mode,
              "configured_profile": profile, "retrieval_mode": retrieval_mode, "repeat": repeat,
              "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
              "counts": {"requested_cases": len(rows), "completed": len(completed),
                         "automated_passed": sum(r["automated_passed"] for r in completed),
                         "not_run": sum(r["run_state"] == "not_run" for r in rows),
                         "runner_errors": sum(r["run_state"] == "runner_error" for r in rows),
                         "real_runs": sum(r.get("model_mode") == "real" for r in completed),
                         "mock_runs": sum(r.get("model_mode") == "mock" for r in completed)},
              "cases": rows, "repetitions": repetitions, "dynamic_paths": dynamic_path_summary(rows),
              "limitation": "自动通过不是人工语义验收；Mock 不计入真实模型动态决策证据。所有人工评审保持 pending。"}
    _write(output_dir / "summary.json", report)
    return report


def compare_retrieval(report: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    from src.retrieval import Corpus
    cases = {c["case_id"]: c for c in _read(ROOT / "data/cases.json")}
    rows = []
    for run in report["cases"]:
        cid = run["case_id"]
        if run.get("run_state") != "completed" or cid == "C10":
            continue
        case = cases[cid]
        gold = {(item["doc_id"], item["chunk_id"]) for item in case.get("required_evidence", [])}
        if not gold:
            continue
        metadata = _read(Path(run["artifact_dir"]) / "metadata.json", {})
        normalized = (metadata.get("normalization") or {}).get("normalized_query")
        if not normalized:
            normalized = next((e.get("result", {}).get("normalized_query") for e in read_trace(Path(run["artifact_dir"]) / "trace.jsonl")
                               if e.get("event") == "normalization"), None)
        if not normalized:
            rows.append({"case_id": cid, "status": "not_run", "reason": "未获得有效的实际 P3 Query"})
            continue
        # Replay the captured corpus, not a potentially edited current data file.
        snapshot_path = Path(run["artifact_dir"]) / "corpus_snapshot.json"
        if not snapshot_path.exists():
            rows.append({"case_id": cid, "status": "not_run", "reason": "缺少实际运行的资料快照"})
            continue
        corpus = Corpus(snapshot_path)
        if corpus.corpus_hash != metadata.get("corpus_hash"):
            rows.append({"case_id": cid, "status": "not_run", "reason": "资料快照哈希与运行记录不符"})
            continue
        row = {"case_id": cid, "repeat": run["repeat"], "status": "completed", "model_mode": run["model_mode"],
               "query_source": "实际运行的 P3 输出；Mock 改写不是模型改进证据",
               "original_query": case["input"]["question"], "normalized_query": normalized,
               "corpus_hash": corpus.corpus_hash, "gold_count": len(gold)}
        for mode, queries in (("original", [case["input"]["question"]]), ("dual", [case["input"]["question"], normalized])):
            results = corpus.search(queries, top_k=5, mode=mode)
            found = {(r["doc_id"], r["chunk_id"]) for r in results}
            row[mode] = {"hit_at_5": bool(gold & found), "covered": len(gold & found), "required": len(gold),
                         "annotated_evidence_coverage": len(gold & found) / len(gold), "results": results}
        rows.append(row)
    result = {"rows": rows, "sample_count": sum(r["status"] == "completed" for r in rows),
              "metric_name": "已标注证据覆盖（非全量标注召回率）", "top_k": 5,
              "limitation": "只有实际 real 模式的 P3 改写能用于模型检索改善结论；不预设双 Query 优于原 Query。"}
    _write(output_dir / "comparison.json", result)
    return result


def _profile_summary(report: dict[str, Any]) -> dict[str, Any]:
    runs = []
    for row in report["cases"]:
        if row.get("run_state") == "completed" and row.get("model_mode") == "real":
            runs.append(row)
            if row.get("follow_up"):
                runs.append(row["follow_up"])
    times = [r["metrics"]["elapsed_ms"] for r in runs if r["metrics"].get("elapsed_ms") is not None]
    p3_times = [r["metrics"]["p3_ms"] for r in runs]
    return {"real_request_count": len(runs), "automated_passed": sum(r["automated_passed"] for r in runs),
            "critical_failures_detected": sum(r.get("detected_critical_failure", False) for r in runs),
            "mean_elapsed_ms": statistics.mean(times) if times else None,
            "median_elapsed_ms": statistics.median(times) if times else None,
            "mean_p3_ms": statistics.mean(p3_times) if p3_times else None,
            "fallback_calls": sum(r["metrics"]["fallback_calls"] for r in runs),
            "normalization_valid_count": sum(bool(r["metrics"].get("normalization")) for r in runs),
            "normalization_failures": sum(r["metrics"]["normalization_failed"] for r in runs),
            "human_review": "pending"}


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--profile", choices=["single", "split"], default=os.getenv("MODEL_PROFILE", "single"))
    parser.add_argument("--retrieval-mode", choices=["original", "dual"], default="dual")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--compare-models", action="store_true")
    parser.add_argument("--compare-retrieval", action="store_true")
    args = parser.parse_args(argv)
    output_dir = args.output_dir or ROOT / "examples" / ("model_comparison" if args.compare_models else args.mode)
    if args.compare_models:
        profiles = {}
        suite_failure = False
        fixed_followups = {}
        input_pairs = []
        reference_report = None
        for profile in ("single", "split"):
            report = run_suite(args.mode, profile, output_dir / profile, args.case_ids, args.repeat, args.retrieval_mode,
                               fixed_followups=fixed_followups)
            if profile == "single":
                reference_report = report
                for row in report["cases"]:
                    if row.get("follow_up"):
                        fixed_followups[f"{row['repeat']}:{row['case_id']}"] = _read(Path(row["follow_up"]["artifact_dir"]) / "input.json")
            elif reference_report:
                reference_rows = {(r["repeat"], r["case_id"]): r for r in reference_report["cases"]}
                for row in report["cases"]:
                    reference = reference_rows.get((row["repeat"], row["case_id"]))
                    if row.get("run_state") != "completed" or not reference or reference.get("run_state") != "completed":
                        continue
                    same = _read(Path(row["artifact_dir"]) / "input.json") == _read(Path(reference["artifact_dir"]) / "input.json")
                    pair = {"case_id": row["case_id"], "repeat": row["repeat"], "same_input": same}
                    if row.get("follow_up") and reference.get("follow_up"):
                        pair["same_follow_up_input"] = _read(Path(row["follow_up"]["artifact_dir"]) / "input.json") == _read(Path(reference["follow_up"]["artifact_dir"]) / "input.json")
                    input_pairs.append(pair)
            suite_failure |= bool(report["counts"]["runner_errors"] or any(r.get("automated_passed") is False for r in report["cases"]))
            profiles[profile] = _profile_summary(report)
            if args.compare_retrieval:
                compare_retrieval(report, output_dir / profile / "retrieval_comparison")
        comparison = {"requested_mode": args.mode, "profiles": profiles, "selected_profile": None,
                      "selection_status": "pending_user_review", "input_pairs": input_pairs,
                      "controlled_follow_up_history": "C05追问使用single实际首轮形成的相同历史，不使用预期回答；普通验收各自保存完整会话链。",
                      "note": "顺序执行；Mock 耗时不可用于模型速度比较。失败与回退均保留，未运行不记为通过。"}
        _write(output_dir / "comparison.json", comparison)
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
        if args.mode == "real" and not any(p["real_request_count"] for p in profiles.values()):
            return 2
        return 1 if suite_failure else 0
    report = run_suite(args.mode, args.profile, output_dir, args.case_ids, args.repeat, args.retrieval_mode)
    if args.compare_retrieval:
        compare_retrieval(report, output_dir / "retrieval_comparison")
    print(json.dumps({"counts": report["counts"], "summary": str(output_dir / "summary.json")}, ensure_ascii=False, indent=2))
    if report["counts"]["not_run"]:
        return 2
    return 1 if report["counts"]["runner_errors"] or any(r.get("automated_passed") is False for r in report["cases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
