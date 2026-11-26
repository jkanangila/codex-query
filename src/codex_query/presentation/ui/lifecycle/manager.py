"""Coordinates startup and orderly shutdown of the Flet application.

Manages lifecycle state transitions across the composition root and the UI
application ViewModel so concurrent start and shutdown calls serialize safely.
"""

from __future__ import annotations

import asyncio

from codex_query.di.bootstrap import CompositionRoot
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.presentation.ui.lifecycle.state import ApplicationState
from codex_query.presentation.ui.viewmodels.app_viewmodel import AppViewModel

logger = create_logger(__name__)


class ApplicationLifecycle:
    """Owns the UI application's CompositionRoot and AppViewModel lifecycle.

    Startup and shutdown are serialized by an internal lock. A shutdown request
    received while startup is in progress waits for startup to finish, then
    disposes resources once and transitions state to `STOPPED`.
    """

    def __init__(
        self,
        composition: CompositionRoot,
        *,
        shutdown_timeout: float = 5.0,
    ) -> None:
        """Initialize the lifecycle coordinator.

        Args:
            composition: Dependency composition root managing background jobs,
                events, and infrastructure resources.
            shutdown_timeout: Maximum time in seconds to wait for running
                background jobs to cancel during shutdown.

        Raises:
            ValueError: If `shutdown_timeout` is less than or equal to zero.
        """
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be greater than zero")

        self.composition = composition
        self.shutdown_timeout = shutdown_timeout
        self.state = ApplicationState.NEW
        self.view_model: AppViewModel | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> AppViewModel:
        """Start infrastructure and create the initialized application ViewModel.

        Transitions from `NEW` through `STARTING` to `RUNNING`. If startup raises,
        attempts best-effort shutdown before re-raising the exception.

        Returns:
            The initialized `AppViewModel` instance.

        Raises:
            RuntimeError: If called from a state other than `NEW` or `RUNNING`,
                or if `RUNNING` state lacks a `ViewModel`.
            BaseException: Propagates any exception raised while starting
                composition resources or creating the ViewModel.
        """
        async with self._lock:
            if self.state is ApplicationState.RUNNING:
                if self.view_model is None:
                    raise RuntimeError("Running lifecycle has no ViewModel")
                return self.view_model

            if self.state is not ApplicationState.NEW:
                raise RuntimeError(
                    f"Cannot start application from state {self.state.value!r}"
                )

            self.state = ApplicationState.STARTING
            logger.info("Starting application lifecycle.")

            try:
                await self.composition.start()
                self.view_model = await AppViewModel.create(self.composition)
                self.state = ApplicationState.RUNNING
                logger.info("Application lifecycle started successfully.")
                return self.view_model
            except BaseException:
                logger.exception("Application startup failed.")
                await self._shutdown_unlocked()
                raise

    async def shutdown(self) -> None:
        """Stop jobs and dispose application resources; safe to call repeatedly.

        Acquires the lifecycle lock so shutdown waits for any in-flight
        `start()` operation to complete before tearing down resources.
        """
        async with self._lock:
            await self._shutdown_unlocked()

    async def _shutdown_unlocked(self) -> None:
        """Perform shutdown steps while holding the lifecycle lock.

        Disposes the ViewModel, clears job event subscriptions, attempts timed
        cancellation of running background jobs, and closes infrastructure
        resources before marking the state as `STOPPED`.
        """
        if self.state is ApplicationState.STOPPED:
            return

        self.state = ApplicationState.STOPPING
        logger.info("Application shutdown started.")

        # Detach presentation listeners before cancelling jobs. A cancelled job
        # must not trigger UI updates while the page is being torn down.
        if self.view_model is not None:
            try:
                self.view_model.dispose()
            except Exception:
                logger.exception("Failed to dispose the application ViewModel.")
            finally:
                self.view_model = None

        # JobEvents owns the event channels, so clear them through that abstraction.
        try:
            self.composition.job_events.clear()
        except Exception:
            logger.exception("Failed to clear background-job event subscriptions.")

        # Job cancellation is best-effort. Infrastructure disposal must still run
        # when cancellation times out or raises.
        try:
            try:
                await asyncio.wait_for(
                    self.composition.job_runner.cancel_all(),
                    timeout=self.shutdown_timeout,
                )
            except TimeoutError:
                logger.warning(
                    "Background jobs did not stop within %.1f seconds.",
                    self.shutdown_timeout,
                )
            except Exception:
                logger.exception("An error occurred while cancelling background jobs.")
        finally:
            # Even task cancellation or a cancellation failure must not skip
            # disposal of database connections and other infrastructure resources.
            try:
                await self.composition.aclose()
            except Exception:
                logger.exception(
                    "Failed to close one or more infrastructure resources."
                )
            finally:
                self.state = ApplicationState.STOPPED
                logger.info("Application shutdown finished.")
