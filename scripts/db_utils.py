#!/usr/bin/env python3
"""Shared database utilities for PostgreSQL operations.

Provides common database patterns used across scripts.
"""
from contextlib import contextmanager
from typing import Generator, Optional, List, Dict, Any
import os
import sys

try:
    import psycopg
except ImportError:
    print("Error: psycopg package required. Install with: pip install psycopg")
    sys.exit(1)


# ============================================================================
# ENTITY NETWORK SCHEMA DEFINITIONS
# ============================================================================

ENTITY_NETWORK_ENTITIES_SQL = """
CREATE TABLE IF NOT EXISTS entity_network_entities (
    entity_id SERIAL PRIMARY KEY,
    entity_name TEXT UNIQUE NOT NULL,
    entity_type TEXT NOT NULL,  -- 'person', 'company', 'organization', 'fund'
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_entity_name ON entity_network_entities(entity_name);
CREATE INDEX IF NOT EXISTS idx_entity_type ON entity_network_entities(entity_type);
"""

ENTITY_NETWORK_RELATIONSHIPS_SQL = """
CREATE TABLE IF NOT EXISTS entity_network_relationships (
    relationship_id SERIAL PRIMARY KEY,
    source_entity_id INTEGER NOT NULL REFERENCES entity_network_entities(entity_id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES entity_network_entities(entity_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,  -- 'works_at', 'founded', 'invested_in', 'partner_of', etc.
    confidence_score FLOAT DEFAULT 1.0,  -- 0.0 to 1.0, indicates data quality/certainty
    degree INTEGER NOT NULL DEFAULT 1,  -- 1 = direct connection, 2 = second-degree
    source_reference TEXT,  -- Where this relationship data came from
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_source_entity ON entity_network_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_target_entity ON entity_network_relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationship_type ON entity_network_relationships(relationship_type);
CREATE INDEX IF NOT EXISTS idx_degree ON entity_network_relationships(degree);
"""

ENTITY_NETWORK_MENTIONS_SQL = """
CREATE TABLE IF NOT EXISTS entity_network_mentions (
    mention_id SERIAL PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entity_network_entities(entity_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(entity_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_mention_entity ON entity_network_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mention_file ON entity_network_mentions(file_path);
"""

ENTITY_NETWORK_SOURCES_SQL = """
CREATE TABLE IF NOT EXISTS entity_network_sources (
    source_id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    citation_chicago TEXT NOT NULL,
    author TEXT,
    title TEXT NOT NULL,
    publication TEXT,
    publication_date DATE,
    url TEXT,
    archive_url TEXT,
    accessed_date DATE,
    document_id TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(citation_chicago)
);
CREATE INDEX IF NOT EXISTS idx_source_type ON entity_network_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_source_doc ON entity_network_sources(document_id);
"""

ENTITY_NETWORK_RELATIONSHIP_SOURCES_SQL = """
CREATE TABLE IF NOT EXISTS entity_network_relationship_sources (
    relationship_id INTEGER NOT NULL REFERENCES entity_network_relationships(relationship_id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES entity_network_sources(source_id) ON DELETE CASCADE,
    page_reference TEXT,
    quote TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (relationship_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_rel_source_rel ON entity_network_relationship_sources(relationship_id);
CREATE INDEX IF NOT EXISTS idx_rel_source_src ON entity_network_relationship_sources(source_id);
"""

ENTITY_NETWORK_ENTITY_SOURCES_SQL = """
CREATE TABLE IF NOT EXISTS entity_network_entity_sources (
    entity_id INTEGER NOT NULL REFERENCES entity_network_entities(entity_id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES entity_network_sources(source_id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (entity_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_ent_source_ent ON entity_network_entity_sources(entity_id);
CREATE INDEX IF NOT EXISTS idx_ent_source_src ON entity_network_entity_sources(source_id);
"""

# ============================================================================
# DATABASE CONNECTION UTILITIES
# ============================================================================


