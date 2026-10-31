-- Control-plane database (created by POSTGRES_DB): extensions Agnostic requires.
\connect agnostic
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- One database per reference AgentOS runtime (just runtimes), with pgvector for knowledge.
CREATE DATABASE agentos_prod OWNER agnostic;
CREATE DATABASE agentos_staging OWNER agnostic;

\connect agentos_prod
CREATE EXTENSION IF NOT EXISTS vector;

\connect agentos_staging
CREATE EXTENSION IF NOT EXISTS vector;
