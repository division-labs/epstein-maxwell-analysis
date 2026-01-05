#!/usr/bin/env python3
"""Load sourced entity network data into PostgreSQL.

This module reads the sourced entity and relationship data from
entity_network_sources.py and loads it into the PostgreSQL database with
proper citation tracking. It creates the necessary database tables and
establishes links between entities, relationships, and their documentary
sources.

Database Tables Created:
    - entity_network_entities: Person and company nodes
    - entity_network_relationships: Connections between entities
    - entity_network_sources: Documentary source references with citations
    - entity_network_relationship_sources: Junction table linking
      relationships to their source citations
    - entity_network_entity_sources: Junction table linking entities
      to sources for their descriptions

Data Sources:
    All data is loaded from entity_network_sources.py, which contains:
    - SOURCED_ENTITIES: List of SourcedEntity dataclass instances
    - SOURCED_RELATIONSHIPS: List of SourcedRelationship dataclass instances
    - Source objects with Chicago-style citations

Example:
    Basic usage with verbose output::

        $ python3 scripts/load_sourced_entity_network.py --verbose

    Clear existing data and print citation report::

        $ python3 scripts/load_sourced_entity_network.py --clear --report

    Use custom database connection::

        $ python3 scripts/load_sourced_entity_network.py --dsn "postgresql://user:pass@host/db"

Note:
    Running this script will clear existing sourced data to avoid conflicts.
    Entity records are preserved as they may be linked to document mentions.
"""

import argparse
import sys
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

try:
    import psycopg
    from psycopg import Connection
except ImportError:
    print("Error: psycopg not installed. Run: pip install psycopg[binary]")
    sys.exit(1)

from db_utils import (
    get_db_connection, connect_db, create_entity_network_tables,
    ENTITY_NETWORK_SOURCES_SQL, ENTITY_NETWORK_RELATIONSHIP_SOURCES_SQL,
    ENTITY_NETWORK_ENTITY_SOURCES_SQL
)
from entity_network_sources import (
    SOURCED_ENTITIES, SOURCED_RELATIONSHIPS,
    Source, SourcedEntity, SourcedRelationship,
    get_all_sources, validate_relationships, validate_entities
)


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def create_tables(conn: Connection, verbose: bool = False) -> None:
    """Create or verify the entity network database tables.

    Creates all tables required for the entity network with appropriate
    indexes and constraints. Uses IF NOT EXISTS to be idempotent.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, print confirmation message on success.

    Tables Created:
        - entity_network_entities: Primary entity storage
        - entity_network_relationships: Entity connections
        - entity_network_sources: Documentary sources
        - entity_network_relationship_sources: Relationship-source links
        - entity_network_entity_sources: Entity-source links
    """
    # Create core entity network tables using centralized schema
    create_entity_network_tables(conn, verbose=False, include_sources=True)
    
    if verbose:
        print("Tables created/verified successfully")


def clear_sourced_data_only(conn: Connection, verbose: bool = False) -> None:
    """Clear sourced relationship data while preserving entities.

    Removes all data from source-related tables and relationships marked
    as 'sourced_data'. Entity records are preserved because they may be
    linked to document mentions from other processing pipelines.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, print confirmation message on success.

    Deleted Data:
        - entity_network_relationship_sources (all records)
        - entity_network_relationships WHERE source_reference = 'sourced_data'
        - entity_network_entity_sources (all records)
        - entity_network_sources (all records)
    """
    with conn.cursor() as cur:
        # Delete sourced relationships (keeping any from build_entity_network.py)
        cur.execute("DELETE FROM entity_network_relationship_sources")
        cur.execute("DELETE FROM entity_network_relationships WHERE source_reference = 'sourced_data'")
        cur.execute("DELETE FROM entity_network_entity_sources")
        cur.execute("DELETE FROM entity_network_sources")
        conn.commit()
        if verbose:
            print("Cleared sourced data (preserved entities and mentions)")


def insert_source(conn: Connection, source: Source) -> int:
    """Insert or update a documentary source in the database.

    Uses the Chicago-style citation as the unique key. If a source with
    the same citation already exists, updates its metadata fields.

    Args:
        conn: Active psycopg database connection.
        source: Source dataclass instance containing citation data.

    Returns:
        The source_id of the inserted or updated source record.
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO entity_network_sources 
            (source_type, citation_chicago, author, title, publication, 
             publication_date, url, archive_url, accessed_date, document_id, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (citation_chicago) DO UPDATE SET
                source_type = EXCLUDED.source_type,
                author = EXCLUDED.author,
                title = EXCLUDED.title,
                publication = EXCLUDED.publication,
                url = EXCLUDED.url
            RETURNING source_id
        """, (
            source.source_type.value,
            source.citation_chicago,
            source.author,
            source.title,
            source.publication,
            source.publication_date,
            source.url,
            source.archive_url,
            source.accessed_date,
            source.document_id,
            source.notes
        ))
        result = cur.fetchone()
        return result[0]


