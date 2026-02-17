import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.postgres import PostgresClient
from app.core.embedder import embedder_instance

def run_ingestion():
    db = PostgresClient()
    print("🔍 Fetching data without vectors from 'cyber_secuitry'...")
    
    # UPDATED: Lowercase column names
    sql = 'SELECT incident_id, threat_category, attack_vector, issue_type FROM "cyber_secuitry" WHERE embedding IS NULL;'
    rows = db.execute_query(sql)

    if not rows:
        print("✅ All data is already vectorized.")
        return

    for row in rows:
        # Dictionary keys are now lowercase
        i_id = row['incident_id']
        text = f"Incident {i_id}: {row['issue_type']} involving {row['threat_category']} via {row['attack_vector']}"
        
        print(f"📦 Vectorizing: {i_id}")
        vector = embedder_instance.get_embedding(text)
        db.update_embedding(i_id, vector)

    print("🎉 Ingestion Complete!")

if __name__ == "__main__":
    run_ingestion()