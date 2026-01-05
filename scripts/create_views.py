#!/usr/bin/env python3
"""Create analytical database views for document analysis.

All SQL view definitions are embedded in this script.

Usage:
    python3 scripts/create_views.py --dsn postgresql://user:pass@localhost/postgres
"""
import argparse
import sys
from typing import Dict, List

try:
    import psycopg
except ImportError:
    print("Error: psycopg required. Install with: pip install psycopg")
    sys.exit(1)

from config import DEFAULT_DSN
from db_utils import get_db_connection


# ==============================================================================
# FUNCTION DEFINITIONS
# ==============================================================================

FUNCTION_DEFINITIONS: Dict[str, str] = {
    'apply_text_corrections': """
        CREATE OR REPLACE FUNCTION apply_text_corrections(
            original_text TEXT,
            corrections JSONB
        ) RETURNS TEXT AS $$
        DECLARE
            corrected_text TEXT;
            correction JSONB;
            word_pattern TEXT;
        BEGIN
            -- Start with the original text
            corrected_text := original_text;
            
            -- Return original if no corrections
            IF corrections IS NULL OR jsonb_array_length(corrections) = 0 THEN
                RETURN corrected_text;
            END IF;
            
            -- Apply each correction using word boundary matching
            FOR correction IN SELECT * FROM jsonb_array_elements(corrections)
            LOOP
                -- Build pattern with word boundaries (case insensitive)
                word_pattern := '\\m' || quote_literal(correction->>'word') || '\\M';
                
                -- Simple word-by-word replacement (case insensitive, global)
                corrected_text := regexp_replace(
                    corrected_text,
                    correction->>'word',
                    correction->>'replacement',
                    'gi'
                );
            END LOOP;
            
            RETURN corrected_text;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
    """
}


# ==============================================================================
# VIEW DEFINITIONS
# ==============================================================================

