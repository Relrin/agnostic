"""Code-defined teams (path mapping: app/teams/*.py)."""

from app.teams.escalation_team import escalation_team
from app.teams.onboarding_team import onboarding_team
from app.teams.research_team import research_team

TEAMS = [research_team, escalation_team, onboarding_team]
