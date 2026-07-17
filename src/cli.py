import os

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from src.epub_parser import BookTracker, extract_text_from_epub
from src.rag_engine import index_new_book_content, query_book, sanitize_collection_name

console = Console()


def show_welcome():
    console.print(
        Panel(
            "[bold green]⚔️  LoreKeeper: Dynamic Book RAG CLI ⚔️[/bold green]\n"
            "[dim]Handles single releases, progressive chapters, and multi-part sagas seamlessly.[/dim]",
            border_style="magenta",
        )
    )


def execute_incremental_indexing():
    pending_files = BookTracker.scan_for_modified_or_new_files()
    if not pending_files:
        return

    console.print(
        f"\n[bold yellow]🔄 Found {len(pending_files)} new or structurally altered EPUB file(s). Processing deltas...[/bold yellow]"
    )

    for item in pending_files:
        filename = item["filename"]
        filepath = item["path"]
        status = item["status"]

        console.print(
            f"\n[bold cyan]File Target: {filename} ({status.upper()})[/bold cyan]"
        )
        existing_dbs = BookTracker.get_indexed_databases()
        collection_id = None
        db_name = None

        # Step A: Figure out collection target mapping
        if status == "updated":
            # Progressive file. Identify its existing database key automatically
            for db_key, db_meta in existing_dbs.items():
                if filepath in db_meta.get("tracked_files", {}):
                    collection_id = db_key
                    db_name = db_meta["database_name"]
                    console.print(
                        f"[dim cyan]→ Auto-detected progressive update for existing database: '{db_name}'[/dim cyan]"
                    )
                    break

        # Step B: If it's brand new text or multipart fallback check
        if not collection_id and existing_dbs:
            if Confirm.ask(
                "[yellow]Is this an extra installment or part belonging to an existing database series?[/yellow]"
            ):
                options = list(existing_dbs.items())
                table = Table(title="Available Series Databases")
                table.add_column("No.", justify="center", style="cyan")
                table.add_column("Database Target Profile", style="white")
                for i, (b_id, data) in enumerate(options, start=1):
                    table.add_row(str(i), data["database_name"])
                console.print(table)

                while not collection_id:
                    choice = Prompt.ask(
                        "[cyan]Select series slot number to merge data with[/cyan]"
                    )
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(options):
                            collection_id = options[idx][0]
                            db_name = options[idx][1]["database_name"]
                        else:
                            console.print("[red]Invalid slot registration.[/red]")
                    except ValueError:
                        console.print("[red]Numerical entry required.[/red]")

        # Step C: Fallback creation logic if standalone or totally new title
        if not collection_id:
            default_name = os.path.splitext(filename)[0]
            db_name = Prompt.ask(
                "[green]Create new database profile name[/green]", default=default_name
            )
            collection_id = sanitize_collection_name(db_name)

        # Step D: Extract text and filter index chunks dynamically
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task(
                description="Extracting text from document layers...", total=None
            )
            try:
                raw_text = extract_text_from_epub(filepath)

                # Fetch existing block hashes to prevent data duplication
                known_hashes = BookTracker.get_all_hashes_for_database(collection_id)
                progress.update(
                    task,
                    description=f"Analyzing data structures & mapping new fragments for '{db_name}'...",
                )

                # Indexes ONLY new text data chunks
                added_hashes = index_new_book_content(
                    collection_id, raw_text, known_hashes
                )

                # Update file tracker registry metadata records
                BookTracker.register_indexing_run(
                    collection_id, db_name, filepath, filename, added_hashes
                )

                console.print(
                    f"[bold green]✓ Processing Complete![/bold green] Added [bold white]{len(added_hashes)}[/bold white] new text blocks to '{db_name}'."
                )
            except Exception as e:
                console.print(
                    f"[bold red]✗ Pipeline processing failed for item {filename}: {e}[/bold red]"
                )


def list_and_select_database() -> str | None:
    databases = BookTracker.get_indexed_databases()
    if not databases:
        console.print(
            "[bold red]All database catalogs are empty. Place EPUB files into 'books/' to start indexing.[/bold red]"
        )
        return None

    table = Table(title="Active Vector Archives", border_style="cyan")
    table.add_column("No.", style="magenta", justify="center")
    table.add_column("Series Database Profile", style="white")
    table.add_column("Source Tracks Monitored", style="dim")

    db_keys = list(databases.keys())
    for i, db_key in enumerate(db_keys, start=1):
        meta = databases[db_key]
        sources = [
            f_meta["filename"] for f_meta in meta.get("tracked_files", {}).values()
        ]
        table.add_row(str(i), meta["database_name"], ", ".join(sources))

    console.print(table)

    selected_key = None
    while not selected_key:
        choice = Prompt.ask("[bold cyan]Load Database Entry Number[/bold cyan]")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(db_keys):
                selected_key = db_keys[idx]
                return selected_key
            else:
                console.print("[red]Invalid entry selection.[/red]")
        except ValueError:
            console.print("[red]Numerical input required.[/red]")
    return None


@click.command()
def start_cli():
    show_welcome()

    # Run structural pipeline analysis on boot
    execute_incremental_indexing()

    selected_db_key = list_and_select_database()
    if not selected_db_key:
        return

    db_meta = BookTracker.get_indexed_databases()[selected_db_key]
    console.print(
        Panel(
            f"[bold green]Connected to Matrix DB Layer:[/bold green] {db_meta['database_name']}",
            border_style="green",
        )
    )

    console.print(
        "\n[dim]Query environment online. Enter 'exit' to terminate session.[/dim]\n"
    )
    while True:
        question = Prompt.ask("[bold yellow]Query[/bold yellow]")
        if question.lower().strip() in ["exit", "quit"]:
            console.print(
                "[bold magenta]Closing terminal pipelines. Safe system logout confirmed.[/bold magenta]"
            )
            break

        if not question.strip():
            continue

        with console.status(
            "[cyan]Traversing local vectors and analyzing text fragments...[/cyan]"
        ):
            try:
                answer = query_book(selected_db_key, question)
                console.print(f"\n[bold green]Lore Engine Output:[/bold green]")
                console.print(answer)
                console.print("-" * 50 + "\n")
            except Exception as e:
                console.print(
                    f"[bold red]Pipeline Query Fault encountered: {e}[/bold red]"
                )
