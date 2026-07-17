import hashlib
import os

import chromadb
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import CHUNK_OVERLAP, CHUNK_SIZE, DB_DIR, EMBEDDING_MODEL, LLM_MODEL

# Initialize persistent ChromaDB Client
chroma_client = chromadb.PersistentClient(path=DB_DIR)


def get_embeddings():
    return OllamaEmbeddings(model=EMBEDDING_MODEL)


def sanitize_collection_name(name: str) -> str:
    sanitized = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    sanitized = sanitized.strip("_")
    if len(sanitized) < 3:
        sanitized += "_db"
    return sanitized[:63].lower()


def compute_string_hash(text: str) -> str:
    """Generates a stable unique identifier for a specific snippet of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def index_new_book_content(
    collection_id: str, text: str, existing_hashes: set[str]
) -> list[str]:
    """
    Slices raw text, filters out chunks that are already recorded in the DB registry,
    and indexes only completely new content chunks.
    """
    embeddings = get_embeddings()
    doc = Document(page_content=text)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    raw_chunks = splitter.split_documents([doc])

    # Audit chunks to filter out duplicates
    new_chunks = []
    newly_added_hashes = []

    for chunk in raw_chunks:
        chunk_hash = compute_string_hash(chunk.page_content)
        if chunk_hash not in existing_hashes:
            new_chunks.append(chunk)
            newly_added_hashes.append(chunk_hash)

    if new_chunks:
        Chroma.from_documents(
            documents=new_chunks,
            embedding=embeddings,
            collection_name=collection_id,
            client=chroma_client,
        )

    return newly_added_hashes


def query_book(collection_id: str, question: str):
    embeddings = get_embeddings()
    llm = ChatOllama(model=LLM_MODEL, temperature=0.2)

    vector_store = Chroma(
        collection_name=collection_id,
        embedding_function=embeddings,
        client=chroma_client,
    )

    retriever = vector_store.as_retriever(search_kwargs={"k": 5})

    system_prompt = (
        "You are an expert lore-master assistant for a LitRPG/Progression Fantasy series.\n"
        "Answer the user's questions truthfully and completely based on the provided text sections.\n"
        "If the context does not contain the answer, state that it's unconfirmed inside the text.\n\n"
        "Context:\n{context}"
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("human", "{input}"),
        ]
    )

    document_chain = create_stuff_documents_chain(llm, prompt)
    retrieval_chain = create_retrieval_chain(retriever, document_chain)

    response = retrieval_chain.invoke({"input": question})
    return response["answer"]