VIEW_DEFINITIONS: Dict[str, str] = {
    'v_document_quality': """
        CREATE OR REPLACE VIEW v_document_quality AS
        SELECT 
            fc.path,
            fc.file_name,
            fc.size_bytes,
            fc.mtime,
            -- Spelling statistics (excluding abbreviations and fragments)
            COUNT(DISTINCT si.word) FILTER (WHERE si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE) AS unique_errors,
            COUNT(si.word) FILTER (WHERE si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE) AS total_errors,
            -- Error rate calculation (only true errors)
            ROUND(
                CAST(COUNT(si.word) FILTER (WHERE si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE) AS NUMERIC) / NULLIF(fc.size_bytes / 500.0, 0) * 100,
                2
            ) AS error_rate_percent,
            -- Confidence distribution (excluding abbreviations and fragments)
            COUNT(CASE WHEN si.correction_confidence = 'HIGH' AND si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE THEN 1 END) AS high_confidence_errors,
            COUNT(CASE WHEN si.correction_confidence = 'MEDIUM' AND si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE THEN 1 END) AS medium_confidence_errors,
            COUNT(CASE WHEN si.correction_confidence = 'LOW' AND si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE THEN 1 END) AS low_confidence_errors,
            -- OCR patterns
            COUNT(CASE WHEN si.ocr_error_pattern IS NOT NULL AND si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE THEN 1 END) AS ocr_pattern_errors,
            COUNT(CASE WHEN si.boundary_error_pattern IS NOT NULL AND si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE THEN 1 END) AS boundary_errors,
            -- Separate counts for abbreviations and fragments (informational only)
            COUNT(CASE WHEN si.is_abbreviation = TRUE THEN 1 END) AS abbreviation_count,
            COUNT(CASE WHEN si.is_ocr_fragment = TRUE THEN 1 END) AS fragment_count,
            -- Foreign language detection
            COUNT(CASE WHEN si.is_foreign_word = TRUE THEN 1 END) AS foreign_word_count,
            COUNT(CASE WHEN si.foreign_language_confidence = 'HIGH' THEN 1 END) AS high_confidence_foreign,
            -- Average distances (excluding abbreviations and fragments)
            ROUND(AVG(si.levenshtein_distance) FILTER (WHERE si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE), 2) AS avg_edit_distance,
            ROUND(AVG(si.damerau_levenshtein_distance) FILTER (WHERE si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE), 2) AS avg_damerau_distance,
            -- Quality score (0-100, higher is better, based on true errors only)
            GREATEST(0, 100 - ROUND(
                CAST(COUNT(si.word) FILTER (WHERE si.is_abbreviation = FALSE AND si.is_ocr_fragment = FALSE) AS NUMERIC) / NULLIF(fc.size_bytes / 500.0, 0) * 100,
                2
            )) AS quality_score
        FROM 
            file_catalog fc
        LEFT JOIN 
            spelling_issues si ON fc.path = si.file_path
        WHERE 
            fc.path LIKE '%_extracted.txt'
        GROUP BY 
            fc.path, fc.file_name, fc.size_bytes, fc.mtime
        ORDER BY 
            error_rate_percent DESC NULLS LAST;
    """,
    
    'v_high_priority_corrections': """
        CREATE OR REPLACE VIEW v_high_priority_corrections AS
        SELECT 
            word,
            suggested_correction,
            COUNT(DISTINCT file_path) AS document_count,
            COUNT(*) AS occurrence_count,
            MIN(levenshtein_distance) AS min_distance,
            MAX(levenshtein_distance) AS max_distance,
            ROUND(AVG(damerau_levenshtein_distance), 2) AS avg_damerau_distance,
            -- Context examples (aggregate first few)
            STRING_AGG(DISTINCT SUBSTRING(context_before || ' [' || word || '] ' || context_after, 1, 100), ' | ') 
                AS example_contexts,
            -- OCR pattern if consistent
            MODE() WITHIN GROUP (ORDER BY ocr_error_pattern) AS common_ocr_pattern
        FROM 
            spelling_issues
        WHERE 
            correction_confidence = 'HIGH'
            AND suggested_correction IS NOT NULL
            AND is_abbreviation = FALSE
            AND is_ocr_fragment = FALSE
        GROUP BY 
            word, suggested_correction
        HAVING 
            COUNT(*) >= 2  -- Appears at least twice
        ORDER BY 
            occurrence_count DESC, document_count DESC;
    """,
    
    'v_document_entities': """
        CREATE OR REPLACE VIEW v_document_entities AS
        SELECT 
            fc.path,
            fc.file_name,
            -- Date entities (aggregated in subquery)
            COALESCE(dates.unique_dates, 0) AS unique_dates,
            COALESCE(dates.total_date_mentions, 0) AS total_date_mentions,
            dates.earliest_date,
            dates.latest_date,
            -- Name entities (aggregated in subquery)
            COALESCE(names.unique_names, 0) AS unique_names,
            COALESCE(names.total_name_mentions, 0) AS total_name_mentions,
            names.all_names,
            -- Location entities (aggregated in subquery)
            COALESCE(locations.unique_locations, 0) AS unique_locations,
            COALESCE(locations.total_location_mentions, 0) AS total_location_mentions,
            locations.all_locations
        FROM 
            file_catalog fc
        LEFT JOIN (
            SELECT 
                file_path,
                COUNT(DISTINCT date_string) AS unique_dates,
                COUNT(*) AS total_date_mentions,
                MIN(date_datetime) AS earliest_date,
                MAX(date_datetime) AS latest_date
            FROM extracted_dates
            GROUP BY file_path
        ) dates ON fc.path = dates.file_path
        LEFT JOIN (
            SELECT 
                file_path,
                COUNT(DISTINCT name_string) AS unique_names,
                SUM(occurrence_count) AS total_name_mentions,
                STRING_AGG(DISTINCT name_string, ', ' ORDER BY name_string) AS all_names
            FROM extracted_names
            WHERE name_string IS NOT NULL
            GROUP BY file_path
        ) names ON fc.path = names.file_path
        LEFT JOIN (
            SELECT 
                file_path,
                COUNT(DISTINCT location_string) AS unique_locations,
                SUM(occurrence_count) AS total_location_mentions,
                STRING_AGG(DISTINCT location_string, ', ' ORDER BY location_string) AS all_locations
            FROM extracted_locations
            WHERE location_string IS NOT NULL
            GROUP BY file_path
        ) locations ON fc.path = locations.file_path
        ORDER BY 
            unique_names DESC, unique_locations DESC, unique_dates DESC;
    """,
    
    'v_person_cooccurrence': """
        CREATE OR REPLACE VIEW v_person_cooccurrence AS
        WITH canonical_names AS (
            SELECT 
                file_path,
                get_canonical_name(name_string) AS canonical_name
            FROM 
                extracted_names
            WHERE 
                name_string IS NOT NULL
        ),
        -- Filter to only include multi-word names or names that resolve via aliases
        filtered_names AS (
            SELECT 
                cn.file_path,
                cn.canonical_name
            FROM 
                canonical_names cn
            WHERE 
                cn.canonical_name IS NOT NULL
                AND (
                    -- Multi-word name (contains a space)
                    cn.canonical_name LIKE '%% %%'
                    -- OR single-word name that is a known alias (resolves to different canonical)
                    OR EXISTS (
                        SELECT 1 FROM entity_aliases ea 
                        WHERE LOWER(ea.alias_name) = LOWER(cn.canonical_name)
                        OR LOWER(ea.canonical_name) = LOWER(cn.canonical_name)
                    )
                )
        ),
        name_pairs AS (
            SELECT 
                fn1.canonical_name AS person_1,
                fn2.canonical_name AS person_2,
                fn1.file_path,
                fc.file_name
            FROM 
                filtered_names fn1
            INNER JOIN 
                filtered_names fn2 
                ON fn1.file_path = fn2.file_path 
                AND fn1.canonical_name < fn2.canonical_name
            INNER JOIN
                file_catalog fc
                ON fn1.file_path = fc.path
            WHERE 
                fn1.canonical_name != fn2.canonical_name
        )
        SELECT 
            person_1,
            person_2,
            COUNT(DISTINCT file_path) AS shared_documents,
            STRING_AGG(DISTINCT file_name, ', ' ORDER BY file_name) AS document_list
        FROM 
            name_pairs
        GROUP BY 
            person_1, person_2
        HAVING 
            COUNT(DISTINCT file_path) >= 2
        ORDER BY 
            shared_documents DESC;
    """,
    
    'v_ocr_pattern_summary': """
        CREATE OR REPLACE VIEW v_ocr_pattern_summary AS
        SELECT 
            ocr_error_pattern,
            COUNT(DISTINCT word) AS unique_words_affected,
            COUNT(*) AS total_occurrences,
            COUNT(DISTINCT file_path) AS documents_affected,
            STRING_AGG(DISTINCT word || ' → ' || suggested_correction, ', ') 
                AS example_corrections,
            -- Average quality of affected documents
            ROUND(AVG(
                CAST((SELECT COUNT(*) FROM spelling_issues si2 WHERE si2.file_path = si.file_path) AS NUMERIC)
            ), 0) AS avg_errors_per_doc
        FROM 
            spelling_issues si
        WHERE 
            ocr_error_pattern IS NOT NULL
        GROUP BY 
            ocr_error_pattern
        ORDER BY 
            total_occurrences DESC;
    """,
    
    'v_document_timeline': """
        CREATE OR REPLACE VIEW v_document_timeline AS
        SELECT 
            ed.date_datetime AS document_date,
            ed.date_string AS date_as_written,
            fc.file_name,
            fc.path,
            fc.mtime AS file_modified,
            -- Confidence indicator (date is valid)
            CASE 
                WHEN ed.date_datetime IS NOT NULL THEN 'Parsed'
                ELSE 'Unparsed'
            END AS date_quality
        FROM 
            extracted_dates ed
        JOIN 
            file_catalog fc ON ed.file_path = fc.path
        WHERE 
            ed.date_datetime IS NOT NULL
        ORDER BY 
            ed.date_datetime DESC NULLS LAST;
    """,
    
    'v_complex_documents': """
        CREATE OR REPLACE VIEW v_complex_documents AS
        WITH doc_errors AS (
            SELECT 
                file_path,
                COUNT(DISTINCT word) AS unique_errors,
                COUNT(*) AS total_errors
            FROM spelling_issues
            GROUP BY file_path
        ),
        doc_names AS (
            SELECT 
                file_path,
                COUNT(DISTINCT name_string) AS unique_names,
                SUM(occurrence_count) AS total_names
            FROM extracted_names
            GROUP BY file_path
        ),
        doc_locations AS (
            SELECT 
                file_path,
                COUNT(DISTINCT location_string) AS unique_locations
            FROM extracted_locations
            GROUP BY file_path
        ),
        doc_dates AS (
            SELECT 
                file_path,
                COUNT(DISTINCT date_string) AS unique_dates
            FROM extracted_dates
            GROUP BY file_path
        )
        SELECT 
            fc.path,
            fc.file_name,
            fc.size_bytes,
            ROUND(fc.size_bytes / 1024.0 / 1024.0, 2) AS size_mb,
            -- Complexity indicators
            COALESCE(de.unique_errors, 0) AS unique_errors,
            COALESCE(dn.unique_names, 0) AS unique_names,
            COALESCE(dl.unique_locations, 0) AS unique_locations,
            COALESCE(dd.unique_dates, 0) AS unique_dates,
            -- Complexity score
            COALESCE(de.total_errors, 0)
            + COALESCE(dn.total_names, 0) * 5
            + COALESCE(dl.unique_locations, 0) * 2
            AS complexity_score
        FROM 
            file_catalog fc
        LEFT JOIN doc_errors de ON fc.path = de.file_path
        LEFT JOIN doc_names dn ON fc.path = dn.file_path
        LEFT JOIN doc_locations dl ON fc.path = dl.file_path
        LEFT JOIN doc_dates dd ON fc.path = dd.file_path
        WHERE 
            fc.path LIKE '%_extracted.txt'
        ORDER BY 
            complexity_score DESC;
    """,
    
    'v_location_summary': """
        CREATE OR REPLACE VIEW v_location_summary AS
        SELECT 
            el.location_string,
            COUNT(DISTINCT el.file_path) AS document_count,
            COUNT(*) AS mention_count,
            STRING_AGG(DISTINCT fc.file_name, ', ') AS mentioned_in_documents
        FROM 
            extracted_locations el
        INNER JOIN
            file_catalog fc
            ON el.file_path = fc.path
        WHERE 
            el.location_string IS NOT NULL
        GROUP BY 
            el.location_string
        HAVING 
            COUNT(DISTINCT el.file_path) >= 2
        ORDER BY 
            document_count DESC, mention_count DESC;
    """,
    
    'v_spelling_variants': """
        CREATE OR REPLACE VIEW v_spelling_variants AS
        WITH word_groups AS (
            SELECT 
                word,
                suggested_correction,
                COUNT(*) AS occurrence_count,
                COUNT(DISTINCT file_path) AS document_count
            FROM 
                spelling_issues
            WHERE 
                suggested_correction IS NOT NULL
                AND is_abbreviation = FALSE
                AND is_ocr_fragment = FALSE
            GROUP BY 
                word, suggested_correction
        )
        SELECT 
            suggested_correction AS canonical_word,
            STRING_AGG(word, ', ' ORDER BY occurrence_count DESC) AS variant_spellings,
            COUNT(DISTINCT word) AS variant_count,
            SUM(occurrence_count) AS total_occurrences,
            SUM(document_count) AS total_document_spread
        FROM 
            word_groups
        GROUP BY 
            suggested_correction
        HAVING 
            COUNT(DISTINCT word) >= 2  -- At least 2 different spellings
        ORDER BY 
            variant_count DESC, total_occurrences DESC;
    """,
    
    'v_foreign_language_words': """
        CREATE OR REPLACE VIEW v_foreign_language_words AS
        SELECT 
            word,
            detected_language,
            foreign_language_suggestion,
            foreign_language_confidence,
            foreign_word_translation,
            COUNT(DISTINCT file_path) AS document_count,
            COUNT(*) AS occurrence_count,
            STRING_AGG(DISTINCT SUBSTRING(context_before || ' [' || word || '] ' || context_after, 1, 100), ' | ') 
                AS example_contexts
        FROM 
            spelling_issues
        WHERE 
            is_foreign_word = TRUE
            AND detected_language IS NOT NULL
        GROUP BY 
            word, detected_language, foreign_language_suggestion, foreign_language_confidence, foreign_word_translation
        ORDER BY 
            occurrence_count DESC, document_count DESC;
    """,
    
    'v_corpus_summary': """
        CREATE OR REPLACE VIEW v_corpus_summary AS
        SELECT 
            -- Document statistics
            (SELECT COUNT(*) FROM file_catalog) AS total_documents,
            (SELECT COUNT(*) FROM file_catalog WHERE path LIKE '%_extracted.txt') AS documents_analyzed,
            (SELECT ROUND(SUM(size_bytes) / 1024.0 / 1024.0, 2) FROM file_catalog) AS total_size_mb,
            
            -- Entity statistics
            (SELECT COUNT(DISTINCT name_string) FROM extracted_names) AS unique_names,
            (SELECT SUM(occurrence_count) FROM extracted_names) AS total_name_mentions,
            (SELECT COUNT(DISTINCT location_string) FROM extracted_locations) AS unique_locations,
            (SELECT SUM(occurrence_count) FROM extracted_locations) AS total_location_mentions,
            (SELECT COUNT(DISTINCT date_string) FROM extracted_dates) AS unique_dates,
            (SELECT MIN(date_datetime) FROM extracted_dates) AS earliest_date,
            (SELECT MAX(date_datetime) FROM extracted_dates) AS latest_date,
            
            -- Spelling statistics (true errors only)
            (SELECT COUNT(DISTINCT word) FROM spelling_issues WHERE is_abbreviation = FALSE AND is_ocr_fragment = FALSE) AS unique_spelling_errors,
            (SELECT COUNT(*) FROM spelling_issues WHERE correction_confidence = 'HIGH' AND is_abbreviation = FALSE AND is_ocr_fragment = FALSE) AS high_confidence_corrections,
            (SELECT COUNT(DISTINCT ocr_error_pattern) FROM spelling_issues WHERE ocr_error_pattern IS NOT NULL AND is_abbreviation = FALSE) AS distinct_ocr_patterns,
            
            -- Tracked but excluded from error counts
            (SELECT COUNT(DISTINCT word) FROM spelling_issues WHERE is_abbreviation = TRUE) AS unique_abbreviations,
            (SELECT COUNT(DISTINCT word) FROM spelling_issues WHERE is_ocr_fragment = TRUE) AS unique_fragments,
            
            -- Foreign language detection
            (SELECT COUNT(DISTINCT word) FROM spelling_issues WHERE is_foreign_word = TRUE) AS unique_foreign_words,
            (SELECT COUNT(DISTINCT detected_language) FROM spelling_issues WHERE is_foreign_word = TRUE) AS languages_detected,
            (SELECT COUNT(*) FROM spelling_issues WHERE is_foreign_word = TRUE AND foreign_word_translation IS NOT NULL) AS translated_words,
            
            -- Quality metrics
            (SELECT ROUND(AVG(quality_score), 1) FROM v_document_quality) AS avg_quality_score,
            (SELECT COUNT(*) FROM v_document_quality WHERE quality_score < 80) AS low_quality_document_count;
    """,
    
    'v_corrected_text': """
        CREATE OR REPLACE VIEW v_corrected_text AS
        WITH high_confidence_corrections AS (
            -- Get all high-confidence spelling corrections and translations
            SELECT DISTINCT ON (file_path, word)
                file_path,
                word,
                COALESCE(
                    CASE WHEN foreign_language_confidence = 'HIGH' AND foreign_word_translation IS NOT NULL 
                         THEN foreign_word_translation 
                         ELSE NULL 
                    END,
                    CASE WHEN correction_confidence = 'HIGH' AND suggested_correction IS NOT NULL 
                         THEN suggested_correction 
                         ELSE NULL 
                    END
                ) AS replacement,
                CASE 
                    WHEN foreign_language_confidence = 'HIGH' AND foreign_word_translation IS NOT NULL 
                         THEN 'translation'
                    WHEN correction_confidence = 'HIGH' AND suggested_correction IS NOT NULL 
                         THEN 'spelling'
                    ELSE NULL
                END AS correction_type
            FROM spelling_issues
            WHERE 
                (correction_confidence = 'HIGH' AND suggested_correction IS NOT NULL AND is_abbreviation = FALSE AND is_ocr_fragment = FALSE)
                OR (foreign_language_confidence = 'HIGH' AND foreign_word_translation IS NOT NULL)
        ),
        correction_aggregates AS (
            -- Aggregate corrections per file
            SELECT 
                file_path,
                COUNT(*) AS correction_count,
                COUNT(*) FILTER (WHERE correction_type = 'spelling') AS spelling_corrections,
                COUNT(*) FILTER (WHERE correction_type = 'translation') AS translation_corrections,
                json_agg(
                    json_build_object(
                        'word', word, 
                        'replacement', replacement, 
                        'type', correction_type
                    ) ORDER BY word
                ) AS corrections
            FROM high_confidence_corrections
            WHERE replacement IS NOT NULL
            GROUP BY file_path
        )
        SELECT 
            etc.file_path,
            fc.file_name,
            etc.text_length AS original_text_length,
            etc.word_count AS original_word_count,
            etc.raw_text AS original_text,
            COALESCE(ca.correction_count, 0) AS total_corrections,
            COALESCE(ca.spelling_corrections, 0) AS spelling_corrections,
            COALESCE(ca.translation_corrections, 0) AS translation_corrections,
            ca.corrections AS correction_details,
            -- Apply corrections to generate corrected text
            CASE 
                WHEN ca.correction_count > 0 
                THEN apply_text_corrections(etc.raw_text, ca.corrections::jsonb)
                ELSE etc.raw_text
            END AS corrected_text,
            etc.last_updated,
            CASE 
                WHEN ca.correction_count > 0 
                THEN 'Corrections applied to corrected_text field'
                ELSE 'No high-confidence corrections needed'
            END AS correction_status
        FROM 
            extracted_text_content etc
        INNER JOIN 
            file_catalog fc ON etc.file_path = fc.path
        LEFT JOIN 
            correction_aggregates ca ON etc.file_path = ca.file_path
        ORDER BY 
            ca.correction_count DESC NULLS LAST,
            etc.text_length DESC;
    """
}

