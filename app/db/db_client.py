import json
import urllib.parse
from sqlalchemy import create_engine, text, inspect
from app.db.config_manager import get_all_configs, get_active_name

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
        
        try:
            user = conf.get('user', '')
            pw = urllib.parse.quote_plus(conf.get('password', ''))
            host = conf.get('host', 'localhost')
            port = conf.get('port', '')
            db = conf.get('database', '')
            
            # Map providers to SQLAlchemy database URLs
            driver_map = {
                'postgresql': 'postgresql+psycopg2',
                'mysql': 'mysql+pymysql',
                'mssql': 'mssql+pyodbc',
                'oracle': 'oracle+cx_oracle',
                'sqlite': 'sqlite'
            }
            driver = driver_map.get(self.provider, 'postgresql+psycopg2')
            
            if self.provider == 'sqlite':
                # db could be a simple file path for sqlite
                uri = f"sqlite:///{db}"
            else:
                port_str = f":{port}" if port else ""
                uri = f"{driver}://{user}:{pw}@{host}{port_str}/{db}"
            
            self.engine = create_engine(uri, pool_pre_ping=True)
            
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
        
        is_select = query.strip().upper().startswith("SELECT")
        
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
                        return [dict(mapping) for mapping in result.mappings().all()]
                    else:
                        conn.commit()
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
