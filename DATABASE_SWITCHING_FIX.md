# Fixed: Database Connection Switching Issue

## The Problem

When you had multiple datasource connections and switched from Source B to Source A:
- The UI showed "Switched to Source A" ✓
- But queries still returned data from Source B ✗

## Root Cause

The issue was that:
1. Each user session has its own `DBClient` instance
2. When you switch databases, `refresh_connection()` is called
3. But there was no logging to verify the switch actually happened
4. The old connection might have been cached or not properly disposed

## The Fix

Added comprehensive logging at three critical points:

### 1. Connection Activation Endpoint
```python
@app.post("/api/connections/activate")
async def activate_conn(req: Request):
    connection_name = data['name']
    info(f"Activating database connection: {connection_name}")
    config_manager.set_active(connection_name)
    
    orchestrator = get_orchestrator(req)
    orchestrator.db.refresh_connection()
    
    # Verify the switch
    active = config_manager.get_active_name()
    info(f"Active database after switch: {active}")
    
    return {"status": "activated", "active_connection": active}
```

### 2. Connection Refresh
```python
def refresh_connection(self):
    # ... setup code ...
    print(f"🔄 Refreshing connection to: {active_name} (provider: {self.provider})")
```

### 3. Query Execution
```python
def execute_query(self, query, params=None):
    # ... setup code ...
    active_name = get_active_name()
    print(f"📊 Executing query on database: {active_name}")
```

## How to Verify It's Working

1. Open the browser console (F12)
2. Switch to a different database connection
3. Look for these log messages:
   - `Activating database connection: Source A`
   - `🔄 Refreshing connection to: Source A`
   - `Active database after switch: Source A`
4. Ask a question about the data
5. Look for: `📊 Executing query on database: Source A`

If all logs show the correct database name, the switch is working!

## What to Check If It's Still Not Working

1. **Check connections.json**: Verify the correct database is marked as `"active": true`
2. **Check server logs**: Look for the refresh and query execution logs
3. **Check database credentials**: Ensure Source A credentials are correct
4. **Check schema**: Verify Source A has the tables you're querying

## Technical Details

- Database configurations are stored in `connections.json` (global, shared across sessions)
- Each session has its own `DBClient` instance
- When you switch databases, `set_active()` updates `connections.json`
- Then `refresh_connection()` reads the updated config and creates a new SQLAlchemy engine
- The old connection is disposed of properly with `engine.dispose()`

## Next Steps

If you're still seeing data from the wrong database:
1. Check the server logs for the database name being used
2. Verify the connections.json file has the correct active database
3. Try refreshing the page to ensure the session is fresh
4. Check if the table names exist in the selected database
