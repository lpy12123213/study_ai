# Windows Codex Runtime Subprocess Design

## Problem

When the backend runs on Windows under Uvicorn `--reload`, Uvicorn selects
`_WindowsSelectorEventLoop`. That loop does not implement asyncio subprocess
transport creation. Starting Codex through `asyncio.create_subprocess_exec`
therefore raises an empty `NotImplementedError`, which is exposed to the task
client only as `codex_runtime_exception`.

## Chosen Design

Keep the existing asyncio subprocess path on supported event loops. When the
default Codex process factory raises `NotImplementedError` on Windows, start the
same command with `subprocess.Popen` inside a worker thread and wrap its standard
input, output, error, and wait operations in a small async-compatible adapter.

The fallback remains local to the Codex runtime launcher. Callers, streamed
events, cancellation, timeout handling, command construction, and injected test
process factories retain their current contracts. Non-Windows behavior is
unchanged.

## Error Handling

Only the Windows/default-factory `NotImplementedError` triggers the fallback.
Other launch exceptions keep their existing error mapping. Process termination
continues to use the existing Windows process-tree cleanup.

If an unexpected exception has no message, diagnostics should include its class
name so the persisted task error is actionable rather than collapsing to the
generic error code.

## Testing

Add a regression test that runs the launch helper on a real Windows selector
event loop and verifies a harmless child process can write stdout and exit
successfully. Keep the existing mocked Codex runner tests to prove streaming,
timeout, error, and cancellation behavior remain intact.

Verification will include the focused Codex runtime test module, the related
study-materials runtime tests, Python compilation, and touched-file diff checks.

## Rejected Alternatives

- Removing Uvicorn hot reload avoids the failing loop but degrades the normal
  development workflow and leaves the runtime fragile under other selector-loop
  hosts.
- Running a permanent helper service adds lifecycle and IPC complexity without
  benefit for a single local subprocess boundary.
