#!/usr/bin/env python3
"""Load extracted text file contents into PostgreSQL database.

This script reads extracted text files and stores their raw content in a database
table for full-text search and analysis. The table joins with file_catalog via
file_path for comprehensive document analysis.

Features:
    - Stores complete raw text content from extracted files
    - Tracks text length and last update timestamp
    - Foreign key relationship with file_catalog table
    - Batch processing with transaction support
    - Progress reporting and error handling

Database Schema:
    Creates 'extracted_text_content' table with:
    - file_path: Primary key and foreign key to file_catalog
    - raw_text: Complete text content from extracted file
    - text_length: Character count for quick reference
    - word_count: Approximate word count
    - last_updated: Timestamp of last content update

Usage:
    python3 scripts/load_extracted_text.py "/path/to/root" \
        --dsn postgresql://user:pass@localhost/postgres \
        --ext _extracted.txt --verbose

Example:
    export DATABASE_URL='postgresql://user:pass@localhost/postgres'
    python3 scripts/load_extracted_text.py "/path/to/data" \
        --ext _extracted.txt --verbose

Requirements:
    - psycopg (PostgreSQL adapter)
    - Extracted text files from extract_pdfs.py
    - file_catalog table must exist
"""
import argparse
import os
import sys
from datetime import datetime
from typing import Optional

try:
    import psycopg
except ImportError:
    print("Error: psycopg required. Install with: pip install psycopg", file=sys.stderr)
    sys.exit(1)

from db_utils import table_exists, get_db_connection

# =============================================================================
# DATABASE SCHEMA
# =============================================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS extracted_text_content (
    file_path TEXT PRIMARY KEY,
    raw_text TEXT NOT NULL,
    text_length INTEGER NOT NULL,
    word_count INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign key to file_catalog
    CONSTRAINT fk_file_catalog 
        FOREIGN KEY (file_path) 
        REFERENCES file_catalog(path) 
        ON DELETE CASCADE
);

-- Index for text search (if using PostgreSQL full-text search)
CREATE INDEX IF NOT EXISTS idx_extracted_text_fts 
    ON extracted_text_content USING gin(to_tsvector('english', raw_text));

-- Index for efficient joins
CREATE INDEX IF NOT EXISTS idx_extracted_text_path 
    ON extracted_text_content(file_path);

-- Index for filtering by size
CREATE INDEX IF NOT EXISTS idx_extracted_text_length 
    ON extracted_text_content(text_length);
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_table(conn, verbose: bool = False) -> None:
    """Create the extracted_text_content table if it doesn't exist.
    
    Args:
        conn: Database connection
        verbose: Print detailed output
    """
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.commit()
        
        if verbose:
            print("✓ Table 'extracted_text_content' ready")
            
    except Exception as e:
        print(f"Error creating table: {e}", file=sys.stderr)
        raise


def count_words(text: str) -> int:
    """Approximate word count for text.
    
    Args:
        text: Text content to count
        
    Returns:
        Approximate number of words
    """
    return len(text.split())


def load_text_file(file_path: str, verbose: bool = False) -> Optional[str]:
    """Load text content from file.
    
    Args:
        file_path: Path to text file
        verbose: Print detailed output
        
    Returns:
        Text content or None if error
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return content
    except Exception as e:
        if verbose:
            print(f"  Error reading {file_path}: {e}")
        return None


def store_text_content(
    conn,
    file_path: str,
    text_content: str,
    verbose: bool = False
) -> bool:
    """Store text content in database.
    
    Args:
        conn: Database connection
        file_path: Path to original file (joins with file_catalog)
        text_content: Raw text content
        verbose: Print detailed output
        
    Returns:
        True if stored successfully, False otherwise
    """
    try:
        text_length = len(text_content)
        word_count = count_words(text_content)
        
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO extracted_text_content (
                    file_path, raw_text, text_length, word_count, last_updated
                )
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (file_path) DO UPDATE SET
                    raw_text = EXCLUDED.raw_text,
                    text_length = EXCLUDED.text_length,
                    word_count = EXCLUDED.word_count,
                    last_updated = CURRENT_TIMESTAMP;
            """, (file_path, text_content, text_length, word_count))
        
        if verbose:
            print(f"  Stored: {text_length:,} chars, {word_count:,} words")
        
        return True
        
    except Exception as e:
        if verbose:
            print(f"  Error storing content: {e}")
        return False


