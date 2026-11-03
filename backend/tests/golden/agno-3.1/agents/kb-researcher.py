from agno.agent import Agent

from app.registry import models, tools

kb_researcher = Agent(
    id="kb-researcher",
    name="kb-researcher",
    description="Finds answers in the help-center knowledge base.",
    model=models.agnostic_mock,
    instructions="Search the knowledge base and cite the article you used.",
    tools=[
        tools.search_knowledge,
    ],
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
)
