import hashlib

import chromadb
from langchain_chroma import Chroma
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
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
) -> tuple[list[Document], list[str]]:
    """
    Slices raw text, audits chunks to filter out duplicates, and returns
    the list of NEW documents along with their corresponding hashes.
    """
    doc = Document(page_content=text)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    raw_chunks = splitter.split_documents([doc])

    new_chunks = []
    newly_added_hashes = []

    for chunk in raw_chunks:
        chunk_hash = compute_string_hash(chunk.page_content)
        if chunk_hash not in existing_hashes:
            new_chunks.append(chunk)
            newly_added_hashes.append(chunk_hash)

    # Return the data chunks back to the CLI context manager to let it drive progress loops
    return new_chunks, newly_added_hashes


def query_book(collection_id: str, question: str):
    embeddings = get_embeddings()
    llm = ChatOllama(model=LLM_MODEL, temperature=0.3, num_ctx=1024, num_thread=2)

    vector_store = Chroma(
        collection_name=collection_id,
        embedding_function=embeddings,
        client=chroma_client,
    )

    retriever = vector_store.as_retriever(search_kwargs={"k": 2})

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