def get_extracted_text_files(root: str, extension: str = "_extracted.txt") -> list:
    """Find all extracted text files in the directory tree.
    
    Args:
        root: Root directory to search
        extension: File extension to match
        
    Returns:
        List of file paths
    """
    files = []
    
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if filename.endswith(extension):
                file_path = os.path.join(dirpath, filename)
                files.append(file_path)
    
    return files


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_files(
    root: str,
    dsn: str,
    extension: str = "_extracted.txt",
    verbose: bool = False,
    batch_size: int = 100
) -> int:
    """Process all extracted text files and load into database.
    
    Args:
        root: Root directory containing files
        dsn: Database connection string
        extension: File extension to match
        verbose: Print detailed output
        batch_size: Number of files to process before committing
        
    Returns:
        Number of files processed successfully
    """
    # Find all extracted text files
    if verbose:
        print(f"Scanning {root} for files with extension '{extension}'...")
    
    files = get_extracted_text_files(root, extension)
    
    if not files:
        print(f"No files found with extension '{extension}'", file=sys.stderr)
        return 0
    
    if verbose:
        print(f"Found {len(files)} extracted text files")
        print()
    
    # Connect to database
    try:
        with get_db_connection(dsn) as conn:
            # Create table
            create_table(conn, verbose)
            
            # Process files in batches
            processed = 0
            errors = 0
            
            for i, file_path in enumerate(files, start=1):
                if verbose:
                    print(f"[{i}/{len(files)}] Processing: {os.path.basename(file_path)}")
                
                # Load text content
                text_content = load_text_file(file_path, verbose)
                
                if text_content is None:
                    errors += 1
                    continue
                
                # Get relative path for database (same format as file_catalog)
                rel_path = os.path.relpath(file_path, root)
                
                # Store in database
                if store_text_content(conn, rel_path, text_content, verbose):
                    processed += 1
                else:
                    errors += 1
                
                # Commit in batches
                if processed % batch_size == 0:
                    conn.commit()
                    if verbose:
                        print(f"  Committed batch ({processed} files processed)")
            
            # Final commit
            conn.commit()
            
            if verbose:
                print()
                print("="*80)
                print("PROCESSING COMPLETE")
                print("="*80)
                print(f"Successfully processed: {processed:,} files")
                if errors > 0:
                    print(f"Errors encountered: {errors:,} files")
                print()
            
            return processed
            
    except Exception as e:
        print(f"Database connection or processing error: {e}", file=sys.stderr)
        return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load extracted text file contents into PostgreSQL database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load all extracted text files
  python3 scripts/load_extracted_text.py "/path/to/files" \\
      --dsn postgresql://user:pass@localhost/postgres \\
      --ext _extracted.txt --verbose

  # Use environment variable for DSN
  export DATABASE_URL='postgresql://user:pass@localhost/postgres'
  python3 scripts/load_extracted_text.py "/path/to/files" --verbose
        """
    )
    
    parser.add_argument(
        "root",
        help="Root directory containing extracted text files"
    )
    
    parser.add_argument(
        "--dsn",
        help="PostgreSQL connection string (or set DATABASE_URL env var)"
    )
    
    parser.add_argument(
        "--ext",
        default="_extracted.txt",
        help="File extension for extracted text files (default: _extracted.txt)"
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of files to process before committing (default: 100)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Get DSN from args or environment
    dsn = args.dsn or os.environ.get('DATABASE_URL')
    if not dsn:
        print("Error: Database DSN required. Use --dsn or set DATABASE_URL", file=sys.stderr)
        return 1
    
    # Validate root directory
    if not os.path.isdir(args.root):
        print(f"Error: Directory not found: {args.root}", file=sys.stderr)
        return 1
    
    # Process files
    start_time = datetime.now()
    
    if args.verbose:
        print("="*80)
        print("LOADING EXTRACTED TEXT CONTENT")
        print("="*80)
        print(f"Root directory: {args.root}")
        print(f"File extension: {args.ext}")
        print(f"Batch size: {args.batch_size}")
        print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        print()
    
    processed = process_files(
        args.root,
        dsn,
        args.ext,
        args.verbose,
        args.batch_size
    )
    
    if args.verbose:
        elapsed = datetime.now() - start_time
        print(f"Elapsed time: {elapsed}")
        print()
    
    return 0 if processed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
