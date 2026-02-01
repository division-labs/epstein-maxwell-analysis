#!/usr/bin/env python3
"""Shared configuration for Epstein-Maxwell analysis scripts.

Central configuration to reduce duplication across scripts.
"""
import os
from pathlib import Path
from typing import Optional

# Load .env file if it exists
_env_file = Path(__file__).parent / '.env'
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


# --- Automatic .env loading ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # If python-dotenv is not installed, skip (env must be set manually)

# Database Configuration
# Set DATABASE_URL in .env file or environment, or override via --dsn argument
# See .env.example for template
DEFAULT_DSN = os.getenv('DATABASE_URL', 'postgresql://localhost/postgres')
DEFAULT_SCHEMA = 'public'

# File Processing Configuration
DEFAULT_EXTRACT_EXTENSION = '_extracted.txt'
DEFAULT_PDF_EXTENSION = '.pdf'

# Spelling Analysis Configuration
CONTEXT_WINDOW_SIZE = 50
HIGH_CONFIDENCE_DISTANCE_THRESHOLD = 2
MEDIUM_CONFIDENCE_MAX_DISTANCE = 4
SHORT_DOCUMENT_THRESHOLD = 1000
MEDIUM_DOCUMENT_THRESHOLD = 5000
HIGH_ERROR_RATE_THRESHOLD = 10.0
TFIDF_LOW_DOC_FREQUENCY_THRESHOLD = 10
AUTO_CORRECTION_SCRIPT_TOP_N = 30
REPORT_MAX_CONSISTENCY_ISSUES = 30
REPORT_TOP_WORDS_LIMIT = 50

# Known Terms Dictionary (for spelling analysis)
KNOWN_LEGAL_TERMS = {
    'plaintiff', 'defendant', 'deposition', 'litigation', 'subpoena',
    'affidavit', 'testimony', 'exhibits', 'petitioner', 'respondent',
    # Add more as needed
}

# NLP Configuration
SPACY_MODEL = 'en_core_web_md'
NLTK_TOKENIZER = 'punkt'

# ─────────────────────────────────────────────────────────────────────────────
# Name Normalization Seed Data
# ─────────────────────────────────────────────────────────────────────────────
# 
# NOTE: These are SEED values used to bootstrap the name_normalization_rules table.
# Once the database is initialized, the table becomes the source of truth.
# Add new rules using SQL: INSERT INTO name_normalization_rules (rule_type, pattern, ...)
# 
# Rule types:
#   - 'title': Words to strip from beginning of names (mr, mrs, judge, etc.)
#   - 'artifact_suffix': Words to strip from end of names (mailto, date, etc.)
#   - 'ocr_pattern': Character substitutions (rn→m, 0→o, etc.)
#
# See: disambiguate_entities_enhanced.py load_normalization_rules()
# ─────────────────────────────────────────────────────────────────────────────

# Seed titles (loaded into name_normalization_rules on table creation)
SEED_TITLES = {
    # Basic honorifics
    'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor',
    'sir', 'lady', 'lord', 'the', 'hon', 'honorable',
    # Legal/judicial titles
    'judge', 'justice', 'magistrate', 'chief', 'associate',
    # Law enforcement titles
    'detective', 'det', 'officer', 'agent', 'special', 'assistant',
    'sa', 'ssa', 'deputy', 'sheriff', 'marshal',
    # Academic titles
    'ph.d', 'phd', 'md', 'esq', 'esquire',
    # Military ranks
    'lt', 'cpt', 'maj', 'col', 'gen', 'sgt', 'pvt',
    'lieutenant', 'captain', 'major', 'colonel', 'general', 'sergeant', 'private',
    # Business titles (often in signature blocks)
    'ceo', 'cfo', 'coo', 'president', 'vp', 'director', 'manager',
}

# Seed artifact suffixes (OCR artifacts attached to names)
SEED_ARTIFACT_SUFFIXES = {
    # Email header artifacts
    'sent', 'cc', 'to', 'from', 'subject', 're', 'fwd', 'mailto',
    # Signature block artifacts  
    'partner', 'counsel', 'associate', 'paralegal',
    # Document/form field artifacts
    'date', 'document', 'defendant', 'documents', 'dob', 'exhibit',
}

# Seed OCR character confusion patterns
SEED_OCR_PATTERNS = {
    'rn': 'm',    # Berman → Bernan
    'cl': 'd',    # Clinton → Dinton
    'vv': 'w',    # Maxwell → Maxvvell
    'nn': 'm',    # Mann → Mam
    'li': 'h',    # light → hght
    '1': 'l',     # 1ight → light
    '0': 'O',     # 0bama → Obama
    '5': 'S',     # 5mith → Smith
}

# ─────────────────────────────────────────────────────────────────────────────
# Legacy aliases (for backward compatibility with existing scripts)
# Use SEED_* versions above for new code
# ─────────────────────────────────────────────────────────────────────────────
TITLES = SEED_TITLES
ARTIFACT_SUFFIXES = list(SEED_ARTIFACT_SUFFIXES)
OCR_PATTERNS = SEED_OCR_PATTERNS

# Term Canonicalization for Community Labels
# Maps canonical display name -> list of term combinations that should be recognized
# Each combination is a tuple of lowercase terms that, when found together in top nouns, 
# should be replaced with the canonical name
TERM_CANONICALIZATION = {
    'White Plains, NY': [('white', 'pls'), ('white', 'pis'), ('white', 'plains')],
    'New York': [('new', 'york'), ('new', 'yorlc'), ('new', 'yodc')],
    'Bronx, NYC': [('bronx', 'nyc')],
    # MCC/Prison terms
    'SHU': [('shu',)],  # Special Housing Unit - always uppercase
    'MCC': [('mcc',)],  # Metropolitan Correctional Center - always uppercase
    # Add more as discovered from OCR patterns
}


def get_database_dsn(dsn_override: Optional[str] = None) -> str:
    """Get database connection string with fallback.
    
    Args:
        dsn_override: Optional custom DSN to use instead of default.
        
    Returns:
        Database connection string (DSN).
    """
    return dsn_override or DEFAULT_DSN


def get_output_directory(base_path: str, subdir: str = 'output') -> str:
    """Get or create output directory for results.
    
    Args:
        base_path: Base directory path.
        subdir: Subdirectory name to create (default: 'output').
        
    Returns:
        Absolute path to the output directory.
    """
    output_dir = os.path.join(base_path, subdir)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir
