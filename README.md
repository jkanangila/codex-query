# Codex Query

**Codex Query** is an offline, local Retrieval-Augmented Generation (RAG) application for EPUB
book collections. It is designed for CPU- and RAM-constrained environments such as an Ubuntu
chroot on Android.

It combines:

- **Python 3.12+** and `uv`
- **Clean Architecture** with dependency inversion
- **EbookLib + BeautifulSoup** for EPUB extraction
- **SQLite** as a durable indexing ledger
- **ChromaDB** as a persistent vector database
- **Ollama** for local embeddings and answer generation
- **Click + Questionary** for the CLI
- **Flet** for a responsive desktop/web/mobile-friendly UI
- **Ruff + basedpyright strict + pytest** for development

Everything required for retrieval and generation can remain on-device. Ollama exposes local
embedding and chat APIs; this project does not require a hosted vector database or hosted LLM.

## Architecture

```text
src/codex_query/
├── domain/
│   ├── models.py          # Entities/value objects
│   ├── ports.py           # Interfaces used by application layer
│   └── chunking.py        # Pure text chunking
├── application/
│   ├── config.py          # Runtime settings
│   ├── factory.py         # Composition root
│   └── services.py        # Index/query use cases
├── infrastructure/
│   ├── epub/reader.py     # EPUB adapter
│   ├── persistence/       # SQLite indexing ledger
│   └── rag/               # Chroma + Ollama adapters
└── presentation/
    ├── cli/app.py         # Click + Questionary
    └── ui/app.py          # Responsive Flet UI

```

The dependency direction is:

```text
presentation → application → domain
infrastructure ───────────→ domain

```

The domain/application layers do not import ChromaDB, Ollama, SQLite, EbookLib, Click, or Flet.

## Why SQLite + ChromaDB?

Chroma stores the vectors and source text needed for semantic retrieval. SQLite stores
**indexing state**, which is deliberately separate from the vector database.

The ledger tracks:

- book identity
- source EPUB path
- file fingerprint
- title/author
- every discovered chapter
- chapter content hash
- chapter status (`pending`, `indexing`, `indexed`, `failed`)
- the last indexing error

This gives Codex Query resumability without requiring a large in-memory manifest.

## Incremental indexing

The indexing unit is a **chapter**, not an entire EPUB.

For each EPUB:

1. The EPUB is read and document items are extracted.
2. Each chapter receives a stable `book_id + href` identity.
3. The normalized chapter text receives a SHA-256 content hash.
4. SQLite compares the current chapter hash with the previously indexed hash.
5. Unchanged/indexed chapters are skipped.
6. New or changed chapters are deleted from the series vector collection and re-indexed.
7. Chapters removed from an EPUB are removed from Chroma as stale chapters.
8. The ledger is committed after each successful chapter.

Chroma chunk IDs are deterministic. Therefore a process interruption after a vector write but
before the SQLite checkpoint does not create permanent duplicates: retrying performs an
`upsert` using the same IDs.

EbookLib supports EPUB2/EPUB3 and exposes document items through the EPUB book API.

## Series isolation

A series gets its own Chroma collection:

```text
series-wheel-of-time
series-discworld
series-foundation

```

Queries explicitly specify the series, so retrieval cannot accidentally mix books from another
series.

## Resource-conscious defaults

The defaults are intentionally conservative for an 8 GB-or-less machine:

```text
chunk size:       1800 characters
chunk overlap:     250 characters
embedding batch:     8 chunks
retrieval:           6 chunks
SQLite:            WAL + NORMAL synchronous mode
Chroma:           persistent local storage

```

Tune these in `application/config.py` if your device has more or less RAM.

## Prerequisites

### 1. Install Python 3.12 and uv

Install `uv` using the official installation method for your platform, then verify:

```bash
python3.12 --version
uv --version

```

### 2. Install and start Ollama

Install Ollama for your Ubuntu environment and make sure its local service is running.

Verify it:

```bash
curl [http://127.0.0.1:11434/api/tags](http://127.0.0.1:11434/api/tags)

```

### 3. Pull local models

The embedding model and generation model are independent:

```bash
ollama pull embeddinggemma
ollama pull gemma3:4b

```

`embeddinggemma` is used for semantic embeddings and `gemma3:4b` is the default answer model.
Ollama's current embedding API supports batch input, which Codex Query uses to reduce per-request
overhead.

For a smaller device, select a smaller local generation model and change
`Settings.generation_model` or add configuration of your own.

## Installation

From the project directory:

```bash
uv sync

```

Run the test suite:

```bash
uv run pytest

```

Run strict type checking:

```bash
uv run basedpyright

```

Run linting:

```bash
uv run ruff check .
uv run ruff format --check .

```