@contextmanager
def get_db_connection(dsn: str, autocommit: bool = False) -> Generator:
    """Context manager for database connections with automatic cleanup.
    
    Args:
        dsn: PostgreSQL connection string
        autocommit: Whether to enable autocommit mode
        
    Yields:
        psycopg connection object
        
    Example:
        with get_db_connection(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM table")
    """
    conn = None
    try:
        conn = psycopg.connect(dsn)
        if autocommit:
            conn.autocommit = True
        yield conn
    except psycopg.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def get_dsn(dsn_arg: Optional[str] = None) -> str:
    """Resolve database connection string from argument or environment.
    
    Args:
        dsn_arg: Optional DSN passed as argument (takes precedence)
        
    Returns:
        Database connection string
        
    Raises:
        SystemExit: If no DSN available from argument or environment
    """
    # Try to load from config if available (loads .env file)
    try:
        from config import DEFAULT_DSN
        default = DEFAULT_DSN
    except ImportError:
        default = os.environ.get('DATABASE_URL')
    
    dsn = dsn_arg or default
    
    if not dsn:
        print("No DATABASE_URL env var and no --dsn provided.")
        sys.exit(1)
    
    return dsn


def connect_db(dsn_arg: Optional[str] = None, autocommit: bool = True):
    """Connect to PostgreSQL database with DSN resolution.
    
    This is a non-context-manager version for scripts that manage
    their own connection lifecycle.
    
    Args:
        dsn_arg: Optional DSN passed as argument (takes precedence over env)
        autocommit: Whether to enable autocommit mode (default: True)
        
    Returns:
        psycopg connection object
        
    Raises:
        SystemExit: If connection fails or no DSN available
    """
    dsn = get_dsn(dsn_arg)
    
    try:
        conn = psycopg.connect(dsn)
        if autocommit:
            conn.autocommit = True
        return conn
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        sys.exit(1)


def create_entity_network_tables(conn, verbose: bool = False, include_sources: bool = True) -> None:
    """Create all entity network tables if they don't exist.
    
    Args:
        conn: Database connection
        verbose: Print confirmation messages
        include_sources: Include source citation tables (default: True)
    """
    with conn.cursor() as cur:
        # Core tables (in dependency order)
        cur.execute(ENTITY_NETWORK_ENTITIES_SQL)
        cur.execute(ENTITY_NETWORK_RELATIONSHIPS_SQL)
        cur.execute(ENTITY_NETWORK_MENTIONS_SQL)
        
        # Source tables (optional)
        if include_sources:
            cur.execute(ENTITY_NETWORK_SOURCES_SQL)
            cur.execute(ENTITY_NETWORK_RELATIONSHIP_SOURCES_SQL)
            cur.execute(ENTITY_NETWORK_ENTITY_SOURCES_SQL)
        
        conn.commit()
        
    if verbose:
        tables = ['entity_network_entities', 'entity_network_relationships', 
                  'entity_network_mentions']
        if include_sources:
            tables.extend(['entity_network_sources', 'entity_network_relationship_sources',
                          'entity_network_entity_sources'])
        print(f"Created/verified tables: {', '.join(tables)}")


def table_exists(conn, table_name: str, schema: str = 'public') -> bool:
    """Check if a table exists in the database.
    
    Args:
        conn: Database connection
        table_name: Name of table to check
        schema: Database schema (default: public)
        
    Returns:
        True if table exists, False otherwise
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            )
        """, (schema, table_name))
        return cur.fetchone()[0]


def create_table_if_not_exists(conn, table_name: str, create_sql: str) -> bool:
    """Create a table if it doesn't already exist.
    
    Args:
        conn: Database connection
        table_name: Name of table to create
        create_sql: SQL CREATE TABLE statement
        
    Returns:
        True if table was created, False if it already existed
    """
    if table_exists(conn, table_name):
        return False
    
    with conn.cursor() as cur:
        cur.execute(create_sql)
        conn.commit()
    return True


