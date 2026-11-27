"""Ask questions about a book: one-shot or an interactive conversation."""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass, field

import questionary
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.spinner import Spinner

from codex_query.domain.models.chat import ChatMessage, Role
from codex_query.domain.models.document import Book
from codex_query.domain.models.rag import (
    Completed,
    Failed,
    FailureKind,
    SourceRef,
    SourcesFound,
    TextDelta,
)
from codex_query.presentation.cli.prompts import Cancelled, ask, pick_book
from codex_query.presentation.cli.render import sources_view
from codex_query.presentation.cli.runtime import Ctx, interruptible

_HELP = (
    "[bold]/new[/]      start a fresh conversation\n"
    "[bold]/sources[/]  show the passages behind the last answer\n"
    "[bold]/book[/]     switch to another book\n"
    "[bold]/help[/]     this help\n"
    "[bold]/quit[/]     leave (or press Ctrl-C)\n"
    "[dim]Ctrl-C while an answer is streaming stops just that answer.[/]"
)

_HINTS: dict[FailureKind, str] = {
    FailureKind.AUTH: "Update the key with: codex-query settings",
    FailureKind.INDEX_MISMATCH: "Re-index the book: codex-query reindex",
    FailureKind.INDEX_MISSING: "Re-index the book: codex-query reindex",
    FailureKind.UNAVAILABLE: "Check the endpoint with: codex-query settings test",
}


@dataclass(slots=True)
class _Stream:
    text: str = ""
    sources: list[SourceRef] = field(default_factory=list[SourceRef])
    failure: Failed | None = None


def _answer_panel(text: str) -> Panel:
    return Panel(
        Markdown(text), title="Answer", title_align="left", border_style="green"
    )


async def _answer(
    ctx: Ctx,
    book: Book,
    question: str,
    history: list[ChatMessage],
    *,
    show_sources: bool,
) -> list[SourceRef]:
    """Stream one answer. Returns the sources it was grounded in."""
    assert book.id is not None
    state = _Stream()

    async def consume(live: Live) -> None:
        assert book.id is not None
        events = ctx.uc.chat.ask_question(book.id, question, list(history))
        async with aclosing(events) as stream:
            async for event in stream:
                match event:
                    case SourcesFound(sources):
                        state.sources = sources
                        live.update(Spinner("dots", text="Writing the answer…"))
                    case TextDelta(token):
                        state.text += token
                        live.update(_answer_panel(state.text))
                    case Completed(full):
                        state.text = full
                        live.update(_answer_panel(full))
                    case Failed():
                        state.failure = event

    interrupted = False
    error: Exception | None = None
    with Live(
        Spinner("dots", text="Searching the book…"),
        console=ctx.console,
        refresh_per_second=12,
    ) as live:
        try:
            interrupted = await interruptible(consume(live)) is None
        except Exception as exc:
            error = exc
        if state.failure or error or (interrupted and not state.text):
            live.update("")

    if state.failure:
        ctx.console.print(
            Panel(
                escape(f"[{state.failure.kind.value}] {state.failure.message}"),
                title="Could not answer",
                title_align="left",
                border_style="red",
            )
        )
        if hint := _HINTS.get(state.failure.kind):
            ctx.console.print(f"[dim]{hint}[/]")
        return []
    if error:
        ctx.console.print(f"[red]Error:[/] {escape(str(error))}")
        return []
    if interrupted:
        ctx.console.print("[yellow]Stopped.[/]")
        return []
    if show_sources and state.sources:
        ctx.console.print(sources_view(state.sources))
    return state.sources


async def chat_screen(
    ctx: Ctx,
    book: Book,
    question: str | None = None,
    *,
    once: bool = False,
    show_sources: bool = True,
) -> None:
    """Conversation about ``book``. With ``once`` it answers and returns."""
    ctx.console.print(
        Panel.fit(
            f"[bold]{escape(book.title)}[/]\n[dim]"
            "Type a question · /help for commands[/]",
            border_style="cyan",
        )
    )
    history: list[ChatMessage] = []
    last_sources: list[SourceRef] = []
    pending = question

    while True:
        if pending is None:
            try:
                text: str = await ask(questionary.text("You", qmark=">"))
            except Cancelled:
                return
        else:
            text, pending = pending, None
        text = text.strip()
        if not text:
            continue

        if text.startswith("/"):
            command = text.lower().split()[0]
            if command in {"/quit", "/exit", "/back", "/q"}:
                return
            if command == "/help":
                ctx.console.print(_HELP)
            elif command == "/new":
                history.clear()
                last_sources = []
                ctx.console.print("[dim]Started a fresh conversation.[/]")
            elif command == "/sources":
                if last_sources:
                    ctx.console.print(sources_view(last_sources))
                else:
                    ctx.console.print("[dim]No sources yet.[/]")
            elif command == "/book":
                book = await pick_book(await ctx.books(), "Switch to")
                history.clear()
                last_sources = []
                ctx.console.print(f"Now asking about [bold]{escape(book.title)}[/]")
            else:
                ctx.console.print(f"[dim]Unknown command {escape(command)}[/]")
            continue

        last_sources = await _answer(
            ctx, book, text, history, show_sources=show_sources
        )
        # Like the UI, follow-ups only carry the user's earlier questions.
        history.append(ChatMessage(role=Role.USER, content=text))
        if once:
            return
