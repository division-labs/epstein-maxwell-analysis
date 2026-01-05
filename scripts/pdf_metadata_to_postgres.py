#!/usr/bin/env python3
"""Extract PDF document metadata and insert into Postgres.

Creates a `pdf_metadata` table (if missing) with per-file metadata:
- path, file_name, size_bytes, page_count
- common PDF info: title, author, subject, keywords, creator, producer
- creation_date, modification_date (parsed from PDF date format)
- raw info map as JSONB (metadata_json)
- mtime, ctime from filesystem

Usage examples:
  python3 scripts/pdf_metadata_to_postgres.py \
      "/path/to/root" --dsn postgresql://user:pass@localhost/postgres

If --dsn is omitted, uses DATABASE_URL from the environment.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

try:
    import psycopg
except Exception:
    psycopg = None  # type: ignore

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore

from db_utils import table_exists, get_db_connection


def parse_pdf_date(s: Optional[str]) -> Optional[datetime]:
    """Parse PDF date strings to naive UTC datetime.
    
    Handles PDF date format (D:YYYYMMDDHHmmSS±HH'MM') and converts to UTC.
    Supports both 'Z' timezone indicator and offset formats like -05'00'.
    
    Args:
        s: PDF date string (e.g., "D:20210329154523-05'00'").
        
    Returns:
        Naive UTC datetime object, or None if parsing fails.
    """
    if not s:
        return None
    s = s.strip()
    if s.startswith("D:"):
        s = s[2:]
    # Base components
    year = int(s[0:4]) if len(s) >= 4 else None
    month = int(s[4:6]) if len(s) >= 6 else 1
    day = int(s[6:8]) if len(s) >= 8 else 1
    hour = int(s[8:10]) if len(s) >= 10 else 0
    minute = int(s[10:12]) if len(s) >= 12 else 0
    second = int(s[12:14]) if len(s) >= 14 else 0
    if not year:
        return None
    dt = datetime(year, month, day, hour, minute, second)
    # Timezone offset
    tz_part = s[14:]
    tz_part = tz_part.strip() if tz_part else ""
    if tz_part.upper().startswith("Z"):
        # already UTC
        return dt.replace(tzinfo=timezone.utc).astimezone(timezone.utc).replace(tzinfo=None)
    # Matches +/-HH'MM' or +/-HHMM or +/-HH
    sign = 1
    offset_hours = 0
    offset_minutes = 0
    if tz_part:
        if tz_part[0] in ['+', '-']:
            sign = -1 if tz_part[0] == '-' else 1
            rest = tz_part[1:]
            # Remove quotes if present
            rest = rest.replace("'", "")
            # HHMM, HH, or HH:MM variants
            try:
                if ":" in rest:
                    parts = rest.split(":")
                    offset_hours = int(parts[0])
                    offset_minutes = int(parts[1]) if len(parts) > 1 else 0
                elif len(rest) >= 3:
                    offset_hours = int(rest[0:2])
                    offset_minutes = int(rest[2:4]) if len(rest) >= 4 else 0
                elif len(rest) >= 2:
                    offset_hours = int(rest[0:2])
                    offset_minutes = 0
            except Exception:
                offset_hours = 0
                offset_minutes = 0
        # else unrecognized/empty tz
    offset = timedelta(hours=sign * offset_hours, minutes=sign * offset_minutes)
    dt_local = dt.replace(tzinfo=timezone(offset))
    dt_utc = dt_local.astimezone(timezone.utc).replace(tzinfo=None)
    return dt_utc


def get_info_value(info: Any, key: str) -> Optional[str]:
    """Extract a string value from pypdf metadata mapping.
    
    Supports both '/Title' style and plain keys. Works with different
    versions of pypdf that may expose metadata differently.
    
    Args:
        info: pypdf metadata object (from reader.metadata or reader.documentInfo).
        key: Metadata key to extract (e.g., '/Title', 'Title', or '/Author').
        
    Returns:
        String value of the metadata field, or None if not found.
    """
    if info is None:
        return None
    # pypdf >= 3 uses reader.metadata, a dict-like with '/Title' etc.
    try:
        if key in info:
            val = info.get(key)
            return str(val) if val is not None else None
        # also try without leading slash
        if key.startswith('/'):
            nk = key[1:]
            if nk in info:
                val = info.get(nk)
                return str(val) if val is not None else None
    except Exception:
        pass
    # pypdf older versions may expose attributes
    try:
        val = getattr(info, key.lstrip('/'), None)
        return str(val) if val is not None else None
    except Exception:
        return None


def info_to_dict(info: Any) -> Dict[str, Any]:
    """Convert pypdf metadata mapping to a plain dictionary.
    
    Extracts all metadata fields from pypdf's internal representation
    and returns them as a simple dict suitable for JSON serialization.
    
    Args:
        info: pypdf metadata object (from reader.metadata or reader.documentInfo).
        
    Returns:
        Dictionary mapping metadata keys to their string values.
    """
    result: Dict[str, Any] = {}
    if info is None:
        return result
    try:
        # Prefer dict-like iteration
        for k in list(getattr(info, 'keys', lambda: [])()):
            try:
                v = info.get(k)
            except Exception:
                v = None
            if v is not None:
                result[str(k)] = str(v)
    except Exception:
        # Fallback: try common keys
        for k in ['/Title', '/Author', '/Subject', '/Keywords', '/Creator', '/Producer', '/CreationDate', '/ModDate']:
            v = get_info_value(info, k)
            if v is not None:
                result[k] = v
    return result


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pdf_metadata (
    path TEXT PRIMARY KEY,
    file_name TEXT,
    size_bytes BIGINT,
    page_count INTEGER,
    title TEXT,
    author TEXT,
    subject TEXT,
    keywords TEXT,
    creator TEXT,
    producer TEXT,
    creation_date TIMESTAMP NULL,
    modification_date TIMESTAMP NULL,
    metadata_json JSONB NULL,
    mtime TIMESTAMP,
    ctime TIMESTAMP
);
"""

