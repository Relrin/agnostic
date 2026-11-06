"""Git host API clients, chosen per connection."""

from __future__ import annotations

from urllib.parse import urlsplit

from agnostic_sources.application.ports import GitRepo, ProviderClient, ProviderError, Secrets
from agnostic_sources.domain.model import PROVIDER_LABEL, Connection
from agnostic_sources.infrastructure.http import SourcesHttp
from agnostic_sources.infrastructure.providers.deploy_key import DeployKeyClient
from agnostic_sources.infrastructure.providers.gitea import GiteaClient
from agnostic_sources.infrastructure.providers.github import GitHubAppTokens, GitHubClient
from agnostic_sources.infrastructure.providers.gitlab import GitLabClient
from agnostic_sources.settings import SourcesSettings

GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})


class HttpProviderClients:
    def __init__(
        self, http: SourcesHttp, settings: SourcesSettings, tokens: GitHubAppTokens, git: GitRepo | None = None
    ) -> None:
        self._http = http
        self._settings = settings
        self._tokens = tokens
        self._git = git

    def client(self, connection: Connection, secrets: Secrets) -> ProviderClient:
        if connection.auth_kind == "deploy_key" and connection.provider != "local":
            if not secrets.private_key:
                raise ProviderError("The connection has no deploy key.")
            return DeployKeyClient(
                self._git,
                self.web_url(connection),
                secrets.private_key,
                PROVIDER_LABEL.get(connection.provider, connection.provider),
            )
        client = self._http.client
        match connection.provider:
            case "github":
                web = self.web_url(connection)
                default = self._settings.github_api_url
                api = connection.api_url or (github_api_url(web, default) if connection.web_url else default)
                if connection.auth_kind == "github_app":
                    if not (secrets.app_id and secrets.private_key and connection.installation_id):
                        raise ProviderError("The GitHub App connection isn't installed yet.")
                    app = (secrets.app_id, secrets.private_key, connection.installation_id)
                    return GitHubClient(client, api, web, app=app, tokens=self._tokens)
                return GitHubClient(client, api, web, token=_token(secrets))
            case "gitlab":
                web = self.web_url(connection)
                return GitLabClient(client, connection.api_url or f"{web}/api/v4", web, _token(secrets))
            case "gitea" | "forgejo":
                web = self.web_url(connection)
                api = connection.api_url or f"{web}/api/v1"
                return GiteaClient(client, api, web, _token(secrets), connection.provider)
            case "local":
                raise ProviderError("Local folders don't have a git host.")

    def web_url(self, connection: Connection) -> str:
        match connection.provider:
            case "github":
                return (connection.web_url or self._settings.github_web_url).rstrip("/")
            case "gitlab":
                return (connection.web_url or "https://gitlab.com").rstrip("/")
            case _:
                if not connection.web_url:
                    raise ProviderError(f"The {connection.name} connection needs the server's URL.")
                return connection.web_url.rstrip("/")


def github_api_url(web_url: str, default: str) -> str:
    """github.com's API is ``api.github.com``; GitHub Enterprise Server serves it under ``/api/v3``."""
    host = (urlsplit(web_url).hostname or "").lower()
    if not host or host in GITHUB_HOSTS:
        return default
    return f"{web_url.rstrip('/')}/api/v3"


def _token(secrets: Secrets) -> str:
    if not secrets.token:
        raise ProviderError("The connection has no token.")
    return secrets.token
