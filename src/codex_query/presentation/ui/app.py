from __future__ import annotations

import asyncio
from pathlib import Path
from queue import Queue

import flet as ft
from dotenv import load_dotenv

from codex_query.application.config import Settings
from codex_query.application.services import ProgressEvent
from codex_query.bootstrap import build_services
from codex_query.infrastructure.logging.config import asyncio_handler, configure_logging
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.rag.utils import get_ollama_base_url
from codex_query.presentation.ui.utils.update_control import update_controls

load_dotenv()
logger = create_logger(__name__)


async def _main(page: ft.Page) -> None:
    """Build and manage the Flet GUI lifecycle."""
    asyncio.get_running_loop().set_exception_handler(asyncio_handler)
    # Configure main UI window properties
    page.title = "Codex Query"
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.on_error = lambda e: logger.error("Flet error: %s", e.data)

    async def pick_directory(e: ft.Event[ft.IconButton]) -> None:
        path = await directory_picker.get_directory_path(
            dialog_title="Select the directory where the series is located"
        )
        if path is not None:
            books_field.value = path
            books_field.update()

    directory_picker = ft.FilePicker()
    books_field = ft.TextField(
        label="EPUB directory",
        expand=True,
        suffix=ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            on_click=pick_directory,
            tooltip="Select directory",
            visible=True,
        ),
    )

    data_field = ft.TextField(label="Data directory", value=".codex-query", expand=True)
    series_field = ft.TextField(label="Series", expand=True)
    question_field = ft.TextField(
        label="Question", multiline=True, min_lines=2, expand=True
    )
    answer = ft.Markdown("Index a series, then ask a question.")
    progress_bar = ft.ProgressBar(value=0, visible=False)
    phase = ft.Text("Idle")
    counters = ft.Text("")
    log_view = ft.ListView(height=220, spacing=2, auto_scroll=True)
    busy = ft.ProgressRing(visible=False)

    async def consume_events(queue: Queue[ProgressEvent]) -> None:
        while True:
            try:
                event = queue.get_nowait()
            except Exception:
                await asyncio.sleep(0.08)
                continue
            phase.value = event.message
            progress_bar.value = event.current / event.total if event.total else 0
            counters.value = (
                f"{event.current}/{event.total} {event.unit} — {event.percent:.1f}%"
                if event.total
                else event.unit
            )
            log_view.controls.append(
                ft.Text(f"[{event.phase}] {event.message}", size=12)
            )
            if len(log_view.controls) > 300:
                del log_view.controls[:-300]

            update_controls([phase, progress_bar, counters, log_view])

    async def run_index(e: ft.Event[ft.Button]) -> None:
        event_queue: Queue[ProgressEvent] = Queue()
        progress_bar.visible = True
        busy.visible = True
        phase.value = "Starting…"
        log_view.controls.clear()
        page.update()
        monitor = asyncio.create_task(consume_events(event_queue))
        try:
            settings = Settings.from_data_dir(
                Path(data_field.value or ".codex-query"), get_ollama_base_url()
            )

            def report(event: ProgressEvent) -> None:
                event_queue.put(event)

            indexer, _, ledger = build_services(settings, report)
            try:
                result = await asyncio.to_thread(
                    indexer.index_series,
                    series_field.value or "default",
                    Path(books_field.value or "."),
                    report,
                )
            finally:
                ledger.close()
            phase.value = "Complete"
            counters.value = f"{result.chapters_indexed} indexed · {
                result.chapters_skipped
            } skipped · {result.chunks_indexed} chunks · {result.failures} failures"
            log_view.controls.append(
                ft.Text("[complete] Indexing finished", weight=ft.FontWeight.BOLD)
            )
        except Exception as exc:
            logger.exception("UI indexing failed")
            phase.value = f"Error: {exc}"
            log_view.controls.append(ft.Text(f"[error] {exc}"))
        finally:
            monitor.cancel()
            progress_bar.visible = False
            busy.visible = False
            page.update()

    async def run_query(e: ft.Event[ft.Button]) -> None:
        queue: Queue[ProgressEvent] = Queue()
        progress_bar.visible = True
        busy.visible = True
        phase.value = "Starting query…"
        page.update()
        monitor = asyncio.create_task(consume_events(queue))
        try:
            settings = Settings.from_data_dir(
                Path(data_field.value or ".codex-query"), get_ollama_base_url()
            )

            def report(event: ProgressEvent) -> None:
                queue.put(event)

            _, query, ledger = build_services(settings, report)
            try:
                result = await asyncio.to_thread(
                    query.ask,
                    series_field.value or "default",
                    question_field.value or "",
                )
            finally:
                ledger.close()
            answer.value = result.answer
            phase.value = (
                f"Answer generated from {len(result.sources)} retrieved passages"
            )
        except Exception as exc:
            logger.exception("UI query failed")
            answer.value = f"**Error:** {exc}"
            phase.value = f"Error: {exc}"
        finally:
            monitor.cancel()
            progress_bar.visible = False
            busy.visible = False
            page.update()

    page.add(
        ft.ResponsiveRow(
            [
                ft.Container(data_field, col={"xs": 12, "md": 6}),
                ft.Container(series_field, col={"xs": 12, "md": 6}),
                ft.Container(books_field, col={"xs": 12, "md": 8}),
                ft.Container(
                    ft.Button("Index / Resume", on_click=run_index, elevation=2),
                    col={"xs": 12, "md": 4},
                ),
                ft.Container(question_field, col={"xs": 12}),
                ft.Container(
                    ft.Button("Ask", on_click=run_query, elevation=2),
                    col={"xs": 12, "md": 3},
                ),
                ft.Container(busy, col={"xs": 12, "md": 1}),
                ft.Container(phase, col={"xs": 12, "md": 8}),
                ft.Container(counters, col={"xs": 12}),
                ft.Container(progress_bar, col={"xs": 12}),
                ft.Container(
                    ft.Text("Activity", weight=ft.FontWeight.BOLD), col={"xs": 12}
                ),
                ft.Container(log_view, col={"xs": 12}),
                ft.Container(answer, col={"xs": 12}),
            ]
        )
    )


def main() -> None:
    """Application entry point to launch the Flet UI."""
    configure_logging()
    ft.run(_main)


if __name__ == "__main__":
    main()
