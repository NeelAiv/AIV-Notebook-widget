import json
import os
from datetime import datetime

HISTORY_FILE = "history.json"


def _load() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        # migrate old dict-keyed format — merge all session entries into one list
        merged = []
        for entries in data.values():
            if isinstance(entries, list):
                merged.extend(entries)
        merged.sort(key=lambda x: x.get("id", 0))
        return merged
    except Exception:
        return []


def _save(history: list) -> None:
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)


def get_all_history() -> list:
    return _load()


def add_to_history(query: str, answer: str, tool: str, notebook_context: str = "", **_ignored):
    history = _load()
    entry = {
        "id": len(history) + 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "answer": answer,
        "tool": tool,
        "notebook": notebook_context,
    }
    history.insert(0, entry)
    _save(history)


def delete_history_item(item_id: int, **_ignored) -> bool:
    history = _load()
    history = [h for h in history if h.get("id") != item_id]
    _save(history)
    return True
