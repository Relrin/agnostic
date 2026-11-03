"""Git host API clients, chosen per connection."""

from __future__ import annotations

from agnostic_sources.application.ports import ProviderClient, ProviderError, Secrets
from agnostic_sources.domain.model import Connection
from agnostic_sources.infrastructure.http import SourcesHttp
from agnostic_sources.infrastructure.providers.gitea import GiteaClient
from agnostic_sources.infrastructure.providers.github import GitHubAppTokens, GitHubClient
from agnostic_sources.infrastructure.providers.gitlab import GitLabClient
from agnostic_sources.settings import SourcesSettings


class HttpProviderClients:
    def __init__(self, http: SourcesHttp, settings: SourcesSettings, tokens: GitHubAppTokens) -> None:
        self._http = http
        self._settings = settings
        self._tokens = tokens

    def client(self, connection: Connection, secrets: Secrets) -> ProviderClient:
        client = self._http.client
        match connection.provider:
            case "github":
                api = connection.api_url or self._settings.github_api_url
                web = connection.web_url or self._settings.github_web_url
                if connection.auth_kind == "github_app":
                    if not (secrets.app_id and secrets.private_key and connection.installation_id):
                        raise ProviderError("The GitHub App connection isn't installed yet.")
                    app = (secrets.app_id, secrets.private_key, connection.installation_id)
                    return GitHubClient(client, api, web, app=app, tokens=self._tokens)
                return GitHubClient(client, api, web, token=_token(secrets))
            case "gitlab":
                web = connection.web_url or "https://gitlab.com"
                return GitLabClient(client, connection.api_url or f"{web}/api/v4", web, _token(secrets))
            case "gitea" | "forgejo":
                if not connection.web_url:
                    raise ProviderError(f"The {connection.name} connection needs the server's URL.")
                web = connection.web_url
                api = connection.api_url or f"{web.rstrip('/')}/api/v1"
                return GiteaClient(client, api, web, _token(secrets), connection.provider)
            case "local":
                raise ProviderError("Local folders don't have a git host.")


def _token(secrets: Secrets) -> str:
    if not secrets.token:
        raise ProviderError("The connection has no token.")
    return secrets.token
