# Codex Query

Ask questions about your own EPUB library, privately, on your own hardware.

Codex Query indexes your books with an embedding model and answers questions about them using retrieval-augmented generation (RAG). It runs fully offline with local models through [Ollama](https://ollama.com), or you can plug in a commercial provider with your own API key.

## Features

- Index EPUBs through a file picker and give each book a name
- Ask questions about any indexed book
- Book series support (book 1, 2, 3, ...)
- Pause and resume indexing, with progress reporting
- Local-first: Ollama for chat and embeddings, no data leaves your machine
- Optional providers via HTTP adapters (OpenAI, Anthropic, Gemini, Mistral, Cohere), with chat and embeddings configured separately
- API keys stored in the platform's secure storage
- Runs as a desktop and mobile app (Flet) or as a CLI

## Download

Grab the latest build from the [Releases](../../releases) page.

| Platform | File              | Notes                                                                                                         |
| -------- | ----------------- | ------------------------------------------------------------------------------------------------------------- |
| Windows  | `*-windows.zip`   | Unzip and run the `.exe`. SmartScreen may warn: _More info → Run anyway_.                                     |
| macOS    | `*-macos.zip`     | Apple Silicon only. The app is unsigned: right-click → _Open_, or run `xattr -dr com.apple.quarantine <app>`. |
| Linux    | `*-linux.tar.gz`  | Needs `libsecret` installed (`libsecret-1-0` on Debian/Ubuntu, `libsecret` on Arch).                          |
| Android  | `*-android-*.apk` | Sideload. Most phones want the `arm64-v8a` APK.                                                               |

## Setup

1. Install [Ollama](https://ollama.com) and pull a chat model and an embedding model, or add a provider API key in the app's settings.
2. Open the app, go to **Settings**, and choose your model names and URL.
3. Add a book and start asking questions.

## Run from source

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/jkanangila/codex-query.git
cd codex-query
uv sync --extra desktop      # includes ChromaDB for desktop
uv run codex-query-ui        # Flet UI
uv run codex-query --help    # CLI
```

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format .
uv run basedpyright
```

The code follows a layered (clean) architecture: `domain`, `application` (use cases), `infrastructure` (providers, persistence, vector stores) and `presentation` (CLI and Flet UI). Only the infrastructure layer knows about specific providers or storage engines.

Vector storage differs by platform: ChromaDB on desktop, NumPy plus SQLite on mobile.

## Releasing

Bump `version` in `pyproject.toml`, run `uv lock`, and push to `main`. The [release workflow](.github/workflows/release.yml) builds every platform and publishes a GitHub release tagged `v<version>`.

## License

MIT
