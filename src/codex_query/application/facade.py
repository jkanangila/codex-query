from dataclasses import dataclass

from codex_query.application.use_cases.settings.apply_budget_preset import (
    ApplyBudgetPreset,
)
from codex_query.application.use_cases.settings.check_embedding_compatibility import (
    CheckEmbeddingCompatibility,
)
from codex_query.application.use_cases.settings.get_draft import GetDraftSettings
from codex_query.application.use_cases.settings.get_settings import GetCurrentSettings
from codex_query.application.use_cases.settings.test_model_connection import (
    TestConnection,
)
from codex_query.application.use_cases.settings.update_settings import UpdateSettings


@dataclass(frozen=True, slots=True)
class ChatFacade:
    ask_question: object
    get_source_passage: object


@dataclass(frozen=True, slots=True)
class IndexingJobsFacade:
    cancel: object
    complete_indexing: object
    list_indexing_jobs: object
    pause: object
    recover_interrupted_jobs: object
    reindex_book: object
    resume: object
    start: object
    submit_book: object


@dataclass(frozen=True, slots=True)
class LibraryFacade:
    delete_book: object
    get_book: object
    list_books: object
    rename_book: object
    search_books: object
    select_ask_scope: object


@dataclass(frozen=True, slots=True)
class SettingsFacade:
    apply_budget_preset: ApplyBudgetPreset
    check_embedding_compatibility: CheckEmbeddingCompatibility
    get_current: GetCurrentSettings
    get_new_draft: GetDraftSettings
    test_model_connection: TestConnection
    update_settings: UpdateSettings


@dataclass(frozen=True, slots=True)
class UseCases:
    settings: SettingsFacade
    # TODO: remove None when Facades ready
    chat: ChatFacade | None = None
    indexing_jobs: IndexingJobsFacade | None = None
    library: LibraryFacade | None = None
