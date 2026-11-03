from agno.agent import Agent

from app.registry import models, tools

web_researcher = Agent(
    id="web-researcher",
    name="web-researcher",
    description="Researches public sources (offline stub in this runtime).",
    model=models.agnostic_mock,
    instructions="Search the web and summarise the three most relevant results.",
    tools=[
        tools.web_search,
    ],
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
)
