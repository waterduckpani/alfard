"""Orchestrator — runs the ReAct loop, wiring the LLM, tools, approval
gate, sandbox, and audit logger into a single agent execution pipeline."""

from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.tools.classifier import classify, REVERSIBLE
from alfard.tools.sanitizer import sanitize
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from alfard.orchestrator.memory import Memory
from alfard.commands.registry import is_command, dispatch

MAX_TURNS = 20
SYSTEM_REINJECT_EVERY = 5


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

    def run(self, task: str) -> str:
        self._memory.add_user(task)

        # Reset job approval for new user turn
        if hasattr(self._gate, '_job_approved'):
            self._gate._job_approved = False

        # Check for slash commands before hitting the LLM
        if is_command(task):
            context = {
                "agent_name": getattr(self, "_agent_name", "agent"),
                "memory": self._memory,
                "loader": self._loader,
                "tool_registry": self._registry,
                "llm": self._llm,
                "turn_count": self._memory.turn_count(),
            }
            result = dispatch(task, context)
            if result is not None:
                return result
            # Unknown command — let LLM handle it
            return f"Unknown command: {task}\nType /help for available commands."

        self._user_triggered = True

        for _ in range(MAX_TURNS):
            if (
                self._memory.turn_count() > 0
                and self._memory.turn_count() % SYSTEM_REINJECT_EVERY == 0
            ):
                self._memory.add_user(f"[SYSTEM REMINDER] {self._system_prompt}")

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
                self._memory.add_assistant(response["content"] or "")
                return response["content"] or ""

            for tool_call in response["tool_calls"]:
                name = tool_call["name"]
                arguments = tool_call["arguments"]

                if not self._registry.is_registered(name):
                    self._memory.add_tool_result(name, f"Error: tool '{name}' is not registered")
                    continue

                classification = classify(name, self._registry)
                source = "user_instruction" if self._user_triggered else "tool_result"

                self._audit.log_tool_call(name, arguments, source)

                if classification != REVERSIBLE:
                    approved = self._gate.request(name, arguments, source)
                    if not approved:
                        self._memory.add_tool_result(name, "Action rejected by user.")
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
                    self._memory.add_tool_result(name, raw)
                else:
                    # Sanitize error strings too — they may contain
                    # content from malicious external sources.
                    error = sanitize(str(result["error"]), source=f"{name}.error")
                    self._memory.add_tool_result(name, error)

            # After processing all tool calls in this cycle,
            # next cycle is tool-initiated unless user sends new input
            self._user_triggered = False

        return "Task stopped: maximum turns reached."

    def reset(self) -> None:
        self._memory.reset()
