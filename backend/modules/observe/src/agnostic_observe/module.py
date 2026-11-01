"""Module declaration: the Home overview."""

from __future__ import annotations

from collections.abc import Iterable

from dishka import Provider
from pydantic_settings import BaseSettings

from agnostic_kernel.modules import BaseModule, JobSpec, RouterSpec
from agnostic_observe import jobs
from agnostic_observe.api.router import router
from agnostic_observe.providers import ObserveProvider
from agnostic_observe.settings import ObserveSettings


class ObserveModule(BaseModule):
    name = "observe"
    version = "0.1.0"
    depends_on = ("access", "audit", "instances")

    def settings_model(self) -> type[BaseSettings] | None:
        return ObserveSettings

    def provide(self) -> Iterable[Provider]:
        return (ObserveProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/instances", tags=("observe",)),)

    def jobs(self) -> Iterable[JobSpec]:
        cron = ObserveSettings().warm_cron
        return (JobSpec(name=jobs.WARM_TASK, func=jobs.warm_overviews, queue="default", periodic=cron or None),)
