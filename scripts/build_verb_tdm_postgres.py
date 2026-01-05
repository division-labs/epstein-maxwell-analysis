#!/usr/bin/env python3
"""Build a term-document matrix from extracted text files using only verbs and save to PostgreSQL.

This script:
1. Crawls a directory for extracted text files (e.g., *_extracted.txt)
2. Extracts verbs using POS tagging (spaCy preferred, NLTK fallback)
3. Builds a term-document matrix with documents as rows and verb terms as columns
4. Saves to PostgreSQL in an efficient normalized format

Database Schema:
    verb_tdm_vocabulary: Stores unique verb terms with IDs
    verb_tdm_documents: Stores document metadata
    verb_tdm_counts: Stores sparse term-document counts (document_id, term_id, count)

Usage:
  python3 scripts/build_verb_tdm_postgres.py "/path/to/root" \\
      --dsn postgresql://user@localhost/postgres \\
      --ext _extracted.txt --verbose
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from typing import List, Dict, Set, Tuple

try:
    import psycopg
    from psycopg import Connection
except ImportError:
    psycopg = None

from db_utils import table_exists, get_db_connection

try:
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm")
        nlp.max_length = 5_000_000
    except:
        print("Downloading spaCy model...")
        from spacy.cli import download
        download("en_core_web_sm")
        nlp = spacy.load("en_core_web_sm")
        nlp.max_length = 5_000_000
    SPACY_AVAILABLE = True
except Exception as e:
    nlp = None
    SPACY_AVAILABLE = False
    print(f"spaCy not available: {e}")

try:
    import nltk
    from nltk import pos_tag, word_tokenize
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)
    try:
        nltk.data.find('taggers/averaged_perceptron_tagger')
    except LookupError:
        nltk.download('averaged_perceptron_tagger', quiet=True)
    NLTK_AVAILABLE = True
except Exception as e:
    NLTK_AVAILABLE = False


# Database schema
CREATE_VOCABULARY_TABLE = """
CREATE TABLE IF NOT EXISTS verb_tdm_vocabulary (
    term_id SERIAL PRIMARY KEY,
    term TEXT UNIQUE NOT NULL,
    document_frequency INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_verb_vocab_term ON verb_tdm_vocabulary(term);
"""

CREATE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS verb_tdm_documents (
    doc_id SERIAL PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    verb_count INTEGER DEFAULT 0,
    unique_verbs INTEGER DEFAULT 0,
    processed_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_verb_doc_path ON verb_tdm_documents(file_path);
"""

CREATE_COUNTS_TABLE = """
CREATE TABLE IF NOT EXISTS verb_tdm_counts (
    doc_id INTEGER NOT NULL REFERENCES verb_tdm_documents(doc_id) ON DELETE CASCADE,
    term_id INTEGER NOT NULL REFERENCES verb_tdm_vocabulary(term_id) ON DELETE CASCADE,
    count INTEGER NOT NULL,
    PRIMARY KEY (doc_id, term_id)
);
CREATE INDEX IF NOT EXISTS idx_verb_counts_doc ON verb_tdm_counts(doc_id);
CREATE INDEX IF NOT EXISTS idx_verb_counts_term ON verb_tdm_counts(term_id);
"""

CREATE_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS verb_tdm_metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);
"""


def extract_verbs_spacy(text: str) -> List[str]:
    """Extract verbs from text using spaCy NLP."""
    if not SPACY_AVAILABLE or nlp is None:
        return []
    doc = nlp(text)
    verbs = [token.lemma_.lower() for token in doc if token.pos_ == 'VERB' and token.is_alpha]
    return verbs


def extract_verbs_nltk(text: str) -> List[str]:
    """Extract verbs from text using NLTK POS tagging."""
    if not NLTK_AVAILABLE:
        return []
    tokens = word_tokenize(text)
    tagged = pos_tag(tokens)
    verbs = [word.lower() for word, tag in tagged if tag.startswith('VB') and word.isalpha()]
    return verbs


def extract_verbs_simple(text: str) -> List[str]:
    """Simple fallback: extract words with common verb endings."""
    import re
    words = re.findall(r'\b[a-z]+(?:ed|ing|s|es)\b', text.lower())
    return words


def extract_verbs(text: str, method: str = 'auto') -> List[str]:
    """Extract verbs from text using the best available method."""
    if method == 'auto':
        if SPACY_AVAILABLE:
            return extract_verbs_spacy(text)
        elif NLTK_AVAILABLE:
            return extract_verbs_nltk(text)
        else:
            return extract_verbs_simple(text)
    elif method == 'spacy':
        return extract_verbs_spacy(text)
    elif method == 'nltk':
        return extract_verbs_nltk(text)
    elif method == 'simple':
        return extract_verbs_simple(text)
    else:
        return []


def initialize_database(conn: Connection, verbose: bool = False) -> None:
    """Create database tables if they don't exist."""
    if verbose:
        print("Initializing database schema...")
    with conn.cursor() as cur:
        cur.execute(CREATE_VOCABULARY_TABLE)
        cur.execute(CREATE_DOCUMENTS_TABLE)
        cur.execute(CREATE_COUNTS_TABLE)
        cur.execute(CREATE_METADATA_TABLE)
    conn.commit()
    if verbose:
        print("Database schema ready.")


