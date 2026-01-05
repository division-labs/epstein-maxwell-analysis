#!/usr/bin/env python3
"""Unified table reset utility for all project scripts.

This utility provides a consistent way to reset database tables across all
scripts in the project. It supports two modes:

1. TRUNCATE mode (default): Clears data but preserves table structure
2. DROP mode (--drop): Completely removes tables and recreates them

Usage:
    # Truncate specific tables
    python3 scripts/reset_tables.py --tables spelling_issues word_frequencies
    
    # Truncate tables for a specific feature
    python3 scripts/reset_tables.py --feature entity_disambiguation
    
    # Drop and recreate tables
    python3 scripts/reset_tables.py --feature entity_disambiguation --drop
    
    # Reset all tables for a feature (interactive confirmation)
    python3 scripts/reset_tables.py --feature all --confirm
    
    # Dry run (show what would be reset without making changes)
    python3 scripts/reset_tables.py --feature spelling --dry-run

Features:
    - spelling: spelling_issues table
    - entity_disambiguation: entity_aliases, name_disambiguation_queue
    - entity_network: entity_network_entities, entity_network_relationships, entity_network_mentions
    - catalog: file_catalog, extracted_dates, extracted_names, extracted_locations
    - text_content: extracted_text_content
    - tdm_nouns: noun_tdm_vocabulary, noun_tdm_documents, noun_tdm_counts, noun_tdm_metadata
    - tdm_verbs: verb_tdm_vocabulary, verb_tdm_documents, verb_tdm_counts, verb_tdm_metadata
    - pdf_metadata: pdf_metadata
    - all: All project tables
"""
import argparse
import sys
from typing import List, Set

try:
    import psycopg
except Exception:
    print("Error: psycopg not available. Install with: pip install psycopg")
    sys.exit(1)

# Import shared utilities
try:
    from db_utils import table_exists, drop_table as db_drop_table, truncate_table as db_truncate_table, get_db_connection
except ImportError:
    print("Warning: Could not import from db_utils. Using local implementations.")
    db_drop_table = None
    db_truncate_table = None
    get_db_connection = None

# Import config
from config import DEFAULT_DSN

# Feature to table mappings
FEATURE_TABLES = {
    'spelling': [
        'spelling_issues'
    ],
    'entity_disambiguation': [
        'entity_aliases',
        'name_disambiguation_queue'
    ],
    'entity_network': [
        'entity_network_entities',
        'entity_network_relationships',
        'entity_network_mentions'
    ],
    'catalog': [
        'file_catalog',
        'extracted_dates',
        'extracted_names',
        'extracted_locations'
    ],
    'text_content': [
        'extracted_text_content'
    ],
    'tdm_nouns': [
        'noun_tdm_vocabulary',
        'noun_tdm_documents',
        'noun_tdm_counts',
        'noun_tdm_metadata'
    ],
    'tdm_verbs': [
        'verb_tdm_vocabulary',
        'verb_tdm_documents',
        'verb_tdm_counts',
        'verb_tdm_metadata'
    ],
    'pdf_metadata': [
        'pdf_metadata'
    ]
}

# Manual-only tables that should be preserved
PROTECTED_MANUAL_COLUMNS = {
    'entity_aliases': ('disambiguation_method', 'manual'),  # (column, value) to preserve
    'name_disambiguation_queue': None  # No manual protection needed
}

def get_all_tables() -> Set[str]:
    """Get set of all project table names.

    Returns:
        Set of table names from all feature categories.
    """
    all_tables = set()
    for tables in FEATURE_TABLES.values():
        all_tables.update(tables)
    return all_tables

def list_features():
    """Print available features and their associated tables.

    Displays a formatted list of all feature categories with their
    database tables for user reference.
    """
    print("\nAvailable Features:")
    print("=" * 80)
    for feature, tables in sorted(FEATURE_TABLES.items()):
        print(f"\n{feature}:")
        for table in tables:
            print(f"  - {table}")
    print(f"\nall: All {len(get_all_tables())} project tables")
    print()

def get_tables_for_feature(feature: str) -> List[str]:
    """Get list of tables for a given feature category.

    Args:
        feature: Feature name ('spelling', 'entity_network', etc.) or 'all'.

    Returns:
        List of table names for the feature, or empty list if not found.
    """
    if feature == 'all':
        return list(get_all_tables())
    return FEATURE_TABLES.get(feature, [])

def truncate_table(conn, table_name: str, preserve_manual: bool = True, dry_run: bool = False):
    """Truncate a table, optionally preserving manual entries.

    For tables with manual/auto distinction (like entity_aliases), can
    preserve manually-entered rows while deleting auto-generated ones.

    Args:
        conn: Database connection.
        table_name: Name of table to truncate.
        preserve_manual: If True, preserve rows marked as manual (default: True).
        dry_run: If True, only show what would be done.
    """
    protection = PROTECTED_MANUAL_COLUMNS.get(table_name)
    
    if protection and preserve_manual:
        column, value = protection
        if dry_run:
            print(f"  Would DELETE FROM {table_name} WHERE {column} != '{value}'")
        else:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table_name} WHERE {column} != %s", (value,))
                deleted = cur.rowcount
            conn.commit()
            print(f"  ✓ Deleted {deleted} auto-generated rows from {table_name} (preserved manual entries)")
    else:
        if dry_run:
            print(f"  Would TRUNCATE TABLE {table_name}")
        else:
            if db_truncate_table:
                db_truncate_table(conn, table_name, cascade=True, restart_identity=True, dry_run=False)
            else:
                with conn.cursor() as cur:
                    cur.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE")
                conn.commit()
            print(f"  ✓ Truncated {table_name}")

