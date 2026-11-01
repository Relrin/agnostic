"""Module declaration: the command-palette search index."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_kernel.modules import BaseModule, JobSpec, RouterSpec
from agnostic_search import jobs
from agnostic_search.api.router import router
from agnostic_search.infrastructure.tables import SearchBase
from agnostic_search.providers import SearchModuleProvider
from agnostic_search.settings import SearchSettings


class SearchModule(BaseModule):
    name = "search"
    version = "0.1.0"
    depends_on = ("instances",)

    def settings_model(self) -> type[BaseSettings] | None:
        return SearchSettings

    def provide(self) -> Iterable[Provider]:
        return (SearchModuleProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, tags=("search",)),)

    def metadata(self) -> MetaData | None:
        return SearchBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def jobs(self) -> Iterable[JobSpec]:
        cron = SearchSettings().reindex_cron
        return (JobSpec(name=jobs.REINDEX_TASK, func=jobs.reindex_all, queue="default", periodic=cron or None),)
