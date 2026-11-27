"""Settings: show, edit interactively, test connections."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import click
import questionary
from rich.markup import escape

from codex_query.domain.errors import ProviderConfigurationError
from codex_query.domain.models.connection import Endpoint
from codex_query.domain.models.provider import (
    CHAT_PROVIDER_CONFIGS,
    EMBEDDING_PROVIDER_CONFIGS,
    EndpointConfig,
    LLMProvider,
)
from codex_query.domain.models.settings import PRESETS, PresetMode, Settings
from codex_query.presentation.cli.indexing import reindex_books
from codex_query.presentation.cli.prompts import Cancelled, ask, confirm
from codex_query.presentation.cli.render import settings_panel
from codex_query.presentation.cli.runtime import Ctx
from codex_query.presentation.ui.utils.formatting import build_test_result_text

_CONFIGS: dict[Endpoint, dict[LLMProvider, EndpointConfig]] = {
    "chat": dict(CHAT_PROVIDER_CONFIGS),
    "embedding": dict(EMBEDDING_PROVIDER_CONFIGS),
}


@dataclass(frozen=True, slots=True)
class _Tuning:
    key: str
    label: str
    low: float
    high: float
    integer: bool


_TUNING = (
    _Tuning("temperature", "Temperature", 0.0, 1.0, False),
    _Tuning("max_tokens", "Max answer tokens", 100, 4000, True),
    _Tuning("top_k", "Passages per question (top-k)", 1, 12, True),
    _Tuning("num_ctx", "Context window", 2048, 32768, True),
    _Tuning(
        "chunk_size", "Chunk size (applies to newly indexed books)", 200, 2000, True
    ),
)


def show_settings(ctx: Ctx) -> None:
    """Print the current settings."""
    settings = ctx.uc.settings.get_current()
    keys = ctx.comp.api_keys_repository
    ctx.console.print(
        settings_panel(
            settings,
            keys.source(settings.chat.provider),
            keys.source(settings.embedding.provider),
        )
    )


async def test_connections(ctx: Ctx, endpoints: Sequence[Endpoint]) -> bool:
    """Probe the configured endpoints. Returns ``True`` if all are healthy."""
    settings = ctx.uc.settings.get_current()
    healthy = True
    for endpoint in endpoints:
        service = settings.chat if endpoint == "chat" else settings.embedding
        label = f"{endpoint} · {service.provider.value} · {service.model}"
        with ctx.console.status(f"Testing {escape(label)}…"):
            result = await ctx.uc.settings.test_model_connection(service, endpoint)
        healthy &= result.ok
        style = "green" if result.ok else "red"
        extra = (
            f" [dim]({result.embedding_dimension} dimensions)[/]"
            if result.embedding_dimension
            else ""
        )
        ctx.console.print(
            f"[{style}]{endpoint:<10}[/] "
            f"{escape(build_test_result_text(result))}{extra}"
        )
    return healthy


async def _save(ctx: Ctx, mutate: Callable[[Settings], None]) -> None:
    draft = ctx.uc.settings.get_new_draft()
    mutate(draft)
    await ctx.uc.settings.update_settings(draft)


async def _save_embedding(ctx: Ctx, mutate: Callable[[Settings], None]) -> None:
    """Save an embedding change; offer to re-index books it makes stale."""
    current = ctx.uc.settings.get_current().embedding
    draft = ctx.uc.settings.get_new_draft()
    mutate(draft)
    changed = (draft.embedding.provider, draft.embedding.model) != (
        current.provider,
        current.model,
    )
    stale = (
        list(
            await ctx.uc.settings.check_embedding_compatibility(
                draft.embedding.provider, draft.embedding.model
            )
        )
        if changed
        else []
    )
    if stale:
        ctx.console.print(
            f"[yellow]Changing the embedding model makes {len(stale)} book(s) "
            "unsearchable until they are re-indexed:[/]"
        )
        for book in stale:
            ctx.console.print(f"  • {escape(book.title)}")
        if not await confirm("Apply the change and re-index them now?"):
            ctx.console.print("[dim]Settings unchanged.[/]")
            return
    await ctx.uc.settings.update_settings(draft)
    if stale:
        await reindex_books(ctx, [b.id for b in stale if b.id is not None])


def _provider_choices(endpoint: Endpoint) -> list[questionary.Choice]:
    return [
        questionary.Choice(config.name, provider)
        for provider, config in _CONFIGS[endpoint].items()
    ]


async def _edit_provider(ctx: Ctx, endpoint: Endpoint) -> None:
    provider: LLMProvider = await ask(
        questionary.select(
            f"{endpoint.title()} provider", choices=_provider_choices(endpoint)
        )
    )
    if endpoint == "chat":

        def apply_chat(s: Settings) -> None:
            s.select_chat_provider(provider)

        await _save(ctx, apply_chat)
    else:

        def apply_embedding(s: Settings) -> None:
            s.select_embedding_provider(provider)

        await _save_embedding(ctx, apply_embedding)


async def _edit_text(ctx: Ctx, endpoint: Endpoint, field: str) -> None:
    settings = ctx.uc.settings.get_current()
    service = settings.chat if endpoint == "chat" else settings.embedding
    value: str = await ask(
        questionary.text(
            f"{endpoint.title()} {'model' if field == 'model' else 'base URL'}",
            default=getattr(service, field),
        )
    )
    value = value.strip()
    if not value:
        return

    def apply(s: Settings) -> None:
        target = s.chat if endpoint == "chat" else s.embedding
        setattr(target, field, value)

    if endpoint == "chat":
        await _save(ctx, apply)
    else:
        await _save_embedding(ctx, apply)


async def _edit_key(ctx: Ctx, endpoint: Endpoint) -> None:
    settings = ctx.uc.settings.get_current()
    service = settings.chat if endpoint == "chat" else settings.embedding
    config = _CONFIGS[endpoint].get(service.provider)
    if config is not None and not config.auth.api_key_required:
        ctx.console.print("[dim]This provider does not need an API key.[/]")
        return
    key: str = await ask(
        questionary.password(
            f"{service.provider.value} API key (empty to keep current)"
        )
    )
    key = key.strip()
    if not key:
        return

    def apply(s: Settings) -> None:
        this = s.chat if endpoint == "chat" else s.embedding
        other = s.embedding if endpoint == "chat" else s.chat
        this.api_key = key
        if other.provider == this.provider and not other.has_api_key:
            other.api_key = key

    await _save(ctx, apply)
    source = ctx.comp.api_keys_repository.source(service.provider)
    if source == "env":
        ctx.console.print(
            "[yellow]An API key environment variable is set and takes precedence "
            "over the saved key.[/]"
        )


async def _edit_preset(ctx: Ctx) -> None:
    choices = [
        questionary.Choice(
            f"{mode.value.title()} (temp {p.temperature:g}, {p.max_tokens} tokens, "
            f"top-k {p.top_k}, ctx {p.num_ctx}, chunk {p.chunk_size})",
            mode,
        )
        for mode, p in PRESETS.items()
    ]
    mode: PresetMode = await ask(questionary.select("Preset", choices=choices))
    await _save(ctx, lambda s: s.select_preset(mode))


async def _edit_tuning(ctx: Ctx) -> None:
    settings = ctx.uc.settings.get_current()
    spec: _Tuning = await ask(
        questionary.select(
            "Which value?",
            choices=[
                questionary.Choice(f"{t.label}: {getattr(settings, t.key):g}", t)
                for t in _TUNING
            ],
        )
    )

    def check(text: str) -> bool | str:
        try:
            number = float(text)
        except ValueError:
            return "Enter a number."
        if not spec.low <= number <= spec.high:
            return f"Enter a value between {spec.low:g} and {spec.high:g}."
        return True

    raw: str = await ask(
        questionary.text(
            f"{spec.label} ({spec.low:g}-{spec.high:g})",
            default=f"{getattr(settings, spec.key):g}",
            validate=check,
        )
    )
    number = float(raw)
    value: float | int = int(number) if spec.integer else number

    def apply(s: Settings) -> None:
        setattr(s, spec.key, value)
        s.select_preset(PresetMode.CUSTOM)

    await _save(ctx, apply)


async def settings_screen(ctx: Ctx) -> None:
    """The UI's settings tab as a menu."""
    while True:
        show_settings(ctx)
        action: str = await ask(
            questionary.select(
                "Edit",
                choices=[
                    questionary.Choice("Chat provider", "chat_provider"),
                    questionary.Choice("Chat model", "chat_model"),
                    questionary.Choice("Chat base URL", "chat_base_url"),
                    questionary.Choice("Chat API key", "chat_key"),
                    questionary.Separator(),
                    questionary.Choice("Embedding provider", "embedding_provider"),
                    questionary.Choice("Embedding model", "embedding_model"),
                    questionary.Choice("Embedding base URL", "embedding_base_url"),
                    questionary.Choice("Embedding API key", "embedding_key"),
                    questionary.Separator(),
                    questionary.Choice("Preset (quality / balanced / low)", "preset"),
                    questionary.Choice("Fine tuning", "tuning"),
                    questionary.Choice("Test connections", "test"),
                    questionary.Choice("Back", "back"),
                ],
            )
        )
        if action == "back":
            return
        try:
            match action:
                case "chat_provider":
                    await _edit_provider(ctx, "chat")
                case "chat_model":
                    await _edit_text(ctx, "chat", "model")
                case "chat_base_url":
                    await _edit_text(ctx, "chat", "base_url")
                case "chat_key":
                    await _edit_key(ctx, "chat")
                case "embedding_provider":
                    await _edit_provider(ctx, "embedding")
                case "embedding_model":
                    await _edit_text(ctx, "embedding", "model")
                case "embedding_base_url":
                    await _edit_text(ctx, "embedding", "base_url")
                case "embedding_key":
                    await _edit_key(ctx, "embedding")
                case "preset":
                    await _edit_preset(ctx)
                case "tuning":
                    await _edit_tuning(ctx)
                case "test":
                    await test_connections(ctx, ("chat", "embedding"))
                case _:
                    pass
        except Cancelled:
            continue  # dismissed a sub-prompt: back to the menu
        except ProviderConfigurationError as exc:
            ctx.console.print(f"[red]{escape(str(exc))}[/]")


def require_endpoints(which: str) -> tuple[Endpoint, ...]:
    """Map the ``settings test`` argument to endpoints."""
    match which:
        case "chat":
            return ("chat",)
        case "embedding":
            return ("embedding",)
        case "all":
            return ("chat", "embedding")
        case _:
            pass
    msg = f"Unknown endpoint {which!r}"
    raise click.BadParameter(msg)
