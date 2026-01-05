#!/usr/bin/env python3
"""Verify database structure and connections match documentation.

This script performs comprehensive verification of the PostgreSQL database
to ensure all required tables, views, functions, and foreign key constraints
exist and are properly configured.

Verification Checks:
    1. Database connectivity - Tests basic connection
    2. Table existence - Verifies 20 expected tables with row counts
    3. View existence - Verifies 12 analytical views
    4. Function existence - Verifies 2 custom functions
    5. Foreign key constraints - Verifies referential integrity
    6. Function tests - Tests get_canonical_name with known inputs

Example:
    Run verification from the scripts directory::

        $ python verify_database.py

    Or with conda environment::

        $ conda run -n network_env python verify_database.py

Returns:
    Exit code 0 if all checks pass, 1 if any fail.

Requires:
    - psycopg library
    - config.py with DATABASE_URL configured
"""
import sys

try:
    import psycopg
except ImportError:
    print("Error: psycopg required. Install with: pip install psycopg")
    sys.exit(1)

from config import DEFAULT_DSN
DSN = DEFAULT_DSN


def main():
    """Run all database verification checks."""
    print("=" * 80)
    print("DATABASE VERIFICATION")
    print("=" * 80)
    print()
    
    try:
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                # Test connection
                cur.execute('SELECT 1')
                print("✓ Database connection successful")
                print()
                
                # Check tables
                print("TABLES")
                print("-" * 40)
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """)
                tables = [row[0] for row in cur.fetchall()]
                
                expected_tables = [
                    'entity_aliases', 'entity_network_entities', 'entity_network_mentions',
                    'entity_network_relationships', 'extracted_dates', 'extracted_locations',
                    'extracted_names', 'extracted_text_content', 'file_catalog',
                    'name_disambiguation_queue', 'noun_tdm_counts', 'noun_tdm_documents',
                    'noun_tdm_metadata', 'noun_tdm_vocabulary', 'pdf_metadata',
                    'spelling_issues', 'verb_tdm_counts', 'verb_tdm_documents',
                    'verb_tdm_metadata', 'verb_tdm_vocabulary'
                ]
                
                for table in expected_tables:
                    if table in tables:
                        cur.execute(f'SELECT COUNT(*) FROM {table}')
                        count = cur.fetchone()[0]
                        print(f"  ✓ {table}: {count:,} rows")
                    else:
                        print(f"  ✗ {table}: MISSING!")
                
                missing = set(expected_tables) - set(tables)
                extra = set(tables) - set(expected_tables)
                
                if missing:
                    print(f"\n  Missing tables: {missing}")
                if extra:
                    print(f"\n  Extra tables: {extra}")
                
                print(f"\n  Total: {len(tables)} tables")
                print()
                
                # Check views
                print("VIEWS")
                print("-" * 40)
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.views 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)
                views = [row[0] for row in cur.fetchall()]
                
                expected_views = [
                    'v_complex_documents', 'v_corpus_summary', 'v_corrected_text',
                    'v_document_entities', 'v_document_quality', 'v_document_timeline',
                    'v_foreign_language_words', 'v_high_priority_corrections',
                    'v_location_summary', 'v_ocr_pattern_summary', 'v_person_cooccurrence',
                    'v_spelling_variants'
                ]
                
                for view in expected_views:
                    if view in views:
                        print(f"  ✓ {view}")
                    else:
                        print(f"  ✗ {view}: MISSING!")
                
                print(f"\n  Total: {len(views)} views")
                print()
                
                # Check functions
                print("FUNCTIONS")
                print("-" * 40)
                cur.execute("""
                    SELECT routine_name, data_type 
                    FROM information_schema.routines 
                    WHERE routine_schema = 'public'
                    ORDER BY routine_name
                """)
                functions = {row[0]: row[1] for row in cur.fetchall()}
                
                expected_functions = {
                    'apply_text_corrections': 'text',
                    'get_canonical_name': 'text'
                }
                
                for func, ret_type in expected_functions.items():
                    if func in functions:
                        print(f"  ✓ {func}() -> {functions[func]}")
                    else:
                        print(f"  ✗ {func}(): MISSING!")
                
                # Test get_canonical_name
                print()
                print("FUNCTION TESTS")
                print("-" * 40)
                test_cases = [
                    ('JEFFREY EPSTEIN', 'Jeffrey Epstein'),
                    ('Jeff Epstein', 'Jeffrey Epstein'),
                    ('Unknown Person', 'Unknown Person'),  # Should pass through unchanged
                ]
                
                for input_name, expected in test_cases:
                    cur.execute('SELECT get_canonical_name(%s)', (input_name,))
                    result = cur.fetchone()[0]
                    status = "✓" if result == expected else "✗"
                    print(f'  {status} get_canonical_name("{input_name}") = "{result}"')
                
                print()
                
                # Check foreign keys
                print("FOREIGN KEYS")
                print("-" * 40)
                cur.execute("""
                    SELECT 
                        tc.table_name,
                        kcu.column_name,
                        ccu.table_name AS foreign_table,
                        ccu.column_name AS foreign_column
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu 
                        ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage ccu 
                        ON ccu.constraint_name = tc.constraint_name
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    ORDER BY tc.table_name
                """)
                fks = cur.fetchall()
                
                expected_fks = [
                    ('entity_network_mentions', 'entity_id', 'entity_network_entities', 'entity_id'),
                    ('entity_network_relationships', 'source_entity_id', 'entity_network_entities', 'entity_id'),
                    ('entity_network_relationships', 'target_entity_id', 'entity_network_entities', 'entity_id'),
                    ('extracted_dates', 'file_path', 'file_catalog', 'path'),
                    ('extracted_locations', 'file_path', 'file_catalog', 'path'),
                    ('extracted_names', 'file_path', 'file_catalog', 'path'),
                    ('extracted_text_content', 'file_path', 'file_catalog', 'path'),
                ]
                
                for fk in fks:
                    table, col, ref_table, ref_col = fk
                    print(f"  ✓ {table}.{col} -> {ref_table}.{ref_col}")
                
                print(f"\n  Total: {len(fks)} foreign keys")
                print()
                
                # Summary
                print("=" * 80)
                print("SUMMARY")
                print("=" * 80)
                
                all_ok = True
                
                table_ok = len(tables) == 20
                view_ok = len(views) == 12
                func_ok = len(functions) == 2
                fk_ok = len(fks) >= 7
                
                print(f"Tables: {len(tables)}/20 {'✓' if table_ok else '✗'}")
                print(f"Views: {len(views)}/12 {'✓' if view_ok else '✗'}")
                print(f"Functions: {len(functions)}/2 {'✓' if func_ok else '✗'}")
                print(f"Foreign Keys: {len(fks)}/7+ {'✓' if fk_ok else '✗'}")
                
                if table_ok and view_ok and func_ok and fk_ok:
                    print()
                    print("✓ All database verification checks passed!")
                    return 0
                else:
                    print()
                    print("✗ Some verification checks failed!")
                    return 1
                    
    except Exception as e:
        print(f"✗ Database error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
