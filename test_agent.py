import sys
from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from alfard.orchestrator.orchestrator import Orchestrator


def send_email(to: str, subject: str, body: str) -> str:
    return f"Email sent to {to} with subject '{subject}'."


if __name__ == "__main__":
    registry = ToolRegistry()
    registry.register(
        name="send_email",
        description="Send an email to a recipient.",
        function=send_email,
        reversible=False,
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject"
                },
                "body": {
                    "type": "string",
                    "description": "Email body"
                }
            },
            "required": ["to", "subject", "body"]
        }
    )

    llm = LLMClient()
    audit = AuditLogger()
    gate = ApprovalGate(audit_logger=audit)
    sandbox = SandboxExecutor()
    credentials = CredentialsManager()

    orchestrator = Orchestrator(
        llm=llm,
        registry=registry,
        audit=audit,
        gate=gate,
        sandbox=sandbox,
        credentials=credentials,
        system_prompt="You are a helpful assistant. Use tools when available."
    )

    print("\n--- Running agent ---\n")
    result = orchestrator.run("Send an email to bharat@example.com with subject 'Test' and body 'Hello from alfard.'")
    print(f"\n--- Agent response ---\n{result}")
    audit.close()
