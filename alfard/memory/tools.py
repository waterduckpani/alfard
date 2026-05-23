"""Memory tool callables — module-level singletons for multiprocessing compatibility."""


_EXPLICIT_PHRASES = (
    "remember that",
    "don't forget",
    "never forget",
    "always remember",
    "make sure you remember",
    "please remember",
    "remember this",
    "keep in mind",
)


class _ProposeMemory:
    def __init__(self) -> None:
        self._manager = None
        self._last_user_message = ""

    def set_manager(self, manager) -> None:
        self._manager = manager

    def set_user_message(self, msg: str) -> None:
        self._last_user_message = msg

    def __call__(
        self,
        content: str,
        memory_type: str = "fact",
        valence: str = "neutral",
        reason: str = "",
    ) -> str:
        if not self._manager:
            return "Memory not available."

        source = "agent_inferred"
        confidence = None
        lower_msg = self._last_user_message.lower()
        if any(phrase in lower_msg for phrase in _EXPLICIT_PHRASES):
            source = "user_explicit"
            confidence = 1.0

        result = self._manager.write(
            content,
            memory_type=memory_type,
            valence=valence,
            source=source,
            confidence=confidence,
            reason=reason,
        )

        if result == "conflict":
            return "Memory saved but conflicts with an existing entry — both are marked disputed. Tell the user."
        if result == "duplicate":
            return "Already known. Nothing written."
        if result.startswith("blocked"):
            return "Blocked — content looks like a secret. Nothing written."
        return result


class _CompleteGoal:
    def __init__(self) -> None:
        self._manager = None

    def set_manager(self, manager) -> None:
        self._manager = manager

    def __call__(self, query: str) -> str:
        if self._manager:
            result = self._manager.complete_goal(query)
            return f"completed: {result}" if result else "no matching goal found"
        return "Memory not available."


class _RecallMemory:
    def __init__(self) -> None:
        self._manager = None

    def set_manager(self, manager) -> None:
        self._manager = manager

    def __call__(self, query: str) -> str:
        if not self._manager:
            return "Memory not available."
        memories = self._manager.retrieve(query, top_k=5)
        if not memories:
            return "No relevant memories found."
        lines = [
            f'[memory: {m["type"]}] "{m["content"]}"'
            for m in memories
        ]
        return "\n".join(lines)


# Module-level singletons — required for multiprocessing pickle on macOS/Windows
_propose_memory = _ProposeMemory()
_complete_goal = _CompleteGoal()
_recall_memory = _RecallMemory()


def register_memory_tools(registry, loader) -> None:
    """Wire memory tools to the agent's memory manager and register them in the registry."""
    mgr = loader.memory_manager

    session_count = mgr.get_session_count()
    mgr.mark_stale_goals(session_count)
    mgr.archive_old_memories()
    mgr.enforce_caps()

    _propose_memory.set_manager(mgr)
    _complete_goal.set_manager(mgr)
    _recall_memory.set_manager(mgr)

    registry.register(
        "propose_memory",
        "REQUIRED: Persist a memory to permanent storage. "
        "Call this BEFORE your text reply whenever: the user states a preference "
        "(memory_type='preference'), corrects you (memory_type='correction'), "
        "shares a goal (memory_type='goal'), or you infer a durable fact "
        "(memory_type='fact'). Without this call the information is lost forever.",
        _propose_memory,
        True,
        {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The memory to store"
                },
                "memory_type": {
                    "type": "string",
                    "description": "Category: fact, preference, project_state, correction, or goal",
                    "default": "fact"
                },
                "valence": {
                    "type": "string",
                    "description": "Sentiment: positive, negative, or neutral",
                    "default": "neutral"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this is worth remembering"
                }
            },
            "required": ["content"]
        },
        is_mcp=True,
    )

    registry.register(
        "complete_goal",
        "Mark an active goal as complete. Call when the user signals a goal has "
        "been achieved — e.g. 'we're done', 'that's shipped', 'finished', "
        "'completed'. Matches the closest goal by semantic similarity.",
        _complete_goal,
        True,
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Description of what was just completed"
                }
            },
            "required": ["query"]
        },
        is_mcp=True,
    )

    registry.register(
        "recall_memory",
        "Search persistent memory for relevant context. "
        "Call this when the user references something not in the current "
        "conversation, asks what you know about a topic, or before making "
        "a decision that past context would improve.",
        _recall_memory,
        True,
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query"
                }
            },
            "required": ["query"]
        },
        is_mcp=True,
    )
