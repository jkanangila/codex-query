import os
import click
from rich.console import Console
from langchain_chroma import Chroma

# Internal project imports
from src.epub_parser import BookTracker
from src.rag_engine import (
    index_new_book_content,
    sanitize_collection_name,
    query_book,
    get_embeddings,
    chroma_client,
)
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import warnings

# Suppress ebooklib's verbose internal structural warnings
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
# Initialize our standard console profile
console = Console()


def extract_text_from_epub(filepath: str) -> str:
    """
    Unzips the EPUB container, extracts all structural document sections,
    and uses BeautifulSoup to strip out HTML tags, leaving clean book text.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Target document not found at: {filepath}")

    try:
        book = epub.read_epub(filepath)
    except Exception as e:
        raise ValueError(f"Failed to unpack EPUB container structure: {e}")

    extracted_chapters = []

    # Iterate through all contents inside the EPUB container
    for item in book.get_items():
        # Filter strictly for text/HTML document layers
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # Parse raw byte contents with HTML parser
            soup = BeautifulSoup(item.get_content(), "html.parser")

            # Clean out script blocks or style headers if any slip through
            for script in soup(["script", "style"]):
                script.decompose()

            # Grab pure text separated by clean spaces
            text = soup.get_text(separator=" ")
            cleaned_text = " ".join(text.split())

            if cleaned_text:
                extracted_chapters.append(cleaned_text)

    if not extracted_chapters:
        raise ValueError(
            "EPUB text extraction completed, but zero readable content layers were discovered."
        )

    return "\n\n".join(extracted_chapters)


@click.group()
def cli():
    """LitRPG Offline Book Indexing and RAG Command-Line Companion."""
    pass


@cli.command()
def sync():
    """Scan local storage directories for modified or unindexed saga content."""
    execute_incremental_indexing()


@cli.command()
@click.option(
    "--db",
    "collection_id",
    required=True,
    help="The collection/database name to query.",
)
@click.option(
    "--query",
    "question",
    required=True,
    help="The question regarding story lore or stats.",
)
def ask(collection_id: str, question: str):
    """Query a specific book index using local Ollama inference."""
    sanitized_id = sanitize_collection_name(collection_id)
    console.print(f"[cyan]Searching context index for '{collection_id}'...[/cyan]")

    try:
        answer = query_book(sanitized_id, question)
        console.print("\n[bold green]Lore-Master Answer:[/bold green]")
        console.print(answer)
    except Exception as e:
        console.print(f"[bold red]Query interface exception: {e}[/bold red]")


def execute_incremental_indexing():
    """Finds structural alterations or new text items and updates indexes with stable chroot progress logs."""
    pending_files = BookTracker.scan_for_modified_or_new_files()
    if not pending_files:
        console.print("[green]✓ All book indexes are up to date.[/green]")
        return

    console.print(
        f"[yellow]Found {len(pending_files)} new or structurally altered EPUB file(s).[/yellow]"
    )
    console.print("Processing updates...\n")

    for item in pending_files:
        filename = item["filename"]
        filepath = item["path"]
        file_hash = item["hash"]

        try:
            # --- Phase 1: Parsing Content Layers ---
            with console.status(
                f"[cyan]Parsing book layers:[/] {filename[:30]}...", spinner="earth"
            ):
                text_content = extract_text_from_epub(filepath)

            # --- Phase 2: Interactive Prompt (No threads active here, perfectly safe) ---
            console.print(f"\n[bold yellow]Target discovered:[/] {filename}")
            db_name = click.prompt(
                "Assign a collection/database profile for this volume",
                default=os.path.splitext(filename)[0],
            )
            database_id = sanitize_collection_name(db_name)

            existing_hashes = set()
            if hasattr(BookTracker, "get_all_hashes_for_database"):
                existing_hashes = set(
                    BookTracker.get_all_hashes_for_database(database_id)
                )

            # Extract and audit text chunks
            with console.status(
                "[magenta]Analyzing and chunking document text...[/magenta]",
                spinner="dots",
            ):
                new_chunks, newly_added_hashes = index_new_book_content(
                    collection_id=database_id,
                    text=text_content,
                    existing_hashes=existing_hashes,
                )

            # --- Phase 3: Synchronous Embedding Loops (Bypasses Chroot Frozen Thread Bug) ---
            if new_chunks:
                num_chunks = len(new_chunks)
                console.print(
                    f"[magenta]Embedding {num_chunks} vector chunks into '{db_name}'...[/magenta]"
                )

                vector_store = Chroma(
                    collection_name=database_id,
                    embedding_function=get_embeddings(),
                    client=chroma_client,
                )

                # Use a larger batch size to maximize performance on mobile processors
                BATCH_SIZE = 50
                processed = 0

                for i in range(0, num_chunks, BATCH_SIZE):
                    batch = new_chunks[i : i + BATCH_SIZE]
                    vector_store.add_documents(documents=batch)

                    processed += len(batch)
                    percentage = (processed / num_chunks) * 100

                    # Print an explicit terminal status carriage return '\r' layout
                    # This completely bypasses threading locks and forces standard terminal updates
                    print(
                        f"\rProgress: [{processed}/{num_chunks}] ─── {percentage:>3.0f}% Complete...",
                        end="",
                        flush=True,
                    )

                # Clear the trailing carriage line layout
                print("")
            else:
                console.print(
                    f"[yellow]! No completely new structural text layers found to embed for {filename}.[/yellow]"
                )

            # --- Phase 4: State Finalization ---
            BookTracker.register_book(filename, file_hash, database_id, db_name)
            console.print(
                f"[bold green]✓ Successfully cataloged:[/] {filename} -> DB: {database_id}\n"
            )

        except Exception as e:
            console.print(
                f"[bold red]✗ Pipeline processing failed for item {filename}: {e}[/bold red]\n"
            )


if __name__ == "__main__":
    cli()