def list_tables(conn, schema: str = 'public') -> List[str]:
    """List all tables in a schema.
    
    Args:
        conn: Database connection
        schema: Database schema (default: public)
        
    Returns:
        List of table names
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, (schema,))
        return [row[0] for row in cur.fetchall()]


def get_table_row_count(conn, table_name: str, schema: str = 'public') -> int:
    """Get the number of rows in a table.
    
    Args:
        conn: Database connection
        table_name: Name of table
        schema: Database schema (default: public)
        
    Returns:
        Number of rows
    """
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table_name}"')
        return cur.fetchone()[0]


def drop_table(conn, table_name: str, schema: str = 'public', 
               cascade: bool = True, dry_run: bool = False) -> bool:
    """Drop a table completely.
    
    Args:
        conn: Database connection
        table_name: Name of table to drop
        schema: Database schema (default: public)
        cascade: Use CASCADE to drop dependent objects (default: True)
        dry_run: If True, only show what would be done
        
    Returns:
        True if table was dropped (or would be in dry_run), False if it doesn't exist
    """
    if not table_exists(conn, table_name, schema):
        return False
    
    cascade_clause = " CASCADE" if cascade else ""
    drop_sql = f'DROP TABLE IF EXISTS "{schema}"."{table_name}"{cascade_clause}'
    
    if dry_run:
        return True
    
    with conn.cursor() as cur:
        cur.execute(drop_sql)
    conn.commit()
    return True


def truncate_table(conn, table_name: str, schema: str = 'public',
                  cascade: bool = True, restart_identity: bool = True,
                  dry_run: bool = False) -> bool:
    """Truncate a table (clear all data, preserve structure).
    
    Args:
        conn: Database connection
        table_name: Name of table to truncate
        schema: Database schema (default: public)
        cascade: Use CASCADE for dependent objects (default: True)
        restart_identity: Reset auto-increment sequences (default: True)
        dry_run: If True, only show what would be done
        
    Returns:
        True if table was truncated (or would be in dry_run), False if it doesn't exist
    """
    if not table_exists(conn, table_name, schema):
        return False
    
    restart_clause = " RESTART IDENTITY" if restart_identity else ""
    cascade_clause = " CASCADE" if cascade else ""
    truncate_sql = f'TRUNCATE TABLE "{schema}"."{table_name}"{restart_clause}{cascade_clause}'
    
    if dry_run:
        return True
    
    with conn.cursor() as cur:
        cur.execute(truncate_sql)
    conn.commit()
    return True


def get_table_stats(conn, schema: str = 'public') -> Dict[str, int]:
    """Get row counts for all tables in a schema.
    
    Args:
        conn: Database connection
        schema: Database schema (default: public)
        
    Returns:
        Dictionary mapping table names to row counts
    """
    tables = list_tables(conn, schema)
    stats = {}
    for table in tables:
        stats[table] = get_table_row_count(conn, table, schema)
    return stats


def execute_query(conn, query: str, params: Optional[tuple] = None) -> List[tuple]:
    """Execute a query and return all results.
    
    Args:
        conn: Database connection
        query: SQL query
        params: Optional query parameters
        
    Returns:
        List of result tuples
    """
    with conn.cursor() as cur:
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        return cur.fetchall()


def bulk_insert(conn, table_name: str, columns: List[str], 
                rows: List[tuple], batch_size: int = 1000) -> int:
    """Bulk insert rows into a table efficiently.
    
    Args:
        conn: Database connection
        table_name: Target table name
        columns: List of column names
        rows: List of row tuples
        batch_size: Number of rows per batch
        
    Returns:
        Number of rows inserted
    """
    if not rows:
        return 0
    
    placeholders = ', '.join(['%s'] * len(columns))
    columns_str = ', '.join(columns)
    insert_sql = f'INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})'
    
    inserted = 0
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            cur.executemany(insert_sql, batch)
            inserted += len(batch)
        conn.commit()
    
    return inserted
