"""
Session Manager
---------------
Maintains per-user Orchestrator instances so multiple users can work
simultaneously without their file contexts, uploaded data, or chat state
bleeding into each other.

Architecture:
  - Each browser session gets a unique SESSION_ID (UUID generated client-side,
    stored in sessionStorage, sent as X-Session-ID header on every request).
  - The SessionManager maps session IDs → independent IncidentOrchestrator instances.
  - DB connections are SHARED (connections.json is global); only file context
    and in-memory state is isolated.
  - Sessions expire after TTL_SECONDS of inactivity and are pruned automatically.
"""

import time
import threading
from typing import Dict, Optional


# Lazy import to avoid circular dependency
_OrchestratorClass = None

def _get_orchestrator_class():
    global _OrchestratorClass
    if _OrchestratorClass is None:
        from app.orchestrator import IncidentOrchestrator
        _OrchestratorClass = IncidentOrchestrator
    return _OrchestratorClass


class SessionManager:
    TTL_SECONDS = 3600        # 1 hour of inactivity → session expires
    MAX_SESSIONS = 50         # Safety cap — prevents memory exhaustion

    def __init__(self):
        self._sessions: Dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_orchestrator(self, session_id: str):
        """
        Returns the Orchestrator for this session, creating one if needed.
        Thread-safe. Automatically prunes expired sessions.
        """
        if not session_id or session_id == "default":
            session_id = "default"

        with self._lock:
            self._prune_expired()

            if session_id not in self._sessions:
                if len(self._sessions) >= self.MAX_SESSIONS:
                    # Evict the oldest idle session to make room
                    oldest = min(self._sessions, key=lambda k: self._sessions[k]["last_active"])
                    del self._sessions[oldest]
                    print(f"♻️  Session evicted (pool full): {oldest[:8]}…")

                OrchestratorClass = _get_orchestrator_class()
                self._sessions[session_id] = {
                    "orchestrator": OrchestratorClass(),
                    "created": time.time(),
                    "last_active": time.time(),
                }
                print(f"🆕 New session created: {session_id[:8]}… (total: {len(self._sessions)})")

            session = self._sessions[session_id]
            session["last_active"] = time.time()
            return session["orchestrator"]

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def session_ids(self):
        with self._lock:
            return list(self._sessions.keys())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _prune_expired(self):
        """Must be called while holding self._lock."""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s["last_active"] > self.TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]
            print(f"🗑️  Session expired & pruned: {sid[:8]}…")


# Module-level singleton — imported by main.py
session_manager = SessionManager()
