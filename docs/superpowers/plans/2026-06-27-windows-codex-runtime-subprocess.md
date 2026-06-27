# Windows Codex Runtime Subprocess Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Codex runtime tasks launch successfully under Windows Uvicorn `--reload` while preserving existing streaming and process cleanup behavior.

**Architecture:** Retain `asyncio.create_subprocess_exec` as the primary launcher. If the default launcher raises `NotImplementedError` on Windows, start the same argv with `subprocess.Popen` in `asyncio.to_thread` and expose its pipes through a minimal async-compatible adapter; injected process factories and non-Windows hosts never use the fallback.

**Tech Stack:** Python 3.13, asyncio, subprocess, unittest

---

## File Structure

- Modify `backend/generation/agentic/claude_code.py`: add the Windows threaded process adapter, centralize runtime process creation, and retain meaningful messages for empty exceptions.
- Modify `backend/tests/test_codex_runtime_runner.py`: reproduce the Uvicorn selector-loop failure with the real runner and cover empty-exception diagnostics.

### Task 1: Reproduce the Windows selector-loop launch failure

**Files:**
- Modify: `backend/tests/test_codex_runtime_runner.py`
- Test: `backend/tests/test_codex_runtime_runner.py`

- [ ] **Step 1: Write the failing selector-loop regression test**

Add a `sys` import, then add this synchronous test method to `CodexRuntimeRunnerTests`:

```python
@unittest.skipUnless(sys.platform == "win32", "Windows selector-loop regression")
def test_windows_selector_loop_falls_back_to_threaded_subprocess(self) -> None:
    from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

    async def collect_events(task_root: Path) -> list[dict[str, Any]]:
        return [
            event
            async for event in run_codex_runtime_agent_events(
                task_type="deepthink",
                request={"question": "x^2"},
                user_id="u-1",
                task_id="selector-loop",
                spec=_spec(),
                config=CodexRuntimeConfig(command=sys.executable, task_root=task_root, timeout_s=5),
            )
        ]

    with tempfile.TemporaryDirectory() as tmp:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            events = runner.run(collect_events(Path(tmp)))

    self.assertEqual(events[-1]["type"], "error")
    self.assertEqual(events[-1]["data"]["code"], "codex_runtime_failed")
    self.assertNotEqual(events[-1]["data"]["code"], "codex_runtime_exception")
```

Using `sys.executable` is intentional: Python rejects the Codex flags and exits nonzero, so the assertion proves that the child process launched and reached normal return-code handling without making a live Codex request.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m unittest backend.tests.test_codex_runtime_runner.CodexRuntimeRunnerTests.test_windows_selector_loop_falls_back_to_threaded_subprocess -v
```

Expected: FAIL because the final code is `codex_runtime_exception`, proving the selector event loop cannot start the asyncio subprocess.

### Task 2: Add the Windows threaded subprocess adapter

**Files:**
- Modify: `backend/generation/agentic/claude_code.py:3-14`
- Modify: `backend/generation/agentic/claude_code.py:395-553`
- Test: `backend/tests/test_codex_runtime_runner.py`

- [ ] **Step 1: Add async-compatible wrappers around `subprocess.Popen`**

Import `subprocess` and add these private adapters near `ProcessFactory`:

```python
class _ThreadedPipeReader:
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def readline(self) -> bytes:
        return await asyncio.to_thread(self._stream.readline)

    async def read(self) -> bytes:
        return await asyncio.to_thread(self._stream.read)


class _ThreadedPipeWriter:
    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._pending = bytearray()

    def write(self, chunk: bytes) -> None:
        self._pending.extend(chunk)

    async def drain(self) -> None:
        chunk = bytes(self._pending)
        self._pending.clear()
        if chunk:
            await asyncio.to_thread(self._write_and_flush, chunk)

    def _write_and_flush(self, chunk: bytes) -> None:
        self._stream.write(chunk)
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


class _ThreadedPopenProcess:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.stdin = _ThreadedPipeWriter(process.stdin) if process.stdin is not None else None
        self.stdout = _ThreadedPipeReader(process.stdout) if process.stdout is not None else None
        self.stderr = _ThreadedPipeReader(process.stderr) if process.stderr is not None else None
        self.pid = process.pid

    @property
    def returncode(self) -> Optional[int]:
        return self._process.returncode

    async def wait(self) -> int:
        return await asyncio.to_thread(self._process.wait)

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()
```

- [ ] **Step 2: Centralize process startup with a narrow fallback**

Add the launcher:

```python
async def _start_runtime_process(
    *cmd: str,
    process_factory: Optional[ProcessFactory] = None,
    **kwargs: Any,
) -> Any:
    factory = process_factory or asyncio.create_subprocess_exec
    try:
        return await factory(*cmd, **kwargs)
    except NotImplementedError:
        if os.name != "nt" or process_factory is not None:
            raise
        process = await asyncio.to_thread(subprocess.Popen, list(cmd), **kwargs)
        return _ThreadedPopenProcess(process)
