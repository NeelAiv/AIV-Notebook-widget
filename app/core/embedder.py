from sentence_transformers import SentenceTransformer
import os
import threading

_DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"


class LocalEmbedder:
    def __init__(self):
        self._lock = threading.Lock()
        model_name = os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        print(f"Loading embedding model (CPU): {model_name} ...")
        os.environ["HF_HUB_DISABLE"] = "1"
        try:
            self.model = SentenceTransformer(
                model_name, device="cpu", local_files_only=True
            )
        except Exception:
            os.environ.pop("HF_HUB_DISABLE", None)
            self.model = SentenceTransformer(model_name, device="cpu")

        dim_fn = getattr(
            self.model, "get_embedding_dimension", self.model.get_sentence_embedding_dimension
        )
        self.dimension = int(dim_fn())
        self._batch_size = max(1, int(os.environ.get("RAG_EMBED_BATCH_SIZE", "32")))
        print(f"Embedding model loaded ({self.dimension} dimensions).")

    def get_embedding(self, text):
        """Encode text to a list of floats (dimension matches EMBEDDING_MODEL)."""
        if not text or not str(text).strip():
            return []
        vecs = self.get_embeddings([text])
        return vecs[0] if vecs else []

    def get_embeddings(self, texts: list, batch_size: int | None = None) -> list[list[float]]:
        """Batch-encode multiple texts (much faster than one-by-one for RAG indexing)."""
        if not texts:
            return []
        batch_size = batch_size or self._batch_size
        cleaned = [str(t).strip() if t else "" for t in texts]
        if not any(cleaned):
            return [[] for _ in texts]

        with self._lock:
            vectors = self.model.encode(
                cleaned,
                batch_size=batch_size,
                show_progress_bar=False,
            )
        if len(cleaned) == 1:
            return [vectors.tolist()]
        return [row.tolist() for row in vectors]


embedder_instance = LocalEmbedder()