## CLI command reference

### Index a series

```bash
uv run codex-query index "My Series" --books ~/books/my-series

```

The first run creates:

```text
.codex-query/
├── chroma/
└── index.sqlite3

```

Run the exact same command later to perform an incremental update.

### Interactive indexing

```bash
uv run codex-query index

```

Questionary asks for the series name and EPUB directory.

### Ask a question

```bash
uv run codex-query ask "My Series" "Who first discovers the hidden city?"

```

Increase or reduce retrieval depth:

```bash
uv run codex-query ask "My Series" "What happened after the battle?" --limit 10

```

### Check indexing status

```bash
uv run codex-query status "My Series"

```

### Use another data directory

```bash
uv run codex-query index "My Series" --books ~/books/my-series --data ~/codex-data

```

The same `--data` directory must be used for subsequent queries and incremental updates.

## UI

Start the Flet interface with:

```bash
uv run codex-query-ui

```

The UI provides:

- data directory selection
- series selection
- EPUB directory
- incremental/resumable indexing
- question input
- retrieved-answer display
- responsive layout through Flet's `ResponsiveRow`

Flet can target desktop/web/mobile-style application surfaces from Python; the UI intentionally
keeps the domain and application layers independent of Flet.

## Organizing EPUBs

Recommended layout:

```text
~/books/
├── wheel-of-time/
│   ├── 01-the-eye-of-the-world.epub
│   ├── 02-the-great-hunt.epub
│   └── 03-the-dragon-reborn.epub
├── discworld/
│   ├── 01-the-colour-of-magic.epub
│   └── 02-the-light-fantastic.epub
└── foundation/
    └── 01-foundation.epub

```

Then index each directory as its own isolated series.

## Updating books

If a book receives new chapters:

```bash
uv run codex-query index "My Series" --books ~/books/my-series

```

Codex Query rereads the EPUB, computes chapter hashes, and only embeds changed/new chapters.

If an existing chapter changes, its previous vectors are deleted before the replacement chunks
are inserted.

If a chapter disappears from an EPUB, the corresponding Chroma vectors are removed.

## Recovery after interruption

You do not need a reset command.

Simply rerun the indexing command:

```bash
uv run codex-query index "My Series" --books ~/books/my-series

```

The SQLite ledger records successful chapters individually. Failed chapters remain retryable,
while deterministic vector IDs prevent repeated indexing from creating duplicate chunks.

## Offline/privacy model

After the software and Ollama models are installed, the normal RAG path is local:

```text
EPUB
  ↓
EbookLib
  ↓
SQLite ledger ─────────────┐
  ↓                        │
chapter hashing            │
  ↓                        │
chunking                   │
  ↓                        │
Ollama embeddings          │
  ↓                        │
ChromaDB                   │
  ↓                        │
semantic retrieval         │
  ↓                        │
Ollama local LLM           │
  ↓                        │
answer + sources           │

```

No cloud vector store is used. Ollama's documented local API exposes `/api/embed` for embeddings
and `/api/chat` for generation.

## Environment variables

`OLLAMA_HOST` overrides the default Ollama endpoint:

```bash
export OLLAMA_HOST=[http://127.0.0.1:11434](http://127.0.0.1:11434)

```

This is useful when Ollama is running outside the chroot or is exposed through a local bridge.

## Development

Install all development dependencies:

```bash
uv sync --all-groups

```

Format:

```bash
uv run ruff format .

```

Lint:

```bash
uv run ruff check .

```

Type check:

```bash
uv run basedpyright

```

Tests:

```bash
uv run pytest

```

Coverage:

```bash
uv run pytest --cov=codex_query --cov-report=term-missing

```

## Design notes for constrained Android/Ubuntu environments

- Keep the Chroma directory on fast local storage.
- Use a small embedding model rather than a large generation model for indexing.
- Keep `batch_size` small; embedding requests are batched but never load an entire book into
  the embedding request.
- Chapters are processed sequentially, so interrupted indexing loses at most the currently
  processing chapter.
- SQLite WAL makes small progress commits practical without rebuilding a large manifest.
- The application never needs to keep all EPUBs or all embeddings in RAM.
- Avoid putting the Chroma database on unreliable external/network storage.

## Current scope and extension points

The architecture deliberately leaves room for:

- configurable embedding/generation models
- hybrid lexical + vector retrieval
- reranking
- conversation memory scoped to a series
- streaming Ollama responses
- EPUB metadata filtering
- author/title filters
- Rich terminal progress bars
- background indexing jobs in the Flet UI
- import/export of the SQLite ledger
- backup/restore of Chroma and ledger state

Those features belong in application/infrastructure adapters rather than being coupled into
the domain.
