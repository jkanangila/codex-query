# Offline LitRPG RAG CLI

A private, offline CLI tool designed to index EPUB format LitRPG/Progression Fantasy novels locally inside your Ubuntu environment (such as an Android Chroot). 

Using **ChromaDB**, each book is stored in its own clean collection, enabling rapid local searches and zero cloud reliance.

## Prerequisites

1. **Ollama running locally:**
   Make sure Ollama is installed and running inside your Ubuntu chroot. Run:
   ```bash
   ollama run llama3.2:1b
   ollama run nomic-embed-text

2. **Pipenv installed:**
```bash
pip install pipenv

```
## Setup & Installation

1. **Clone or Copy this project** into your chroot storage.
2. **Install dependencies** using Pipenv:
```bash
pipenv install

```
## Usage Guide

1. **Add Your Books:**
Drop your LitRPG novel `.epub` files into the `books/` directory of this project.
2. **Start the Companion CLI:**
Enter the virtual environment and boot up the main application:
```bash
pipenv run python main.py

```
3. **How It Works:**
* On startup, the program will automatically detect any new `.epub` files inside `books/`.
* It will parse, chunk, embed, and store them in their own dedicated databases inside `db/`.
* The program outputs a list of ready books.
* Type the number corresponding to the book you want to load, then enter your questions!
