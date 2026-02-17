from sentence_transformers import SentenceTransformer
import os

class LocalEmbedder:
    def __init__(self):
        # We use BGE-Small because it is:
        # 1. Very accurate for retrieval
        # 2. Very small (only 384 dimensions)
        # 3. Fast enough to run on a CPU without lag
        print("📥 Loading Embedding Model (CPU)...")
        
        # device='cpu' is CRITICAL here to save your GPU for the LLM
        self.model = SentenceTransformer('BAAI/bge-small-en-v1.5', device='cpu')
        print("✅ Embedding Model Loaded.")

    def get_embedding(self, text):
        """
        Converts a text string into a list of 384 floats.
        """
        if not text:
            return []
            
        # .tolist() converts the numpy array to a standard Python list
        # so it can be sent to PostgreSQL
        return self.model.encode(text).tolist()

# Singleton instance for easy import
# This prevents reloading the model every time we import this file
embedder_instance = LocalEmbedder()