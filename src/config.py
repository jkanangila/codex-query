import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(BASE_DIR, "books")
DB_DIR = os.path.join(BASE_DIR, "db")
TRACKER_FILE = os.path.join(BOOKS_DIR, "tracker.json")

# Ensure directories exist
os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)

# Ollama Models
LLM_MODEL = "Qwen2.5:1.5b"  # Use "llama3.2" (3B) if your hardware has 8GB+ RAM
EMBEDDING_MODEL = "nomic-embed-text"

# Text Splitting Settings (optimized for LitRPG stat blocks and chapters)
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
