"""Knowledge-base ingestion and retrieval for the support agent.

Embeddings are real hashed TF-IDF bags of words computed locally: deterministic,
offline and dependency-free. Retrieval scores cosine similarity against the
business's chunk corpus (inverse document frequency computed at query time).
No LLM is involved in indexing, so there are no fabricated vectors.
"""

import math
import re
from collections import Counter

from sqlmodel import Session, select

from app.db.models import KnowledgeChunk, KnowledgeDocument

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
MAX_CHARS = 800
OVERLAP = 120


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text) if len(t) > 1]


def embed(text: str) -> dict[str, float]:
    tokens = tokenize(text)
    if not tokens:
        return {}
    counts = Counter(tokens)
    norm = math.sqrt(sum(v * v for v in counts.values()))
    return {token: value / norm for token, value in counts.items()}


def split_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:MAX_CHARS])
            para = para[MAX_CHARS - OVERLAP :]
        if len(current) + len(para) + 1 <= MAX_CHARS:
            current = f"{current}\n\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks or ([text] if text.strip() else [])


def ingest_document(
    session: Session, business_id: str, title: str, content: str, source: str = ""
) -> KnowledgeDocument:
    doc = KnowledgeDocument(business_id=business_id, title=title, content=content, source=source)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    for chunk_text in split_text(content):
        session.add(
            KnowledgeChunk(
                document_id=doc.id,
                business_id=business_id,
                text=chunk_text,
                embedding=embed(chunk_text),
            )
        )
    session.commit()
    return doc


def delete_document(session: Session, document_id: str) -> bool:
    doc = session.get(KnowledgeDocument, document_id)
    if doc is None:
        return False
    for chunk in session.exec(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
    ).all():
        session.delete(chunk)
    session.delete(doc)
    session.commit()
    return True


def search(session: Session, business_id: str, query: str, top_k: int = 4) -> list[dict]:
    """Return [{text, score, document_id}] for the best matching chunks."""
    q = embed(query)
    if not q:
        return []
    chunks = session.exec(
        select(KnowledgeChunk).where(KnowledgeChunk.business_id == business_id)
    ).all()
    if not chunks:
        return []
    # IDF over this business's corpus
    n = len(chunks)
    df: Counter[str] = Counter()
    for chunk in chunks:
        df.update((chunk.embedding or {}).keys())
    idf = {term: math.log((n + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}
    scored: list[dict] = []
    for chunk in chunks:
        vec = chunk.embedding or {}
        dot = 0.0
        for term, q_weight in q.items():
            if term in vec:
                dot += q_weight * vec[term] * idf.get(term, 1.0)
        if dot > 0:
            scored.append(
                {
                    "text": chunk.text,
                    "score": round(dot, 4),
                    "document_id": chunk.document_id,
                }
            )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def context_for(business_id: str, query: str, session: Session) -> str:
    hits = search(session, business_id, query)
    if not hits:
        return ""
    return "\n\n".join(f"[source {h['document_id'][:8]}] {h['text']}" for h in hits)
