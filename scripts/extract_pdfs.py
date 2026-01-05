#!/usr/bin/env python3
"""Walk a folder tree, extract text from PDFs and save as text files.

Usage:
  python3 scripts/extract_pdfs.py /path/to/root --ext _extracted.txt

Defaults to current directory. Use --force to overwrite existing outputs.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Tuple

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore


def extract_pdf_to_text(pdf_path: str, out_path: str) -> Tuple[bool, str]:
    """Extract text from a PDF file and save to a text file.
    
    Args:
        pdf_path: Path to the input PDF file.
        out_path: Path where the extracted text will be saved.
        
    Returns:
        Tuple of (success, error_message). On success, returns (True, "").
        On failure, returns (False, error_description).
    """
    if PdfReader is None:
        return False, "pypdf not installed"
    try:
        reader = PdfReader(pdf_path)
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        return True, ""
    except Exception as e:
        return False, str(e)


def should_process(file_name: str) -> bool:
    """Determine if a file should be processed based on its extension.
    
    Args:
        file_name: Name of the file to check.
        
    Returns:
        True if the file is a PDF (ends with .pdf), False otherwise.
    """
    return file_name.lower().endswith(".pdf")


def main() -> int:
    """Main entry point for PDF text extraction.
    
    Walks a directory tree, extracts text from all PDFs, and saves the
    extracted text to corresponding .txt files.
    
    Returns:
        Exit code: 0 on success.
    """
    parser = argparse.ArgumentParser(description="Extract text from PDFs into .txt files")
    parser.add_argument("root", nargs="?", default=".", help="Root folder to crawl")
    parser.add_argument("--ext", default="_extracted.txt", help="Output filename suffix")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if args.verbose:
        print(f"Crawling: {root}")

    count_total = 0
    count_ok = 0
    count_skipped = 0
    count_err = 0

    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            if not should_process(name):
                continue
            count_total += 1
            pdf_path = os.path.join(dirpath, name)
            base = name.rsplit(".", 1)[0]
            out_name = base + args.ext
            out_path = os.path.join(dirpath, out_name)

            if os.path.exists(out_path) and not args.force:
                count_skipped += 1
                if args.verbose:
                    print(f"Skipping existing: {out_path}")
                continue

            if args.dry_run:
                print(f"Would extract: {pdf_path} -> {out_path}")
                continue

            ok, err = extract_pdf_to_text(pdf_path, out_path)
            if ok:
                count_ok += 1
                print(f"Wrote: {out_path}")
            else:
                count_err += 1
                print(f"Error extracting {pdf_path}: {err}", file=sys.stderr)

    print(f"Done. Found {count_total} PDFs, extracted {count_ok}, skipped {count_skipped}, errors {count_err}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
