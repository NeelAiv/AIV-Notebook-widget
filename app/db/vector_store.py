import os
import chromadb
from chromadb.config import Settings
import hashlib
import json

class LocalVectorStore:
    def __init__(self, persist_directory="./chroma_db"):
        self.persist_directory = persist_directory
        os.makedirs(self.persist_directory, exist_ok=True)
        # Initialize persistent ChromaDB client
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        
        self.collection_name = "workspace_knowledge"
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def _generate_id(self, source_name: str, chunk_text: str) -> str:
        """Generates a stable unique hash for a chunk to prevent duplicates."""
        # Combines the source name and actual text to create a unique signature
        content_signature = f"{source_name}::{chunk_text.strip()}"
        return hashlib.sha256(content_signature.encode('utf-8')).hexdigest()

    def add_chunks(self, source_name: str, chunks: list[str], embeddings: list[list[float]] = None):
        """Indexes text chunks. 
        Note: We let Chroma use its built-in sentence-transformers, OR we can pass our own embeddings.
        Because we already have an embedder model loaded on CPU, we'll pass our embeddings natively.
        """
        if not chunks: return

        ids = []
        metadatas = []
        valid_chunks = []
        valid_embeddings = []

        for i, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk: continue
            
            chunk_id = self._generate_id(source_name, chunk)
            ids.append(chunk_id)
            metadatas.append({"source": source_name})
            valid_chunks.append(chunk)
            
            if embeddings and i < len(embeddings):
                valid_embeddings.append(embeddings[i])

        if not valid_chunks: return

        try:
            self.collection.delete(where={"source": source_name})
        except Exception:
            pass


        try:
            if valid_embeddings:
                self.collection.upsert(
                    ids=ids,
                    documents=valid_chunks,
                    metadatas=metadatas,
                    embeddings=valid_embeddings
                )
            else:
                self.collection.upsert(
                    ids=ids,
                    documents=valid_chunks,
                    metadatas=metadatas
                )
        except Exception as e:
            print(f"Error indexing to ChromaDB: {e}")

    def search(self, query_embedding: list[float], n_results: int = 5, where: dict = None):
        """Searches ChromaDB using an embedding vector."""
        if self.collection.count() == 0:
            return []

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where
            )
            
            # Format the output to identically match our previous Postgres results
            formatted_results = []
            
            if not results['documents'] or not results['documents'][0]:
                return formatted_results

            docs = results['documents'][0]
            metas = results['metadatas'][0]

            for i in range(len(docs)):
                formatted_results.append({
                    "source_name": metas[i].get("source", "Unknown"),
                    "chunk_text": docs[i]
                })

            return formatted_results
        except Exception as e:
            print(f"ChromaDB Search Error: {e}")
            return []


vector_store = LocalVectorStore()
