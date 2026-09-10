DATABASE_NAME = "cre_Drama_Workshop_Groups"
DB_PATH = f"database/{DATABASE_NAME}/{DATABASE_NAME}.sqlite"
COLLECTION_NAME = "TextSQL_Schema_Store"

SCHEMA_FILE = f"{DATABASE_NAME}_schema"

QDRANT_URL = "http://localhost:6333"

EMBEDDING_MODEL = "text-embedding-3-small"
SYSTEM_PROMPT = """You translate questions into SQLite queries.

Schema:
{schema}

Return exactly one SQLite statement and nothing else.
No explanation, no markdown fences, no function or tool call syntax.
"""
