"""
vector_store.py
----------------
"create embeddings" -> "store in vector database".

Uses Chroma with a real neural embedding model.
"""

import os
import chromadb
import chromadb.utils.embedding_functions as embedding_functions

from data_loader import build_documents

PERSIST_DIR = r"\RAG_supervisor\chroma_db"
COLLECTION_NAME = "driver_trips"
DATA_PATH = r"\data\synthetic_trips.json"


def get_embedding_function():
    # Local Sentence-Transformers (Free / CPU / No API key)
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )


def build_index(json_path: str, persist_dir: str = PERSIST_DIR):
    documents, metadatas, ids = build_documents(json_path)

    client = chromadb.PersistentClient(path=persist_dir)
    
    # Fresh build each time this is called
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    print(f"Indexed {len(ids)} trips into Chroma collection '{COLLECTION_NAME}'.")
    return collection


def get_collection(persist_dir: str = PERSIST_DIR):
    client = chromadb.PersistentClient(path=persist_dir)
    return client.get_collection(
        name=COLLECTION_NAME, embedding_function=get_embedding_function()
    )


def semantic_search(query: str, n_results: int = 5, where: dict | None = None):
    """Plain vector similarity search, optionally filtered by metadata."""
    collection = get_collection()
    kwargs = {"query_texts": [query], "n_results": n_results}
    if where:
        kwargs["where"] = where
    results = collection.query(**kwargs)
    hits = []
    for doc, meta, dist, id_ in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
        results["ids"][0],
    ):
        hits.append({"id": id_, "text": doc, "metadata": meta, "distance": dist})
    return hits
 
 
if __name__ == "__main__":
    build_index(DATA_PATH)
 
    print("\n--- test query: 'What happened during Ahmed's last trip?' ---")
    for h in semantic_search(
        "Ahmed's last trip what happened",
        n_results=3,
        where={"driver_name": "Ahmed Ali"},
    ):
        print(h["id"], h["metadata"]["departure_time"], "dist=", round(h["distance"], 3))


 
