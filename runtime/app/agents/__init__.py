"""Code-defined agents (path mapping: app/agents/*.py)."""

from app.agents.billing_agent import billing_agent
from app.agents.kb_researcher import kb_researcher
from app.agents.qa_reviewer import qa_reviewer
from app.agents.summarizer import summarizer
from app.agents.support_triage import support_triage
from app.agents.web_researcher import web_researcher

AGENTS = [support_triage, billing_agent, kb_researcher, qa_reviewer, web_researcher, summarizer]
