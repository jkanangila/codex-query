import hashlib
import json
import os

from epub_to_text import epub_to_text

from src.config import BOOKS_DIR, TRACKER_FILE


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
    def get_unindexed_epubs(cls) -> list[tuple[str, str]]:
        tracker = cls._load_tracker()
        # Parse flat list of processed hashes across all database objects
        indexed_hashes = set()
        for data in tracker["indexed_books"].values():
            for h in data.get("hashes", []):
                indexed_hashes.add(h)
            if "hash" in data:  # Legacy compatibility
                indexed_hashes.add(data["hash"])

        new_epubs = []
        for filename in os.listdir(BOOKS_DIR):
            if filename.endswith(".epub"):
                file_path = os.path.join(BOOKS_DIR, filename)
                file_hash = cls.calculate_file_hash(file_path)
                if file_hash not in indexed_hashes:
                    new_epubs.append((filename, file_path))
        return new_epubs

    @classmethod
    def register_book(cls, filename: str, file_hash: str, book_id: str, db_name: str):
        tracker = cls._load_tracker()

        if book_id in tracker["indexed_books"]:
            # Append file metadata to existing database entry
            if filename not in tracker["indexed_books"][book_id]["source_files"]:
                tracker["indexed_books"][book_id]["source_files"].append(filename)
            if file_hash not in tracker["indexed_books"][book_id]["hashes"]:
                tracker["indexed_books"][book_id]["hashes"].append(file_hash)
        else:
            # Create a brand new database collection tracking system
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


def extract_text_from_epub(epub_path: str) -> str:
    try:
        # Use epub_to_text for conversion
        return epub_to_text(epub_path)
    except Exception as e:
        raise RuntimeError(f"Failed parsing epub {epub_path}: {e}")
