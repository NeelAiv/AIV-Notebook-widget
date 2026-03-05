from fastapi import FastAPI, Request, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi import UploadFile, File
import uvicorn
import sys
import os
import json
from io import StringIO
import datetime
import nbformat
import base64
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell, new_output


# Custom Modules - Ensure these exist in app/db/
from app.db import config_manager, history_manager
from app.orchestrator import IncidentOrchestrator
from app.session_manager import session_manager
from app.request_models import QueryRequest
from app.utils.file_parser import extract_text_from_file, is_structured_file, is_unstructured_file, extract_structured_metadata

app = FastAPI(title="InsightEdge AI Notebook")

# ---------------------------------------------------------------------------
# Helper: get the per-session orchestrator from the X-Session-ID header
# Falls back to a shared "default" session if no header is present.
# ---------------------------------------------------------------------------
def get_orchestrator(request: Request) -> IncidentOrchestrator:
    session_id = request.headers.get("X-Session-ID", "default")
    return session_manager.get_orchestrator(session_id)

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
async def run_ai_query(req: QueryRequest, request: Request):
    orchestrator = get_orchestrator(request)
    try:
        # 1. If user attached text/csv files via chat, set them as the active context
        if req.datasets:
            parsed_datasets = []
            last_filename = ''
            last_file_bytes = None
            for d in req.datasets:
                filename = d.get('filename', '')
                content_raw = d.get('content', '')
                last_filename = filename
                
                # Check if frontend sent base64 (DataURL)
                if content_raw.startswith('data:'):
                    try:
                        b64_data = content_raw.split(',', 1)[1]
                        file_bytes = base64.b64decode(b64_data)
                        last_file_bytes = file_bytes
                        content_text = extract_text_from_file(file_bytes, filename)
                    except Exception as e:
                        content_text = f"Error decoding {filename}: {str(e)}"
                else:
                    content_text = content_raw
                    
                parsed_datasets.append(f"--- File: {filename} ---\n{content_text}")
                
            combined_text = "\n\n".join(parsed_datasets)
            
            # Smart context setting based on file type
            if is_structured_file(last_filename) and last_file_bytes:
                metadata = extract_structured_metadata(last_file_bytes, last_filename)
                orchestrator.set_file_context(combined_text, metadata=metadata, file_type='structured', filename=last_filename)
            elif is_unstructured_file(last_filename):
                orchestrator.set_file_context(combined_text, file_type='unstructured', filename=last_filename)
                # Auto-index into RAG for unstructured files
                from app.db.vector_store import vector_store as vs
                try:
                    chunks = [c.strip() for c in combined_text.split('\n') if c.strip()]
                    embeddings = []
                    valid_chunks = []
                    for chunk in chunks[:500]:
                        try:
                            vec = orchestrator.embedder.get_embedding(chunk)
                            valid_chunks.append(chunk)
                            embeddings.append(vec)
                        except: pass
                    if valid_chunks:
                        vs.add_chunks(last_filename, valid_chunks, embeddings)
                        print(f"\u2705 Auto-indexed {last_filename} into RAG ({len(valid_chunks)} chunks)")
                except Exception as e:
                    print(f"Auto-RAG indexing failed: {e}")
            else:
                orchestrator.set_file_context(combined_text, filename=last_filename)

        # 2. Retrieve images from chat history if current request has none
        active_images = list(req.images) if req.images else []
        if not active_images and req.chat_history:
            for msg in reversed(req.chat_history):
                if isinstance(msg, dict) and msg.get("images"):
                    active_images = msg["images"]
                    break

        # Pass all arguments to the per-session Orchestrator
        result = orchestrator.route_and_execute(
            req.prompt, 
            req.notebook_cells, 
            req.variables,
            req.chat_history,
            images=active_images,
            is_modification=req.is_modification,
            original_code=req.original_code,
            active_cell_id=req.active_cell_id,
            use_db_context=req.use_db_context
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

from app.db.vector_store import vector_store

def process_and_index_rag(text_data: str, source_name: str, session_id: str = "default"):
    """Runs in the background: Chunks text, gets embeddings, saves to ChromaDB"""
    orchestrator = session_manager.get_orchestrator(session_id)
    chunks = text_data.split('\n')
    valid_chunks = []
    embeddings = []
    
    for chunk in chunks:
        if not chunk.strip(): continue
        try:
            vec = orchestrator.embedder.get_embedding(chunk)
            valid_chunks.append(chunk)
            embeddings.append(vec)
        except Exception as e:
            print(f"Error embedding chunk: {e}")
            
    vector_store.add_chunks(source_name, valid_chunks, embeddings)
    print(f"✅ Finished indexing {source_name} for RAG into ChromaDB!")

def process_and_index_table(table_name: str, session_id: str = "default"):
    """Retrieves all rows from a DB table, embeds them, and saves to ChromaDB."""
    orchestrator = session_manager.get_orchestrator(session_id)
    print(f"Starting to index table '{table_name}'...")
    db = orchestrator.db
    if not db.engine:
        print("No active DB connection to index table.")
        return

    # Basic fetch (we assume table size is manageable for a demo. In production, paginate)
    query = f"SELECT * FROM {table_name}"
    rows = db.execute_query(query)
    
    if not rows:
        print(f"⚠️ Table {table_name} is empty or unreadable.")
        return

    valid_chunks = []
    embeddings = []
    
    for row in rows:
        # Convert dictionary row into a clean string representation
        # Ex: "id: 1, name: parth, product: Apple"
        row_str = ", ".join([f"{k}: {v}" for k, v in row.items()])
        try:
            vec = orchestrator.embedder.get_embedding(row_str)
            valid_chunks.append(row_str)
            embeddings.append(vec)
        except Exception:
            continue
            
    vector_store.add_chunks(table_name, valid_chunks, embeddings)
    print(f"✅ Finished indexing table '{table_name}' for RAG into ChromaDB!")

@app.post("/api/index_rag")
async def trigger_rag_indexing(req: Request, background_tasks: BackgroundTasks):
    data = await req.json()
    source_name = data.get('source_name', 'unknown_file')
    orchestrator = get_orchestrator(req)
    text_content = orchestrator.active_file_context  # The file they just uploaded
    
    if not text_content:
        return {"status": "error", "message": "No active file context found to index."}
    
    # Send the heavy lifting to the background so the API returns instantly
    session_id = req.headers.get("X-Session-ID", "default")
    background_tasks.add_task(process_and_index_rag, text_content, source_name, session_id)
    
    return {"status": "indexing_started", "message": f"Indexing {source_name} in the background..."}

@app.post("/api/index_table")
async def trigger_table_indexing(req: Request, background_tasks: BackgroundTasks):
    data = await req.json()
    table_name = data.get('table_name')
    if not table_name:
        return {"status": "error", "message": "No table name provided."}
    session_id = req.headers.get("X-Session-ID", "default")
    background_tasks.add_task(process_and_index_table, table_name, session_id)
    return {"status": "indexing_started", "message": f"Indexing table '{table_name}' in the background..."}

@app.get("/api/vector_memory")
async def get_vector_memory():
    """Returns a list of all unique data sources currently in the ChromaDB RAG."""
    try:
        data = vector_store.collection.get()
        metas = data.get("metadatas", [])
        
        sources = set()
        for m in metas:
            if m and "source" in m:
                sources.add(m["source"])
                
        return {"sources": list(sources)}
    except Exception as e:
        return {"sources": [], "error": str(e)}

@app.delete("/api/vector_memory/{source_name}")
async def delete_vector_memory(source_name: str):
    """Deletes a specific data source from the ChromaDB RAG."""
    try:
        vector_store.collection.delete(where={"source": source_name})
        return {"status": "success", "message": f"Deleted '{source_name}' from memory."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tables")
async def get_db_tables(req: Request):
    """Returns the list of tables from the active connection to power the Semantic Search UI."""
    db = get_orchestrator(req).db
    if not db.engine:
        return {"tables": []}
    schema = db.get_schema()
    tables = set()
    for row in schema:
        tables.add(row['table_name'])
    return {"tables": list(tables)}

@app.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...), request: Request = None):
    """
    Uploads a file, extracts text, and sets it as context for the user's session Orchestrator.
    """
    orchestrator = get_orchestrator(request)
    ALLOWED_EXTENSIONS = {
        ".txt", ".pdf", ".docx", ".csv", ".py", ".js", ".json", ".ipynb", 
        ".html", ".css", ".md", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp"
    }
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {ALLOWED_EXTENSIONS}")

    try:
        content = await file.read()
        extracted_text = extract_text_from_file(content, filename)
        
        # Smart context setting based on file type
        if is_structured_file(filename):
            metadata = extract_structured_metadata(content, filename)
            orchestrator.set_file_context(extracted_text, metadata=metadata, file_type='structured', filename=filename)
            return {
                "status": "success",
                "filename": filename,
                "message": f"Structured file uploaded. AI will use metadata ({metadata.split(chr(10))[1] if chr(10) in metadata else 'summary'}) instead of full data for smart analysis."
            }
        elif is_unstructured_file(filename):
            orchestrator.set_file_context(extracted_text, file_type='unstructured', filename=filename)
            # Auto-index into ChromaDB for RAG (shared across all sessions)
            session_id = request.headers.get("X-Session-ID", "default") if request else "default"
            process_and_index_rag(extracted_text, filename, session_id)
            return {
                "status": "success",
                "filename": filename,
                "message": f"Document uploaded and auto-indexed for semantic search. AI will use RAG to find relevant sections when you ask questions."
            }
        else:
            orchestrator.set_file_context(extracted_text, filename=filename)
            return {
                "status": "success",
                "filename": filename,
                "message": "File uploaded and processed successfully. You can now ask questions about it."
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")
        
@app.get("/api/llm/settings")
async def get_llm_settings(request: Request):
    """Returns current LLM configuration (reads from the session's orchestrator)"""
    return get_orchestrator(request).llm.config

@app.post("/api/llm/settings")
async def save_llm_settings(req: Request):
    """Saves new LLM configuration (applies to the calling session's orchestrator)"""
    data = await req.json()
    get_orchestrator(req).llm.update_config(data)
    return {"status": "success", "message": "LLM Settings updated"}

@app.get("/api/sessions")
async def get_active_sessions():
    """Admin endpoint: shows how many sessions are active."""
    return {
        "active_sessions": session_manager.active_count,
        "session_ids": [s[:8] + "..." for s in session_manager.session_ids()]
    }
@app.get("/api/connections")
async def list_conns(): return config_manager.get_all_configs()

@app.post("/api/connections")
async def add_conn(req: Request):
    data = await req.json()
    name = data.get('name', '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="Connection name is required.")

    # 1. Save config TEMPORARILY to disk so DBClient can read it
    config_manager.save_config(name, data)

    orchestrator = get_orchestrator(req)
    
    # 2. Test the connection immediately
    orchestrator.db.refresh_connection()

    # 3. If it failed (engine is None), remove the bad config and return error
    if orchestrator.db.engine is None:
        config_manager.delete_config(name)
        # Re-activate whatever was previously active (refresh again)
        orchestrator.db.refresh_connection()
        raise HTTPException(
            status_code=400,
            detail=f"Could not connect to '{name}'. Check your Connection URL and credentials."
        )

    return {"status": "saved", "active": True}
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
 
        # Use the existing DB client inside the session's orchestrator
        # This uses whatever connection is currently 'Active' in config_manager
        orchestrator = get_orchestrator(req)
        results = orchestrator.db.execute_query(sql_query)

        return {"status": "success", "data": results}

    except Exception as e:

        return {"status": "error", "message": str(e)}
 
@app.post("/api/connections/activate")
async def activate_conn(req: Request):
    data = await req.json()
    config_manager.set_active(data['name'])
    get_orchestrator(req).db.refresh_connection()
    return {"status": "activated"}

@app.get("/api/history")
async def get_hist(): return history_manager.get_all_history()

@app.delete("/api/history/{item_id}")
async def delete_history(item_id: int):
    history_manager.delete_history_item(item_id)
    return {"status": "deleted"}

# In main.py
@app.delete("/api/notebooks/{name}")
async def delete_notebook(name: str):
    filepath = f'notebooks/{name}.ipynb'
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Notebook not found")

@app.post("/api/notebooks/save")
async def save_notebook(req: Request):
    try:
        data = await req.json()
        name = data.get('name')
        cells_data = data.get('cells', [])
        chat_data = data.get('chat_data')
        
        if not name:
            raise HTTPException(status_code=400, detail="Notebook name is required.")

        # --- LOGIC TO BUILD A VALID JUPYTER NOTEBOOK ---
        
        # 1. Create a new, empty notebook structure
        nb = new_notebook()
        
        if chat_data:
            nb.metadata['chat_data'] = chat_data
        
        # 2. Loop through the cell data from the frontend and convert each one
        for cell_data in cells_data:
            cell_type = cell_data.get("cell_type")
            source = cell_data.get("source", "")
            
            if cell_type == "code":
                # Create a new code cell
                code_cell = new_code_cell(source=source)
                
                # Handle outputs (this is a simplified conversion)
                # A true .ipynb output is complex, but this makes it readable.
                if "output" in cell_data and cell_data["output"]:
                    # Create a standard display_data output object
                    output_node = new_output(
                        output_type="display_data",
                        data={"text/html": cell_data["output"]}
                    )
                    code_cell.outputs.append(output_node)
                    
                nb.cells.append(code_cell)
                
            elif cell_type == "markdown":
                # Create a new markdown cell
                md_cell = new_markdown_cell(source=source)
                nb.cells.append(md_cell)

        # 3. Define the filename with the correct .ipynb extension
        filepath = f'notebooks/{name}.ipynb'
        
        # 4. Use the nbformat library to write the file correctly
        with open(filepath, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
            
        print(f"✅ Successfully saved notebook to: {filepath}")
        return {"status": "saved", "filename": f"{name}.ipynb"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save notebook: {str(e)}")
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
        
    old_path = f'notebooks/{old_name}.ipynb'
    new_path = f'notebooks/{new_name}.ipynb'
    
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
        
        name = file.filename.replace('.ipynb', '')
        filepath = f'notebooks/{name}.ipynb'
        
        counter = 1
        while os.path.exists(filepath):
            filepath = f'notebooks/{name}_{counter}.ipynb'
            counter += 1
        
        with open(filepath, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
            
        return {"status": "uploaded", "name": name, "cells_count": len(nb.cells)}
    except Exception as e:
        print(f"!!! ERROR SAVING NOTEBOOK: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write .ipynb file: {str(e)}")

# List all saved notebooks
@app.get("/api/notebooks")
async def list_notebooks():
    nb_list = []
    if os.path.exists('notebooks'):
        for filename in os.listdir('notebooks'):
            if filename.endswith('.ipynb'): 
                path = os.path.join('notebooks', filename)
                mtime = os.path.getmtime(path)
                dt = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                
                cell_count = 0
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        nb = nbformat.read(f, as_version=4)
                        cell_count = len(nb.cells)
                except Exception as e:
                    print(f"Warning: Could not read cell count from {filename}: {e}")

                nb_list.append({
                    "display_name": filename.replace('.ipynb', ''),
                    "timestamp": dt,
                    "cell_count": cell_count
                })
    
    # Sort and remove duplicates by display_name
    unique_nbs = {}
    for nb in sorted(nb_list, key=lambda x: x['timestamp'], reverse=True):
        if nb['display_name'] not in unique_nbs:
            unique_nbs[nb['display_name']] = nb
            
    return list(unique_nbs.values())

# ⭐ NEW ENDPOINT: Open a specific saved notebook
@app.get("/api/notebooks/{name}")
async def get_notebook(name: str):
    filepath = f'notebooks/{name}.ipynb'
    if not os.path.exists(filepath):
        return {"error": "Notebook not found"}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
            
        cells = []
        for cell in nb.cells:
            cell_data = {
                "cell_type": cell.cell_type,
                "source": cell.source,
                "output": ""
            }
            if cell.cell_type == 'code' and hasattr(cell, 'outputs'):
                outputs = []
                for output in cell.outputs:
                    if output.output_type == 'display_data' and 'text/html' in output.data:
                        outputs.append(output.data['text/html'])
                    elif output.output_type == 'stream':
                        outputs.append(output.text)
                    elif output.output_type == 'execute_result':
                        outputs.append(str(output.data.get('text/plain', '')))
                cell_data["output"] = '\n'.join(outputs)
            cells.append(cell_data)
            
        chat_data = nb.metadata.get('chat_data')
        return {"cells": cells, "chat_data": chat_data}
        
    except Exception as e:
        return {"error": f"Failed to read notebook: {str(e)}"}

@app.get("/api/notebooks/{name}/download")
async def download_notebook(name: str):
    filepath = f'notebooks/{name}.ipynb'
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Notebook not found")
        
    return FileResponse(filepath, media_type='application/x-ipynb+json', filename=f"{name}.ipynb")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8090)


