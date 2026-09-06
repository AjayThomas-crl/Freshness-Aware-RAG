import chromadb

from app.config import settings

COLLECTION = "live_chunks"
DIM = 384  # all-MiniLM-L6-v2


def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.chroma_dir)


def _get_collection(client: chromadb.ClientAPI):
    return client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_live(
    *,
    ids: list[str],
    contents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    """
    Store (or overwrite) the LIVE vector for each chunk.

    One vector per stable chunk id. History is NOT kept here — old versions live
    only in the SQL `chunk_versions` table, so no stale vectors are ever queried.
    On content change we upsert the same id with the new embedding.
    """
    client = _client()
    col = _get_collection(client)
    col.upsert(ids=ids, documents=contents, embeddings=embeddings, metadatas=metadatas)


def get_all_ids() -> list[str]:
    client = _client()
    col = _get_collection(client)
    return col.get(include=[])["ids"]


def delete(ids: list[str]) -> None:
    client = _client()
    col = _get_collection(client)
    if ids:
        col.delete(ids=ids)


def delete_for_source(source_id: int) -> None:
    """Drop every live vector belonging to a source (ids are '{source_id}:{chunk_key}')."""
    prefix = f"{source_id}:"
    stale = [i for i in get_all_ids() if i.startswith(prefix)]
    delete(stale)


def search(query_embedding: list[float], top_k: int) -> list[dict]:
    client = _client()
    col = _get_collection(client)
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    out = []
    for i, mid in enumerate(ids):
        meta = metas[i] or {}
        out.append(
            {
                "chunk_id": mid,
                "content": docs[i],
                "distance": dists[i],
                "metadata": meta,
            }
        )
    return out
