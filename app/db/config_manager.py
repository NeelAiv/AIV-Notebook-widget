import json
import os

CONFIG_FILE = "connections.json"

def get_all_configs():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_config(name, details):
    configs = get_all_configs()
    # Deactivate others
    for k in configs:
        configs[k]["active"] = False
    
    details["active"] = True
    configs[name] = details
    with open(CONFIG_FILE, "w") as f:
        json.dump(configs, f, indent=4)

def get_active_name():
    configs = get_all_configs()
    for name, detail in configs.items():
        if detail.get("active"):
            return name
    return None

def set_active(name):
    configs = get_all_configs()
    for k in configs:
        configs[k]["active"] = (k == name)
    with open(CONFIG_FILE, "w") as f:
        json.dump(configs, f, indent=4)

def delete_config(name):
    """Delete a database connection by name"""
    configs = get_all_configs()
    
    if name not in configs:
        return False
    
    was_active = configs[name].get('active', False)
    del configs[name]
    
    # If deleted connection was active, make another one active
    if was_active and len(configs) > 0:
        first_key = list(configs.keys())[0]
        configs[first_key]['active'] = True
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(configs, f, indent=4)
    
    return True
