"""Orchestrator — runs the ReAct loop, wiring the LLM, tools, approval
gate, sandbox, and audit logger into a single agent execution pipeline."""

import threading

from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.tools.classifier import classify, REVERSIBLE
from alfard.tools.sanitizer import sanitize
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from rich import print as rprint
from rich.panel import Panel

from alfard.orchestrator.memory import Memory
from alfard.commands.registry import is_command, dispatch

MAX_TURNS = 20
_WEB_TOOLS = {"web_search", "web_fetch"}
# Lazy-tool catalog meta-tools are internal read-only operations and cannot
# be used as injection pivot points — exempt them from the injection gate.
_INJECTION_EXEMPT = {
    "lazy-tool.search_tools",
    "lazy-tool.list_tools",
    "lazy-tool.get_tool_schema",
    # invoke_proxy_tool is a pass-through dispatcher — it is not itself an
    # injection pivot; the downstream MCP tool handles its own approval.
    "lazy-tool.invoke_proxy_tool",
}


class Orchestrator:

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        audit: AuditLogger,
        gate: ApprovalGate,
        sandbox: SandboxExecutor,
        credentials: CredentialsManager,
        system_prompt: str = "You are a helpful AI agent.",
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._audit = audit
        self._gate = gate
        self._sandbox = sandbox
        self._credentials = credentials
        self._system_prompt = system_prompt
        self._memory = Memory(system_prompt)
        self._user_triggered = True  # tracks if current cycle is user-initiated
        self._loader = None  # set externally after construction
        self._facts_learned = 0
        self._memory_manager = None  # set externally
        self._web_context_active = False  # True after a web tool returns results
        self._web_access_enabled = False  # set externally from web_config
        self._guide_event = threading.Event()
        self._guide_text: str = ""
        self._stop_event = threading.Event()

    def signal_guide(self, text: str) -> None:
        """Thread-safe: inject user guidance at the next inter-step boundary."""
        self._guide_text = text
        self._guide_event.set()

    def stop(self) -> None:
        """Thread-safe: abort the current ReAct loop after the current step."""
        self._stop_event.set()

    def run(self, task: str) -> str:
        self._stop_event.clear()
        self._memory.add_user(task)
        self._gate.reset_job()

        # Check for slash commands before hitting the LLM
        if is_command(task):
            context = {
                "agent_name": getattr(self, "_agent_name", "agent"),
                "memory": self._memory,
                "loader": self._loader,
                "tool_registry": self._registry,
                "llm": self._llm,
                "turn_count": self._memory.turn_count(),
                "orchestrator": self,
            }
            result = dispatch(task, context)
            if result is not None:
                return result
            # Unknown command — let LLM handle it
            return f"Unknown command: {task}\nType /help for available commands."

        self._user_triggered = True

        for _ in range(MAX_TURNS):
            if self._stop_event.is_set():
                return "Task interrupted."

            if self._guide_event.is_set():
                guide = self._guide_text
                self._guide_text = ""
                self._guide_event.clear()
                self._memory.add_user(f"[USER GUIDANCE] {guide}")

            messages = self._memory.get_messages()
            tools = self._registry.get_schemas()

            response = self._llm.complete(messages, tools or None)
            self._audit.log_llm_call(
                self._llm.provider_name,
                self._llm.model,
                len(messages),
                response,
            )

            if response["tool_calls"] is None:
                self._web_context_active = False
                self._memory.add_assistant(response["content"] or "")
                return response["content"] or ""

            self._memory.add_assistant_tool_calls(response["tool_calls"])

            for tool_call in response["tool_calls"]:
                name = tool_call["name"]
                arguments = tool_call["arguments"]
                tool_call_id = tool_call["id"]

                if not self._registry.is_registered(name):
                    self._memory.add_tool_result(tool_call_id, f"Error: tool '{name}' is not registered")
                    continue

                classification = classify(name, self._registry)
                source = "user_instruction" if self._user_triggered else "tool_result"

                self._audit.log_tool_call(name, arguments, source)

                injection_intercepted = False
                if (
                    self._web_access_enabled
                    and self._web_context_active
                    and name not in _WEB_TOOLS
                    and name not in _INJECTION_EXEMPT
                ):
                    injection_intercepted = True
                    rprint(Panel(
                        f"The agent read web content and is now calling: [bold]{name}[/bold]\n"
                        "Web pages can contain hidden instructions that hijack agents.",
                        title="⚠️  Possible prompt injection",
                        border_style="yellow",
                    ))
                    approved = self._gate.request(name, arguments, source)
                    self._audit.log_prompt_injection_warning(name, approved)
                    if not approved:
                        self._memory.add_tool_result(tool_call_id, "Action blocked for security reasons.")
                        continue

                if not injection_intercepted and classification != REVERSIBLE:
                    approved = self._gate.request(name, arguments, source)
                    if not approved:
                        self._memory.add_tool_result(tool_call_id, "Action rejected by user.")
                        continue

                tool = self._registry.get(name)
                # MCP tool functions use async under the hood and cannot
                # be pickled for ProcessPoolExecutor. Run them directly.
                # They are already isolated — the MCP server runs in its
                # own subprocess managed by the MCP client.
                if tool.get("is_mcp", False):
                    try:
                        raw_result = tool["function"](**arguments)
                        result = {"success": True, "result": raw_result, "error": None}
                    except Exception as exc:
                        result = {"success": False, "result": None,
                                  "error": f"Tool '{name}' raised {type(exc).__name__}: {exc}"}
                else:
                    result = self._sandbox.execute(tool, arguments)

                if result["success"]:
                    raw = str(result["result"])
                    # Always sanitize and wrap with source attribution.
                    # is_suspicious() is an additional signal — flag it
                    # but sanitize regardless.
                    raw = sanitize(raw, source=name)
                    self._memory.add_tool_result(tool_call_id, raw)
                    if name in _WEB_TOOLS:
                        self._web_context_active = True
                else:
                    # Sanitize error strings too — they may contain
                    # content from malicious external sources.
                    error = sanitize(str(result["error"]), source=f"{name}.error")
                    self._memory.add_tool_result(tool_call_id, error)

            # After processing all tool calls in this cycle,
            # next cycle is tool-initiated unless user sends new input
            self._user_triggered = False

        return "Task stopped: maximum turns reached."

    def checkpoint_session(self) -> None:
        """Save in-progress conversation to sessions.db, run post-session hooks, clear history.

        Writes a session_end + session_start pair to the audit trail so the log stays
        coherent. Does NOT touch brain.db. Safe to call mid-conversation.
        """
        if self._memory_manager is None:
            return

        messages = self._memory.get_messages()
        turns = [m for m in messages if m["role"] in ("user", "assistant") and m.get("content")]
        turn_count = self._memory.turn_count()

        self._audit.log_session_end(
            outcome="checkpoint",
            turns=turn_count,
            tool_calls_total=self._audit._tool_calls_total,
            tool_calls_failed=self._audit._tool_calls_failed,
            corrections_detected=self._audit._corrections_detected,
        )

        if len(turns) >= 2:
            try:
                conv_text = "\n".join(
                    f"{m['role'].upper()}: {m['content'][:300]}" for m in turns[-20:]
                )
                response = self._llm.complete([{
                    "role": "user",
                    "content": (
                        "Summarise this conversation in 2-3 sentences. "
                        "List 3-5 topic keywords. Be factual and concise.\n\n"
                        "Format:\nSummary: <text>\nTopics: <comma-separated keywords>\n\n"
                        + conv_text
                    ),
                }])
                raw = (response.get("content") or "").strip()
                summary = raw
                topics: list[str] = []
                for line in raw.splitlines():
                    if line.lower().startswith("summary:"):
                        summary = line[len("summary:"):].strip()
                    elif line.lower().startswith("topics:"):
                        topics = [t.strip() for t in line[len("topics:"):].split(",") if t.strip()]
                if summary:
                    self._memory_manager.save_session(
                        summary=summary,
                        topics=topics,
                        turn_count=turn_count,
                        outcome="checkpoint",
                    )
            except Exception:
                pass

        count = self._memory_manager.get_session_count()
        self._memory_manager.mark_stale_goals(count)
        self._memory_manager.archive_old_memories()
        self._memory_manager.enforce_caps()

        if count > 0 and count % 10 == 0:
            try:
                self._memory_manager.run_reflect(self._llm, self._audit.log_path)
            except Exception:
                pass

        self._memory.reset()
        self._audit._tool_calls_total = 0
        self._audit._tool_calls_failed = 0
        self._audit._corrections_detected = 0

        self._audit.log_session_start(
            agent_name=getattr(self, "_agent_name", "agent"),
            provider=self._llm.provider_name,
            model=self._llm.model,
        )

    def reset(self) -> None:
        self._memory.reset()
        self._web_context_active = False