# View descriptions for comments
VIEW_DESCRIPTIONS: Dict[str, str] = {
    'v_document_quality': 'Document quality metrics showing error rates, confidence distribution, and quality scores',
    'v_high_priority_corrections': 'High-confidence spelling corrections that appear multiple times across documents',
    'v_document_entities': 'Summary of all extracted entities (dates, names, locations) per document',
    'v_person_cooccurrence': 'People who appear together in multiple documents (network analysis)',
    'v_ocr_pattern_summary': 'Summary of OCR error patterns to identify systematic scanning issues',
    'v_document_timeline': 'Chronological timeline of documents based on extracted dates',
    'v_complex_documents': 'Documents ranked by complexity (size, entities, errors) requiring more review',
    'v_location_summary': 'Summary of locations mentioned across multiple documents',
    'v_spelling_variants': 'Words with multiple variant spellings that should be standardized',
    'v_foreign_language_words': 'Foreign language words detected with translations and confidence levels',
    'v_corpus_summary': 'Executive summary dashboard showing key metrics across entire document corpus',
    'v_corrected_text': 'Original and corrected text with high-confidence spelling/translation substitutions applied'
}


def create_views(dsn: str, verbose: bool = False) -> int:
    """Create all analytical views in the database.
    
    Args:
        dsn: Database connection string
        verbose: Print detailed output
        
    Returns:
        0 on success, 1 on error
    """
    if verbose:
        print(f"Creating {len(FUNCTION_DEFINITIONS)} function(s) and {len(VIEW_DEFINITIONS)} view(s)...")
    
    try:
        with get_db_connection(dsn) as conn:
            # First, create functions
            functions_created = 0
            functions_failed = []
            
            for func_name, func_sql in FUNCTION_DEFINITIONS.items():
                try:
                    with conn.cursor() as cur:
                        cur.execute(func_sql)
                        functions_created += 1
                        if verbose:
                            print(f"✓ Created function: {func_name}")
                except Exception as e:
                    functions_failed.append((func_name, str(e)))
                    if verbose:
                        print(f"✗ Failed to create function {func_name}: {e}")
            
            # Then create views
            created = 0
            failed = []
            
            for view_name, view_sql in VIEW_DEFINITIONS.items():
                try:
                    with conn.cursor() as cur:
                        # Create view
                        cur.execute(view_sql)
                        
                        # Add comment if available
                        if view_name in VIEW_DESCRIPTIONS:
                            comment_sql = f"COMMENT ON VIEW {view_name} IS '{VIEW_DESCRIPTIONS[view_name]}';"
                            cur.execute(comment_sql)
                    
                    conn.commit()
                    created += 1
                    if verbose:
                        print(f"✓ Created view: {view_name}")
                        
                except Exception as e:
                    conn.rollback()
                    failed.append((view_name, str(e)))
                    print(f"✗ Failed to create view {view_name}: {e}")
            
            # Summary
            if functions_created > 0 or created > 0:
                print(f"\n✓ Successfully created {functions_created}/{len(FUNCTION_DEFINITIONS)} function(s) and {created}/{len(VIEW_DEFINITIONS)} view(s)")
            
            if functions_failed:
                print(f"\n✗ Failed to create {len(functions_failed)} function(s):")
                for func_name, error in functions_failed:
                    print(f"  - {func_name}: {error}")
            
            if failed:
                print(f"\n✗ Failed to create {len(failed)} view(s):")
                for view_name, error in failed:
                    print(f"  - {view_name}: {error}")
            
            # List all created views
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.views 
                    WHERE table_schema = 'public' 
                    AND table_name LIKE 'v_%'
                    ORDER BY table_name
                """)
                views = [row[0] for row in cur.fetchall()]
            
            if views:
                print(f"\nAvailable views ({len(views)}):")
                for view in views:
                    desc = VIEW_DESCRIPTIONS.get(view, 'No description')
                    print(f"  - {view}: {desc}")
            
            return 0 if not (failed or functions_failed) else 1
            
    except Exception as e:
        print(f"Database connection error: {e}")
        return 1


def list_views() -> None:
    """List all available view definitions.
    
    Prints a formatted list of all database view definitions with their
    descriptions to standard output.
    
    Returns:
        None
    """
    print("Available view definitions:")
    print("=" * 80)
    for view_name, description in VIEW_DESCRIPTIONS.items():
        print(f"\n{view_name}")
        print(f"  {description}")


def main():
    """Main entry point for creating database views.
    
    Handles command-line arguments and coordinates view creation.
    Supports listing available views or creating all views.
    
    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="Create analytical database views",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  # Create all views
  python3 create_views.py --dsn postgresql://user:pass@localhost/postgres
  
  # Create with verbose output
  python3 create_views.py --dsn postgresql://user:pass@localhost/postgres --verbose
  
  # List available views
  python3 create_views.py --list
"""
    )
    parser.add_argument(
        "--dsn",
        default=DEFAULT_DSN,
        help="PostgreSQL connection string"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available view definitions and exit"
    )
    
    args = parser.parse_args()
    
    if args.list:
        list_views()
        return 0
    
    return create_views(args.dsn, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
