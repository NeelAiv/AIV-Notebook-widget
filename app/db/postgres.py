import psycopg2
from psycopg2.extras import RealDictCursor
from app.db.config_manager import get_all_configs, get_active_name

class PostgresClient:
    def __init__(self):
        self.conn = None
        self.refresh_connection()

    def refresh_connection(self):
        """Reloads credentials from the active config and reconnects."""
        if self.conn:
            try: self.conn.close()
            except: pass
        
        configs = get_all_configs()
        active_name = get_active_name()

        if not active_name:
            print("⚠️ No active database configuration found.")
            return

        conf = configs[active_name]
        try:
            self.conn = psycopg2.connect(
                host=conf['host'],
                database=conf['database'],
                user=conf['user'],
                password=conf['password'],
                port=conf['port'],
                connect_timeout=5
            )
            self.conn.autocommit = True
            print(f"✅ Connected to Database: {active_name}")
        except Exception as e:
            print(f"❌ Failed to connect to {active_name}: {e}")
            self.conn = None

    def execute_query(self, query, params=None):
        if not self.conn or self.conn.closed != 0:
            self.refresh_connection()
        if not self.conn: return []
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchall() if query.strip().upper().startswith("SELECT") else []
        except Exception as e:
            print(f"❌ SQL Error: {e}")
            return []

    def search_vectors(self, embedding, limit=3):
        # Change table name to your actual table if needed
        query = 'SELECT * FROM "cyber_secuitry" ORDER BY embedding <=> %s::vector LIMIT %s;'
        return self.execute_query(query, (embedding, limit))    