from app.db.postgres import PostgresClient
import os
from dotenv import load_dotenv

load_dotenv()

def diagnostic():
    print("--- 🔍 Database Diagnostic ---")
    print(f"Target Database: {os.getenv('DB_NAME')}")
    print(f"Target Host: {os.getenv('DB_HOST')}")
    
    try:
        db = PostgresClient()
        # Query to list all tables in the 'public' schema
        query = "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        tables = db.execute_query(query)
        
        if not tables:
            print("❌ No tables found in the 'public' schema!")
            print("💡 Tip: You might have created the table in the default 'postgres' database instead of the one in your .env.")
        else:
            print("✅ Tables found in database:")
            for t in tables:
                print(f"   - {t['table_name']}")
                
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    diagnostic()