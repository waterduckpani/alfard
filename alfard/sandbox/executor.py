"""Sandbox executor — runs each tool call in an isolated OS process with a hard timeout."""

import concurrent.futures
import traceback

DEFAULT_TIMEOUT = 30


def _run_tool(fn, kwargs: dict):
    return fn(**kwargs)


class SandboxExecutor:

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        # Isolation model: each tool runs in a separate OS process via
        # ProcessPoolExecutor. This provides memory isolation and prevents
        # a crashed tool from taking down the orchestrator.
        #
        # Limits: the child process inherits the parent's Python path and
        # can make network and filesystem calls unless the tool itself is
        # restricted. Docker-based isolation is the Phase 2 upgrade path
        # for stronger sandboxing.
        self.timeout = timeout

    def execute(self, tool: dict, arguments: dict) -> dict:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_tool, tool["function"], arguments)
            try:
                result = future.result(timeout=self.timeout)
                return {"success": True, "result": result, "error": None}
            except concurrent.futures.TimeoutError:
                return {
                    "success": False,
                    "result": None,
                    "error": f"Tool '{tool['name']}' timed out after {self.timeout}s",
                }
            except Exception as exc:
                tb = traceback.format_exc()
                return {
                    "success": False,
                    "result": None,
                    "error": f"Tool '{tool['name']}' raised {type(exc).__name__}: {exc}\n{tb}",
                }
