"""Benchmark runner：HTTP/SSE 跑生成 → 采集事件与成稿 → 评分 → 报告。

用法::

    python -m backend.evals.study_materials.runner --case all --dry-run   # 校验 40 例
    python -m backend.evals.study_materials.runner --case light           # 轻量 8 例、自动并发
    python -m backend.evals.study_materials.runner --case lebesgue_integral \
        --base-url http://127.0.0.1:8000 [--llm-judge] [--check-links]

每个用例在 ``--out/<case_id>/<timestamp>/`` 下落盘：
``events.jsonl``、``final.md``、``meta.json``、``task_info.json``、
``score.json``、``report.md``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from backend.evals.study_materials.case_schema import (
    BenchmarkCase,
    CaseValidationError,
    default_cases_dir,
    load_case_file,
    load_cases,
)
from backend.evals.study_materials.scorecard import grade_case, write_outputs

GENERATE_URL = "/api/study-materials/generate"
TASK_URL = "/api/study-materials/tasks/{task_id}"
TASK_STREAM_URL = "/api/study-materials/tasks/{task_id}/stream"


# ---------------------------------------------------------------- 采集


def _extract_markdown(done_data: Dict[str, Any]) -> str:
    material = done_data.get("material")
    if isinstance(material, dict):
        return str(material.get("markdown") or "")
    if isinstance(material, str):
        return material
    return str(done_data.get("markdown") or "")


def _done_md_url(events: List[Dict[str, Any]]) -> str:
    """done 事件 material.md_url：归档已落盘但 done 未携带正文时的回退下载地址。"""
    for frame in reversed(events):
        if str(frame.get("type") or "") != "done":
            continue
        data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
        material = data.get("material") if isinstance(data.get("material"), dict) else {}
        md_url = str(material.get("md_url") or "").strip()
        if md_url:
            return md_url
    return ""


def _fetch_url_markdown(base_url: str, md_url: str) -> str:
    if not md_url.startswith("/"):
        return ""
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(base_url.rstrip("/") + md_url)
            if resp.status_code == 200:
                return resp.text
    except httpx.HTTPError:
        pass
    return ""


def _last_text_delta_content(events: List[Dict[str, Any]]) -> str:
    """事件流中最后一条 text_delta 的正文（设计契约：text_delta 即全量成稿快照）。

    done 载荷超 DB JSON 上限被整包截断（``{"_truncated": ...}``）时，成稿只存在于
    事件流里；此时最后一条快照就是最终成稿。
    """
    for frame in reversed(events):
        if str(frame.get("type") or "") != "text_delta":
            continue
        data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
        content = str(data.get("content") or "")
        if content.strip():
            return content
    return ""


def resolve_markdown(events: List[Dict[str, Any]], *, base_url: str = "") -> tuple[str, str]:
    """(markdown, 来源说明)。done 未携带正文时依次回退 md_url 下载、最后一条 text_delta 快照。"""
    markdown = ""
    for frame in reversed(events):
        if str(frame.get("type") or "") == "done":
            data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
            markdown = _extract_markdown(data)
            break
    if markdown.strip():
        return markdown, "done_event"
    if base_url:
        md_url = _done_md_url(events)
        if md_url:
            fetched = _fetch_url_markdown(base_url, md_url)
            if fetched.strip():
                return fetched, f"md_url 回退（{md_url}）"
    snapshot = _last_text_delta_content(events)
    if snapshot.strip():
        return snapshot, "text_delta_fallback"
    return "", "none"


def _consume_sse_lines(
    lines: Any,
    events: List[Dict[str, Any]],
    state: Dict[str, Any],
) -> None:
    """消费一个 SSE 流的 data 行，更新 events/state（last_seq、terminal、error）。"""
    for line in lines:
        if not line or not line.startswith("data:"):
            continue
        body = line[len("data:"):].strip()
        if not body:
            continue
        if body == "[DONE]":
            state["terminal"] = True
            break
        try:
            frame = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(frame, dict):
            continue
        seq = int(frame.get("seq") or 0)
        if seq and seq <= int(state.get("last_seq") or 0):
            continue
        if seq:
            state["last_seq"] = seq
        events.append(frame)
        ftype = str(frame.get("type") or "")
        if ftype in {"done", "error"}:
            state["terminal"] = True
            if ftype == "error":
                data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
                state["error"] = str(data.get("message") or data.get("error") or "unknown_error")


def collect_run(
    case: BenchmarkCase,
    *,
    base_url: str,
    timeout_s: float,
    max_resumes: int = 3,
) -> Dict[str, Any]:
    """POST /generate 并消费 SSE；断流时按 after_seq 断点重连（API 原生支持续流）。"""
    root = base_url.rstrip("/")
    payload = case.request_payload()
    events: List[Dict[str, Any]] = []
    task_id = ""
    started = time.monotonic()
    state: Dict[str, Any] = {"last_seq": 0, "terminal": False, "error": ""}
    timeout = httpx.Timeout(connect=10.0, read=timeout_s, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        try:
            with client.stream("POST", root + GENERATE_URL, json=payload, headers={"Accept": "text/event-stream"}) as resp:
                resp.raise_for_status()
                task_id = str(resp.headers.get("X-Task-Id") or "")
                _consume_sse_lines(resp.iter_lines(), events, state)
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout) as exc:
            if not task_id:
                raise
            state["error"] = state["error"] or f"stream_dropped: {exc}"

        # 断流恢复：任务在服务端继续运行，按 last_seq 续流直到终态或重试耗尽。
        resumes = 0
        while not state["terminal"] and task_id and resumes < max(0, int(max_resumes)):
            resumes += 1
            time.sleep(min(5.0 * resumes, 15.0))
            try:
                stream_url = f"{root}{TASK_STREAM_URL.format(task_id=task_id)}?after_seq={state['last_seq']}"
                with client.stream("GET", stream_url, headers={"Accept": "text/event-stream"}) as resp:
                    resp.raise_for_status()
                    _consume_sse_lines(resp.iter_lines(), events, state)
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout) as exc:
                state["error"] = state["error"] or f"stream_dropped: {exc}"
            if not state["terminal"]:
                info = fetch_task_info(base_url, task_id)
                status = str(info.get("status") or "").lower()
                if status and status != "running":
                    state["terminal"] = True
                    state["error"] = state["error"] or str(info.get("error") or "")
    markdown, markdown_source = resolve_markdown(events, base_url=base_url)
    return {
        "events": events,
        "markdown": markdown,
        "markdown_source": markdown_source,
        "task_id": task_id,
        "error": str(state.get("error") or ""),
        "elapsed_s": round(time.monotonic() - started, 1),
    }


def fetch_task_info(base_url: str, task_id: str) -> Dict[str, Any]:
    if not task_id:
        return {}
    url = base_url.rstrip("/") + TASK_URL.format(task_id=task_id)
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                obj = resp.json()
                return obj if isinstance(obj, dict) else {}
    except (httpx.HTTPError, ValueError):
        pass
    return {}


# ---------------------------------------------------------------- judge 注入（可选）


def build_llm_fact_judge() -> Callable[[str, str, List[str]], bool]:
    from backend.agent.config import AgentConfig
    from backend.llm.client import chat_completion_text

    model = str(AgentConfig().reflector_model or "").strip() or None

    def judge(markdown: str, description: str, source_urls: List[str]) -> bool:
        prompt = (
            "你是严格的事实核查员。判断下面的自学资料是否准确传达了给定事实点"
            "（表述方式可以不同，但关键论断必须实质等价且无科学性错误）。\n"
            f"事实点：{description}\n"
            f"参考来源：{'; '.join(source_urls) or '（无）'}\n\n"
            f"自学资料摘录：\n{markdown[:8000]}\n\n"
            "只回答 PASS 或 FAIL。"
        )
        kwargs: Dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 16,
        }
        if model:
            kwargs["model"] = model
        text = asyncio.run(chat_completion_text(**kwargs))
        return "pass" in str(text or "").strip().lower()

    return judge


def build_llm_aesthetics_judge() -> Callable[[str, str], float]:
    from backend.agent.config import AgentConfig
    from backend.llm.client import chat_completion_text

    model = str(AgentConfig().reflector_model or "").strip() or None

    def judge(markdown: str, title: str) -> float:
        prompt = (
            "你是排版评审。按 0-10 分评价这份自学资料的排版与可读性：标题层级与目录、"
            "段落长度与节奏、列表/表格/公式/图示的丰富度与一致性、视觉分隔是否清晰。"
            "只输出一个 0 到 10 的数字。\n"
            f"标题：{title}\n\n资料全文：\n{markdown[:12000]}"
        )
        kwargs: Dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 64,
        }
        if model:
            kwargs["model"] = model
        text = asyncio.run(chat_completion_text(**kwargs))
        match = re.search(r"\d+(?:\.\d+)?", str(text or ""))
        if not match:
            # 解析失败必须抛出：grade_aesthetics 只在异常时回退确定性代理，
            # 静默返回 0.0 会把「judge 失败」误记为「排版 0 分」。
            raise ValueError(f"aesthetics judge unparseable: {str(text or '')[:120]}")
        return max(0.0, min(10.0, float(match.group(0)))) / 10.0

    return judge


def build_llm_rubric_judge() -> Callable[[str, str], Any]:
    """W 维度 rubric judge：(system_prompt, markdown) -> LLM 原始输出（JSON 文本或 dict）。"""
    from backend.agent.config import AgentConfig
    from backend.llm.client import chat_completion_text

    model = str(AgentConfig().reflector_model or "").strip() or None

    def judge(system_prompt: str, markdown: str) -> Any:
        kwargs: Dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请评审以下自学资料：\n\n{markdown[:12000]}"},
            ],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        if model:
            kwargs["model"] = model
        return asyncio.run(chat_completion_text(**kwargs))

    return judge


def build_link_checker() -> Callable[[str], bool]:
    def check(url: str) -> bool:
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.head(url)
                if resp.status_code >= 400 or resp.status_code == 405:
                    resp = client.get(url, headers={"Range": "bytes=0-0"})
                return resp.status_code < 400
        except httpx.HTTPError:
            return False

    return check


# ---------------------------------------------------------------- 编排


def _resolve_cases(selector: str, cases_dir: Path) -> List[BenchmarkCase]:
    candidate = Path(selector)
    if candidate.is_file():
        return load_case_file(candidate)
    cases = load_cases(cases_dir)
    normalized = selector.strip().lower()
    tier_sets = {
        "light": {"smoke"},
        "heavy": {"core", "extended"},
        "smoke": {"smoke"},
        "core": {"smoke", "core"},
        "extended": {"extended"},
        "all": {"smoke", "core", "extended"},
    }
    if normalized in tier_sets:
        return [case for case in cases if case.tier in tier_sets[normalized]]
    matched = [c for c in cases if c.id == selector.strip()]
    if not matched:
        raise CaseValidationError(
            f"未找到用例/套件 {selector!r}（负载套件: light, heavy；"
            f"分层套件: smoke, core, extended, all；"
            f"用例: {', '.join(c.id for c in cases)}）"
        )
    return matched


def _select_shard(cases: List[BenchmarkCase], *, count: int, index: int) -> List[BenchmarkCase]:
    """按排序后的 case id 做稳定的 0-based 分片。"""
    if count < 1:
        raise CaseValidationError("--shard-count 必须大于等于 1")
    if index < 0 or index >= count:
        raise CaseValidationError(f"--shard-index 必须满足 0 <= index < {count}")
    ordered = sorted(cases, key=lambda case: case.id)
    selected = [case for position, case in enumerate(ordered) if position % count == index]
    if not selected:
        raise CaseValidationError(f"分片 {index}/{count} 没有用例（当前套件共 {len(ordered)} 个）")
    return selected


def _effective_parallel(requested: int, case_count: int) -> int:
    """0 表示自动：单例串行，多例最多 4 并发，避免压垮本地后端。"""
    if requested < 0:
        raise CaseValidationError("--parallel 不能为负数（0 表示自动）")
    if case_count < 1:
        return 0
    if requested == 0:
        return min(4, case_count)
    return min(requested, case_count)


def run_case(
    case: BenchmarkCase,
    *,
    base_url: str,
    out_root: Path,
    timeout_s: float,
    llm_judge: bool,
    check_links: bool,
) -> Dict[str, Any]:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(out_root) / case.id / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{case.id}] 开始生成（{case.preset}）→ {base_url} ...", flush=True)
    run = collect_run(case, base_url=base_url, timeout_s=timeout_s)
    events: List[Dict[str, Any]] = run["events"]
    markdown: str = run["markdown"]

    (out_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8"
    )
    (out_dir / "final.md").write_text(markdown, encoding="utf-8")
    task_info = fetch_task_info(base_url, run["task_id"])
    (out_dir / "task_info.json").write_text(json.dumps(task_info, ensure_ascii=False, indent=2), encoding="utf-8")

    notes: List[str] = []
    if run["error"]:
        notes.append(f"生成侧报错: {run['error']}")
    if run.get("markdown_source") not in ("done_event", "none", ""):
        notes.append(f"markdown 来源: {run['markdown_source']}")
    if not markdown.strip():
        notes.append("未取得成稿 markdown（生成失败或 done 事件为空）")

    meta = {
        "case_id": case.id,
        "task_id": run["task_id"],
        "elapsed_s": run["elapsed_s"],
        "event_count": len(events),
        "markdown_chars": len(markdown),
        "markdown_source": run.get("markdown_source") or "",
        "request": case.request_payload(),
        "base_url": base_url,
        "llm_judge": llm_judge,
        "check_links": check_links,
        "error": run["error"],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    card = grade_case(
        case,
        events,
        markdown,
        task_info=task_info,
        llm_fact_judge=build_llm_fact_judge() if llm_judge else None,
        llm_aesthetics_judge=build_llm_aesthetics_judge() if llm_judge else None,
        llm_rubric_judge=build_llm_rubric_judge() if llm_judge else None,
        link_checker=build_link_checker() if check_links else None,
        notes=notes,
    )
    paths = write_outputs(card, out_dir)
    print(
        f"[{case.id}] 成熟度 {card.total:.1f}/100（原始诊断 {card.raw_total:.1f}，"
        f"封顶 {card.applied_ceiling:.0f}）→ {paths['report']}",
        flush=True,
    )
    return card.to_dict()


def regrade_run(
    run_dir: Path,
    *,
    cases_dir: Path,
    llm_judge: bool,
    check_links: bool,
    base_url: str = "",
) -> Dict[str, Any]:
    """对已落盘的运行目录重新评分（不重新生成）。

    校准调权重/阈值后用它对同一批 artifacts 快速复评。
    """
    run_dir = Path(run_dir)
    meta_path = run_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseValidationError(f"无法读取 {meta_path}: {exc}") from exc
    case_id = str(meta.get("case_id") or "").strip()
    matched = [c for c in load_cases(cases_dir) if c.id == case_id]
    if not matched:
        raise CaseValidationError(f"用例目录中找不到 meta 指向的 case_id {case_id!r}")
    case = matched[0]

    events: List[Dict[str, Any]] = []
    events_path = run_dir / "events.jsonl"
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(frame, dict):
                events.append(frame)
    markdown = ""
    final_path = run_dir / "final.md"
    if final_path.is_file():
        markdown = final_path.read_text(encoding="utf-8")
    markdown_source = "final.md"
    if not markdown.strip() and base_url:
        markdown, markdown_source = resolve_markdown(events, base_url=base_url)
        if markdown.strip():
            final_path.write_text(markdown, encoding="utf-8")
    task_info: Dict[str, Any] = {}
    info_path = run_dir / "task_info.json"
    if info_path.is_file():
        try:
            obj = json.loads(info_path.read_text(encoding="utf-8"))
            task_info = obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            task_info = {}

    notes = ["regrade（基于已落盘 artifacts 复评，未重新生成）"]
    if markdown_source != "final.md":
        notes.append(f"markdown 来源: {markdown_source}")
    if str(meta.get("error") or "").strip():
        notes.append(f"生成侧报错: {meta['error']}")
    if not markdown.strip():
        notes.append("未取得成稿 markdown（生成失败或 done 事件为空）")
    card = grade_case(
        case,
        events,
        markdown,
        task_info=task_info,
        llm_fact_judge=build_llm_fact_judge() if llm_judge else None,
        llm_aesthetics_judge=build_llm_aesthetics_judge() if llm_judge else None,
        llm_rubric_judge=build_llm_rubric_judge() if llm_judge else None,
        link_checker=build_link_checker() if check_links else None,
        notes=notes,
    )
    paths = write_outputs(card, run_dir)
    print(
        f"[regrade {case.id}] 成熟度 {card.total:.1f}/100（原始诊断 {card.raw_total:.1f}，"
        f"封顶 {card.applied_ceiling:.0f}）→ {paths['report']}",
        flush=True,
    )
    return card.to_dict()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="自学资料生成质量 benchmark")
    parser.add_argument(
        "--case",
        help="用例 id / light / heavy / smoke / core / extended / all / 用例 JSON 路径",
    )
    parser.add_argument("--regrade", metavar="RUN_DIR", help="对已落盘的运行目录重新评分（不重新生成）")
    parser.add_argument("--cases-dir", default=str(default_cases_dir()), help="用例目录")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端服务地址")
    parser.add_argument("--out", default="artifacts/evals/study_materials", help="输出根目录")
    parser.add_argument("--timeout-s", type=float, default=2400.0, help="单用例 SSE 读取超时（秒）")
    parser.add_argument("--parallel", type=int, default=0, help="并发跑用例数（默认 0=自动，最多 4；1=串行）")
    parser.add_argument("--shard-count", type=int, default=1, help="把所选套件稳定分成 N 片（默认 1）")
    parser.add_argument("--shard-index", type=int, default=0, help="运行第几片，0-based（默认 0）")
    parser.add_argument("--llm-judge", action="store_true", help="启用 LLM 复核（事实点/排版/写作 rubric）")
    parser.add_argument("--check-links", action="store_true", help="抽查参考文献 URL 可访问性")
    parser.add_argument("--dry-run", action="store_true", help="只加载校验用例，不跑生成")
    args = parser.parse_args(argv)

    if args.regrade:
        try:
            regrade_run(
                Path(args.regrade),
                cases_dir=Path(args.cases_dir),
                llm_judge=args.llm_judge,
                check_links=args.check_links,
                base_url=args.base_url,
            )
        except CaseValidationError as exc:
            print(f"regrade 错误: {exc}", file=sys.stderr)
            return 2
        return 0

    if not args.case:
        parser.error("需要 --case 或 --regrade")

    try:
        cases = _resolve_cases(args.case, Path(args.cases_dir))
        cases = _select_shard(cases, count=args.shard_count, index=args.shard_index)
        workers = _effective_parallel(args.parallel, len(cases))
    except CaseValidationError as exc:
        print(f"用例错误: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        for case in cases:
            print(
                f"[dry-run] {case.id}: tier={case.tier} preset={case.preset} "
                f"kp={len(case.expected_knowledge_points)} "
                f"facts={len(case.required_facts)} traps={len(case.traps)} contrasts={len(case.contrasts)} "
                f"questions>={case.learning_requirements.min_practice_questions}"
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
                    run_case,
                    case,
                    base_url=args.base_url,
                    out_root=Path(args.out),
                    timeout_s=args.timeout_s,
                    llm_judge=args.llm_judge,
                    check_links=args.check_links,
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
                results.append(run_case(
                    case,
                    base_url=args.base_url,
                    out_root=Path(args.out),
                    timeout_s=args.timeout_s,
                    llm_judge=args.llm_judge,
                    check_links=args.check_links,
                ))
            except (httpx.HTTPError, OSError) as exc:
                print(f"[{case.id}] 采集失败: {exc}", file=sys.stderr)
                results.append({"case_id": case.id, "total": 0.0, "error": str(exc)})

    if not results:
        return 1
    print("\n==== 汇总 ====")
    for item in results:
        final_score = float(item.get("total", 0.0))
        raw_score = float(item.get("raw_total", final_score))
        line = f"{item['case_id']}: 成熟度 {final_score:.1f}/100（原始诊断 {raw_score:.1f}）"
        if item.get("error"):
            line += f"（采集异常: {item['error']}）"
        print(line)
    mean = sum(float(r.get("total", 0.0)) for r in results) / len(results)
    raw_mean = sum(float(r.get("raw_total", r.get("total", 0.0))) for r in results) / len(results)
    print(f"成熟度平均: {mean:.1f}/100；原始诊断平均: {raw_mean:.1f}/100")
    failed_gates: Dict[str, int] = {}
    for result in results:
        for gate in result.get("quality_gates") or []:
            if isinstance(gate, dict) and not bool(gate.get("passed")):
                gate_id = str(gate.get("id") or "unknown")
                failed_gates[gate_id] = failed_gates.get(gate_id, 0) + 1
    if failed_gates:
        summary = "、".join(f"{gate_id}={count}/{len(results)}" for gate_id, count in sorted(failed_gates.items()))
        print(f"未通过门槛: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
