-- 1. Enable the pgvector extension (Crucial for AI)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create the Incidents table
-- We combine text fields later for the AI, but store them separately here for structure.
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    incident_id VARCHAR(50) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    severity_level INT CHECK (severity_level BETWEEN 1 AND 5), -- 1=Critical, 5=Info
    status VARCHAR(20) DEFAULT 'Open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding VECTOR(384) -- Dimension size must match BAAI/bge-small-en-v1.5
);

-- 3. Create a vector index for faster searching
-- IVFFlat is good for speed. We use cosine distance (vector_cosine_ops).
CREATE INDEX ON incidents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 4. Insert dummy data (OPTIONAL - Just to prove it works before you add real data)
-- Note: The 'embedding' column here is NULL. We will fill it using Python later.
INSERT INTO incidents (incident_id, title, description, severity_level, status) VALUES
('INC-001', 'Database Timeout', 'Production DB latency observed above 500ms.', 2, 'Open'),
('INC-002', 'Phishing Email', 'User reported suspicious link in HR email.', 1, 'Closed'),
('INC-003', 'Laptop Update', 'Routine windows patch failed on host X1.', 4, 'Open')
ON CONFLICT (incident_id) DO NOTHING;