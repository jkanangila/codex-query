import json
import os

from epub_to_text import epub_to_text

from src.config import BOOKS_DIR, TRACKER_FILE


class BookTracker:
    @staticmethod
    def _load_tracker() -> dict:
        if not os.path.exists(TRACKER_FILE):
            return {"databases": {}}
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"databases": {}}

    @staticmethod
    def _save_tracker(tracker_data: dict):
        with open(TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(tracker_data, f, indent=4)

    @classmethod
    def scan_for_modified_or_new_files(cls) -> list[dict]:
        """
        Inspects directory. Finds new EPUB files or progressive files where
        the file metadata (file size or mod-time) has changed since the last run.
        """
        tracker = cls._load_tracker()
        all_processed_files = {}

        # Build mapping of files we already know about
        for db_id, db_meta in tracker["databases"].items():
            for f_path, f_meta in db_meta.get("tracked_files", {}).items():
                all_processed_files[f_path] = f_meta

        pending_updates = []
        for filename in os.listdir(BOOKS_DIR):
            if filename.endswith(".epub"):
                file_path = os.path.join(BOOKS_DIR, filename)
                stat = os.stat(file_path)
                current_size = stat.st_size
                current_mtime = stat.st_mtime

                # Check if file has never been seen, or size/mtime changed
                if file_path not in all_processed_files:
                    pending_updates.append(
                        {"filename": filename, "path": file_path, "status": "new"}
                    )
                else:
                    known = all_processed_files[file_path]
                    if current_size != known["size"] or current_mtime != known["mtime"]:
                        pending_updates.append(
                            {
                                "filename": filename,
                                "path": file_path,
                                "status": "updated",  # Chapter count increased in progressive build
                            }
                        )

        return pending_updates

    @classmethod
    def get_all_hashes_for_database(cls, db_id: str) -> set[str]:
        tracker = cls._load_tracker()
        if db_id in tracker["databases"]:
            return set(tracker["databases"][db_id].get("chunk_hashes", []))
        return set()

    @classmethod
    def register_indexing_run(
        cls,
        db_id: str,
        db_name: str,
        file_path: str,
        filename: str,
        new_hashes: list[str],
    ):
        tracker = cls._load_tracker()
        stat = os.stat(file_path)

        if db_id not in tracker["databases"]:
            tracker["databases"][db_id] = {
                "database_name": db_name,
                "tracked_files": {},
                "chunk_hashes": [],
            }

        # Log metadata parameters to stop tracking matching loops
        tracker["databases"][db_id]["tracked_files"][file_path] = {
            "filename": filename,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }

        # Append unique paragraph fingerprints to block list duplicates
        existing_hashes = set(tracker["databases"][db_id]["chunk_hashes"])
        for h in new_hashes:
            if h not in existing_hashes:
                tracker["databases"][db_id]["chunk_hashes"].append(h)

        cls._save_tracker(tracker)

    @classmethod
    def get_indexed_databases(cls) -> dict:
        return cls._load_tracker().get("databases", {})


def extract_text_from_epub(epub_path: str) -> str:
    try:
        return epub_to_text(epub_path)
    except Exception as e:
        raise RuntimeError(f"Error accessing or structural failure inside EPUB: {e}")