UPSERT_SQL = """
INSERT INTO pdf_metadata (
    path, file_name, size_bytes, page_count,
    title, author, subject, keywords, creator, producer,
    creation_date, modification_date, metadata_json,
    mtime, ctime
) VALUES (
    %(path)s, %(file_name)s, %(size_bytes)s, %(page_count)s,
    %(title)s, %(author)s, %(subject)s, %(keywords)s, %(creator)s, %(producer)s,
    %(creation_date)s, %(modification_date)s, %(metadata_json)s,
    %(mtime)s, %(ctime)s
)
ON CONFLICT (path) DO UPDATE SET
  file_name = EXCLUDED.file_name,
  size_bytes = EXCLUDED.size_bytes,
  page_count = EXCLUDED.page_count,
  title = EXCLUDED.title,
  author = EXCLUDED.author,
  subject = EXCLUDED.subject,
  keywords = EXCLUDED.keywords,
  creator = EXCLUDED.creator,
  producer = EXCLUDED.producer,
  creation_date = EXCLUDED.creation_date,
  modification_date = EXCLUDED.modification_date,
  metadata_json = EXCLUDED.metadata_json,
  mtime = EXCLUDED.mtime,
  ctime = EXCLUDED.ctime;
"""


def get_dsn(cli_dsn: Optional[str]) -> Optional[str]:
    """Get database connection string from CLI argument or environment.
    
    Args:
        cli_dsn: Connection string from command line argument.
        
    Returns:
        Connection string from CLI or DATABASE_URL environment variable.
    """
    if cli_dsn:
        return cli_dsn
    return os.environ.get('DATABASE_URL')


def process_pdf(path: str) -> Optional[dict]:
    """Extract metadata from a PDF file.
    
    Reads PDF metadata using pypdf and combines it with filesystem
    information to create a complete metadata record.
    
    Args:
        path: Absolute path to the PDF file.
        
    Returns:
        Dictionary containing all metadata fields ready for database insertion,
        or None if extraction fails.
    """
    if PdfReader is None:
        return None
    try:
        reader = PdfReader(path)
        info = getattr(reader, 'metadata', None)
        if info is None:
            info = getattr(reader, 'documentInfo', None)
        info_map = info_to_dict(info)
        title = get_info_value(info, '/Title')
        author = get_info_value(info, '/Author')
        subject = get_info_value(info, '/Subject')
        keywords = get_info_value(info, '/Keywords')
        creator = get_info_value(info, '/Creator')
        producer = get_info_value(info, '/Producer')
        creation_raw = get_info_value(info, '/CreationDate')
        mod_raw = get_info_value(info, '/ModDate')
        creation_date = parse_pdf_date(creation_raw)
        modification_date = parse_pdf_date(mod_raw)
        page_count = len(reader.pages)
        st = os.stat(path)
        rec = {
            'path': path,
            'file_name': os.path.basename(path),
            'size_bytes': st.st_size,
            'page_count': page_count,
            'title': title,
            'author': author,
            'subject': subject,
            'keywords': keywords,
            'creator': creator,
            'producer': producer,
            'creation_date': creation_date,
            'modification_date': modification_date,
            'metadata_json': json.dumps(info_map) if info_map else None,
            'mtime': datetime.fromtimestamp(st.st_mtime),
            'ctime': datetime.fromtimestamp(st.st_ctime),
        }
        return rec
    except Exception:
        return None


def main() -> int:
    """Main entry point for PDF metadata extraction.
    
    Walks a directory tree, extracts metadata from all PDFs, and stores
    the metadata in a PostgreSQL database table.
    
    Returns:
        Exit code: 0 on success, 2 on configuration error.
    """
    parser = argparse.ArgumentParser(description="Extract PDF metadata into Postgres")
    parser.add_argument("root", help="Root directory to scan for PDFs")
    parser.add_argument("--dsn", help="Postgres DSN (overrides DATABASE_URL)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    dsn = get_dsn(args.dsn)
    if not dsn:
        print("Missing DSN: set --dsn or DATABASE_URL", file=sys.stderr)
        return 2
    if psycopg is None:
        print("psycopg not available", file=sys.stderr)
        return 2

    start_time = time.time()
    total = 0
    inserted = 0
    
    if args.verbose:
        print(f"Scanning {args.root} for PDF files...")
    
    with get_db_connection(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        for root, _dirs, files in os.walk(args.root):
            for name in files:
                if not name.lower().endswith('.pdf'):
                    continue
                path = os.path.join(root, name)
                total += 1
                rec = process_pdf(path)
                if rec is None:
                    if args.verbose:
                        print(f"Skip (no metadata) {path}")
                    continue
                try:
                    with conn.cursor() as cur:
                        cur.execute(UPSERT_SQL, rec)
                    inserted += 1
                    if args.verbose:
                        print(f"[{inserted}/{total}] Inserted metadata: {name}")
                except Exception as e:
                    if args.verbose:
                        print(f"Error inserting {path}: {e}")
                    # continue on errors
                    continue
    
    elapsed = time.time() - start_time
    if args.verbose:
        print(f"\nProcessed PDFs: {total}, inserted: {inserted}")
        print(f"Elapsed time: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