def drop_table(conn, table_name: str, schema: str = 'public', dry_run: bool = False):
    """Drop a table completely from the database.

    Args:
        conn: Database connection.
        table_name: Name of table to drop.
        schema: Database schema (default: 'public').
        dry_run: If True, only show what would be done.
    """
    if dry_run:
        print(f"  Would DROP TABLE IF EXISTS \"{schema}\".\"{table_name}\" CASCADE")
    else:
        if db_drop_table:
            db_drop_table(conn, table_name, schema=schema, cascade=True, dry_run=False)
        else:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{schema}"."{table_name}" CASCADE')
            conn.commit()
        print(f"  ✓ Dropped {table_name}")

def reset_tables(
    conn,
    tables: List[str],
    mode: str = 'truncate',
    preserve_manual: bool = True,
    dry_run: bool = False
):
    """Reset specified tables by truncating or dropping them.

    Args:
        conn: Database connection.
        tables: List of table names to reset.
        mode: Reset mode - 'truncate' (default) or 'drop'.
        preserve_manual: If True, preserve manual entries in supported tables.
        dry_run: If True, only show what would be done.

    Returns:
        int: 0 on success, 1 on error.
    """
    existing_tables = [t for t in tables if table_exists(conn, t)]
    
    if not existing_tables:
        print("\n⚠️  No specified tables exist in the database")
        return 0
    
    print(f"\n{'DRY RUN: ' if dry_run else ''}{'Dropping' if mode == 'drop' else 'Truncating'} {len(existing_tables)} tables:")
    print("=" * 80)
    
    for table in existing_tables:
        try:
            if mode == 'drop':
                drop_table(conn, table, dry_run=dry_run)
            else:
                truncate_table(conn, table, preserve_manual=preserve_manual, dry_run=dry_run)
        except Exception as e:
            print(f"  ✗ Error resetting {table}: {e}")
            return 1
    
    if not dry_run:
        print(f"\n✓ Successfully reset {len(existing_tables)} tables")
        if mode == 'drop':
            print("\n⚠️  Tables dropped. Run the appropriate scripts to recreate them.")
    else:
        print(f"\n✓ Dry run complete. Would reset {len(existing_tables)} tables.")
    
    return 0

def main():
    parser = argparse.ArgumentParser(
        description='Unified table reset utility for all project scripts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available features
  %(prog)s --list-features
  
  # Truncate specific tables
  %(prog)s --tables spelling_issues entity_aliases
  
  # Truncate all tables for a feature
  %(prog)s --feature entity_disambiguation
  
  # Drop and recreate tables (requires confirmation)
  %(prog)s --feature entity_disambiguation --drop --confirm
  
  # Dry run to see what would be reset
  %(prog)s --feature spelling --dry-run
  
  # Reset everything (DANGEROUS - requires confirmation)
  %(prog)s --feature all --confirm
  
  # Truncate but don't preserve manual entries
  %(prog)s --feature entity_disambiguation --no-preserve-manual

Notes:
  - TRUNCATE mode (default): Clears data, preserves table structure
  - DROP mode (--drop): Completely removes tables, requires recreation
  - Manual entries in entity_aliases are preserved by default
  - Use --dry-run to preview changes without modifying database
  - --confirm required for 'all' feature or DROP mode
"""
    )
    
    parser.add_argument('--dsn', default=DEFAULT_DSN,
                        help='PostgreSQL connection string')
    
    parser.add_argument('--tables', nargs='+', metavar='TABLE',
                        help='Specific table names to reset')
    
    parser.add_argument('--feature', choices=list(FEATURE_TABLES.keys()) + ['all'],
                        help='Reset all tables for a feature')
    
    parser.add_argument('--drop', action='store_true',
                        help='Drop tables completely (requires --confirm)')
    
    parser.add_argument('--no-preserve-manual', action='store_true',
                        help='Do not preserve manual entries (e.g., manual entity aliases)')
    
    parser.add_argument('--confirm', action='store_true',
                        help='Confirm destructive operations')
    
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be reset without making changes')
    
    parser.add_argument('--list-features', action='store_true',
                        help='List available features and their tables')
    
    args = parser.parse_args()
    
    # Handle --list-features
    if args.list_features:
        list_features()
        return 0
    
    # Validate arguments
    if not args.tables and not args.feature:
        parser.print_help()
        return 1
    
    # Get tables to reset
    tables_to_reset = []
    if args.tables:
        tables_to_reset.extend(args.tables)
    if args.feature:
        tables_to_reset.extend(get_tables_for_feature(args.feature))
    
    # Remove duplicates while preserving order
    tables_to_reset = list(dict.fromkeys(tables_to_reset))
    
    if not tables_to_reset:
        print(f"Error: Feature '{args.feature}' not found")
        list_features()
        return 1
    
    # Require confirmation for dangerous operations
    if (args.drop or args.feature == 'all') and not args.confirm and not args.dry_run:
        print("\n⚠️  DESTRUCTIVE OPERATION")
        print("=" * 80)
        if args.drop:
            print("You are about to DROP (completely remove) the following tables:")
        else:
            print("You are about to reset ALL project tables:")
        print()
        for table in tables_to_reset:
            print(f"  - {table}")
        print()
        print("This operation cannot be undone.")
        print()
        response = input("Type 'yes' to continue: ")
        if response.lower() != 'yes':
            print("Operation cancelled.")
            return 1
    
    # Connect and reset
    try:
        with get_db_connection(args.dsn, autocommit=True) as conn:
            mode = 'drop' if args.drop else 'truncate'
            preserve_manual = not args.no_preserve_manual
            
            return reset_tables(
                conn,
                tables_to_reset,
                mode=mode,
                preserve_manual=preserve_manual,
                dry_run=args.dry_run
            )
    
    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
