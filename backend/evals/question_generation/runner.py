"""AI 出题 benchmark runner：HTTP/SSE 跑生成 → 拉取预览草稿 → 确定性评分 → 报告。

用法::

    python -m backend.evals.question_generation.runner --case all --dry-run
    python -m backend.evals.question_generation.runner --case all            # 真实出题并评分
    python -m backend.evals.question_generation.runner --case math_arithmetic_sequence_sum

前置条件：本地后端已启动（默认 http://127.0.0.1:8000）。生成走
``POST /api/question-library/generate``（SSE），终态 done 携带 preview_id，
再经 ``GET /api/question-library/previews/{preview_id}`` 取回草稿列表。

每个用例在 ``--out/<case_id>/<timestamp>/`` 下落盘：``events.jsonl``、
``preview.json``、``meta.json``、``score.json``、``report.md``。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.evals.question_generation.case_schema import (
    CaseValidationError,
    QuestionCase,
    default_cases_dir,
    load_case_file,
    load_cases,
)
from backend.evals.question_generation.graders import (
    grade_case,
    render_report,
)

GENERATE_URL = "/api/question-library/generate"
PREVIEW_URL = "/api/question-library/previews/{preview_id}"


# ---------------------------------------------------------------- 采集


def _consume_sse_lines(lines: Any, events: List[Dict[str, Any]], state: Dict[str, Any]) -> None:
    """消费 SSE data 行；done/error 置 terminal，记录 preview_id 与错误。"""
    for line in lines:
        if not line or not line.startswith("data:"):
            continue
        body = line[len("data:"):].strip()
        if not body or body == "[DONE]":
            if body == "[DONE]":
                state["terminal"] = True
            continue
        try:
            frame = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(frame, dict):
            continue
        events.append(frame)
        task_id = str(frame.get("taskId") or frame.get("task_id") or "").strip()
        if task_id:
            state["task_id"] = task_id
        ftype = str(frame.get("type") or frame.get("eventType") or "")
        data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
        if ftype in {"done", "error"}:
            state["terminal"] = True
            if ftype == "done":
                state["preview_id"] = str(data.get("preview_id") or "").strip()
                state["session_id"] = str(data.get("session_id") or "").strip()
            else:
                state["error"] = str(data.get("error") or data.get("message") or "unknown_error")


def _apply_task_status(payload: Any, state: Dict[str, Any]) -> bool:
    """Recover a terminal SSE result from the durable task endpoint.

    A task can commit its final events and close the live stream in the same
    scheduler tick.  Some HTTP clients then observe EOF after the last ping but
    before the done frame.  The durable task result is authoritative in that
    narrow race and contains the same preview/session identifiers.
    """

    task = payload if isinstance(payload, dict) else {}
    status = str(task.get("status") or "").strip().lower()
    if status not in {"completed", "failed", "cancelled", "canceled"}:
        return False
    state["terminal"] = True
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    if status == "completed":
        state["preview_id"] = str(result.get("preview_id") or result.get("previewId") or "").strip()
        state["session_id"] = str(result.get("session_id") or result.get("sessionId") or "").strip()
    else:
        error = task.get("error")
        if isinstance(error, dict):
            error = error.get("message") or error.get("detail") or status
        state["error"] = str(error or status).strip()
    return True


def _fetch_preview(base_url: str, preview_id: str, *, timeout_s: float = 30.0) -> Dict[str, Any]:
    url = base_url.rstrip("/") + PREVIEW_URL.format(preview_id=preview_id)
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                obj = resp.json()
                return obj if isinstance(obj, dict) else {}
    except (httpx.HTTPError, ValueError):
        pass
    return {}


def collect_run(
    case: QuestionCase,
    *,
    base_url: str,
    timeout_s: float,
) -> Dict[str, Any]:
    """POST 生成并消费 SSE；done 后拉取预览草稿。"""
    root = base_url.rstrip("/")
    payload = case.request_payload()
    events: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {
        "terminal": False,
        "error": "",
        "preview_id": "",
        "session_id": "",
        "task_id": "",
    }
    timeout = httpx.Timeout(connect=10.0, read=timeout_s, write=30.0, pool=30.0)
    started = time.monotonic()
    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST", root + GENERATE_URL, json=payload, headers={"Accept": "text/event-stream"}
        ) as resp:
            resp.raise_for_status()
            _consume_sse_lines(resp.iter_lines(), events, state)
        if not state["terminal"] and state["task_id"]:
            task_url = f"{root}/api/tasks/{state['task_id']}"
            for attempt in range(6):
                try:
                    task_resp = client.get(task_url)
                    if task_resp.status_code == 200 and _apply_task_status(task_resp.json(), state):
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(0.5 * (attempt + 1))

    if state["error"]:
        print(f"[{case.id}] 生成侧报错: {state['error']}", file=sys.stderr, flush=True)

    preview: Dict[str, Any] = {}
    if state["preview_id"]:
        # 预览在 done 事件后即可读取；短暂重试以越过落盘竞态。
        for attempt in range(3):
            preview = _fetch_preview(base_url, state["preview_id"])
            if preview:
                break
            time.sleep(1.5 * (attempt + 1))
    drafts = [d for d in (preview.get("draft_questions") or []) if isinstance(d, dict)]
    return {
        "events": events,
        "preview": preview,
        "drafts": drafts,
        "preview_id": state["preview_id"],
        "session_id": state["session_id"],
        "error": state["error"] or ("" if state["terminal"] else "stream_ended_without_terminal_event"),
        "elapsed_s": round(time.monotonic() - started, 1),
    }


# ---------------------------------------------------------------- 编排


def _resolve_cases(selector: str, cases_dir: Path) -> List[QuestionCase]:
    candidate = Path(selector)
    if candidate.is_file():
        return load_case_file(candidate)
    cases = load_cases(cases_dir)
    normalized = selector.strip().lower()
    if normalized in {"all", "light"}:
        return cases
    matched = [c for c in cases if c.id == selector.strip()]
    if not matched:
        raise CaseValidationError(
            f"未找到用例/套件 {selector!r}（套件: all；用例: {', '.join(c.id for c in cases)}）"
        )
    return matched


def _effective_parallel(requested: int, case_count: int) -> int:
    if requested < 0:
        raise CaseValidationError("--parallel 不能为负数（0 表示自动）")
    if case_count < 1:
        return 0
    if requested == 0:
        return min(4, case_count)
    return min(requested, case_count)


def run_case(
    case: QuestionCase,
    *,
    base_url: str,
    out_root: Path,
    timeout_s: float,
) -> Dict[str, Any]:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(out_root) / case.id / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[{case.id}] 开始出题（{case.subject}·{case.difficulty}·{case.question_type}×{case.count}）"
        f"→ {base_url} ...",
        flush=True,
    )
    run = collect_run(case, base_url=base_url, timeout_s=timeout_s)
    events: List[Dict[str, Any]] = run["events"]

    (out_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8"
    )
    (out_dir / "preview.json").write_text(
        json.dumps(run["preview"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta = {
        "case_id": case.id,
        "request": case.request_payload(),
        "base_url": base_url,
        "preview_id": run["preview_id"],
        "session_id": run["session_id"],
        "draft_count": len(run["drafts"]),
        "elapsed_s": run["elapsed_s"],
        "event_count": len(events),
        "error": run["error"],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    notes: List[str] = []
    if run["error"]:
        notes.append(f"生成侧报错: {run['error']}")
    if not run["drafts"]:
        notes.append("未取得草稿（生成失败或预览为空）")

    card = grade_case(case, run["drafts"], notes=notes)
    score_path = out_dir / "score.json"
    score_path.write_text(json.dumps(card.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(card), encoding="utf-8")
    print(
        f"[{case.id}] 成熟度 {card.total:.1f}/{card.total_max:.0f}"
        f"（原始诊断 {card.raw_total:.1f}，封顶 {card.applied_ceiling:.0f}）→ {score_path}",
        flush=True,
    )
    return card.to_dict()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AI 出题质量 benchmark")
    parser.add_argument("--case", help="用例 id / all / 用例 JSON 路径（默认 all）")
    parser.add_argument("--cases-dir", default=str(default_cases_dir()), help="用例目录")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端服务地址")
    parser.add_argument("--out", default="artifacts/evals/question_generation", help="输出根目录")
    parser.add_argument("--timeout-s", type=float, default=900.0, help="单用例 SSE 读取超时（秒）")
    parser.add_argument("--parallel", type=int, default=0, help="并发跑用例数（默认 0=自动，最多 4；1=串行）")
    parser.add_argument("--dry-run", action="store_true", help="只加载校验用例，不出题")
    args = parser.parse_args(argv)

    selector = args.case or "all"
    try:
        cases = _resolve_cases(selector, Path(args.cases_dir))
        workers = _effective_parallel(args.parallel, len(cases))
    except CaseValidationError as exc:
        print(f"用例错误: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        for case in cases:
            print(
                f"[dry-run] {case.id}: {case.subject} {case.difficulty} {case.question_type}×{case.count} "
                f"kp={len(case.knowledge_points)} stem锚={len(case.stem_anchors)} "
                f"答案锚={len(case.answer_anchors)} 禁用={len(case.forbidden_patterns)}"
            )
        print(f"[dry-run] {len(cases)} 个用例校验通过；真实运行并发={workers}")
        return 0

    results: List[Dict[str, Any]] = []
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"并行跑 {len(cases)} 个用例（并发 {workers}）", flush=True)
        results_by_id: Dict[str, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    run_case, case, base_url=args.base_url, out_root=Path(args.out), timeout_s=args.timeout_s
                ): case
                for case in cases
            }
            for future in as_completed(futures):
                case = futures[future]
                try:
                    results_by_id[case.id] = future.result()
                except (httpx.HTTPError, OSError) as exc:
                    print(f"[{case.id}] 采集失败: {exc}", file=sys.stderr)
                    results_by_id[case.id] = {"case_id": case.id, "total": 0.0, "error": str(exc)}
        results = [results_by_id[c.id] for c in cases]
    else:
        for case in cases:
            try:
                results.append(
                    run_case(
                        case, base_url=args.base_url, out_root=Path(args.out), timeout_s=args.timeout_s
                    )
                )
            except (httpx.HTTPError, OSError) as exc:
                print(f"[{case.id}] 采集失败: {exc}", file=sys.stderr)
                results.append({"case_id": case.id, "total": 0.0, "error": str(exc)})

    if not results:
        return 1
    print("\n==== 汇总 ====")
    for item in results:
        line = f"{item['case_id']}: 成熟度 {float(item.get('total', 0.0)):.1f}"
        if item.get("error"):
            line += f"（采集异常: {item['error']}）"
        print(line)
    mean = sum(float(r.get("total", 0.0)) for r in results) / len(results)
    raw_mean = sum(float(r.get("raw_total", r.get("total", 0.0))) for r in results) / len(results)
    print(f"平均: {mean:.1f}/100；原始诊断平均: {raw_mean:.1f}/100")
    failed_gates: Dict[str, int] = {}
    for result in results:
        for gate in result.get("quality_gates") or []:
            if isinstance(gate, dict) and not bool(gate.get("passed")):
                gate_id = str(gate.get("id") or "unknown")
                failed_gates[gate_id] = failed_gates.get(gate_id, 0) + 1
    if failed_gates:
        summary = "、".join(f"{gid}={count}/{len(results)}" for gid, count in sorted(failed_gates.items()))
        print(f"未通过门槛: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