def clear_existing_data(conn: Connection, verbose: bool = False) -> None:
    """Clear existing TDM data (useful for rebuilding)."""
    if verbose:
        print("Clearing existing verb TDM data...")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM verb_tdm_counts")
        cur.execute("DELETE FROM verb_tdm_documents")
        cur.execute("DELETE FROM verb_tdm_vocabulary")
        cur.execute("DELETE FROM verb_tdm_metadata WHERE key LIKE 'verb_tdm_%'")
    conn.commit()
    if verbose:
        print("Existing data cleared.")


def build_and_save_tdm(
    conn: Connection,
    file_paths: List[str],
    extension: str,
    method: str = 'auto',
    min_df: int = 2,
    max_df_ratio: float = 0.8,
    verbose: bool = False
) -> Tuple[int, int, int]:
    """Build TDM and save to PostgreSQL.
    
    Returns:
        (num_documents, num_terms, num_nonzero_entries)
    """
    # Filter files by extension
    filtered_files = [f for f in file_paths if f.endswith(extension)]
    if verbose:
        print(f"Processing {len(filtered_files)} files with extension '{extension}'")
    
    # Extract verbs from each document
    doc_verbs: Dict[str, List[str]] = {}
    for i, path in enumerate(filtered_files):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            verbs = extract_verbs(text, method=method)
            doc_verbs[path] = verbs
            if verbose and (i + 1) % 100 == 0:
                print(f"Processed {i + 1}/{len(filtered_files)} files, found {len(verbs)} verbs in {os.path.basename(path)}")
        except Exception as e:
            if verbose:
                print(f"Error processing {path}: {e}")
            continue
    
    if not doc_verbs:
        if verbose:
            print("No documents processed successfully")
        return (0, 0, 0)
    
    # Build vocabulary with document frequency filtering
    term_doc_freq: Dict[str, int] = Counter()
    for verbs in doc_verbs.values():
        unique_verbs = set(verbs)
        for verb in unique_verbs:
            term_doc_freq[verb] += 1
    
    num_docs = len(doc_verbs)
    max_df = int(max_df_ratio * num_docs)
    
    # Filter terms by document frequency
    vocabulary: Set[str] = {
        term for term, df in term_doc_freq.items()
        if min_df <= df <= max_df and len(term) > 2
    }
    
    if verbose:
        print(f"Vocabulary size: {len(vocabulary)} (from {len(term_doc_freq)} total)")
        print(f"Min doc freq: {min_df}, Max doc freq: {max_df}")
    
    # Insert vocabulary into database
    if verbose:
        print("Inserting vocabulary into database...")
    term_to_id: Dict[str, int] = {}
    with conn.cursor() as cur:
        for term in sorted(vocabulary):
            result = cur.execute(
                """INSERT INTO verb_tdm_vocabulary (term, document_frequency) 
                   VALUES (%s, %s) 
                   ON CONFLICT (term) DO UPDATE SET document_frequency = EXCLUDED.document_frequency
                   RETURNING term_id""",
                (term, term_doc_freq[term])
            ).fetchone()
            term_to_id[term] = result[0]
    conn.commit()
    
    if verbose:
        print(f"Inserted {len(term_to_id)} terms into vocabulary table")
    
    # Insert documents and counts
    if verbose:
        print("Inserting documents and term counts...")
    
    doc_count = 0
    nonzero_count = 0
    batch_size = 1000
    count_batch = []
    
    for path, verbs in doc_verbs.items():
        # Insert document
        with conn.cursor() as cur:
            result = cur.execute(
                """INSERT INTO verb_tdm_documents (file_path, file_name, verb_count, unique_verbs) 
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (file_path) DO UPDATE 
                   SET verb_count = EXCLUDED.verb_count, 
                       unique_verbs = EXCLUDED.unique_verbs,
                       processed_at = NOW()
                   RETURNING doc_id""",
                (path, os.path.basename(path), len(verbs), len(set(verbs) & vocabulary))
            ).fetchone()
            doc_id = result[0]
        conn.commit()
        
        # Prepare counts for this document
        verb_counts = Counter(verbs)
        for term, count in verb_counts.items():
            if term in term_to_id:
                count_batch.append((doc_id, term_to_id[term], count))
                nonzero_count += 1
        
        # Batch insert counts
        if len(count_batch) >= batch_size:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO verb_tdm_counts (doc_id, term_id, count) 
                       VALUES (%s, %s, %s)
                       ON CONFLICT (doc_id, term_id) DO UPDATE SET count = EXCLUDED.count""",
                    count_batch
                )
            conn.commit()
            count_batch = []
        
        doc_count += 1
        if verbose and doc_count % 100 == 0:
            print(f"Inserted {doc_count}/{len(doc_verbs)} documents")
    
    # Insert remaining counts
    if count_batch:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO verb_tdm_counts (doc_id, term_id, count) 
                   VALUES (%s, %s, %s)
                   ON CONFLICT (doc_id, term_id) DO UPDATE SET count = EXCLUDED.count""",
                count_batch
            )
        conn.commit()
    
    # Save metadata
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO verb_tdm_metadata (key, value, updated_at) 
               VALUES (%s, %s, NOW()) 
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            ('verb_tdm_num_documents', str(doc_count))
        )
        cur.execute(
            """INSERT INTO verb_tdm_metadata (key, value, updated_at) 
               VALUES (%s, %s, NOW()) 
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            ('verb_tdm_num_terms', str(len(vocabulary)))
        )
        cur.execute(
            """INSERT INTO verb_tdm_metadata (key, value, updated_at) 
               VALUES (%s, %s, NOW()) 
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            ('verb_tdm_nonzero_entries', str(nonzero_count))
        )
        sparsity = 1 - (nonzero_count / (doc_count * len(vocabulary))) if doc_count and vocabulary else 0
        cur.execute(
            """INSERT INTO verb_tdm_metadata (key, value, updated_at) 
               VALUES (%s, %s, NOW()) 
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            ('verb_tdm_sparsity', f"{sparsity:.4f}")
        )
    conn.commit()
    
    if verbose:
        print(f"TDM matrix: {doc_count} documents × {len(vocabulary)} terms")
        print(f"Non-zero entries: {nonzero_count}")
        print(f"Sparsity: {sparsity:.2%}")
    
    return (doc_count, len(vocabulary), nonzero_count)


def crawl_files(root: str, extension: str) -> List[str]:
    """Crawl directory tree and collect file paths matching extension."""
    matches = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(extension):
                # Normalize path to remove leading ./ for consistency
                path = os.path.join(dirpath, name)
                if path.startswith('./'):
                    path = path[2:]
                matches.append(path)
    return matches


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build verb term-document matrix and save to PostgreSQL"
    )
    parser.add_argument("root", help="Root directory to scan for text files")
    parser.add_argument(
        "--dsn",
        default=None,
        help="PostgreSQL connection string (default: DATABASE_URL env var)"
    )
    parser.add_argument(
        "--ext",
        default="_extracted.txt",
        help="File extension to match (default: _extracted.txt)"
    )
    parser.add_argument(
        "--method",
        choices=['auto', 'spacy', 'nltk', 'simple'],
        default='auto',
        help="Verb extraction method (default: auto)"
    )
    parser.add_argument(
        "--min-df",
        type=int,
        default=2,
        help="Minimum document frequency for terms (default: 2)"
    )
    parser.add_argument(
        "--max-df",
        type=float,
        default=0.8,
        help="Maximum document frequency ratio (default: 0.8)"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing verb TDM data before building (requires --confirm)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required for --clear operation"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()
    
    if psycopg is None:
        print("psycopg is required. Install with: pip install psycopg", file=sys.stderr)
        return 2
    
    # Check for --confirm on destructive operations
    if args.clear and not args.confirm and not args.dry_run:
        print("ERROR: --clear requires --confirm flag for safety.", file=sys.stderr)
        print("Use --dry-run to preview what would be cleared.", file=sys.stderr)
        print("\nExample: python3 scripts/build_verb_tdm_postgres.py . --clear --confirm", file=sys.stderr)
        return 1
    
    if not SPACY_AVAILABLE and not NLTK_AVAILABLE:
        print("Warning: Neither spaCy nor NLTK available. Using simple fallback method.")
    
    # Handle dry-run mode
    if args.dry_run:
        print("[DRY RUN] Would perform the following operations:")
        if args.clear:
            print("  - Clear existing verb TDM data (DELETE from all verb_tdm_* tables)")
        print(f"  - Scan {args.root} for files ending with '{args.ext}'")
        print(f"  - Build verb term-document matrix using '{args.method}' method")
        print(f"  - Filter terms with min_df={args.min_df}, max_df_ratio={args.max_df}")
        print("  - Save results to PostgreSQL")
        return 0
    
    # Connect to database
    try:
        with get_db_connection(args.dsn) as conn:
            start_time = time.time()
            
            # Initialize database
            initialize_database(conn, verbose=args.verbose)
            
            # Clear existing data if requested
            if args.clear:
                clear_existing_data(conn, verbose=args.verbose)
            
            # Crawl for files
            if args.verbose:
                print(f"Scanning {args.root} for files ending with '{args.ext}'...")
            file_paths = crawl_files(args.root, args.ext)
            if args.verbose:
                print(f"Found {len(file_paths)} files")
            
            if not file_paths:
                print(f"No files found with extension '{args.ext}'", file=sys.stderr)
                return 1
            
            # Build and save TDM
            num_docs, num_terms, num_entries = build_and_save_tdm(
                conn,
                file_paths,
                args.ext,
                method=args.method,
                min_df=args.min_df,
                max_df_ratio=args.max_df,
                verbose=args.verbose
            )
            
            if num_docs == 0:
                print("Failed to build term-document matrix", file=sys.stderr)
                return 1
            
            elapsed = time.time() - start_time
            if args.verbose:
                print(f"\nSuccessfully saved verb TDM to PostgreSQL")
                print(f"  Documents: {num_docs}")
                print(f"  Terms: {num_terms}")
                print(f"  Non-zero entries: {num_entries}")
                print(f"  Elapsed time: {elapsed:.1f}s")
            
            return 0
    except Exception as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
