"""Knowledge store + RAG (pgvector). Independiente del producto GIA."""

from app.services.knowledge.embeddings import embed_texts
from app.services.knowledge.ingest import chunk_text, extract_text, ingest_file
from app.services.knowledge.retriever import RetrievedHit, format_hits, retrieve_knowledge
from app.services.knowledge.seed import seed_from_agent_info
from app.services.knowledge.store import KnowledgeStore
from app.services.knowledge.tools_registry import REGISTERED_TOOLS

__all__ = [
    "KnowledgeStore",
    "RetrievedHit",
    "REGISTERED_TOOLS",
    "chunk_text",
    "embed_texts",
    "extract_text",
    "format_hits",
    "ingest_file",
    "retrieve_knowledge",
    "seed_from_agent_info",
]
