# LoreKeeper: Dynamic Local Book RAG CLI

An advanced, offline RAG (Retrieval-Augmented Generation) CLI tool designed to index and query book collections locally within CPU- and RAM-constrained environments (like an Ubuntu chroot running on Android).

Powered by **ChromaDB** and **Ollama**, LoreKeeper abstracts away the complexity of handling shifting text formats. Each series gets its own dedicated database collection, completely isolated from cross-contamination and running 100% privately on your device.

## Advanced Delta-Indexing Protocol

Unlike static RAG pipelines, LoreKeeper features a smart **Content Chunk Auditing** system built specifically for progression fantasy, web novels, and changing libraries:

*   **Single Complete Files:** Drops in clean, isolated `.epub` novels instantly.
*   **Multi-Part Sagas:** Merge Book 1, Book 2, and side stories manually into a single unified series database for macro-lore querying.
*   **Progressive/Changing Releases:** If an external app appends newly released chapters to an existing `.epub` file, LoreKeeper automatically detects the modified file-size/timestamp, parses the changes, filters out previously indexed text chunks, and pipes **only the new content deltas** into the database. Zero duplicates, zero prompt confusion.

## Prerequisites

1. **Ollama running locally:**
   Ensure Ollama is running inside your chroot environment with the necessary foundational models downloaded:
   ```bash
   ollama run llama3.2:1b
   ollama run nomic-embed-text
   ```

2. **Pipenv Environment Manager:**
```bash
pip install pipenv

```



## Installation & Setup

1. Clone or copy this repository into your local Ubuntu workspace.
2. Initialize and download the optimized dependency stack:
```bash
pipenv install

```



## Usage Instructions

1. **Add Your Documents:**
Place your novel `.epub` files inside the `books/` folder.
2. **Launch the Core CLI:**
```bash
pipenv run python main.py

```


3. **Index Automation:**
On boot, LoreKeeper scans your directory. If it detects a completely brand new file, it will prompt you to create a new database or add it to an existing series. If it detects a size variation in an already-tracked file, it will silently process and append the new chapters.
4. **Query:**
Select your active target database matrix from the interactive visual menu and start asking questions! Type `exit` to close the interface safely.
