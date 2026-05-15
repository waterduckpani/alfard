"""Entry point for the alfard agent orchestration framework."""

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from alfard.audit.logger import AuditLogger
from alfard.llm.client import LLMClient

_CONFIG_PATH = Path(__file__).parent / "config" / "alfard.yaml"


def main():
    console = Console()

    try:
        if not _CONFIG_PATH.exists():
            console.print(Panel("Run setup first: python setup_alfard.py", style="red"))
            sys.exit(1)

        client = LLMClient()
        messages = [{"role": "user", "content": "Reply with exactly three words: alfard is ready"}]
        result = client.complete(messages)
        logger = AuditLogger()
        logger.log_llm_call(client.provider_name, client.model, len(messages), result)
        logger.close()
        console.print(result["content"])

    except RuntimeError as e:
        console.print(Panel(str(e), style="red"))
        sys.exit(1)


if __name__ == "__main__":
    main()
