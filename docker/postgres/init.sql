CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS langgraph;

COMMENT ON EXTENSION vector IS 'pgvector extension for semantic and episodic memory embeddings';
