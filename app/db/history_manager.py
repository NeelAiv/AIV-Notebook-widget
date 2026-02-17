import json
import os
from datetime import datetime

HISTORY_FILE = "history.json"

def get_all_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def add_to_history(query, answer, tool, notebook_context=""):
    history = get_all_history()
    new_entry = {
        "id": len(history) + 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "answer": answer,
        "tool": tool,
        "notebook": notebook_context
    }
    # Add to start of list so newest is first
    history.insert(0, new_entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def delete_history_item(item_id: int):
    history = get_all_history()
    history = [h for h in history if h.get("id") != item_id]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)
    return True