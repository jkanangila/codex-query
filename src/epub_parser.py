import os
import json
import hashlib
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from src.config import TRACKER_FILE, BOOKS_DIR


class BookTracker:
    @staticmethod
    def _load_tracker() -> dict:
        if not os.path.exists(TRACKER_FILE):
            return {"indexed_books": {}}
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"indexed_books": {}}

    @staticmethod
    def _save_tracker(tracker_data: dict):
        with open(TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(tracker_data, f, indent=4)

    @staticmethod
    def calculate_file_hash(filepath: str) -> str:
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @classmethod
    def get_unindexed_epubs(cls) -> list[dict]:
        """Returns a list of dicts for new epubs matching CLI key structures."""
        tracker = cls._load_tracker()
        indexed_hashes = set()
        for data in tracker["indexed_books"].values():
            for h in data.get("hashes", []):
                indexed_hashes.add(h)
            if "hash" in data:
                indexed_hashes.add(data["hash"])

        new_books = []
        for filename in os.listdir(BOOKS_DIR):
            if filename.endswith(".epub"):
                file_path = os.path.join(BOOKS_DIR, filename)
                file_hash = cls.calculate_file_hash(file_path)
                if file_hash not in indexed_hashes:
                    new_books.append(
                        {
                            "filename": filename,
                            "path": file_path,
                            "hash": file_hash,
                            "status": "new",  # Added this to satisfy the status check!
                        }
                    )
        return new_books

    @classmethod
    def register_book(cls, filename: str, file_hash: str, book_id: str, db_name: str):
        tracker = cls._load_tracker()

        if book_id in tracker["indexed_books"]:
            if filename not in tracker["indexed_books"][book_id]["source_files"]:
                tracker["indexed_books"][book_id]["source_files"].append(filename)
            if file_hash not in tracker["indexed_books"][book_id]["hashes"]:
                tracker["indexed_books"][book_id]["hashes"].append(file_hash)
        else:
            tracker["indexed_books"][book_id] = {
                "database_name": db_name,
                "source_files": [filename],
                "hashes": [file_hash],
                "id": book_id,
            }
        cls._save_tracker(tracker)

    @classmethod
    def get_indexed_books(cls) -> dict:
        return cls._load_tracker().get("indexed_books", {})

    @classmethod
    def scan_for_modified_or_new_files(cls) -> list[dict]:
        """Satisfies the CLI's check for new or updated files with dictionaries."""
        return cls.get_unindexed_epubs()

    @classmethod
    def get_indexed_databases(cls) -> dict:
        """
        Returns the dictionary of currently indexed books/collections
        to satisfy the CLI query workflow for multi-part merging.
        """
        tracker = cls._load_tracker()
        return tracker.get("indexed_books", {})

    @classmethod
    def get_all_hashes_for_database(cls, database_id: str) -> list[str]:
        """
        Retrieves all file hashes associated with a specific database profile ID
        to prevent chunk replication during progressive indexing.
        """
        tracker = cls._load_tracker()
        book_entry = tracker.get("indexed_books", {}).get(database_id, {})

        # Pull from the 'hashes' array if it's a multi-part series,
        # fallback to the singular 'hash' field for backwards compatibility.
        hashes = book_entry.get("hashes", [])
        if not hashes and "hash" in book_entry:
            hashes = [book_entry["hash"]]

        return hashes


def extract_text_from_epub(epub_path: str) -> str:
    """Extracts and strips HTML tags from an EPUB file to yield clean text."""
    try:
        # Suppress ebooklib warning logs
        book = epub.read_epub(epub_path, options={"ignore_ncx": True})
        text_content = []

        # Iterate through HTML items in the EPUB spine
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_body_content(), "html.parser")
            # Extract text elements cleanly
            text = soup.get_text(separator="\n")
            if text.strip():
                text_content.append(text)

        return "\n\n".join(text_content)
    except Exception as e:
        raise RuntimeError(f"Failed parsing epub {epub_path}: {e}")
