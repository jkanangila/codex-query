import os

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from src.epub_parser import BookTracker, extract_text_from_epub
from src.rag_engine import index_new_book, query_book, sanitize_collection_name

console = Console()


def show_welcome():
    console.print(
        Panel(
            "[bold green]⚔️  LitRPG RAG Companion CLI ⚔️[/bold green]\n"
            "[dim]Read, track, and ask your offline AI anything about your library.[/dim]",
            border_style="magenta",
        )
    )


def check_and_index_new_books():
    new_epubs = BookTracker.get_unindexed_epubs()
    if not new_epubs:
        return

    console.print(
        f"\n[bold yellow]🔍 Found {len(new_epubs)} unindexed EPUB(s) in your books directory![/bold yellow]"
    )

    for filename, filepath in new_epubs:
        book_default_title = os.path.splitext(filename)[0]
        console.print(f"\n[bold cyan]Configuring: {book_default_title}[/bold cyan]")

        # Check if the user wants to merge this into an existing series/database
        existing_books = BookTracker.get_indexed_books()
        collection_id = None

        if existing_books and Confirm.ask(
            "[yellow]Add this book as an additional part/volume to an existing database?[/yellow]"
        ):
            # Show list of existing collections to pick from
            options = list(existing_books.items())
            table = Table(title="Select Target Database")
            table.add_column("No.", justify="center", style="cyan")
            table.add_column("Database Name", style="white")

            for i, (b_id, meta) in enumerate(options, start=1):
                table.add_row(str(i), meta["database_name"])
            console.print(table)

            selected_idx = None
            while selected_idx is None:
                choice = Prompt.ask(
                    "[cyan]Enter the database number to merge with[/cyan]"
                )
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(options):
                        selected_idx = idx
                        collection_id = options[idx][
                            0
                        ]  # Retrieve the existing collection key
                    else:
                        console.print("[red]Invalid selection.[/red]")
                except ValueError:
                    console.print("[red]Please enter a valid number.[/red]")

        # If starting a new collection
        if not collection_id:
            db_name = Prompt.ask(
                "[green]Enter database display name (e.g., 'Defiance of the Fall Series')[/green]",
                default=book_default_title,
            )
            collection_id = sanitize_collection_name(db_name)
        else:
            db_name = existing_books[collection_id]["database_name"]

        # Run parser with Rich progress overlay
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task(
                description=f"Extracting text from {filename}...", total=None
            )
            try:
                text = extract_text_from_epub(filepath)
                progress.update(
                    task,
                    description=f"Embedding and Indexing into database '{db_name}'...",
                )

                # Append chunks into the shared vector database collection
                index_new_book(collection_id, text)
                file_hash = BookTracker.calculate_file_hash(filepath)

                # Register under tracker file
                BookTracker.register_book(filename, file_hash, collection_id, db_name)
                console.print(
                    f"[bold green]✓ Indexed '{filename}' into database: {db_name}[/bold green]"
                )
            except Exception as e:
                console.print(f"[bold red]✗ Failed to index {filename}: {e}[/bold red]")


def list_indexed_books() -> dict:
    books = BookTracker.get_indexed_books()
    if not books:
        console.print(
            "[bold red]No books have been indexed yet. Add some .epub files to 'books/' first![/bold red]"
        )
        return {}

    table = Table(title="Available Databases", border_style="cyan")
    table.add_column("Index", style="magenta", justify="center")
    table.add_column("Database Name", style="white")
    table.add_column("Included Source Files", style="dim")

    # Group tracks by collection_id
    grouped = {}
    for book_id, meta in books.items():
        grouped[book_id] = {
            "name": meta["database_name"],
            "files": meta.get("source_files", [meta.get("filename")]),
        }

    for i, (coll_id, data) in enumerate(grouped.items(), start=1):
        files_list = ", ".join(data["files"])
        table.add_row(str(i), data["name"], files_list)

    console.print(table)
    return grouped


@click.command()
def start_cli():
    show_welcome()
    check_and_index_new_books()

    databases = list_indexed_books()
    if not databases:
        return

    db_keys = list(databases.keys())
    selected_key = None

    while not selected_key:
        choice = Prompt.ask("[bold cyan]Select a database index to load[/bold cyan]")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(db_keys):
                selected_key = db_keys[idx]
            else:
                console.print("[red]Invalid option.[/red]")
        except ValueError:
            console.print("[red]Please enter a valid number.[/red]")

    active_db = databases[selected_key]["name"]
    console.print(
        Panel(
            f"[bold green]Active Database Set To:[/bold green] {active_db}",
            border_style="green",
        )
    )

    console.print("\n[dim]Query active. Type 'exit' or 'quit' to close.[/dim]\n")
    while True:
        question = Prompt.ask("[bold yellow]Ask[/bold yellow]")
        if question.lower().strip() in ["exit", "quit"]:
            console.print("[bold magenta]Goodbye![/bold magenta]")
            break

        if not question.strip():
            continue

        with console.status("[cyan]Analyzing databases and retrieving lore...[/cyan]"):
            try:
                answer = query_book(selected_key, question)
                console.print(f"\n[bold green]AI Answer:[/bold green]")
                console.print(answer)
                console.print("-" * 40 + "\n")
            except Exception as e:
                console.print(f"[bold red]An error occurred: {e}[/bold red]")
