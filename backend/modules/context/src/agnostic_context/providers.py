"""Dependency wiring of the context module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_context.application.calls import ContextCalls
from agnostic_context.application.files import FindFileProvenance
from agnostic_context.application.knowledge import ListContent, ListKnowledgeBases
from agnostic_context.application.learnings import DataSubjectRequest, DeleteUserLearnings, LearningCounts
from agnostic_context.application.memories import FindDuplicates, FindMemorySource, OptimizeMemories
from agnostic_context.settings import ContextSettings


class ContextProvider(Provider):
    scope = Scope.REQUEST

    calls = provide(ContextCalls)
    optimize = provide(OptimizeMemories)
    bases = provide(ListKnowledgeBases)
    learning_counts = provide(LearningCounts)
    delete_user = provide(DeleteUserLearnings)
    data_subject = provide(DataSubjectRequest)

    @provide
    def duplicates(self, calls: ContextCalls, settings: ContextSettings) -> FindDuplicates:
        return FindDuplicates(calls, settings.duplicate_threshold, settings.max_duplicate_scan)

    @provide
    def memory_source(self, calls: ContextCalls, settings: ContextSettings) -> FindMemorySource:
        return FindMemorySource(calls, settings.provenance_sessions)

    @provide
    def content(self, calls: ContextCalls, settings: ContextSettings) -> ListContent:
        return ListContent(calls, settings.max_content_pages)

    @provide
    def file_provenance(self, calls: ContextCalls, settings: ContextSettings) -> FindFileProvenance:
        return FindFileProvenance(calls, settings.provenance_traces)
