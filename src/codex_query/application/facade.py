from dataclasses import dataclass

from codex_query.application.use_cases.indexing.cancel_indexing import CancelIndexing
from codex_query.application.use_cases.indexing.pause_indexing import PauseIndexing
from codex_query.application.use_cases.indexing.recover_interrupted_jobs import (
    RecoverInterruptedJobs,
)
from codex_query.application.use_cases.indexing.reindex_book import ReindexDocument
from codex_query.application.use_cases.indexing.resume_indexing import ResumeIndexing
from codex_query.application.use_cases.indexing.start_indexing import StartIndexing
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
    cancel: CancelIndexing
    pause: PauseIndexing
    recover_interrupted_jobs: RecoverInterruptedJobs
    reindex_document: ReindexDocument
    resume: ResumeIndexing
    start: StartIndexing


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
    indexing: IndexingJobsFacade
    # TODO: remove None when Facades ready
    chat: ChatFacade | None = None
    library: LibraryFacade | None = None
