# List Tables by Database Type

When you ask "show my list of tables", the AI now generates database-specific code based on your active connection.

## MySQL

```python
df = await query_db('''SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()''')

if df is not None and not df.empty:
    print("Tables in database:")
else:
    print("No tables found")

df
```

**Key Points:**
- Uses `information_schema.TABLES` system table
- Filters by current database with `TABLE_SCHEMA = DATABASE()`
- Returns column name: `TABLE_NAME`

## PostgreSQL

```python
df = await query_db('''SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ''')

if df is not None and not df.empty:
    print("Tables in database:")
else:
    print("No tables found")

df
```

**Key Points:**
- Uses `information_schema.tables` system table
- Filters by schema (usually 'public')
- Returns column name: `table_name`

## SQLite

```python
df = await query_db('''SELECT name FROM sqlite_master WHERE type='table' ''')

if df is not None and not df.empty:
    print("Tables in database:")
else:
    print("No tables found")

df
```

**Key Points:**
- Uses `sqlite_master` system table
- Filters by `type='table'`
- Returns column name: `name`

## What Changed

The AI now:
1. Detects your database type (MySQL, PostgreSQL, SQLite, etc.)
2. Generates the correct query for that database
3. Includes this information in the system prompt

## How to Verify

When you ask "show my list of tables", check the server logs:
- Look for: `⚠️ DATABASE: MySQL` (or PostgreSQL/SQLite)
- This confirms the AI knows which database you're using

## If It Still Doesn't Work

1. **Check your database type**: Look at the connection info
2. **Verify permissions**: Your database user needs permission to query `information_schema` or `sqlite_master`
3. **Check for tables**: Make sure your database actually has tables
4. **Try manually**: Run the appropriate query above directly in a cell

## Example: MySQL

If you're connected to MySQL and ask "show my list of tables", you should get:

```
Tables in database:
┌────────────────────┐
│ TABLE_NAME         │
├────────────────────┤
│ raw_materials      │
│ products           │
│ sales_data         │
│ customers          │
└────────────────────┘
```
