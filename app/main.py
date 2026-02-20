from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi import UploadFile, File
import uvicorn
import sys
import os
import json
from io import StringIO
import datetime
import nbformat 


# Custom Modules - Ensure these exist in app/db/
from app.db import config_manager, history_manager
from app.orchestrator import IncidentOrchestrator
from app.request_models import QueryRequest
from app.utils.file_parser import extract_text_from_file # Import file parser

app = FastAPI(title="InsightEdge AI Notebook")
orchestrator = IncidentOrchestrator()

# Create notebooks directory if not exists
if not os.path.exists('notebooks'):
    os.makedirs('notebooks')

# PERSISTENT KERNEL STATE


app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/health")
async def health(): return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()



# --- main.py --- (Focus on the /query endpoint)

@app.post("/query")
async def run_ai_query(req: QueryRequest):
    try:
        # Pass all 3 arguments to the Orchestrator
        result = orchestrator.route_and_execute(
            req.prompt, 
            req.notebook_cells, 
            req.variables,
            req.chat_history,
            is_modification=req.is_modification,
            original_code=req.original_code,
            active_cell_id=req.active_cell_id
        )
        
        history_manager.add_to_history(
            req.prompt, 
            result['answer'], 
            result['tool_used'], 
            str(req.notebook_cells)
        )
        return result
    except Exception as e:
        print(f"ERROR IN /query: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@app.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...)):
    """
    Uploads a file, extracts text, and sets it as context for the Orchestrator.
    """
    ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {ALLOWED_EXTENSIONS}")

    try:
        content = await file.read()
        extracted_text = extract_text_from_file(content, filename)
        
        # Set context in Orchestrator
        orchestrator.set_file_context(extracted_text)
        
        return {
            "status": "success",
            "filename": filename,
            "message": "File uploaded and processed successfully. You can now ask questions about it."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

@app.get("/api/connections")
async def list_conns(): return config_manager.get_all_configs()

@app.post("/api/connections")
async def add_conn(req: Request):
    data = await req.json()
    config_manager.save_config(data['name'], data)
    orchestrator.db.refresh_connection()
    return {"status": "saved"}
# --- main.py ---
 
@app.post("/api/execute_sql")

async def execute_sql_bridge(req: Request):

    """

    Executes SQL sent from the browser notebook via the Server's active connection.

    """

    try:

        data = await req.json()

        sql_query = data.get("sql")

        if not sql_query:

            return {"status": "error", "message": "No SQL provided"}
 
        # Use the existing DB client inside the orchestrator

        # This uses whatever connection is currently 'Active' in config_manager

        results = orchestrator.db.execute_query(sql_query)

        return {"status": "success", "data": results}

    except Exception as e:

        return {"status": "error", "message": str(e)}
 
@app.post("/api/connections/activate")
async def activate_conn(req: Request):
    data = await req.json()
    config_manager.set_active(data['name'])
    orchestrator.db.refresh_connection()
    return {"status": "activated"}

@app.get("/api/history")
async def get_hist(): return history_manager.get_all_history()

@app.delete("/api/history/{item_id}")
async def delete_history(item_id: int):
    history_manager.delete_history_item(item_id)
    return {"status": "deleted"}

@app.delete("/api/notebooks/{name}")
async def delete_notebook(name: str):
    filepath = f'notebooks/{name}.json'
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Notebook not found")

@app.post("/api/notebooks/save")
async def save_notebook(req: Request):
    data = await req.json()
    name = data['name']
    cells = data['cells']
    # Multi-chat data (new format)
    chat_data = data.get('chat_data', {})
    # Legacy flat chat_history (backward compatibility)
    chat_history = data.get('chat_history', [])
    
    filepath = f'notebooks/{name}.json'

    # Prepare data structure with both new and legacy chat formats
    notebook_data = {
        "cells": cells,
        "chat_data": chat_data,
        "chat_history": chat_history
    }
    
    with open(filepath, 'w') as f:
        json.dump(notebook_data, f)
    return {"status": "saved"}
@app.delete("/api/connections/{name}")
async def delete_db_connection(name: str):
    try:
        print(f"🗑️ DELETE REQUEST for: {name}")
        
        # Use config_manager's delete function
        success = config_manager.delete_config(name)
        
        if not success:
            print(f"❌ Connection '{name}' not found")
            raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
        
        print(f"✅ Successfully deleted '{name}'")
        
        # Refresh orchestrator connection if there are remaining connections
        remaining = config_manager.get_all_configs()
        if len(remaining) > 0:
            try:
                orchestrator.db.refresh_connection()
                print(f"🔄 Refreshed orchestrator to new active connection")
            except Exception as e:
                print(f"⚠️ Could not refresh orchestrator: {e}")
        
        return {"status": "deleted", "name": name}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ DELETE FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")
@app.put("/api/notebooks/rename")
async def rename_notebook(req: Request):
    data = await req.json()
    old_name = data.get('old_name')
    new_name = data.get('new_name')
    
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="Missing old_name or new_name")
        
    old_path = f'notebooks/{old_name}.json'
    new_path = f'notebooks/{new_name}.json'
    
    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail="Notebook not found")
    if os.path.exists(new_path):
        raise HTTPException(status_code=409, detail="Notebook with this name already exists")
        
    try:
        os.rename(old_path, new_path)
        return {"status": "renamed", "new_name": new_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename failed: {str(e)}")

# Upload .ipynb files
@app.post("/api/notebooks/upload")
async def upload_notebook(file: UploadFile = File(...)):
    if not file.filename.endswith('.ipynb'):
        return {"error": "Only .ipynb files are allowed"}
    
    try:
        content = await file.read()
        nb = nbformat.reads(content.decode('utf-8'), as_version=4)
        
        converted_cells = []
        for cell in nb.cells:
            cell_data = {
                "cell_type": cell.cell_type,
                "source": cell.source,
                "outputs": []
            }
            
            if cell.cell_type == 'code' and hasattr(cell, 'outputs'):
                for output in cell.outputs:
                    if output.output_type == 'stream':
                        cell_data["outputs"].append(output.text)
                    elif output.output_type == 'execute_result':
                        cell_data["outputs"].append(str(output.data.get('text/plain', '')))
            
            converted_cells.append(cell_data)
        
        name = file.filename.replace('.ipynb', '')
        filepath = f'notebooks/{name}.json'
        
        counter = 1
        while os.path.exists(filepath):
            filepath = f'notebooks/{name}_{counter}.json'
            counter += 1
        
        with open(filepath, 'w') as f:
            json.dump(converted_cells, f)
        
        return {"status": "uploaded", "name": name, "cells_count": len(converted_cells)}
    
    except Exception as e:
        return {"error": f"Failed to process notebook: {str(e)}"}


# List all saved notebooks
@app.get("/api/notebooks")
async def list_notebooks():
    nb_list = []
    if os.path.exists('notebooks'):
        for filename in os.listdir('notebooks'):
            if filename.endswith('.json'):
                path = os.path.join('notebooks', filename)
                # This gets the time the file was saved
                mtime = os.path.getmtime(path)
                dt = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                nb_list.append({
                    "display_name": filename.replace('.json', ''),
                    "timestamp": dt
                })
    # Sort so newest is at the top
    return sorted(nb_list, key=lambda x: x['timestamp'], reverse=True)

# ⭐ NEW ENDPOINT: Open a specific saved notebook
@app.get("/api/notebooks/{name}")
async def get_notebook(name: str):
    filepath = f'notebooks/{name}.json'
    if not os.path.exists(filepath):
        return {"error": "Notebook not found"}
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    # Backward compatibility
    if isinstance(data, list):
        return {"cells": data, "chat_history": []}
        
    return data


# Add this new endpoint for uploading .ipynb files
@app.post("/api/notebooks/upload")
async def upload_notebook(file: UploadFile = File(...)):
    if not file.filename.endswith('.ipynb'):
        return {"error": "Only .ipynb files are allowed"}
    
    try:
        # Read the uploaded file
        content = await file.read()
        nb = nbformat.reads(content.decode('utf-8'), as_version=4)
        
        # Convert Jupyter notebook cells to your internal format
        converted_cells = []
        for cell in nb.cells:
            cell_data = {
                "type": cell.cell_type,  # 'code' or 'markdown'
                "content": cell.source,
                "output": ""
            }
            
            # If it's a code cell with outputs, capture them
            if cell.cell_type == 'code' and hasattr(cell, 'outputs'):
                outputs = []
                for output in cell.outputs:
                    if output.output_type == 'stream':
                        outputs.append(output.text)
                    elif output.output_type == 'execute_result':
                        outputs.append(str(output.data.get('text/plain', '')))
                    elif output.output_type == 'error':
                        outputs.append(f"Error: {output.ename}: {output.evalue}")
                cell_data["output"] = '\n'.join(outputs)
            
            converted_cells.append(cell_data)
        
        # Save with original filename (without .ipynb extension)
        name = file.filename.replace('.ipynb', '')
        filepath = f'notebooks/{name}.json'
        
        # Handle duplicate names
        counter = 1
        while os.path.exists(filepath):
            filepath = f'notebooks/{name}_{counter}.json'
            counter += 1
        
        with open(filepath, 'w') as f:
            json.dump(converted_cells, f)
        
        return {"status": "uploaded", "name": name, "cells_count": len(converted_cells)}
    
    except Exception as e:
        return {"error": f"Failed to process notebook: {str(e)}"}

# Modify the list_notebooks endpoint to show file type
@app.get("/api/notebooks")
async def list_notebooks():
    nb_list = []
    if os.path.exists('notebooks'):
        for filename in os.listdir('notebooks'):
            if filename.endswith('.json'):
                path = os.path.join('notebooks', filename)
                mtime = os.path.getmtime(path)
                dt = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                
                # Count cells
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                    
                    # Handle both list (legacy) and dict (new) formats
                    if isinstance(data, list):
                        cell_count = len(data)
                    else:
                        cell_count = len(data.get("cells", []))
                    
                    nb_list.append({
                        "display_name": filename.replace('.json', ''),
                        "timestamp": dt,
                        "cell_count": cell_count
                    })
                except Exception as e:
                    print(f"Error reading {filename}: {e}")
    
    return sorted(nb_list, key=lambda x: x['timestamp'], reverse=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8090)
