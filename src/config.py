import os

from src.utils import get_ollama_host_ip

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(BASE_DIR, "books")
DB_DIR = os.path.join(BASE_DIR, "db")
TRACKER_FILE = os.path.join(BOOKS_DIR, "tracker.json")

# Ensure directories exist
os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)

# Ollama Models
LLM_MODEL = "qwen2.5-coder:1.5b"  # Use "llama3.2" (3B) if your hardware has 8GB+ RAM
EMBEDDING_MODEL = "nomic-embed-text"

# Text Splitting Settings (optimized for LitRPG stat blocks and chapters)
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Dynamically resolves host IP (e.g., '172.25.160.1' in WSL, or '127.0.0.1' on Termux/Linux)
HOST_IP = get_ollama_host_ip()
OLLAMA_BASE_URL = f"http://{HOST_IP}:11434"
