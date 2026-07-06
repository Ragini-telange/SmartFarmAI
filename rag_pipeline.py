"""
SmartFarm AI – RAG Pipeline
Handles: document loading, chunking, embedding, ChromaDB indexing, retrieval
"""

import os
import glob
import logging
from typing import List, Optional, Tuple
from pathlib import Path

from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config from env / agent_instructions ────────────────────────────────────
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chromadb_store")
KB_DIR             = os.getenv("KB_DIR", "./knowledge_base")
COLLECTION_NAME    = "smartfarm_kb"

# Local sentence-transformer model for embeddings (no IBM key needed for indexing)
EMBED_MODEL_NAME   = "all-MiniLM-L6-v2"   # Fast, accurate, runs on CPU

# Import RAG settings from agent instructions
try:
    from agent_instructions import (
        CHUNK_SIZE, CHUNK_OVERLAP, TOP_K_RETRIEVAL, SIMILARITY_THRESHOLD
    )
except ImportError:
    CHUNK_SIZE = 600
    CHUNK_OVERLAP = 100
    TOP_K_RETRIEVAL = 4
    SIMILARITY_THRESHOLD = 0.35


# ─── Singleton state ─────────────────────────────────────────────────────────
_embed_model: Optional[SentenceTransformer] = None
_chroma_client: Optional[chromadb.PersistentClient] = None
_collection = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        logger.info("Loading embedding model: %s", EMBED_MODEL_NAME)
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _get_chroma_collection():
    global _chroma_client, _collection
    if _collection is None:
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False),
        )
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ─── Document loaders ────────────────────────────────────────────────────────

def _load_txt(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _load_pdf(filepath: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        logger.warning("PDF load failed %s: %s", filepath, e)
        return ""


def _load_docx(filepath: str) -> str:
    try:
        from docx import Document
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        logger.warning("DOCX load failed %s: %s", filepath, e)
        return ""


def load_document(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext == ".txt":
        return _load_txt(filepath)
    elif ext == ".pdf":
        return _load_pdf(filepath)
    elif ext in (".docx", ".doc"):
        return _load_docx(filepath)
    logger.warning("Unsupported file type: %s", filepath)
    return ""


# ─── Chunking ────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping character-based chunks."""
    if not text.strip():
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap
    return chunks


# ─── Indexing ────────────────────────────────────────────────────────────────

def index_knowledge_base(force_reindex: bool = False) -> int:
    """
    Walk KB_DIR, load all supported documents, chunk, embed, and store in ChromaDB.
    Returns total number of chunks indexed.
    """
    collection = _get_chroma_collection()
    model = _get_embed_model()

    # Check if already indexed
    existing_count = collection.count()
    if existing_count > 0 and not force_reindex:
        logger.info("Knowledge base already indexed (%d chunks). Skipping.", existing_count)
        return existing_count

    if force_reindex and existing_count > 0:
        logger.info("Force re-index: deleting %d existing chunks.", existing_count)
        collection.delete(where={"source": {"$ne": ""}})

    supported_exts = {".txt", ".pdf", ".docx", ".doc"}
    files = []
    for ext in supported_exts:
        files.extend(glob.glob(os.path.join(KB_DIR, "**", f"*{ext}"), recursive=True))

    if not files:
        logger.warning("No documents found in KB_DIR: %s", KB_DIR)
        return 0

    total_chunks = 0
    for filepath in files:
        logger.info("Indexing: %s", filepath)
        raw_text = load_document(filepath)
        if not raw_text:
            continue

        chunks = chunk_text(raw_text)
        if not chunks:
            continue

        # Generate IDs and embeddings
        rel_path = os.path.relpath(filepath, KB_DIR)
        doc_ids = [f"{rel_path}::chunk_{i}" for i in range(len(chunks))]
        embeddings = model.encode(chunks, show_progress_bar=False).tolist()
        metadatas = [{"source": rel_path, "chunk_index": i} for i in range(len(chunks))]

        # Batch upsert (ChromaDB max 5461 per call)
        batch_size = 500
        for i in range(0, len(chunks), batch_size):
            collection.upsert(
                ids=doc_ids[i:i + batch_size],
                embeddings=embeddings[i:i + batch_size],
                documents=chunks[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size],
            )
        total_chunks += len(chunks)
        logger.info("  → %d chunks from %s", len(chunks), rel_path)

    logger.info("Knowledge base indexing complete. Total chunks: %d", total_chunks)
    return total_chunks


# ─── Retrieval ───────────────────────────────────────────────────────────────

def retrieve_context(query: str, top_k: int = TOP_K_RETRIEVAL) -> Tuple[str, List[dict]]:
    """
    Retrieve top-k most relevant knowledge base chunks for a query.
    Returns:
        context_str  : formatted string of retrieved passages (for LLM prompt)
        sources      : list of metadata dicts for citations
    """
    collection = _get_chroma_collection()
    model = _get_embed_model()

    if collection.count() == 0:
        logger.warning("ChromaDB collection is empty. Run index_knowledge_base() first.")
        return "", []

    query_embedding = model.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    passages = []
    sources = []
    if results and results["documents"] and results["documents"][0]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            similarity = 1.0 - dist   # cosine distance → similarity
            if similarity >= SIMILARITY_THRESHOLD:
                passages.append(f"[Source: {meta.get('source', 'KB')}]\n{doc}")
                sources.append({
                    "source": meta.get("source", "KB"),
                    "similarity": round(similarity, 3),
                    "snippet": doc[:120] + "…",
                })

    context_str = "\n\n---\n\n".join(passages) if passages else "No relevant knowledge base context found."
    return context_str, sources


# ─── Status ──────────────────────────────────────────────────────────────────

def get_kb_status() -> dict:
    """Return current indexing status for health-check endpoint."""
    try:
        collection = _get_chroma_collection()
        return {
            "indexed": True,
            "chunk_count": collection.count(),
            "collection_name": COLLECTION_NAME,
            "persist_dir": CHROMA_PERSIST_DIR,
        }
    except Exception as e:
        return {"indexed": False, "error": str(e)}
