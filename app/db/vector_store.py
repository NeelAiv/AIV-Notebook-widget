import os
import hashlib
import time
import psycopg2
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector
from pgvector import Vector


def _resolve_embedding_dim() -> int:
    env = os.environ.get("EMBEDDING_DIMENSION", "").strip()
    if env:
        d = int(env)
    else:
        from app.core.embedder import embedder_instance

        d = embedder_instance.dimension
    if not (32 <= d <= 4096):
        raise ValueError("embedding dimension must be between 32 and 4096")
    return d


class LocalVectorStore:
    """RAG vector storage backed by PostgreSQL + pgvector."""

    def __init__(self):
        self._dsn = os.environ.get(
            "RAG_DATABASE_URL",
            "postgresql://rag:ragsecret@127.0.0.1:5432/rag",
        )
        self._dim = _resolve_embedding_dim()
        self._conn = None

    def _connect(self):
        last_err = None
        for _ in range(45):
            try:
                conn = psycopg2.connect(self._dsn)
                register_vector(conn)
                return conn
            except Exception as e:
                last_err = e
                time.sleep(1)
        raise RuntimeError(
            f"Could not connect to RAG database (RAG_DATABASE_URL). Last error: {last_err}"
        )

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._connect()
            self._ensure_schema(self._conn)
        return self._conn

    def _ensure_schema(self, conn):
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        finally:
            conn.autocommit = False

        dim = self._dim
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS rag_workspace_chunks (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    chunk_text TEXT NOT NULL,
                    embedding vector({dim})
                )
                """
            )
            conn.commit()

        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS rag_workspace_chunks_embedding_hnsw
                        ON rag_workspace_chunks
                        USING hnsw (embedding vector_cosine_ops)
                        """
                    )
                except Exception:
                    try:
                        cur.execute(
                            """
                            CREATE INDEX IF NOT EXISTS rag_workspace_chunks_embedding_ivf
                            ON rag_workspace_chunks
                            USING ivfflat (embedding vector_cosine_ops)
                            WITH (lists = 100)
                            """
                        )
                    except Exception:
                        pass
        finally:
            conn.autocommit = False

    def _generate_id(self, source_name: str, chunk_text: str, session_id: str) -> str:
        content_signature = f"{session_id}::{source_name}::{chunk_text.strip()}"
        return hashlib.sha256(content_signature.encode("utf-8")).hexdigest()

    def add_chunks(
        self,
        source_name: str,
        chunks: list[str],
        embeddings: list[list[float]] | None = None,
        session_id: str = "default",
    ):
        if not chunks:
            return

        rows = []
        for i, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk:
                continue
            chunk_id = self._generate_id(source_name, chunk, session_id)
            emb = None
            if embeddings and i < len(embeddings):
                emb = embeddings[i]
            if not emb:
                continue
            if len(emb) != self._dim:
                print(
                    f"RAG skip chunk: embedding dim {len(emb)} != expected {self._dim}"
                )
                continue
            rows.append((chunk_id, source_name, session_id, chunk, Vector(emb)))

        if not rows:
            return

        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rag_workspace_chunks WHERE source = %s AND session_id = %s",
                    (source_name, session_id),
                )
                execute_values(
                    cur,
                    "INSERT INTO rag_workspace_chunks (id, source, session_id, chunk_text, embedding) VALUES %s",
                    rows,
                    template="(%s, %s, %s, %s, %s)",
                )
                conn.commit()
        except Exception as e:
            print(f"Error indexing to pgvector: {e}")

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
        session_id: str = "default",
    ):
        _ = where  # reserved for future metadata filters (Chroma API compatibility)

        if not query_embedding or len(query_embedding) != self._dim:
            return []

        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM rag_workspace_chunks WHERE session_id = %s",
                    (session_id,),
                )
                (cnt,) = cur.fetchone()
                if not cnt:
                    return []

                cur.execute(
                    """
                    SELECT source, chunk_text
                    FROM rag_workspace_chunks
                    WHERE session_id = %s
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (session_id, Vector(query_embedding), n_results),
                )
                return [
                    {"source_name": src, "chunk_text": txt}
                    for src, txt in cur.fetchall()
                ]
        except Exception as e:
            print(f"pgvector search error: {e}")
            return []

    def list_sources(self) -> list[str]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT source FROM rag_workspace_chunks ORDER BY source"
            )
            return [r[0] for r in cur.fetchall() if r[0]]

    def delete_by_source(self, source_name: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM rag_workspace_chunks WHERE source = %s", (source_name,)
            )
            conn.commit()


vector_store = LocalVectorStore()
