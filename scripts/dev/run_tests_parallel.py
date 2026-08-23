"""按文件分片并行运行后端 unittest 套件。

用法（仓库根目录）：

  python scripts/dev/run_tests_parallel.py              # 全量，默认 jobs=CPU 核数（上限 8）
  python scripts/dev/run_tests_parallel.py -j 4         # 指定分片数
  python scripts/dev/run_tests_parallel.py -k zujuan    # 只跑文件名包含 zujuan 的测试文件
  python scripts/dev/run_tests_parallel.py --hermetic   # 用 model.example.json 隔离本地 config/model.json

设计约束：

- 分片单位是测试文件：unittest 模块内可能共享状态，文件内保持串行；
  文件间按体积贪心装桶，尽量均衡各分片耗时。
- 并行跑的是独立进程，共享资源（SQLite 文件、固定端口）的测试文件应加入
  SERIAL_FILES，强制合并到同一分片串行执行。
- 任一分片失败即退出码非 0；失败分片的输出尾部直接打印，完整日志在
  .local/test-logs/ 下。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "backend" / "tests"

# 已知共享固定资源、必须串行的测试文件（按需补充；跑挂时把文件加进来）。
SERIAL_FILES: frozenset[str] = frozenset()

LOG_DIR = ROOT / ".local" / "test-logs"


def _venv_python() -> str | None:
    vpy = ROOT / "venv" / "Scripts" / "python.exe"
    if vpy.exists():
        return str(vpy)
    vpy = ROOT / "venv" / "bin" / "python"
    if vpy.exists():
        return str(vpy)
    return None


def discover_test_files(keyword: str) -> list[Path]:
    files = sorted(TESTS_DIR.glob("test_*.py"))
    if keyword:
        files = [f for f in files if keyword.lower() in f.name.lower()]
    return files


def build_shards(files: list[Path], jobs: int) -> list[list[Path]]:
    """按文件体积贪心装桶：大文件先分，始终给当前最轻的分片。"""

    serial = [f for f in files if f.name in SERIAL_FILES]
    parallel = [f for f in files if f.name not in SERIAL_FILES]
    shards: list[list[Path]] = [[] for _ in range(jobs)]
    weights = [0] * jobs

    for path in sorted(parallel, key=lambda p: p.stat().st_size, reverse=True):
        lightest = weights.index(min(weights))
        shards[lightest].append(path)
        weights[lightest] += path.stat().st_size

    # 串行文件合并进最后一个分片，保证同进程顺序执行。
    if serial:
        shards[-1].extend(serial)
    return [s for s in shards if s]


def _hermetic_env(env: dict[str, str]) -> dict[str, str]:
    """用仓库自带的 model.example.json 副本隔离本地 config/model.json。

    这是"本机过、CI 挂（或反过来）"的最大来源：model_name() 直接读真实
    model_roles，本地配置会改变被测行为。.env 里的值不会覆盖显式设置的环境变量。
    """

    example = ROOT / "config" / "model.example.json"
    if not example.exists():
        raise SystemExit("hermetic mode requires config/model.example.json")
    tmp = tempfile.mkdtemp(prefix="study-ai-hermetic-model-")
    synthetic = Path(tmp) / "model.json"
    shutil.copyfile(example, synthetic)
    env["MODEL_CONFIG_PATH"] = str(synthetic)
    return env


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="按文件分片并行运行后端 unittest 套件")
    parser.add_argument("-j", "--jobs", type=int, default=0, help="并行进程数（默认 CPU 核数，上限 8）")
    parser.add_argument("-k", "--keyword", default="", help="只跑文件名包含该关键字的测试文件")
    parser.add_argument("--hermetic", action="store_true", help="用 model.example.json 隔离本地模型配置")
    args = parser.parse_args(argv)

    jobs = args.jobs or min(os.cpu_count() or 4, 8)
    jobs = max(1, jobs)

    files = discover_test_files(args.keyword)
    if not files:
        print(f"[paratest] no test files match keyword: {args.keyword!r}")
        return 1

    shards = build_shards(files, jobs)
    python = _venv_python() or sys.executable

    env = dict(os.environ)
    if args.hermetic:
        env = _hermetic_env(env)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    procs: list[tuple[subprocess.Popen, list[Path], Path]] = []
    for index, shard in enumerate(shards):
        modules = [".".join((*p.parent.relative_to(ROOT).parts, p.stem)) for p in shard]
        log_path = LOG_DIR / f"shard-{stamp}-{index:02d}.log"
        proc = subprocess.Popen(
            [python, "-m", "unittest", *modules],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        procs.append((proc, shard, log_path))

    print(f"[paratest] {len(files)} files / {len(shards)} shards / jobs={len(shards)}"
          f"{' / hermetic' if args.hermetic else ''}")
    for index, (_, shard, _) in enumerate(procs):
        names = ", ".join(p.name for p in shard[:4])
        more = f" (+{len(shard) - 4})" if len(shard) > 4 else ""
        print(f"[paratest] shard {index:02d}: {names}{more}")

    failed_shards: list[tuple[list[Path], Path, str]] = []
    for proc, shard, log_path in procs:
        out, _ = proc.communicate()
        log_path.write_text(out or "", encoding="utf-8")
        if proc.returncode != 0:
            failed_shards.append((shard, log_path, out or ""))
            print(f"[paratest] shard FAILED (see {log_path}): {', '.join(p.name for p in shard)}")
        else:
            print(f"[paratest] shard ok: {', '.join(p.name for p in shard[:3])}"
                  f"{' …' if len(shard) > 3 else ''}")

    if failed_shards:
        print("\n[paratest] ============ failures ============")
        for shard, log_path, out in failed_shards:
            tail = "\n".join((out or "").splitlines()[-40:])
            print(f"\n----- {', '.join(p.name for p in shard)} (full log: {log_path}) -----\n{tail}")
        return 1

    print("[paratest] all shards passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
