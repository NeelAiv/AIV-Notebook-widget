import json
import os
from datetime import datetime

HISTORY_FILE = "history.json"

def get_all_history(session_id: str = "default"):
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                if session_id == "default": return data
                return []
            return data.get(session_id, [])
    except:
        return []

def add_to_history(query: str, answer: str, tool: str, notebook_context: str = "", session_id: str = "default"):
    history_dict = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                data = json.load(f)
                # Migrate old list-based history if it exists
                if isinstance(data, list):
                    history_dict = {"default": data}
                elif isinstance(data, dict):
                    history_dict = data
        except:
            pass
            
    session_history = history_dict.get(session_id, [])
    new_entry = {
        "id": len(session_history) + 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "answer": answer,
        "tool": tool,
        "notebook": notebook_context
    }
    # Add to start of list so newest is first
    session_history.insert(0, new_entry)
    history_dict[session_id] = session_history
    
    with open(HISTORY_FILE, "w") as f:
        json.dump(history_dict, f, indent=4)

def delete_history_item(item_id: int, session_id: str = "default"):
    history_dict = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    history_dict = {"default": data}
                elif isinstance(data, dict):
                    history_dict = data
        except:
            pass
            
    if session_id in history_dict:
        history_dict[session_id] = [h for h in history_dict[session_id] if h.get("id") != item_id]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history_dict, f, indent=4)
    return True