def insert_entity(conn: Connection, entity: SourcedEntity, source_ids: Dict[str, int]) -> int:
    """Insert or update an entity and link it to its description sources.

    Creates the entity record and establishes links to any sources that
    document the entity's description.

    Args:
        conn: Active psycopg database connection.
        entity: SourcedEntity dataclass instance with entity data.
        source_ids: Dictionary mapping Chicago citations to source_id values.

    Returns:
        The entity_id of the inserted or updated entity record.
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO entity_network_entities (entity_name, entity_type, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (entity_name) DO UPDATE SET
                entity_type = EXCLUDED.entity_type,
                description = EXCLUDED.description,
                updated_at = NOW()
            RETURNING entity_id
        """, (entity.name, entity.entity_type, entity.description))
        entity_id = cur.fetchone()[0]
        
        # Link entity to its description sources
        for source in entity.description_sources:
            source_id = source_ids.get(source.citation_chicago)
            if source_id:
                cur.execute("""
                    INSERT INTO entity_network_entity_sources (entity_id, source_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (entity_id, source_id))
        
        return entity_id


def get_or_create_entity(conn: Connection, name: str, entity_type: str = "person") -> int:
    """Retrieve an existing entity or create a minimal placeholder.

    Used when processing relationships that reference entities not yet
    in the sourced entity list. Creates a placeholder with a pending
    description note.

    Args:
        conn: Active psycopg database connection.
        name: Entity name to look up or create.
        entity_type: Type of entity ('person' or 'company'). Defaults to 'person'.

    Returns:
        The entity_id of the existing or newly created entity.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT entity_id FROM entity_network_entities WHERE entity_name = %s", (name,))
        result = cur.fetchone()
        if result:
            return result[0]
        
        # Create minimal entity
        cur.execute("""
            INSERT INTO entity_network_entities (entity_name, entity_type, description)
            VALUES (%s, %s, %s)
            RETURNING entity_id
        """, (name, entity_type, f"[Description pending - requires sourced research]"))
        return cur.fetchone()[0]


def insert_relationship(
    conn: Connection,
    rel: SourcedRelationship,
    source_ids: Dict[str, int],
    entity_ids: Dict[str, int]
) -> Optional[int]:
    """Insert a relationship and link it to its documentary sources.

    Creates the relationship record between two entities and establishes
    links to all sources that document this relationship. If referenced
    entities don't exist, creates placeholder entities.

    Args:
        conn: Active psycopg database connection.
        rel: SourcedRelationship dataclass instance with relationship data.
        source_ids: Dictionary mapping Chicago citations to source_id values.
        entity_ids: Dictionary mapping entity names to entity_id values.
            Updated in-place if new entities are created.

    Returns:
        The relationship_id of the inserted relationship, or None on failure.

    Note:
        Quotes and page references from the relationship are stored in the
        relationship_sources junction table for citation granularity.
    """
    source_entity_id = entity_ids.get(rel.source_entity)
    target_entity_id = entity_ids.get(rel.target_entity)
    
    if not source_entity_id:
        source_entity_id = get_or_create_entity(conn, rel.source_entity)
        entity_ids[rel.source_entity] = source_entity_id
    
    if not target_entity_id:
        # Guess entity type based on relationship
        target_type = "company" if rel.relationship_type in ["founder", "ceo", "chairman", "employee_of", "partner", "director"] else "person"
        target_entity_id = get_or_create_entity(conn, rel.target_entity, target_type)
        entity_ids[rel.target_entity] = target_entity_id
    
    with conn.cursor() as cur:
        # Insert relationship
        cur.execute("""
            INSERT INTO entity_network_relationships 
            (source_entity_id, target_entity_id, relationship_type, confidence_score, degree, source_reference, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_entity_id, target_entity_id, relationship_type) DO UPDATE SET
                confidence_score = EXCLUDED.confidence_score,
                notes = EXCLUDED.notes
            RETURNING relationship_id
        """, (
            source_entity_id,
            target_entity_id,
            rel.relationship_type,
            rel.confidence_score,
            1,  # degree
            "sourced_data",  # Mark as sourced
            rel.notes
        ))
        relationship_id = cur.fetchone()[0]
        
        # Link to sources
        for source in rel.sources:
            source_id = source_ids.get(source.citation_chicago)
            if source_id:
                quote = rel.quotes.get(source.title)
                page_ref = rel.page_references.get(source.title)
                
                cur.execute("""
                    INSERT INTO entity_network_relationship_sources 
                    (relationship_id, source_id, page_reference, quote)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (relationship_id, source_id, page_ref, quote))
        
        return relationship_id


def load_all_data(conn: Connection, verbose: bool = False) -> Dict[str, int]:
    """Load all sourced entity and relationship data into the database.

    Orchestrates the full data loading process: validates data integrity,
    inserts sources, entities, and relationships, and establishes all
    citation links.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, print progress messages to stdout.

    Returns:
        Dictionary with counts of loaded records:
            - 'sources': Number of source records inserted
            - 'entities': Number of entity records inserted
            - 'relationships': Number of relationship records inserted
            - 'citations_linked': Total citation links established

    Note:
        Returns empty counts if validation errors are found. Validation
        errors are printed to stdout.
    """
    stats = {
        "sources": 0,
        "entities": 0,
        "relationships": 0,
        "citations_linked": 0
    }
    
    # First, validate data
    rel_errors = validate_relationships()
    entity_errors = validate_entities()
    
    if rel_errors or entity_errors:
        print("Validation errors found:")
        for e in rel_errors + entity_errors:
            print(f"  - {e}")
        return stats
    
    # Insert all sources first
    source_ids: Dict[str, int] = {}
    all_sources = get_all_sources()
    
    for source in all_sources:
        source_id = insert_source(conn, source)
        source_ids[source.citation_chicago] = source_id
        stats["sources"] += 1
    
    if verbose:
        print(f"Inserted {stats['sources']} sources")
    
    # Insert entities
    entity_ids: Dict[str, int] = {}
    for entity in SOURCED_ENTITIES:
        entity_id = insert_entity(conn, entity, source_ids)
        entity_ids[entity.name] = entity_id
        stats["entities"] += 1
    
    if verbose:
        print(f"Inserted {stats['entities']} entities")
    
    # Insert relationships
    for rel in SOURCED_RELATIONSHIPS:
        relationship_id = insert_relationship(conn, rel, source_ids, entity_ids)
        if relationship_id:
            stats["relationships"] += 1
            stats["citations_linked"] += len(rel.sources)
    
    conn.commit()
    
    if verbose:
        print(f"Inserted {stats['relationships']} relationships")
        print(f"Linked {stats['citations_linked']} citations to relationships")
    
    return stats


def print_citation_report(conn: Connection) -> None:
    """Print a summary report of citations in the database.

    Displays statistics about source distribution, most-cited relationships,
    and identifies any relationships lacking source citations.

    Args:
        conn: Active psycopg database connection.

    Output Sections:
        - Sources by type: Count of sources per source_type category
        - Top relationships by citation count: 10 most-cited relationships
        - Unsourced relationships: Count of relationships without citations
    """
    with conn.cursor() as cur:
        # Count sources by type
        cur.execute("""
            SELECT source_type, COUNT(*) 
            FROM entity_network_sources 
            GROUP BY source_type 
            ORDER BY COUNT(*) DESC
        """)
        print("\nSources by type:")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]}")
        
        # Count relationships by source count
        cur.execute("""
            SELECT r.relationship_id, e1.entity_name, e2.entity_name, r.relationship_type,
                   COUNT(rs.source_id) as source_count
            FROM entity_network_relationships r
            JOIN entity_network_entities e1 ON r.source_entity_id = e1.entity_id
            JOIN entity_network_entities e2 ON r.target_entity_id = e2.entity_id
            LEFT JOIN entity_network_relationship_sources rs ON r.relationship_id = rs.relationship_id
            GROUP BY r.relationship_id, e1.entity_name, e2.entity_name, r.relationship_type
            ORDER BY source_count DESC
            LIMIT 10
        """)
        print("\nTop relationships by citation count:")
        for row in cur.fetchall():
            print(f"  {row[1]} --[{row[3]}]--> {row[2]}: {row[4]} citations")
        
        # Relationships without sources
        cur.execute("""
            SELECT COUNT(*) FROM entity_network_relationships r
            WHERE NOT EXISTS (
                SELECT 1 FROM entity_network_relationship_sources rs 
                WHERE rs.relationship_id = r.relationship_id
            )
        """)
        unsourced = cur.fetchone()[0]
        print(f"\nRelationships without sources: {unsourced}")


def main() -> None:
    """Main entry point for loading sourced entity network data.

    Parses command-line arguments, connects to the database, creates
    tables, clears existing sourced data, and loads fresh data from
    entity_network_sources.py.

    Command-Line Arguments:
        --dsn: PostgreSQL connection string. Defaults to local connection.
        --verbose, -v: Enable verbose output with progress messages.
        --clear: Clear sourced data before loading (always done by default).
        --report: Print citation report after loading.

    Exit Codes:
        0: Success
        1: Database connection error
    """
    parser = argparse.ArgumentParser(description="Load sourced entity network data")
    parser.add_argument("--dsn", default=None,
                        help="PostgreSQL connection string (default: DATABASE_URL env var)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--clear", action="store_true", help="Clear sourced data before loading (preserves entities)")
    parser.add_argument("--report", action="store_true", help="Print citation report after loading")
    
    args = parser.parse_args()
    
    # Connect using centralized utility
    conn = connect_db(args.dsn)
    
    try:
        # Create tables
        create_tables(conn, args.verbose)
        
        # Clear sourced data (preserves entities and mentions)
        if args.clear:
            clear_sourced_data_only(conn, args.verbose)
        else:
            # Always clear sourced data to avoid conflicts
            clear_sourced_data_only(conn, args.verbose)
        
        # Load data
        stats = load_all_data(conn, args.verbose)
        
        print(f"\nLoaded: {stats['sources']} sources, {stats['entities']} entities, "
              f"{stats['relationships']} relationships, {stats['citations_linked']} citation links")
        
        # Print report if requested
        if args.report:
            print_citation_report(conn)
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