```

Replace the direct factory call in `run_codex_runtime_agent_events` with:

```python
proc = await _start_runtime_process(
    *cmd,
    process_factory=process_factory,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=str(task_dir),
    env=_codex_subprocess_env(),
)
```

This preserves injected-factory behavior: a custom factory that raises `NotImplementedError` is not silently replaced.

- [ ] **Step 3: Run the selector-loop test and verify GREEN**

Run:

```powershell
python -m unittest backend.tests.test_codex_runtime_runner.CodexRuntimeRunnerTests.test_windows_selector_loop_falls_back_to_threaded_subprocess -v
```

Expected: PASS; the child launches and produces `codex_runtime_failed`, not `codex_runtime_exception`.

### Task 3: Preserve actionable empty-exception diagnostics

**Files:**
- Modify: `backend/tests/test_codex_runtime_runner.py`
- Modify: `backend/generation/agentic/claude_code.py:543-553`

- [ ] **Step 1: Write the failing diagnostic test**

Add this async test:

```python
async def test_empty_runtime_exception_uses_exception_class_name(self) -> None:
    from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

    async def failing_factory(*cmd: str, **kwargs: Any) -> _FakeProcess:
        raise RuntimeError()

    with tempfile.TemporaryDirectory() as tmp:
        events = [
            event
            async for event in run_codex_runtime_agent_events(
                task_type="deepthink",
                request={"question": "x^2"},
                user_id="u-1",
                task_id="empty-error",
                spec=_spec(),
                config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                process_factory=failing_factory,
            )
        ]

    self.assertEqual(events[-1]["data"]["code"], "codex_runtime_exception")
    self.assertEqual(events[-1]["data"]["message"], "RuntimeError")
```

- [ ] **Step 2: Run the diagnostic test and verify RED**

Run:

```powershell
python -m unittest backend.tests.test_codex_runtime_runner.CodexRuntimeRunnerTests.test_empty_runtime_exception_uses_exception_class_name -v
```

Expected: FAIL because the current empty message falls back to `codex_runtime_exception`.

- [ ] **Step 3: Add and use the exception-message helper**

Add:

```python
def _exception_message(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__
```

Then change the defensive exception mapping to:

```python
yield _error_event("codex_runtime_exception", message=_exception_message(exc))
```

- [ ] **Step 4: Run both regression tests**

Run:

```powershell
python -m unittest backend.tests.test_codex_runtime_runner.CodexRuntimeRunnerTests.test_windows_selector_loop_falls_back_to_threaded_subprocess backend.tests.test_codex_runtime_runner.CodexRuntimeRunnerTests.test_empty_runtime_exception_uses_exception_class_name -v
```

Expected: 2 tests PASS.

### Task 4: Verify the runtime chain

**Files:**
- Verify: `backend/generation/agentic/claude_code.py`
- Verify: `backend/tests/test_codex_runtime_runner.py`

- [ ] **Step 1: Run the focused Codex runtime test module**

```powershell
python -m unittest backend.tests.test_codex_runtime_runner -q
```

Expected: PASS with no failures or errors.

- [ ] **Step 2: Run the adjacent study-materials runtime tests**

```powershell
python -m unittest backend.tests.test_study_materials_agentic_flow backend.tests.test_study_materials_resume_state -q
```

Expected: PASS with no failures or errors.

- [ ] **Step 3: Compile and check only touched paths**

```powershell
python -m py_compile backend/generation/agentic/claude_code.py backend/tests/test_codex_runtime_runner.py
git diff --check -- backend/generation/agentic/claude_code.py backend/tests/test_codex_runtime_runner.py
```

Expected: both commands exit 0.

- [ ] **Step 4: Commit the implementation**

```powershell
git add -- backend/generation/agentic/claude_code.py backend/tests/test_codex_runtime_runner.py docs/superpowers/plans/2026-06-27-windows-codex-runtime-subprocess.md
git commit -m "fix(agent): support Codex runtime under Windows reload"
```

Expected: one scoped commit containing the runtime adapter, its tests, and this plan; unrelated dirty-tree files remain unstaged.
