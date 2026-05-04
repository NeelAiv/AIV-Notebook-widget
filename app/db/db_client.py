import json
import time
import urllib.parse
from sqlalchemy import create_engine, text, inspect
from app.db.config_manager import get_all_configs, get_active_name

# Simple in-memory query cache: key → (result, timestamp)
_query_cache: dict = {}
_CACHE_TTL_SECONDS = 60  # cache SELECT results for 60 seconds

class DBClient:
    def __init__(self):
        self.engine = None
        self.provider = "postgresql"
        self.refresh_connection()

    def refresh_connection(self):
        """Reloads credentials from the active config and reconnects using SQLAlchemy."""
        if self.engine:
            self.engine.dispose()
            self.engine = None
        
        configs = get_all_configs()
        active_name = get_active_name()

        if not active_name:
            print("⚠️ No active database configuration found.")
            return

        conf = configs[active_name]
        self.provider = conf.get('provider', 'postgresql')
        
        print(f"🔄 Refreshing connection to: {active_name} (provider: {self.provider})")
        
        try:
            # NEW: If a direct Connection URL was provided, use it as-is
            direct_url = conf.get('url', '').strip()
            
            if direct_url:
                uri = direct_url
                # SQLAlchemy needs SQLAlchemy-style URLs, not JDBC-style.
                # Convert common jdbc: prefixes automatically.
                if uri.startswith('jdbc:mysql'):
                    uri = uri.replace('jdbc:mysql', 'mysql+pymysql', 1)
                elif uri.startswith('jdbc:postgresql'):
                    uri = uri.replace('jdbc:postgresql', 'postgresql+psycopg2', 1)
                elif uri.startswith('jdbc:sqlserver') or uri.startswith('jdbc:mssql'):
                    # jdbc:sqlserver://host:1433;databaseName=mydb
                    rest = uri.split('://', 1)[-1]
                    host_part = rest.split(';')[0]
                    db_name = ''
                    for seg in rest.split(';'):
                        if seg.lower().startswith('databasename='):
                            db_name = seg.split('=', 1)[1]
                    uri = f"mssql+pyodbc://{host_part}/{db_name}?driver=ODBC+Driver+17+for+SQL+Server"
                elif uri.startswith('jdbc:oracle'):
                    # jdbc:oracle:thin:@host:1521:SID  or  jdbc:oracle:thin:@//host:1521/service
                    rest = uri.replace('jdbc:oracle:thin:@//', '').replace('jdbc:oracle:thin:@', '')
                    uri = f"oracle+cx_oracle://{rest}"
                elif uri.startswith('jdbc:sqlite'):
                    uri = uri.replace('jdbc:sqlite', 'sqlite', 1)
                # Inject credentials if URL is bare (no user:pass in it)
                user = conf.get('user', '')
                pw = urllib.parse.quote_plus(conf.get('password', ''))
                if user and '@' not in uri.split('://', 1)[-1].split('/')[0]:
                    scheme, rest = uri.split('://', 1)
                    uri = f"{scheme}://{user}:{pw}@{rest}"
            else:
                # FALLBACK: Build from legacy host/port/database fields
                user = conf.get('user', '')
                pw = urllib.parse.quote_plus(conf.get('password', ''))
                host = conf.get('host', 'localhost')
                port = conf.get('port', '')
                db = conf.get('database', '')
                driver_map = {
                    'postgresql': 'postgresql+psycopg2',
                    'mysql':      'mysql+pymysql',
                    'mssql':      'mssql+pyodbc',
                    'oracle':     'oracle+cx_oracle',
                    'sqlite':     'sqlite',
                }
                driver = driver_map.get(self.provider, 'postgresql+psycopg2')
                if self.provider == 'sqlite':
                    uri = f"sqlite:///{db}"
                else:
                    port_str = f":{port}" if port else ""
                    uri = f"{driver}://{user}:{pw}@{host}{port_str}/{db}"

            # Connection timeout
            wait_time = conf.get('wait_time', 30)
            connect_args = {"connect_timeout": wait_time}
            
            self.engine = create_engine(uri, pool_pre_ping=True, connect_args=connect_args)
            
            # Test connection
            with self.engine.connect() as conn:
                pass
                
            print(f"✅ Connected to SQL Database: {active_name} [{self.provider}]")
                
        except Exception as e:
            print(f"❌ Failed to connect to {active_name}: {e}")
            self.engine = None

    def execute_query(self, query, params=None):
        if not self.engine:
            self.refresh_connection()
        if not self.engine:
            return []

        active_name = get_active_name()
        print(f"📊 Executing query on database: {active_name}")

        is_select = query.strip().upper().startswith("SELECT")

        # Cache SELECT queries for TTL seconds
        if is_select and not params:
            cache_key = f"{active_name}::{query.strip()}"
            cached = _query_cache.get(cache_key)
            if cached:
                result, ts = cached
                if time.time() - ts < _CACHE_TTL_SECONDS:
                    print(f"  ↳ Cache hit ({int(time.time()-ts)}s old)")
                    return result
                else:
                    del _query_cache[cache_key]
        
        try:
            # SQLAlchemy text() requires dicts/kwargs. 
            # If the user provides positional params or tuples (used by pgvector psycopg2 bindings),
            # we need to fallback to raw DBAPI execution:
            if isinstance(params, (list, tuple)):
                with self.engine.connect() as conn:
                    raw_conn = conn.connection
                    cursor = raw_conn.cursor()
                    cursor.execute(query, params)
                    if is_select:
                        columns = [col[0] for col in cursor.description]
                        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                        cursor.close()
                        return results
                    else:
                        if hasattr(raw_conn, 'commit'):
                            raw_conn.commit()
                        cursor.close()
                        return []
            else:
                with self.engine.connect() as conn:
                    result = conn.execute(text(query), params or {})
                    if is_select:
                        rows = [dict(mapping) for mapping in result.mappings().all()]
                        # Store in cache
                        if not params:
                            cache_key = f"{active_name}::{query.strip()}"
                            _query_cache[cache_key] = (rows, time.time())
                            # Evict old entries if cache grows large
                            if len(_query_cache) > 200:
                                oldest = sorted(_query_cache.items(), key=lambda x: x[1][1])[:50]
                                for k, _ in oldest:
                                    del _query_cache[k]
                        return rows
                    else:
                        conn.commit()
                        # Invalidate cache for this DB on writes
                        keys_to_del = [k for k in _query_cache if k.startswith(f"{active_name}::")]
                        for k in keys_to_del:
                            del _query_cache[k]
                        return []
        except Exception as e:
            print(f"❌ SQL Error: {e}")
            return []

    def get_schema(self):
        """Returns the table names and columns dynamically using SQLAlchemy Inspector."""
        if not self.engine: return []
        try:
            inspector = inspect(self.engine)
            schema_data = []
            
            # Universal schema extraction
            for tbl in inspector.get_table_names():
                for col in inspector.get_columns(tbl):
                    schema_data.append({
                        'table_name': tbl,
                        'column_name': col['name'],
                        'data_type': str(col['type'])
                    })
            return schema_data
        except Exception as e:
            print(f"❌ Error getting schema: {e}")
            return []
