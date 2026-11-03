"""Functions Studio workflows may run as steps, evaluators or selectors (``Registry(functions=...)``).

A Studio-built workflow names them by ``__name__`` (``executor_ref``, or an evaluator of type ``function``), so each
is registered under the name the code uses. They return canned, deterministic answers.
"""

from agno.workflow import StepInput, StepOutput


def check_status(step_input: StepInput) -> StepOutput:
    """Look the ticket's symptoms up on the status page."""
    ticket = step_input.get_input_as_string() or ""
    outage = any(word in ticket.lower() for word in ("502", "down", "outage", "login"))
    status = "Partial outage on login (investigating since 10:41)." if outage else "All systems operational."
    return StepOutput(content=f"Status page: {status}")


def send_reply(step_input: StepInput) -> StepOutput:
    """Send the drafted reply to the customer (offline stub: nothing leaves the runtime)."""
    draft = str(step_input.previous_step_content or "").strip() or "Thanks for reaching out; we're on it."
    return StepOutput(content=f"Reply sent: {draft[:200]}")


def needs_escalation(step_input: StepInput) -> bool:
    """A Condition evaluator: escalate when the previous step asked for it."""
    return "ESCALATE" in str(step_input.previous_step_content or "")


ALL_FUNCTIONS = [check_status, send_reply, needs_escalation]
