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
    """ChromaDB collection names must match a specific regex."""
    sanitized = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    sanitized = sanitized.strip("_")
    # Must be 3-63 characters, start with alpha-numeric
    if len(sanitized) < 3:
        sanitized += "_db"
    return sanitized[:63].lower()


def index_new_book(book_title: str, text: str) -> str:
    """Chops book text up and embeds it into its own Chroma collection."""
    collection_id = sanitize_collection_name(book_title)
    embeddings = get_embeddings()

    # Wrap text in Langchain Doc
    doc = Document(page_content=text, metadata={"source": book_title})

    # Split text (LitRPG optimization: preserving lists and stat blocks)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents([doc])

    # Store in ChromaDB collection
    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=collection_id,
        client=chroma_client,
    )
    return collection_id


def query_book(collection_id: str, question: str):
    """Retrieves context from specific collection and queries LLM."""
    embeddings = get_embeddings()
    llm = ChatOllama(model=LLM_MODEL, temperature=0.2)

    # Fetch collection vector store
    vector_store = Chroma(
        collection_name=collection_id,
        embedding_function=embeddings,
        client=chroma_client,
    )

    # Find top 5 matching blocks
    retriever = vector_store.as_retriever(search_kwargs={"k": 5})

    # System Prompt for LitRPG context
    system_prompt = (
        "You are an expert assistant on LitRPG and Progression Fantasy novels.\n"
        "Use the retrieved passages from the novel below to answer the user's question.\n"
        "Provide a comprehensive, accurate answer based strictly on the text provided.\n"
        "If you do not know or if the source context doesn't contain it, say so clearly.\n\n"
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

    # Run query
    response = retrieval_chain.invoke({"input": question})
    return response["answer"]
