"""
Framework integrations for agent-audit.

Plug into popular agent frameworks with minimal code.
Currently supported: LangChain, custom agents.
"""

import time
import uuid
from dataclasses import dataclass

from .engine import AuditEngine
from .policy import PolicyEngine

# ═══════════════════════════════ LangChain Integration ═══════════════════════════════


def langchain_audit_callback(engine: AuditEngine, policy: PolicyEngine | None = None):
    """
    Returns a LangChain callback handler that automatically logs all agent activity.

    Usage:
        from agent_audit.integrations import langchain_audit_callback
        from agent_audit.engine import AuditEngine

        engine = AuditEngine("jsonl://./logs/my-agent")
        handler = langchain_audit_callback(engine)

        from langchain.agents import create_react_agent
        agent = create_react_agent(llm, tools, prompt)
        result = agent.invoke({"input": "..."}, config={"callbacks": [handler]})

    Requirements: pip install langchain-core
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:
        raise ImportError(
            "LangChain not installed. Run: pip install langchain-core"
        ) from None

    class AuditCallback(BaseCallbackHandler):
        def __init__(self):
            self.session_id = str(uuid.uuid4())[:12]
            self.prompt_version = "v1"

        def on_llm_start(self, serialized, prompts, **kwargs):
            for prompt in prompts:
                engine.log(
                    session_id=self.session_id,
                    event_type="model_request",
                    agent_id="langchain-agent",
                    prompt_version=self.prompt_version,
                    input_text=str(serialized.get("name", "llm"))[:500],
                    output_text=str(prompt)[:500],
                )

        def on_tool_start(self, serialized, input_str, **kwargs):
            engine.log(
                session_id=self.session_id,
                event_type="tool_call",
                agent_id="langchain-agent",
                prompt_version=self.prompt_version,
                input_text=str(input_str)[:2000],
                output_text=f"CALL: {serialized.get('name', 'unknown')}",
            )

        def on_tool_end(self, output, **kwargs):
            engine.log(
                session_id=self.session_id,
                event_type="tool_result",
                agent_id="langchain-agent",
                prompt_version=self.prompt_version,
                input_text="",
                output_text=str(output)[:2000],
            )

        def on_agent_action(self, action, **kwargs):
            # Policy check before executing
            if policy:
                result = policy.evaluate(
                    event_type="tool_call",
                    input_snapshot=action.tool_input
                    if hasattr(action, "tool_input")
                    else str(action),
                    output_snapshot=f"CALL: {action.tool}",
                    session_id=self.session_id,
                    agent_id="langchain-agent",
                    prompt_version=self.prompt_version,
                )
                if result.blocked:
                    raise PermissionError(f"Agent action blocked by policy: {result.reason}")

            engine.log(
                session_id=self.session_id,
                event_type="decision",
                agent_id="langchain-agent",
                prompt_version=self.prompt_version,
                input_text=f"Tool: {action.tool}",
                output_text=f"Input: {str(action.tool_input)[:2000]}",
            )

        def on_agent_finish(self, finish, **kwargs):
            engine.log(
                session_id=self.session_id,
                event_type="agent_finish",
                agent_id="langchain-agent",
                prompt_version=self.prompt_version,
                input_text="",
                output_text=str(finish.return_values)[:3000],
            )

    return AuditCallback()


# ═══════════════════════════════ Generic Agent Wrapper ═══════════════════════════════


@dataclass
class AuditedAgent:
    """
    Wrapper that adds audit logging + policy checks to ANY agent function.

    Usage:
        engine = AuditEngine("jsonl://./logs/my-agent")
        policy = PolicyEngine()

        audited = AuditedAgent(
            agent_fn=my_agent.run,
            engine=engine,
            policy=policy,
            agent_id="refund-bot",
            prompt_version="v3",
        )

        result = audited.invoke("User wants a refund of $45")

        # Verify everything was logged correctly
        engine.verify()
    """

    agent_fn: callable
    engine: AuditEngine
    agent_id: str = "default-agent"
    prompt_version: str = "v1"
    policy: PolicyEngine | None = None

    def invoke(self, input_text: str) -> str:
        """Run the agent with full audit logging and policy checks."""
        session_id = str(uuid.uuid4())[:12]
        start = time.time()

        # Log the incoming request
        self.engine.log(
            session_id=session_id,
            event_type="request",
            agent_id=self.agent_id,
            prompt_version=self.prompt_version,
            input_text=input_text[:3000],
            output_text="",
        )

        # Run the agent
        try:
            output = self.agent_fn(input_text)
        except Exception as e:
            self.engine.log(
                session_id=session_id,
                event_type="error",
                agent_id=self.agent_id,
                prompt_version=self.prompt_version,
                input_text=input_text[:500],
                output_text=f"ERROR: {e}",
            )
            raise

        elapsed = time.time() - start

        # Policy check on output
        policy_blocked = False
        if self.policy:
            result = self.policy.evaluate(
                event_type="decision",
                input_snapshot=input_text[:500],
                output_snapshot=output[:2000],
                session_id=session_id,
                agent_id=self.agent_id,
                prompt_version=self.prompt_version,
            )
            if result.blocked:
                policy_blocked = True
                output = f"[BLOCKED by policy: {result.reason}]"

        # Log the response
        self.engine.log(
            session_id=session_id,
            event_type="response",
            agent_id=self.agent_id,
            prompt_version=self.prompt_version,
            input_text=input_text[:500],
            output_text=output[:3000],
            metadata={
                "elapsed_ms": round(elapsed * 1000, 1),
                "policy_blocked": policy_blocked,
            },
        )

        return output
