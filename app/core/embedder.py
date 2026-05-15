from sentence_transformers import SentenceTransformer
import os

_DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"


class LocalEmbedder:
    def __init__(self):
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
        print(f"Embedding model loaded ({self.dimension} dimensions).")

    def get_embedding(self, text):
        """Encode text to a list of floats (dimension matches EMBEDDING_MODEL)."""
        if not text:
            return []
        return self.model.encode(text).tolist()


embedder_instance = LocalEmbedder()
