from agno.agent import Agent

from app.registry import memory, models, schemas, tools

golden_full_agent = Agent(
    id="golden-full-agent",
    name="Golden full agent",
    description="Exercises every serializable field Studio edits.",
    role="Triage incoming tickets",
    model=models.mock_precise,
    instructions=[
        "Classify the ticket.",
        "Escalate refunds over 100 to a human.",
    ],
    expected_output="A TriageResult.",
    additional_context="Customers on the gold tier get priority.",
    add_datetime_to_context=True,
    tools=[
        tools.lookup_order,
        tools.search_knowledge,
        tools.refund_customer,
    ],
    tool_call_limit=4,
    add_search_knowledge_instructions=True,
    memory_manager=memory.support_memory,
    enable_agentic_memory=True,
    update_memory_on_run=True,
    add_memories_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    enable_session_summaries=True,
    add_session_summary_to_context=True,
    read_chat_history=True,
    output_schema=schemas.TriageResult,
    markdown=True,
    session_state={
        "open_tickets": [],
        "tier": "gold",
    },
    add_session_state_to_context=True,
    enable_agentic_state=True,
    retries=2,
    store_events=True,
    metadata={
        "owner": "support",
    },
)
