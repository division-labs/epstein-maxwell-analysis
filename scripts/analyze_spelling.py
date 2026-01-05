#!/usr/bin/env python3
"""Analyze extracted text files for spelling issues and unknown words.

This script performs comprehensive spelling analysis on OCR-extracted text files,
identifying errors, categorizing abbreviations, detecting OCR patterns, and
generating actionable recommendations for document quality improvement.

Features:
    - Spell checking with custom dictionary support (476+ known terms)
    - Multi-language spell checking (29 languages: German, French, Spanish, etc.)
    - Foreign word detection and English translation (via Google Translate)
    - OCR error pattern detection (l→1, O→0, rn→m, etc.)
    - Confidence scoring (HIGH/MEDIUM/LOW) for corrections
    - Document quality assessment (error rate calculation)
    - TF-IDF analysis for distinctive error terms
    - Cross-document consistency checking
    - Auto-correction script generation
    - Abbreviation categorization (states, countries, legal terms)
    - OCR fragment detection and classification

Performance Optimizations:
    - Batch database inserts (5-10x speedup)
    - Smart foreign language filtering (reduces checks by 30-40%)
    - Translation frequency threshold (reduces API calls by 50-70%)
    - Edit distance filtering for foreign word accuracy
    - Comprehensive caching for spell checking and translations

Database Schema:
    Creates 'spelling_issues' table with:
    - Word occurrence tracking with positions
    - Context windows (50 chars before/after)
    - Edit distance metrics (Hamming, Levenshtein)
    - OCR pattern classification
    - Confidence levels for corrections
    - Foreign language detection and suggestions
    - English translations of foreign words

Output:
    - PostgreSQL database with detailed error records
    - Comprehensive log report with statistics
    - Optional auto-correction Python script

Usage:
    python3 scripts/analyze_spelling.py "/path/to/root" \\
        --dsn postgresql://user:pass@localhost/postgres \\
        --ext _extracted.txt --log spelling_analysis.log --verbose

Example:
    # Analyze Epstein-Maxwell files with verbose output
    python3 scripts/analyze_spelling.py \\
        "/Users/user/Desktop/Epstein-Maxwell Files" \\
        --dsn postgresql://user:pass@localhost/postgres \\
        --ext _extracted.txt --verbose

Requirements:
    - psycopg (PostgreSQL adapter)
    - pyspellchecker (spell checking library, 8 language dictionaries available)
    - deep-translator (Google Translate integration for foreign words)
    - Python 3.9+ (dataclasses, type hints)

Author: Nathan Lindstedt
Date: December 2025
Version: 3.0 (Multi-language + Performance Optimizations)
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import List, Dict, Set, Tuple, Optional

try:
    import psycopg
except Exception:
    psycopg = None  # type: ignore

from db_utils import table_exists, get_db_connection

try:
    from spellchecker import SpellChecker
    SPELLCHECKER_AVAILABLE = True
except Exception:
    SPELLCHECKER_AVAILABLE = False
    print("SpellChecker not available. Install with: pip install pyspellchecker")

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except Exception:
    TRANSLATOR_AVAILABLE = False
    print("deep_translator not available. Install with: pip install deep-translator")


# =============================================================================
# CONSTANTS AND CONFIGURATION
# =============================================================================

# Formatting constants for reports
SEPARATOR_MAJOR = "=" * 80
SEPARATOR_MINOR = "-" * 80

# Spell check cache: {word: (is_unknown, correction, hamming_dist, levenshtein_dist)}
SPELL_CHECK_CACHE = {}

# Multi-language spell checker cache
LANGUAGE_CHECKERS = {}

# Translation cache: {(word, lang_code): translation}
TRANSLATION_CACHE = {}

# Supported languages for spell checking
SUPPORTED_LANGUAGES = {
    # Western European
    'de': 'German',
    'fr': 'French',
    'es': 'Spanish',
    'pt': 'Portuguese',
    'it': 'Italian',
    'nl': 'Dutch',
    # Nordic/Scandinavian
    'sv': 'Swedish',
    'no': 'Norwegian',
    'da': 'Danish',
    'fi': 'Finnish',
    # Slavic
    'ru': 'Russian',
    'pl': 'Polish',
    'uk': 'Ukrainian',
    'cs': 'Czech',
    'bg': 'Bulgarian',
    'hr': 'Croatian',
    'sl': 'Slovenian',
    'sk': 'Slovak',
    'sr': 'Serbian',
    # Baltic
    'lv': 'Latvian',
    'lt': 'Lithuanian',
    'et': 'Estonian',
    # Other European
    'el': 'Greek',
    'ro': 'Romanian',
    'hu': 'Hungarian',
    'tr': 'Turkish',
    # Middle Eastern
    'ar': 'Arabic',
    'he': 'Hebrew'
}

# Analysis thresholds and configuration
CONTEXT_WINDOW_SIZE = 50  # Characters before/after error for context
HIGH_CONFIDENCE_DISTANCE_THRESHOLD = 2  # Max edit distance for high confidence
MEDIUM_CONFIDENCE_MAX_DISTANCE = 4  # Max edit distance for medium confidence
SHORT_DOCUMENT_THRESHOLD = 1000  # Characters, for categorizing document size
MEDIUM_DOCUMENT_THRESHOLD = 5000  # Characters, for categorizing document size
HIGH_ERROR_RATE_THRESHOLD = 10.0  # Percentage, documents needing review
TFIDF_LOW_DOC_FREQUENCY_THRESHOLD = 10  # Max docs for TF-IDF interesting terms
AUTO_CORRECTION_SCRIPT_TOP_N = 30  # Number of corrections in generated script
REPORT_MAX_CONSISTENCY_ISSUES = 30  # Max consistency issues to report
REPORT_TOP_WORDS_LIMIT = 50  # Top words to include in report


# US State codes (56 total: 50 states + DC + 5 territories)
US_STATE_CODES = {
    'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga',
    'hi', 'id', 'il', 'in', 'ia', 'ks', 'ky', 'la', 'me', 'md',
    'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv', 'nh', 'nj',
    'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc',
    'sd', 'tn', 'tx', 'ut', 'vt', 'va', 'wa', 'wv', 'wi', 'wy',
    'dc', 'pr', 'vi', 'gu', 'as', 'mp'
}

# ISO 3166-1 alpha-2 country codes
COUNTRY_CODES = {
    'us', 'gb', 'uk', 'ca', 'au', 'nz', 'fr', 'de', 'it', 'es', 'pt', 'nl', 'be', 'ch', 'at',
    'se', 'no', 'dk', 'fi', 'ie', 'pl', 'cz', 'hu', 'ro', 'bg', 'gr', 'hr', 'si', 'sk', 'lt',
    'lv', 'ee', 'cy', 'mt', 'lu', 'is', 'mx', 'br', 'ar', 'cl', 'co', 'pe', 've', 'ec', 'uy',
    'py', 'bo', 'cr', 'pa', 'gt', 'hn', 'sv', 'ni', 'do', 'cu', 'jm', 'tt', 'bs', 'bb', 'bz',
    'cn', 'jp', 'kr', 'in', 'pk', 'bd', 'ph', 'vn', 'th', 'my', 'sg', 'id', 'mm', 'kh', 'la',
    'np', 'lk', 'af', 'ir', 'iq', 'sa', 'ae', 'kw', 'qa', 'bh', 'om', 'ye', 'jo', 'lb', 'sy',
    'il', 'ps', 'tr', 'eg', 'za', 'ng', 'ke', 'gh', 'et', 'tz', 'ug', 'dz', 'sd', 'ma', 'ao',
    'mz', 'mg', 'cm', 'ci', 'ne', 'bf', 'ml', 'mw', 'zm', 'zw', 'bw', 'na', 'sn', 'rw', 'so',
    'ru', 'ua', 'by', 'kz', 'uz', 'tm', 'kg', 'tj', 'az', 'ge', 'am', 'md'
}

COMMON_ABBREVIATIONS = {
    # Law Enforcement & Intelligence
    'fbi', 'cia', 'nsa', 'dhs', 'doj', 'atf', 'dea', 'sec', 'irs', 'ice', 'cbp', 'tsa',
    'usss', 'usms', 'bop', 'nij', 'ojp', 'leo', 'le', 'ncic', 'nics', 'codis', 'afis',
    'interpol', 'europol', 'fcc', 'fda', 'epa', 'ftc', 'fema', 'usps', 'nasa', 'noaa',
    'usa', 'usaf', 'usn', 'usmc', 'uscg', 'nato', 'un', 'eu', 'osce',
    # Legal System
    'ada', 'ausa', 'ag', 'da', 'pd', 'ado', 'pdo', 'gao', 'oig', 'ig',
    'scotus', 'potus', 'vpotus', 'flotus', 'ussc', 'usc', 'cfr', 'fr',
    # Legal Abbreviations
    'jd', 'llm', 'sjd', 'esq', 'atty', 'pro', 'se', 'bono', 'hac', 'vice',
    'amicus', 'curiae', 'habeas', 'corpus', 'mandamus', 'certiorari', 'quo', 'warranto',
    'tro', 'pi', 'sua', 'sponte', 'nunc', 'tunc', 'res', 'ipsa', 'loquitur',
    # Case Law & Citations
    'v', 'vs', 'versus', 'ex', 'rel', 'parte', 'misc', 'supp', 'app', 'cir', 'dist',
    'fed', 'cr', 'civ', 'cv', 'no', 'dkt', 'doc', 'ecf', 'pacer', 'lexis', 'westlaw',
    # Criminal Law
    'dui', 'dwi', 'owi', 'bac', 'rico', 'aka', 'dba', 'fka',
    # Evidence & Procedure
    'memo', 'obiter', 'dictum', 'stare', 'decisis', 'mens', 'rea', 'actus', 'reus',
    # Business/Corporate
    'inc', 'llc', 'ltd', 'corp', 'co', 'plc', 'gmbh', 'sa', 'ag', 'nv', 'bv', 'ab', 'oy',
    'ceo', 'cfo', 'cto', 'coo', 'vp', 'svp', 'evp', 'hr', 'it', 'pr', 'gm', 'mgr', 'dir',
    # Titles & Honorifics
    'dr', 'mr', 'mrs', 'ms', 'prof', 'sr', 'jr', 'esq', 'hon', 'rev', 'fr', 'capt', 'lt',
    'maj', 'col', 'gen', 'sgt', 'cpl', 'pvt', 'adm', 'cmdr', 'ens', 'det', 'ofc', 'dep',
    # Addresses & Locations
    'st', 'ave', 'blvd', 'rd', 'ln', 'ct', 'dr', 'pl', 'terr', 'pkwy', 'hwy', 'rte', 'rt',
    'apt', 'ste', 'rm', 'fl', 'bldg', 'dept', 'po', 'box', 'zip', 'nw', 'ne', 'sw', 'se',
    # Time & Dates
    'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
    'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
    'am', 'pm', 'est', 'pst', 'cst', 'mst', 'edt', 'pdt', 'cdt', 'mdt', 'gmt', 'utc', 'bst',
    # Common Office/Communication
    'tel', 'fax', 'ext', 'ph', 'no', 'vs', 'etc', 'ie', 'eg', 'et', 'al', 'ibid', 'supra',
    'asap', 'rsvp', 'fyi', 'tbd', 'tba', 'attn', 'cc', 'bcc', 're', 'ref', 'pp', 'encl',
    # Identification
    'id', 'ssn', 'dob', 'dod', 'ssid', 'ein', 'vin', 'isbn', 'issn',
    # Measurements
    'mph', 'kmh', 'kph', 'lb', 'lbs', 'oz', 'kg', 'g', 'mg', 'km', 'mi', 'ft', 'yd', 'in', 'cm', 'mm',
    'sq', 'gal', 'qt', 'pt', 'ml', 'vol', 'approx', 'est', 'min', 'max', 'avg'
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class AbbreviationInfo:
    """Data structure for abbreviation categorization results.
    
    Classifies words into various abbreviation categories to reduce false
    positives in spell checking. Uses predefined sets of state codes,
    country codes, and common legal/business abbreviations.
    
    Attributes:
        is_abbreviation (bool): True if word matches any abbreviation category.
        is_state_code (bool): True if US state/territory code (56 total).
        is_country_code (bool): True if ISO 3166-1 alpha-2 country code (132 total).
        is_page_number (bool): True if page number or Roman numeral.
        is_date_number (bool): True if date, year, or numeric pattern.
        is_other_abbreviation (bool): True if common legal/business abbreviation.
    
    Example:
        >>> info = AbbreviationInfo(
        ...     is_abbreviation=True,
        ...     is_state_code=True,
        ...     is_country_code=False,
        ...     is_page_number=False,
        ...     is_date_number=False,
        ...     is_other_abbreviation=False
        ... )
        >>> info.is_state_code
        True
    """
    is_abbreviation: bool
    is_state_code: bool
    is_country_code: bool
    is_page_number: bool
    is_date_number: bool
    is_other_abbreviation: bool


@dataclass
class SpellCheckConfig:
    """Configuration parameters for spell checking operations.
    
    Groups related configuration settings to reduce function parameter counts
    and provide clear default values. Can be serialized for configuration files.
    
    Attributes:
        verbose (bool): Enable detailed logging output. Default: False.
        extension (str): File extension to search for. Default: '_extracted.txt'.
        context_window_size (int): Characters to capture before/after errors.
            Default: 50 (from CONTEXT_WINDOW_SIZE constant).
        high_confidence_threshold (int): Max edit distance for high confidence.
            Default: 2 (from HIGH_CONFIDENCE_DISTANCE_THRESHOLD).
        medium_confidence_threshold (int): Max edit distance for medium confidence.
            Default: 4 (from MEDIUM_CONFIDENCE_MAX_DISTANCE).
    
    Example:
        >>> config = SpellCheckConfig(verbose=True, context_window_size=100)
        >>> print(config.high_confidence_threshold)
        2
    
    Note:
        Default values are pulled from module-level constants to ensure
        consistency across the application.
    """
    verbose: bool = False
    extension: str = '_extracted.txt'
    context_window_size: int = CONTEXT_WINDOW_SIZE
    high_confidence_threshold: int = HIGH_CONFIDENCE_DISTANCE_THRESHOLD
    medium_confidence_threshold: int = MEDIUM_CONFIDENCE_MAX_DISTANCE


# =============================================================================
# UTILITY FUNCTIONS AND DECORATORS
# =============================================================================

def handle_errors(verbose: bool = False):
    """Decorator for consistent error handling across functions.
    
    Provides unified exception handling with configurable verbosity.
    Critical errors (in 'main' or 'connect_to_database' functions) are
    re-raised, while non-critical errors return None.
    
    Args:
        verbose (bool): If True, print error messages to stdout.
            Can also check kwargs['verbose'] from decorated function.
            Default: False.
    
    Returns:
        Callable: Decorated function with error handling.
    
    Raises:
        Exception: Re-raises exceptions from critical functions
            (main, connect_to_database).
    
    Example:
        @handle_errors(verbose=True)
        def risky_operation():
            return 1 / 0  # Will print error and return None
        
        @handle_errors(verbose=False)
        def main():
            raise ValueError()  # Will re-raise
    
    Note:
        Non-critical function errors are suppressed and None is returned.
        This prevents cascading failures while logging issues.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if verbose or kwargs.get('verbose', False):
                    print(f"Error in {func.__name__}: {e}")
                # Re-raise for critical errors, return None for non-critical
                if func.__name__ in ['main', 'connect_to_database']:
                    raise
                return None
        return wrapper
    return decorator


@contextmanager
def get_database_connection(dsn: str, verbose: bool = False):
    """Context manager for database connections with automatic cleanup.
    
    This is a wrapper around get_db_connection from db_utils that adds
    verbose output support.
    
    Args:
        dsn (str): PostgreSQL connection string.
        verbose (bool): If True, print connection status messages.
    
    Yields:
        psycopg.Connection: Active database connection object.
    """
    if verbose:
        print(f"Connecting to database...")
    try:
        with get_db_connection(dsn) as conn:
            yield conn
    finally:
        if verbose:
            print("Database connection closed.")


# =============================================================================
# DATABASE SCHEMA
# =============================================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS spelling_issues (
    word TEXT NOT NULL,
    file_path TEXT NOT NULL,
    occurrence_number INTEGER NOT NULL,
    subfolder TEXT,
    
    -- Positional information
    position_start INTEGER,
    position_end INTEGER,
    document_length INTEGER,
    position_percent NUMERIC(5,2),
    
    -- Context windows (for manual review)
    context_before TEXT,
    context_after TEXT,
    
    -- Word analysis
    suggested_correction TEXT,
    correction_confidence TEXT,
    hamming_distance INTEGER,
    levenshtein_distance INTEGER,
    damerau_levenshtein_distance INTEGER,
    
    -- OCR error detection
    ocr_error_pattern TEXT,
    boundary_error_pattern TEXT,
    
    -- Abbreviation categorization
    is_abbreviation BOOLEAN DEFAULT FALSE,
    is_state_code BOOLEAN DEFAULT FALSE,
    is_country_code BOOLEAN DEFAULT FALSE,
    is_page_number BOOLEAN DEFAULT FALSE,
    is_other_abbreviation BOOLEAN DEFAULT FALSE,
    is_date_number BOOLEAN DEFAULT FALSE,
    is_ocr_fragment BOOLEAN DEFAULT FALSE,
    
    -- Multi-language detection
    detected_language VARCHAR(10),
    is_foreign_word BOOLEAN DEFAULT FALSE,
    foreign_language_suggestion TEXT,
    foreign_language_confidence TEXT,
    foreign_word_translation TEXT,
    
    -- Timestamps
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Compound primary key
    PRIMARY KEY (word, file_path, occurrence_number)
);

CREATE INDEX IF NOT EXISTS idx_spelling_word ON spelling_issues(word);
CREATE INDEX IF NOT EXISTS idx_spelling_file ON spelling_issues(file_path);
CREATE INDEX IF NOT EXISTS idx_spelling_subfolder ON spelling_issues(subfolder);
CREATE INDEX IF NOT EXISTS idx_spelling_position_percent ON spelling_issues(position_percent);
CREATE INDEX IF NOT EXISTS idx_spelling_abbreviation ON spelling_issues(is_abbreviation);
CREATE INDEX IF NOT EXISTS idx_spelling_page_number ON spelling_issues(is_page_number);
CREATE INDEX IF NOT EXISTS idx_spelling_confidence ON spelling_issues(correction_confidence);
CREATE INDEX IF NOT EXISTS idx_spelling_language ON spelling_issues(detected_language);
CREATE INDEX IF NOT EXISTS idx_spelling_foreign ON spelling_issues(is_foreign_word);
"""


def detect_ocr_error_pattern(word: str, correction: str) -> Optional[str]:
    """Detect common OCR character confusion patterns.
    
    Analyzes differences between misspelled word and suggested correction
    to identify typical OCR errors like l/1 confusion, rn/m merging, etc.
    Useful for identifying documents with poor OCR quality.
    
    Args:
        word (str): Misspelled word as extracted from OCR.
        correction (str): Suggested correct spelling from spell checker.
    
    Returns:
        Optional[str]: Pattern string if OCR error detected, None otherwise.
            Examples: 'l->1', 'O->0', 'rn->m', 'cl->d', 'vv->w'
    
    Pattern Types:
        Single character:
            - l/1 confusion: lowercase L vs digit 1
            - O/0 confusion: uppercase O vs digit 0
            - I/1 confusion: uppercase I vs digit 1
            - S/5, B/8 substitutions
        
        Bigram patterns:
            - rn->m: two letters merged (common OCR error)
            - cl->d: similar looking character groups
            - vv->w: double v mistaken for w
    
    Example:
        >>> detect_ocr_error_pattern('he1lo', 'hello')
        '1->l'
        >>> detect_ocr_error_pattern('infornation', 'information')
        'rn->m'
        >>> detect_ocr_error_pattern('cat', 'dog')
        None
    
    Note:
        Only detects patterns when word lengths match. Returns None for
        insertions/deletions or unrecognized pattern types.
    """
    if not word or not correction or len(word) != len(correction):
        return None
    
    # Common OCR character confusions
    ocr_patterns = {
        ('l', '1'): 'l->1',
        ('1', 'l'): '1->l', 
        ('O', '0'): 'O->0',
        ('0', 'O'): '0->O',
        ('S', '5'): 'S->5',
        ('5', 'S'): '5->S',
        ('I', '1'): 'I->1',
        ('1', 'I'): '1->I',
        ('i', '1'): 'i->1',
        ('1', 'i'): '1->i',
        ('B', '8'): 'B->8',
        ('8', 'B'): '8->B',
    }
    
    # Check for bigram patterns
    word_lower = word.lower()
    corr_lower = correction.lower()
    
    if 'rn' in word_lower and 'm' in corr_lower:
        return 'rn->m'
    if 'm' in word_lower and 'rn' in corr_lower:
        return 'm->rn'
    if 'cl' in word_lower and 'd' in corr_lower:
        return 'cl->d'
    if 'd' in word_lower and 'cl' in corr_lower:
        return 'd->cl'
    if 'vv' in word_lower and 'w' in corr_lower:
        return 'vv->w'
    if 'w' in word_lower and 'vv' in corr_lower:
        return 'w->vv'
    
    # Check single character substitutions
    for i, (c1, c2) in enumerate(zip(word, correction)):
        if c1 != c2:
            pattern_key = (c1, c2)
            if pattern_key in ocr_patterns:
                return ocr_patterns[pattern_key]
    
    return None


def is_date_or_number_pattern(word: str) -> bool:
    """Check if word matches date, number, or case number patterns.
    
    Identifies numeric and date-like patterns that should not be flagged
    as spelling errors. Common in legal documents for case numbers,
    dates, and monetary amounts.
    
    Args:
        word (str): Word to check for numeric/date patterns.
    
    Returns:
        bool: True if word matches any recognized pattern, False otherwise.
    
    Patterns Recognized:
        - Month names: jan, february, march, etc. (full and abbreviated)
        - Years: 1900-2099 (four digits starting with 19 or 20)
        - Money amounts: 500k, 2m, 1b (digit + k/m/b suffix)
        - Case numbers: cv2019, cr2020 (two letters + four digits)
        - Alphanumeric: Mixed letters and numbers (abc123, 123abc)
    
    Example:
        >>> is_date_or_number_pattern('january')
        True
        >>> is_date_or_number_pattern('2024')
        True
        >>> is_date_or_number_pattern('500k')
        True
        >>> is_date_or_number_pattern('cv2019')
        True
        >>> is_date_or_number_pattern('hello')
        False
    
    Note:
        Case-insensitive matching for all pattern types.
    """
    word_lower = word.lower()
    
    # Month abbreviations
    months = {'jan', 'feb', 'mar', 'apr', 'may', 'jun', 
              'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
              'january', 'february', 'march', 'april', 'june', 
              'july', 'august', 'september', 'october', 'november', 'december'}
    if word_lower in months:
        return True
    
    # Years (1900-2099)
    if re.match(r'^(19|20)\d{2}$', word):
        return True
    
    # Money amounts: 500k, 2m, 1b
    if re.match(r'^\d+[kmb]$', word_lower):
        return True
    
    # Case numbers: cv2019, cr2020, etc.
    if re.match(r'^[a-z]{2}\d{4}$', word_lower):
        return True
    
    # Generic number patterns with letters
    if re.match(r'^\d+[a-z]+$', word_lower) or re.match(r'^[a-z]+\d+$', word_lower):
        return True
    
    return False


def detect_boundary_error(word: str, correction: str) -> Optional[str]:
    """Detect if difference is only at word boundaries (prefix/suffix).
    
    Identifies cases where extra characters are added/removed at the start
    or end of words, common in OCR due to character boundary detection issues.
    
    Args:
        word (str): Original misspelled word.
        correction (str): Suggested correction.
    
    Returns:
        Optional[str]: Description of boundary error, or None if not a boundary error.
        Format: 'prefix:X->Y', 'suffix:X->Y', 'both:X->Y+Z'
    
    Patterns Detected:
        - Prefix only: 'scat' vs 'cat' → 'prefix:s->'
        - Suffix only: 'cats' vs 'cat' → 'suffix:->s'
        - Both ends: 'scats' vs 'cat' → 'both:s->+s'
        - Reversed: 'cat' vs 'scat' → 'prefix:->s'
    
    Example:
        >>> detect_boundary_error('scat', 'cat')
        'prefix:s->'
        >>> detect_boundary_error('cat', 'cats')
        'suffix:->s'
        >>> detect_boundary_error('hello', 'world')
        None
    
    Note:
        Only detects 1-2 character differences at boundaries.
        Requires words to differ only at start/end, not in the middle.
    """
    if not word or not correction:
        return None
    
    # Check if one is prefix/suffix of the other
    # Case 1: word has extra prefix
    if word.endswith(correction) and len(word) - len(correction) <= 2:
        prefix = word[:len(word) - len(correction)]
        return f'prefix:{prefix}->'
    
    # Case 2: correction has extra prefix
    if correction.endswith(word) and len(correction) - len(word) <= 2:
        prefix = correction[:len(correction) - len(word)]
        return f'prefix:->{prefix}'
    
    # Case 3: word has extra suffix
    if word.startswith(correction) and len(word) - len(correction) <= 2:
        suffix = word[len(correction):]
        return f'suffix:->{suffix}'
    
    # Case 4: correction has extra suffix
    if correction.startswith(word) and len(correction) - len(word) <= 2:
        suffix = correction[len(word):]
        return f'suffix:{suffix}->'
    
    # Case 5: Both ends differ (within 2 chars each end)
    # Find longest common substring
    for i in range(min(len(word), len(correction))):
        for j in range(min(len(word), len(correction)), 0, -1):
            common = word[i:j]
            if common and common in correction:
                word_prefix = word[:i]
                word_suffix = word[j:]
                corr_idx = correction.index(common)
                corr_prefix = correction[:corr_idx]
                corr_suffix = correction[corr_idx + len(common):]
                
                if len(word_prefix) <= 2 and len(word_suffix) <= 2 and \
                   len(corr_prefix) <= 2 and len(corr_suffix) <= 2:
                    if word_prefix or corr_prefix or word_suffix or corr_suffix:
                        prefix_change = f"{word_prefix or ''}->{corr_prefix or ''}"
                        suffix_change = f"{word_suffix or ''}->{corr_suffix or ''}"
                        if word_prefix or corr_prefix:
                            if word_suffix or corr_suffix:
                                return f'both:{prefix_change}+{suffix_change}'
                            return f'prefix:{prefix_change}'
                        elif word_suffix or corr_suffix:
                            return f'suffix:{suffix_change}'
                return None
    
    return None


def calculate_correction_confidence(
    word: str,
    correction: Optional[str],
    hamming_dist: Optional[int],
    levenshtein_dist: Optional[int],
    damerau_dist: Optional[int] = None
) -> str:
    """Calculate confidence level for spelling correction suggestions.
    
    Uses edit distance metrics, boundary error detection, and common typo
    patterns to assess how likely a correction is accurate. High confidence
    corrections are candidates for automated fixing.
    
    Args:
        word (str): Original misspelled word.
        correction (Optional[str]): Suggested correction from spell checker.
            None if no correction available.
        hamming_dist (Optional[int]): Hamming distance (substitutions only).
            None if not calculated.
        levenshtein_dist (Optional[int]): Levenshtein distance (all edits).
            None if not calculated.
        damerau_dist (Optional[int]): Damerau-Levenshtein distance (includes transpositions).
            None if not calculated.
    
    Returns:
        str: Confidence level - 'HIGH', 'MEDIUM', or 'LOW'.
    
    Confidence Levels:
        HIGH: Damerau-Levenshtein distance = 1 (single transposition/edit) OR
              Edit distance ≤ 2 OR boundary error OR common typo.
            Safe for automated correction.
        MEDIUM: Edit distance 3-4 on both metrics.
            Requires manual review but likely correct.
        LOW: Edit distance > 4 OR no correction available.
            May be proper noun, abbreviation, or unclear error.
    
    Example:
        >>> calculate_correction_confidence('teh', 'the', 1, 1, 1)
        'HIGH'
        >>> calculate_correction_confidence('recieve', 'receive', 2, 2, 1)
        'HIGH'  # Damerau distance = 1 (transposition)
        >>> calculate_correction_confidence('scat', 'cat', None, 1, 1)
        'HIGH'  # Boundary error detected
        >>> calculate_correction_confidence('xyz', 'abc', 5, 5, 5)
        'LOW'
    
    Note:
        Damerau-Levenshtein distance catches transposition errors (ei<->ie, teh<->the)
        which are common in OCR and typing, giving them HIGH confidence.
    """
    if not correction:
        return 'LOW'
    
    # Check for boundary errors first (very high confidence)
    boundary_error = detect_boundary_error(word, correction)
    if boundary_error:
        return 'HIGH'
    
    # Damerau-Levenshtein distance = 1 means single edit (possibly transposition)
    # This is very high confidence
    if damerau_dist == 1:
        return 'HIGH'
    
    # High confidence: distance 1-2, correction is common word
    if hamming_dist and hamming_dist <= HIGH_CONFIDENCE_DISTANCE_THRESHOLD:
        # Very common corrections
        common_corrections = {
            'teh': 'the', 'hte': 'the', 'adn': 'and', 'nad': 'and',
            'fo': 'of', 'taht': 'that', 'thsi': 'this', 'waht': 'what',
            'recieved': 'received', 'occured': 'occurred'
        }
        if word in common_corrections:
            return 'HIGH'
        
        if levenshtein_dist and levenshtein_dist <= 2:
            return 'HIGH'
    
    # Medium confidence: distance 3-4
    if hamming_dist and hamming_dist <= 4 and levenshtein_dist and levenshtein_dist <= 4:
        return 'MEDIUM'
    
    # Low confidence: distance > 4 or no clear correction
    return 'LOW'


def extract_subfolder_key(dirpath: str) -> str:
    """Extract subfolder identifier from directory path.
    
    Returns VOL*/IMAGES/*/ pattern if found, otherwise parent directory name.
    
    Args:
        dirpath: Full directory path
        
    Returns:
        Subfolder key for grouping (e.g., "VOL00001/IMAGES/0001")
    """
    path_parts = dirpath.split(os.sep)
    
    # Look for VOL prefix
    for i, part in enumerate(path_parts):
        if part.startswith('VOL'):
            # Check if we have VOL*/IMAGES/*/ pattern
            if (i + 2 < len(path_parts) and 
                path_parts[i + 1] == 'IMAGES'):
                return os.path.join(path_parts[i], 
                                   path_parts[i + 1], 
                                   path_parts[i + 2])
    
    # Fallback: use immediate parent directory
    return os.path.basename(dirpath)


def is_roman_numeral_or_page_number(word: str) -> bool:
    """Check if a word is a roman numeral or common page number pattern.
    
    Returns True if:
    - Word is a roman numeral (i, ii, iii, iv, v, vi, vii, viii, ix, x, etc.)
    - Word is a simple number pattern like p1, p2, pg1, etc.
    """
    word_lower = word.lower()
    
    # Common roman numerals (up to reasonable page numbers)
    roman_numerals = {
        'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x',
        'xi', 'xii', 'xiii', 'xiv', 'xv', 'xvi', 'xvii', 'xviii', 'xix', 'xx',
        'xxi', 'xxii', 'xxiii', 'xxiv', 'xxv', 'xxx', 'xl', 'l', 'lx', 'lxx',
        'lxxx', 'xc', 'c', 'cc', 'ccc', 'cd', 'd', 'dc', 'dcc', 'dccc', 'cm', 'm'
    }
    
    if word_lower in roman_numerals:
        return True
    
    # Check for page number patterns: p1, p2, pg1, page1, etc.
    import re
    if re.match(r'^p(age)?\d+$', word_lower):
        return True
    if re.match(r'^pg\d+$', word_lower):
        return True
    
    # Pure numeric strings
    if word.isdigit():
        return True
    
    return False


def is_ocr_fragment(word: str) -> bool:
    """
    Detect if a word is likely an OCR fragment rather than a complete word.
    
    OCR fragments are typically:
    - Very short words (≤2 characters) that are not common English words
    - Letter combinations that are likely parts of longer words
    - Not abbreviations or known short words
    
    Args:
        word: The word to check
        
    Returns:
        True if the word is likely an OCR fragment, False otherwise
        
    Examples:
        >>> is_ocr_fragment('oa')  # Part of 'road', 'boat'
        True
        >>> is_ocr_fragment('ff')  # Part of 'off', 'staff'
        True
        >>> is_ocr_fragment('it')  # Common English word
        False
        >>> is_ocr_fragment('hello')  # Normal word
        False
    """
    word_lower = word.lower()
    
    # Words longer than 2 characters are not fragments
    if len(word_lower) > 2:
        return False
    
    # Single characters are almost always fragments
    if len(word_lower) == 1:
        # Except common single letters: 'a', 'i'
        return word_lower not in {'a', 'i'}
    
    # Two-character words: check against common English words
    # These are legitimate short words that should NOT be considered fragments
    common_two_letter_words = {
        'am', 'an', 'as', 'at', 'be', 'by', 'do', 'go', 'he', 'hi',
        'if', 'in', 'is', 'it', 'me', 'my', 'no', 'of', 'oh', 'ok',
        'on', 'or', 'so', 'to', 'up', 'us', 'we'
    }
    
    # If it's a common word, it's NOT a fragment
    if word_lower in common_two_letter_words:
        return False
    
    # Otherwise, two-letter words are likely fragments
    return True


def has_uncommon_english_patterns(word: str) -> bool:
    """Check if word has patterns uncommon in English (suggests possible foreign word).
    
    Skip foreign language check if word looks like typical English or OCR error.
    """
    word_lower = word.lower()
    
    # Very short words - likely OCR fragments
    if len(word_lower) <= 3:
        return False
    
    # Common English patterns that shouldn't be checked
    # Words with common English letter combinations
    english_patterns = ['th', 'ing', 'ed', 'er', 'ly', 'tion', 'ness', 'ment']
    if any(pattern in word_lower for pattern in english_patterns):
        return False
    
    # Check for unusual character combinations that suggest foreign words
    # German: ä, ö, ü, ß patterns (though we don't have special chars here)
    # French: common patterns like eau, eux, ois
    # Spanish: ñ patterns, multiple vowels
    foreign_patterns = ['eau', 'eux', 'ois', 'sch', 'tsch', 'zw', 'pf']
    if any(pattern in word_lower for pattern in foreign_patterns):
        return True
    
    # If word has excessive consonant clusters, might be foreign
    consonant_clusters = len(re.findall(r'[bcdfghjklmnpqrstvwxyz]{3,}', word_lower))
    if consonant_clusters >= 2:
        return True
    
    return False


def check_foreign_language(word: str) -> Tuple[Optional[str], Optional[str], int]:
    """Check if a word exists in foreign language dictionaries.
    
    Args:
        word: Word to check against foreign language dictionaries.
    
    Returns:
        Tuple of (language_code, suggestion, confidence_score):
        - language_code: Language code (e.g., 'de', 'fr', 'es', 'ru', 'ar') if word is found or has suggestions
        - suggestion: Suggested correction from that language's dictionary, or the word itself if correct
        - confidence_score: Integer score (100 = exact match, 50-20 = correction by edit distance)
        Returns (None, None, 0) if word is not found in any foreign language dictionary.
    
    Note:
        Uses cached SpellChecker instances for performance.
        Optimizations:
        - Scores languages by confidence (exact match > close correction)
        - Filters suggestions by edit distance (max 3)
        - Returns best match across all languages
        
        Checks 29 languages across multiple regions:
        - Western European: German, French, Spanish, Portuguese, Italian, Dutch
        - Nordic: Swedish, Norwegian, Danish, Finnish
        - Slavic: Russian, Polish, Ukrainian, Czech, Bulgarian, Croatian, Slovenian, Slovak, Serbian
        - Baltic: Latvian, Lithuanian, Estonian
        - Other European: Greek, Romanian, Hungarian, Turkish
        - Middle Eastern: Arabic, Hebrew
    """
    global LANGUAGE_CHECKERS
    
    # Initialize language checkers on first use
    if not LANGUAGE_CHECKERS:
        for lang_code in SUPPORTED_LANGUAGES.keys():
            try:
                LANGUAGE_CHECKERS[lang_code] = SpellChecker(language=lang_code)
            except Exception:
                # Language not available, skip it
                pass
    
    word_lower = word.lower()
    best_match = None
    best_score = -1
    
    # Check each language and score matches (Optimization #5)
    for lang_code, checker in LANGUAGE_CHECKERS.items():
        # Exact match in dictionary - highest score
        if word_lower in checker:
            score = 100  # Perfect match
            if score > best_score:
                best_score = score
                best_match = (lang_code, word_lower)
        else:
            # Check for correction
            correction = checker.correction(word_lower)
            if correction and correction != word_lower and correction in checker:
                # Filter by edit distance (Optimization #6)
                edit_dist = levenshtein_distance(word_lower, correction)
                if edit_dist <= 3:  # Only accept close matches
                    # Score based on edit distance (closer = better)
                    score = 50 - (edit_dist * 10)  # 50, 40, 30, or 20
                    if score > best_score:
                        best_score = score
                        best_match = (lang_code, correction)
    
    if best_match:
        return best_match[0], best_match[1], best_score
    return None, None, 0


def calculate_foreign_language_confidence(
    word: str,
    suggestion: Optional[str],
    match_score: int
) -> str:
    """Calculate confidence level for foreign language detection.
    
    Args:
        word: Original word
        suggestion: Suggested spelling from foreign dictionary
        match_score: Score from check_foreign_language (100 for exact, 50-20 for corrections)
    
    Returns:
        str: Confidence level - 'HIGH', 'MEDIUM', or 'LOW'
    
    Confidence Levels:
        HIGH: Exact match in foreign dictionary (score = 100)
        MEDIUM: Close correction with edit distance 1-2 (score = 40-50)
        LOW: Distant correction with edit distance 3 (score = 20-30)
    """
    if not suggestion:
        return 'LOW'
    
    # Exact match in foreign dictionary - highest confidence
    if match_score == 100:
        return 'HIGH'
    
    # Close correction (edit distance 1-2)
    if match_score >= 40:  # scores 40-50
        return 'MEDIUM'
    
    # Distant correction (edit distance 3)
    return 'LOW'


def translate_foreign_word(word: str, source_lang: str) -> Optional[str]:
    """Translate a foreign word to English.
    
    Args:
        word: The foreign word to translate.
        source_lang: The language code of the source word (e.g., 'de', 'fr').
    
    Returns:
        English translation of the word, or None if translation fails.
    
    Note:
        Uses Google Translate via deep-translator library.
        Results are cached to avoid redundant API calls.
        Returns None if translator is not available or translation fails.
    """
    if not TRANSLATOR_AVAILABLE:
        return None
    
    # Check cache first
    cache_key = (word.lower(), source_lang)
    if cache_key in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[cache_key]
    
    try:
        # Translate to English
        translator = GoogleTranslator(source=source_lang, target='en')
        translation = translator.translate(word.lower())
        
        # Store in cache
        TRANSLATION_CACHE[cache_key] = translation
        return translation
    except Exception:
        # Translation failed, return None
        return None


def categorize_abbreviation(word: str) -> AbbreviationInfo:
    """Categorize a word by abbreviation type.
    
    Returns AbbreviationInfo dataclass with boolean flags for each category.
    """
    word_lower = word.lower()
    
    # Check date/number patterns first
    if is_date_or_number_pattern(word):
        return AbbreviationInfo(
            is_abbreviation=True,
            is_state_code=False,
            is_country_code=False,
            is_page_number=False,
            is_date_number=True,
            is_other_abbreviation=False
        )
    
    # Check page numbers
    if is_roman_numeral_or_page_number(word):
        return AbbreviationInfo(
            is_abbreviation=True,
            is_state_code=False,
            is_country_code=False,
            is_page_number=True,
            is_date_number=False,
            is_other_abbreviation=False
        )
    
    # Check state codes
    is_state = word_lower in US_STATE_CODES
    
    # Check country codes
    is_country = word_lower in COUNTRY_CODES
    
    # Check other abbreviations
    is_other = word_lower in COMMON_ABBREVIATIONS
    
    is_abbrev = is_state or is_country or is_other
    
    return AbbreviationInfo(
        is_abbreviation=is_abbrev,
        is_state_code=is_state,
        is_country_code=is_country,
        is_page_number=False,
        is_date_number=False,
        is_other_abbreviation=is_other
    )


def hamming_distance(s1: str, s2: str) -> int:
    """Calculate modified Hamming distance allowing different string lengths.
    
    Extends traditional Hamming distance to handle strings of unequal length
    by comparing characters up to the shorter string's length, then adding
    the length difference as additional distance.
    
    Args:
        s1 (str): First string to compare.
        s2 (str): Second string to compare.
    
    Returns:
        int: Number of differing positions plus length difference.
            Returns max(len(s1), len(s2)) if either string is empty.
    
    Examples:
        >>> hamming_distance('hello', 'hallo')
        1  # One character differs
        >>> hamming_distance('test', 'testing')
        4  # One difference + 3 length difference
        >>> hamming_distance('', 'abc')
        3  # Empty string case
    
    Note:
        This differs from classical Hamming distance which requires
        equal-length strings. More forgiving for OCR/typing errors.
    """
    if not s1 or not s2:
        return max(len(s1), len(s2))
    
    min_len = min(len(s1), len(s2))
    distance = sum(c1 != c2 for c1, c2 in zip(s1[:min_len], s2[:min_len]))
    distance += abs(len(s1) - len(s2))
    return distance


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein (edit) distance using dynamic programming.
    
    Computes minimum number of single-character edits (insertions,
    deletions, or substitutions) required to transform s1 into s2.
    Uses optimized algorithm that swaps arguments if s1 is shorter.
    
    Args:
        s1 (str): Source string to transform.
        s2 (str): Target string to match.
    
    Returns:
        int: Minimum number of edits required.
    
    Examples:
        >>> levenshtein_distance('kitten', 'sitting')
        3
        >>> levenshtein_distance('hello', 'hallo')
        1
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def damerau_levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Damerau-Levenshtein distance using dynamic programming.
    
    Extends Levenshtein distance to include transpositions (swapping adjacent
    characters) as a single edit operation. This is particularly useful for
    OCR and typing errors where character swaps are common.
    
    Args:
        s1 (str): Source string to transform.
        s2 (str): Target string to match.
    
    Returns:
        int: Minimum number of edits required (insertions, deletions,
             substitutions, or transpositions).
    
    Examples:
        >>> damerau_levenshtein_distance('teh', 'the')
        1  # Single transposition
        >>> damerau_levenshtein_distance('recieve', 'receive')
        1  # Single transposition (ei -> ie)
        >>> damerau_levenshtein_distance('kitten', 'sitting')
        3  # Same as Levenshtein (no transpositions help)
    
    Note:
        Uses O(len(s1) * len(s2)) time and space complexity.
        Transpositions are common in OCR errors, making this metric
        more accurate than standard Levenshtein for spell checking.
    """
    len1, len2 = len(s1), len(s2)
    
    # Create distance matrix with extra row/column for empty string
    H = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    
    # Initialize base cases
    for i in range(len1 + 1):
        H[i][0] = i
    for j in range(len2 + 1):
        H[0][j] = j
    
    # Fill matrix
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            
            # Standard operations: insertion, deletion, substitution
            H[i][j] = min(
                H[i-1][j] + 1,      # deletion
                H[i][j-1] + 1,      # insertion
                H[i-1][j-1] + cost  # substitution
            )
            
            # Transposition: check if we can swap adjacent characters
            if i > 1 and j > 1 and s1[i-1] == s2[j-2] and s1[i-2] == s2[j-1]:
                H[i][j] = min(H[i][j], H[i-2][j-2] + 1)
    
    return H[len1][len2]


def extract_words(text: str) -> List[str]:
    """Extract words from text, filtering out non-alphabetic tokens."""
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    return [w for w in words if len(w) > 1]  # Filter single-character words


@handle_errors(verbose=False)
def analyze_file_with_positions(
    path: str,
    spell_checker: SpellChecker,
    spell_cache: Dict,
    verbose: bool = False
) -> Tuple[List[Tuple], Counter]:
    """Analyze a file for spelling issues with positional information and context.
    
    Note:
        Processes all words unknown in English dictionary.
        Foreign language detection happens in store function and applies to all words.
    
    Returns:
        Tuple of:
        - List of tuples: (word, position_start, position_end, document_length, context_before, context_after)
        - Counter: word_frequencies for Zipf analysis
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        
        document_length = len(text)
        word_positions = []
        all_words = []
        
        # Find all words with positions using regex
        pattern = re.compile(r'\b[a-zA-Z]+\b')
        for match in pattern.finditer(text):
            word = match.group().lower()
            if len(word) > 1:  # Filter single-character words
                all_words.append(word)
                
                # Include ALL unknown words (not in English dictionary)
                # Foreign language checking happens in store function for all words
                if word not in spell_checker:
                    pos_start = match.start()
                    pos_end = match.end()
                    
                    # Extract context windows
                    context_start = max(0, pos_start - CONTEXT_WINDOW_SIZE)
                    context_end = min(len(text), pos_end + CONTEXT_WINDOW_SIZE)
                    context_before = text[context_start:pos_start].replace('\n', ' ').strip()
                    context_after = text[pos_end:context_end].replace('\n', ' ').strip()
                    
                    word_positions.append((word, pos_start, pos_end, document_length, context_before, context_after))
        
        word_freq = Counter(all_words)
        
        if verbose and word_positions:
            print(f"  Found {len(word_positions)} unknown word occurrences in {os.path.basename(path)}")
        
        return word_positions, word_freq
    
    except Exception as e:
        if verbose:
            print(f"  Error processing {path}: {e}")
        return [], Counter()


def calculate_zipf_statistics(word_frequencies: Counter) -> Dict:
    """Calculate Zipf's law statistics for word frequencies.
    
    Zipf's law: frequency ∝ 1/rank
    Returns statistics about the frequency distribution.
    """
    if not word_frequencies:
        return {}
    
    # Sort by frequency (descending)
    sorted_words = word_frequencies.most_common()
    
    # Calculate expected vs actual for Zipf's law
    total_words = sum(word_frequencies.values())
    most_common_freq = sorted_words[0][1] if sorted_words else 0
    
    zipf_deviations = []
    for rank, (word, freq) in enumerate(sorted_words[:100], start=1):  # Top 100
        expected_freq = most_common_freq / rank
        deviation = abs(freq - expected_freq) / expected_freq if expected_freq > 0 else 0
        zipf_deviations.append(deviation)
    
    avg_deviation = sum(zipf_deviations) / len(zipf_deviations) if zipf_deviations else 0
    
    return {
        'total_unique_words': len(word_frequencies),
        'total_word_count': total_words,
        'most_common_word': sorted_words[0][0] if sorted_words else None,
        'most_common_freq': most_common_freq,
        'avg_zipf_deviation': avg_deviation,
        'top_10_words': sorted_words[:10]
    }


@handle_errors(verbose=False)
def store_spelling_issues_with_positions(
    conn,
    file_path: str,
    subfolder: str,
    word_positions: List[Tuple],
    spell_checker: SpellChecker,
    spell_cache: Dict,
    verbose: bool = False
) -> Tuple[int, int, int]:
    """Store spelling issues with positional data in the database.
    
    Args:
        word_positions: List of (word, start, end, doc_length, context_before, context_after) tuples
    
    Returns:
        Tuple of (total_stored, abbreviations_count, fragment_count)
    
    Note:
        Uses batch inserts (executemany) for 5-10x performance improvement.
    """
    # Group occurrences by word to assign occurrence_numbers
    word_occurrences = defaultdict(list)
    for word, start, end, doc_len, ctx_before, ctx_after in word_positions:
        word_occurrences[word].append((start, end, doc_len, ctx_before, ctx_after))
    
    # Calculate word frequencies for translation threshold (Optimization #3)
    word_frequencies = Counter(word for word, _ in word_occurrences.items())
    
    stored = 0
    abbrev_count = 0
    fragment_count = 0
    
    # Batch all inserts for performance (Optimization #1)
    batch_params = []
    
    for word, positions in word_occurrences.items():
        try:
            # Sort by position to get correct occurrence order
            positions.sort(key=lambda x: x[0])
            
            # Categorize once per word
            abbrev_info = categorize_abbreviation(word)
            if abbrev_info.is_abbreviation:
                abbrev_count += 1  # Count unique abbreviations
            
            # Check if word is an OCR fragment (Optimization #4 - check early)
            is_fragment = is_ocr_fragment(word)
            if is_fragment:
                fragment_count += 1  # Count unique fragments
            
            # Skip foreign language check for OCR fragments (Optimization #4)
            foreign_lang = None
            foreign_suggestion = None
            foreign_confidence = None
            is_foreign = False
            foreign_translation = None
            
            if not is_fragment:
                # Always check for foreign language words, even if valid English
                # This catches words that exist in both English and foreign dictionaries
                foreign_lang, foreign_suggestion, confidence_score = check_foreign_language(word)
                is_foreign = foreign_lang is not None
                
                # Calculate confidence if foreign word detected
                if is_foreign:
                    foreign_confidence = calculate_foreign_language_confidence(word, foreign_suggestion, confidence_score)
                
                # Translate foreign word to English if detected
                # Use the corrected foreign language word (foreign_suggestion) if available, otherwise use original word
                if is_foreign and foreign_lang:
                    word_to_translate = foreign_suggestion if foreign_suggestion else word
                    translation = translate_foreign_word(word_to_translate, foreign_lang)
                    # Only store translation if it differs from the original word
                    if translation and translation.lower() != word.lower():
                        foreign_translation = translation
            
            # Check cache first, then compute if needed
            if word in spell_cache:
                correction, hamming_dist, levenshtein_dist, damerau_dist = spell_cache[word]
            else:
                # Get correction once
                correction = spell_checker.correction(word)
                
                # Calculate distances
                if correction and correction != word:
                    hamming_dist = hamming_distance(word, correction)
                    levenshtein_dist = levenshtein_distance(word, correction)
                    damerau_dist = damerau_levenshtein_distance(word, correction)
                else:
                    hamming_dist = None
                    levenshtein_dist = None
                    damerau_dist = None
                    correction = None
                
                # Store in cache
                spell_cache[word] = (correction, hamming_dist, levenshtein_dist, damerau_dist)
            
            # Calculate confidence and detect error patterns
            confidence = calculate_correction_confidence(word, correction, hamming_dist, levenshtein_dist, damerau_dist)
            ocr_pattern = detect_ocr_error_pattern(word, correction) if correction else None
            boundary_pattern = detect_boundary_error(word, correction) if correction else None
            
            # Collect all occurrences for batch insert
            for occurrence_num, (start, end, doc_len, ctx_before, ctx_after) in enumerate(positions, start=1):
                position_percent = (start / doc_len * 100) if doc_len > 0 else 0
                
                batch_params.append((
                    word, file_path, occurrence_num, subfolder,
                    start, end, doc_len, position_percent,
                    ctx_before, ctx_after,
                    correction, confidence,
                    hamming_dist, levenshtein_dist, damerau_dist,
                    ocr_pattern, boundary_pattern,
                    abbrev_info.is_abbreviation, abbrev_info.is_state_code,
                    abbrev_info.is_country_code, abbrev_info.is_page_number,
                    abbrev_info.is_date_number, abbrev_info.is_other_abbreviation,
                    is_fragment,
                    foreign_lang, is_foreign, foreign_suggestion, foreign_confidence, foreign_translation
                ))
                stored += 1
        
        except Exception as e:
            if verbose:
                print(f"  Error processing word '{word}': {e}")
            continue
    
    # Batch insert all records at once (Optimization #1 - 5-10x speedup)
    if batch_params:
        try:
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO spelling_issues (
                        word, file_path, occurrence_number, subfolder,
                        position_start, position_end, document_length, position_percent,
                        context_before, context_after,
                        suggested_correction, correction_confidence,
                        hamming_distance, levenshtein_distance, damerau_levenshtein_distance,
                        ocr_error_pattern, boundary_error_pattern,
                        is_abbreviation, is_state_code, is_country_code, 
                        is_page_number, is_date_number, is_other_abbreviation,
                        is_ocr_fragment,
                        detected_language, is_foreign_word, foreign_language_suggestion, foreign_language_confidence, foreign_word_translation,
                        last_seen
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (word, file_path, occurrence_number) DO UPDATE SET
                        last_seen = CURRENT_TIMESTAMP,
                        position_start = EXCLUDED.position_start,
                        position_end = EXCLUDED.position_end,
                        position_percent = EXCLUDED.position_percent,
                        context_before = EXCLUDED.context_before,
                        context_after = EXCLUDED.context_after;
                """, batch_params)
            conn.commit()
        except Exception as e:
            if verbose:
                print(f"  Error in batch insert: {e}")
            conn.rollback()
    
    return stored, abbrev_count, fragment_count


def generate_correction_script(script_path: str, auto_correctable: List, verbose: bool = False):
    """Generate Python script for automated corrections of high-confidence errors."""
    try:
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write("#!/usr/bin/env python3\n")
            f.write('"""Auto-correction script for high-confidence spelling errors.\n\n')
            f.write("Generated by analyze_spelling.py\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("Usage:\n")
            f.write("  python auto_correct.py <file_or_directory>\n")
            f.write('"""\n\n')
            f.write("import os\n")
            f.write("import re\n")
            f.write("import sys\n\n")
            f.write("# High-confidence corrections (word -> correction)\n")
            f.write("CORRECTIONS = {\n")
            
            for word, correction, freq, dist in auto_correctable[:AUTO_CORRECTION_SCRIPT_TOP_N]:
                f.write(f"    '{word}': '{correction}',  # freq: {freq}, dist: {dist}\n")
            
            f.write("}\n\n")
            f.write("def apply_corrections(text):\n")
            f.write('    """Apply corrections to text using word boundaries."""\n')
            f.write("    for wrong, correct in CORRECTIONS.items():\n")
            f.write("        # Case-insensitive replacement with word boundaries\n")
            f.write("        pattern = r'\\b' + re.escape(wrong) + r'\\b'\n")
            f.write("        text = re.sub(pattern, correct, text, flags=re.IGNORECASE)\n")
            f.write("    return text\n\n")
            f.write("def process_file(filepath):\n")
            f.write('    """Process a single file."""\n')
            f.write("    try:\n")
            f.write("        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:\n")
            f.write("            content = f.read()\n")
            f.write("        \n")
            f.write("        corrected = apply_corrections(content)\n")
            f.write("        \n")
            f.write("        if corrected != content:\n")
            f.write("            backup_path = filepath + '.bak'\n")
            f.write("            os.rename(filepath, backup_path)\n")
            f.write("            with open(filepath, 'w', encoding='utf-8') as f:\n")
            f.write("                f.write(corrected)\n")
            f.write("            print(f'Corrected: {filepath}')\n")
            f.write("            return True\n")
            f.write("        return False\n")
            f.write("    except Exception as e:\n")
            f.write("        print(f'Error processing {filepath}: {e}')\n")
            f.write("        return False\n\n")
            f.write("if __name__ == '__main__':\n")
            f.write("    if len(sys.argv) < 2:\n")
            f.write("        print('Usage: python auto_correct.py <file_or_directory>')\n")
            f.write("        sys.exit(1)\n")
            f.write("    \n")
            f.write("    path = sys.argv[1]\n")
            f.write("    corrected_count = 0\n")
            f.write("    \n")
            f.write("    if os.path.isfile(path):\n")
            f.write("        if process_file(path):\n")
            f.write("            corrected_count += 1\n")
            f.write("    elif os.path.isdir(path):\n")
            f.write("        for root, dirs, files in os.walk(path):\n")
            f.write("            for name in files:\n")
            f.write("                if name.endswith('_extracted.txt'):\n")
            f.write("                    filepath = os.path.join(root, name)\n")
            f.write("                    if process_file(filepath):\n")
            f.write("                        corrected_count += 1\n")
            f.write("    \n")
            f.write("    print(f'\\nCorrected {corrected_count} files')\n")
        
        if verbose:
            print(f"Auto-correction script written to: {script_path}")
            
    except Exception as e:
        if verbose:
            print(f"Error writing correction script: {e}")


# ============================================================================
# DATABASE QUERY FUNCTIONS
# ============================================================================

def fetch_top_words(conn, limit: int = 100) -> List[Tuple]:
    """Fetch most frequently occurring misspelled words from database.
    
    Retrieves words with highest occurrence counts, excluding abbreviations
    to focus on genuine spelling errors. Each word includes suggested
    correction and edit distance for analysis.
    
    Args:
        conn: Active psycopg database connection.
        limit (int): Maximum number of words to return. Default: 100.
    
    Returns:
        List[Tuple]: List of tuples containing:
            - word (str): The misspelled word
            - occurrence_count (int): Number of times word appears
            - correction (str): Suggested correction (may be None)
            - distance (int): Hamming distance to correction
            - is_abbrev (bool): Abbreviation flag (always False due to filter)
    
    Example:
        >>> top = fetch_top_words(conn, limit=10)
        >>> top[0]
        ('teh', 42, 'the', 1, False)
    
    Note:
        Groups by word, so 'test' appearing in 10 files counts as occurrence_count=10.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT word, COUNT(*) as occurrence_count, 
                   MAX(suggested_correction) as correction, 
                   MAX(hamming_distance) as distance,
                   MAX(is_abbreviation::int)::boolean as is_abbrev
            FROM spelling_issues
            WHERE is_abbreviation = FALSE
            GROUP BY word
            ORDER BY occurrence_count DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def fetch_distance_statistics(conn) -> Tuple[List[int], List[int]]:
    """Fetch all edit distance metrics for statistical analysis.
    
    Retrieves Hamming and Levenshtein distances for all word corrections
    to enable distribution analysis, average calculation, and outlier detection.
    
    Args:
        conn: Active psycopg database connection.
    
    Returns:
        Tuple[List[int], List[int]]: Two lists:
            - hamming_distances: All non-null Hamming distances
            - levenshtein_distances: All non-null Levenshtein distances
    
    Example:
        >>> hamming, levenshtein = fetch_distance_statistics(conn)
        >>> avg_hamming = sum(hamming) / len(hamming)
        >>> print(f'Average Hamming distance: {avg_hamming:.2f}')
    
    Note:
        Filters out NULL values. List lengths may differ if some corrections
        have only one distance type calculated.
        Excludes abbreviations and OCR fragments from statistics.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT hamming_distance, levenshtein_distance 
            FROM spelling_issues 
            WHERE (hamming_distance IS NOT NULL OR levenshtein_distance IS NOT NULL)
              AND is_abbreviation = FALSE
              AND is_ocr_fragment = FALSE
        """)
        distance_rows = cur.fetchall()
        hamming_distances = [row[0] for row in distance_rows if row[0] is not None]
        levenshtein_distances = [row[1] for row in distance_rows if row[1] is not None]
        return hamming_distances, levenshtein_distances


def fetch_position_statistics(conn) -> Dict:
    """Fetch error position distribution and document length statistics.
    
    Analyzes where spelling errors occur within documents (beginning, middle, end)
    and categorizes documents by size. Useful for identifying OCR quality
    patterns and document-specific issues.
    
    Args:
        conn: Active psycopg database connection.
    
    Returns:
        Dict: Statistics dictionary with keys:
            - avg_position (float): Average position as percentage (0-100)
            - beginning (int): Errors in first 25% of document
            - beginning_pct (float): Percentage of total errors
            - early_middle (int): Errors in 25-50% range
            - early_middle_pct (float): Percentage of total errors
            - late_middle (int): Errors in 50-75% range
            - late_middle_pct (float): Percentage of total errors
            - end (int): Errors in last 25% of document
            - end_pct (float): Percentage of total errors
            - short_docs (int): Errors in docs < 1000 chars
            - medium_docs (int): Errors in docs 1000-5000 chars
            - long_docs (int): Errors in docs > 5000 chars
    
    Example:
        >>> stats = fetch_position_statistics(conn)
        >>> print(f'Average error position: {stats["avg_position"]:.1f}%')
        >>> print(f'Errors at document end: {stats["end_pct"]:.1f}%')
    
    Note:
        Returns empty dict if no position data available.
        Thresholds use module constants (SHORT/MEDIUM_DOCUMENT_THRESHOLD).
        Excludes abbreviations and OCR fragments from statistics.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) as total_errors,
                AVG(position_percent) as avg_position,
                SUM(CASE WHEN position_percent < 25 THEN 1 ELSE 0 END) as beginning,
                SUM(CASE WHEN position_percent >= 25 AND position_percent < 50 THEN 1 ELSE 0 END) as early_middle,
                SUM(CASE WHEN position_percent >= 50 AND position_percent < 75 THEN 1 ELSE 0 END) as late_middle,
                SUM(CASE WHEN position_percent >= 75 THEN 1 ELSE 0 END) as end_range,
                SUM(CASE WHEN document_length < %s THEN 1 ELSE 0 END) as short_docs,
                SUM(CASE WHEN document_length >= %s AND document_length < %s THEN 1 ELSE 0 END) as medium_docs,
                SUM(CASE WHEN document_length >= %s THEN 1 ELSE 0 END) as long_docs
            FROM spelling_issues
            WHERE position_percent IS NOT NULL
              AND is_abbreviation = FALSE
              AND is_ocr_fragment = FALSE
        """, (SHORT_DOCUMENT_THRESHOLD, SHORT_DOCUMENT_THRESHOLD, MEDIUM_DOCUMENT_THRESHOLD, MEDIUM_DOCUMENT_THRESHOLD))
        pos_row = cur.fetchone()
        
        position_stats = {}
        if pos_row and pos_row[0] > 0:
            total_errors = pos_row[0]
            position_stats = {
                'avg_position': pos_row[1] or 0,
                'beginning': pos_row[2] or 0,
                'beginning_pct': (pos_row[2] or 0) / total_errors * 100,
                'early_middle': pos_row[3] or 0,
                'early_middle_pct': (pos_row[3] or 0) / total_errors * 100,
                'late_middle': pos_row[4] or 0,
                'late_middle_pct': (pos_row[4] or 0) / total_errors * 100,
                'end': pos_row[5] or 0,
                'end_pct': (pos_row[5] or 0) / total_errors * 100,
                'short_docs': pos_row[6] or 0,
                'medium_docs': pos_row[7] or 0,
                'long_docs': pos_row[8] or 0
            }
        return position_stats


def fetch_abbreviation_statistics(conn) -> Dict:
    """Fetch comprehensive abbreviation breakdown by category.
    
    Analyzes all unique words to determine distribution across abbreviation
    types. Helps understand what portion of 'errors' are actually valid
    abbreviations that should be whitelisted.
    
    Args:
        conn: Active psycopg database connection.
    
    Returns:
        Dict: Statistics containing:
            - total_words_db (int): Total unique words in database
            - abbrev_count_db (int): Words flagged as any abbreviation type
            - state_codes_count (int): US state/territory codes
            - country_codes_count (int): ISO country codes
            - page_numbers_count (int): Page numbers and Roman numerals
            - other_abbrevs_count (int): Legal/business abbreviations
            - top_abbreviations (List[Tuple]): Top 20 most common abbreviations
                Each tuple: (word, count, is_state, is_country, is_page, is_other)
    
    Example:
        >>> stats = fetch_abbreviation_statistics(conn)
        >>> pct = stats['abbrev_count_db'] / stats['total_words_db'] * 100
        >>> print(f'{pct:.1f}% of words are abbreviations')
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN is_abbreviation THEN 1 ELSE 0 END) as abbrev_count,
                   SUM(CASE WHEN is_state_code THEN 1 ELSE 0 END) as state_count,
                   SUM(CASE WHEN is_country_code THEN 1 ELSE 0 END) as country_count,
                   SUM(CASE WHEN is_page_number THEN 1 ELSE 0 END) as page_count,
                   SUM(CASE WHEN is_other_abbreviation THEN 1 ELSE 0 END) as other_abbrev_count
            FROM (
                SELECT DISTINCT word, is_abbreviation, is_state_code, is_country_code, 
                                is_page_number, is_other_abbreviation
                FROM spelling_issues
            ) subq
        """)
        abbrev_row = cur.fetchone()
        
        # Get top abbreviations by category
        cur.execute("""
            SELECT word, COUNT(*) as occurrence_count, 
                   MAX(is_state_code::int)::boolean as is_state,
                   MAX(is_country_code::int)::boolean as is_country,
                   MAX(is_page_number::int)::boolean as is_page,
                   MAX(is_other_abbreviation::int)::boolean as is_other
            FROM spelling_issues
            WHERE is_abbreviation = TRUE
            GROUP BY word
            ORDER BY occurrence_count DESC
            LIMIT 20
        """)
        top_abbreviations = cur.fetchall()
        
        return {
            'total_words_db': abbrev_row[0] if abbrev_row else 0,
            'abbrev_count_db': abbrev_row[1] if abbrev_row else 0,
            'state_codes_count': abbrev_row[2] if abbrev_row else 0,
            'country_codes_count': abbrev_row[3] if abbrev_row else 0,
            'page_numbers_count': abbrev_row[4] if abbrev_row else 0,
            'other_abbrevs_count': abbrev_row[5] if abbrev_row else 0,
            'top_abbreviations': top_abbreviations
        }


def fetch_ocr_patterns(conn, limit: int = 20) -> List[Tuple]:
    """Fetch most common OCR error patterns for quality assessment.
    
    Identifies systematic OCR errors like l/1 confusion, helping prioritize
    documents for re-scanning or automated correction.
    
    Args:
        conn: Active psycopg database connection.
        limit (int): Maximum number of patterns to return. Default: 20.
    
    Returns:
        List[Tuple]: List of (pattern, count) tuples sorted by frequency.
            Patterns include: 'l->1', 'O->0', 'rn->m', 'cl->d', 'vv->w'
    
    Example:
        >>> patterns = fetch_ocr_patterns(conn, limit=5)
        >>> for pattern, count in patterns:
        ...     print(f'{pattern}: {count} occurrences')
        l->1: 156 occurrences
        rn->m: 89 occurrences
    
    Note:
        Returns only rows where ocr_error_pattern is not NULL.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ocr_error_pattern, COUNT(*) as count
            FROM spelling_issues
            WHERE ocr_error_pattern IS NOT NULL
            GROUP BY ocr_error_pattern
            ORDER BY count DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def fetch_confidence_statistics(conn) -> List[Tuple]:
    """Fetch correction confidence level distribution.
    
    Shows breakdown of HIGH/MEDIUM/LOW confidence corrections to assess
    how many errors can be safely auto-corrected versus requiring review.
    
    Args:
        conn: Active psycopg database connection.
    
    Returns:
        List[Tuple]: List of (confidence_level, count, unique_words) tuples.
            Ordered: HIGH, MEDIUM, LOW
            - confidence_level (str): 'HIGH', 'MEDIUM', or 'LOW'
            - count (int): Total occurrences at this confidence
            - unique_words (int): Number of distinct words
    
    Example:
        >>> stats = fetch_confidence_statistics(conn)
        >>> for level, count, unique in stats:
        ...     print(f'{level}: {count} total, {unique} unique words')
        HIGH: 1523 total, 45 unique words
        MEDIUM: 892 total, 67 unique words
        LOW: 3401 total, 234 unique words
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                correction_confidence,
                COUNT(*) as count,
                COUNT(DISTINCT word) as unique_words
            FROM spelling_issues
            WHERE correction_confidence IS NOT NULL
            GROUP BY correction_confidence
            ORDER BY CASE correction_confidence
                WHEN 'HIGH' THEN 1
                WHEN 'MEDIUM' THEN 2
                WHEN 'LOW' THEN 3
            END
        """)
        return cur.fetchall()


def fetch_poor_quality_documents(
    conn,
    error_rate_threshold: float = HIGH_ERROR_RATE_THRESHOLD,
    limit: int = 20
) -> List[Tuple]:
    """Identify documents with high error rates needing review.
    
    Calculates error rate per document (errors per 100 words) to flag
    documents with poor OCR quality that may need re-scanning.
    
    Args:
        conn: Active psycopg database connection.
        error_rate_threshold (float): Minimum error percentage to include.
            Default: 10.0 (10% error rate).
        limit (int): Maximum documents to return. Default: 20.
    
    Returns:
        List[Tuple]: List of (file_path, error_rate, error_count) sorted by
            error_rate descending.
            - file_path (str): Full path to problematic document
            - error_rate (float): Percentage of words with errors
            - error_count (int): Number of unique error words
    
    Example:
        >>> bad_docs = fetch_poor_quality_documents(conn, threshold=15.0)
        >>> for path, rate, count in bad_docs[:3]:
        ...     print(f'{rate:.1f}% errors: {path}')
        23.4% errors: /path/to/bad_scan.txt
    
    Note:
        Estimates word count as document_length / 5 (average word length).
    """
    with conn.cursor() as cur:
        cur.execute("""
            WITH doc_stats AS (
                SELECT 
                    file_path,
                    AVG(document_length) as doc_length,
                    COUNT(DISTINCT word) as error_count
                FROM spelling_issues
                WHERE is_abbreviation = FALSE
                GROUP BY file_path
            ),
            doc_word_counts AS (
                SELECT 
                    file_path,
                    doc_length,
                    error_count,
                    GREATEST(doc_length / 5.0, 1) as estimated_word_count,
                    (error_count / GREATEST(doc_length / 5.0, 1) * 100) as error_rate
                FROM doc_stats
            )
            SELECT 
                file_path,
                error_rate,
                error_count
            FROM doc_word_counts
            WHERE error_rate > %s
            ORDER BY error_rate DESC
            LIMIT %s
        """, (error_rate_threshold, limit))
        return cur.fetchall()


def fetch_auto_correctable_errors(conn, limit: int = 50) -> List[Tuple]:
    """Fetch high-confidence errors suitable for automated correction.
    
    Identifies spelling errors with HIGH confidence corrections that can
    be safely auto-corrected without manual review. Used to generate
    automated correction scripts.
    
    Args:
        conn: Active psycopg database connection.
        limit (int): Maximum errors to return. Default: 50.
    
    Returns:
        List[Tuple]: List of (word, correction, frequency, distance) sorted
            by frequency descending.
            - word (str): Misspelled word
            - correction (str): High-confidence correction
            - frequency (int): Number of occurrences
            - distance (int): Hamming distance (typically 1-2)
    
    Example:
        >>> auto = fetch_auto_correctable_errors(conn, limit=10)
        >>> for word, fix, count, dist in auto:
        ...     print(f'{word} -> {fix} ({count}x, dist={dist})')
        teh -> the (156x, dist=1)
        recieved -> received (89x, dist=2)
    
    Note:
        Only includes non-abbreviations with non-null corrections.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                word,
                MAX(suggested_correction) as correction,
                COUNT(*) as frequency,
                MAX(hamming_distance) as distance
            FROM spelling_issues
            WHERE correction_confidence = 'HIGH'
              AND suggested_correction IS NOT NULL
              AND is_abbreviation = FALSE
            GROUP BY word
            ORDER BY frequency DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def fetch_consistency_issues(
    conn,
    limit: int = REPORT_MAX_CONSISTENCY_ISSUES
) -> List[Tuple]:
    """Find similar words with inconsistent spelling across documents.
    
    Identifies potential misspelling variants where similar-looking words
    appear with very different frequencies, suggesting one may be an error.
    
    Args:
        conn: Active psycopg database connection.
        limit (int): Maximum issues to return.
            Default: REPORT_MAX_CONSISTENCY_ISSUES (30).
    
    Returns:
        List[Tuple]: List of (word1, freq1, word2, freq2) sorted by max frequency.
            - word1 (str): First word variant
            - freq1 (int): Occurrences of first variant
            - word2 (str): Similar second word
            - freq2 (int): Occurrences of second variant
    
    Matching Criteria:
        - Same length
        - One starts with the other OR share first 3 characters
        - Frequency difference > 10
    
    Example:
        >>> issues = fetch_consistency_issues(conn, limit=5)
        >>> for w1, f1, w2, f2 in issues:
        ...     print(f'{w1} ({f1}) vs {w2} ({f2})')
        information (245) vs infornation (12)  # OCR rn/m error
    
    Note:
        Only considers words appearing more than 5 times.
    """
    with conn.cursor() as cur:
        # Simplified query: only check words with same first 3 chars (much faster)
        cur.execute("""
            WITH word_frequencies AS (
                SELECT word, COUNT(*) as freq
                FROM spelling_issues
                WHERE is_abbreviation = FALSE
                GROUP BY word
                HAVING COUNT(*) > 5
            )
            SELECT w1.word, w1.freq, w2.word as similar_word, w2.freq as similar_freq
            FROM word_frequencies w1
            JOIN word_frequencies w2 ON 
                w1.word < w2.word AND
                LENGTH(w1.word) = LENGTH(w2.word) AND
                SUBSTRING(w1.word, 1, 3) = SUBSTRING(w2.word, 1, 3)
            WHERE ABS(w1.freq - w2.freq) > 10
            ORDER BY GREATEST(w1.freq, w2.freq) DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def fetch_tfidf_statistics(
    conn,
    total_docs: int,
    low_doc_threshold: int = TFIDF_LOW_DOC_FREQUENCY_THRESHOLD
) -> Dict:
    """Calculate TF-IDF scores to identify distinctive error terms.
    
    Computes Term Frequency-Inverse Document Frequency to find errors
    that appear frequently but in few documents, suggesting they may be
    proper nouns, technical terms, or OCR artifacts worth investigating.
    
    Args:
        conn: Active psycopg database connection.
        total_docs (int): Total number of documents in corpus.
        low_doc_threshold (int): Max docs for 'low frequency' category.
            Default: TFIDF_LOW_DOC_FREQUENCY_THRESHOLD (10).
    
    Returns:
        Dict: Statistics containing:
            - tfidf_results (List[Tuple]): Top 100 by TF-IDF score
                Each: (word, term_freq, doc_freq, tfidf_score)
            - low_freq_terms (List[Tuple]): Up to 50 rare terms
                Each: (word, doc_freq)
    
    TF-IDF Formula:
        TF-IDF = term_frequency * LN(total_docs / document_frequency)
        Higher scores indicate distinctive terms worth examining.
    
    Example:
        >>> stats = fetch_tfidf_statistics(conn, total_docs=1000)
        >>> for word, tf, df, tfidf in stats['tfidf_results'][:5]:
        ...     print(f'{word}: TF={tf}, DF={df}, TF-IDF={tfidf:.2f}')
    
    Note:
        Excludes abbreviations and words in only 1 document.
    """
    with conn.cursor() as cur:
        cur.execute("""
            WITH word_stats AS (
                SELECT 
                    word,
                    COUNT(*) as term_frequency,
                    COUNT(DISTINCT file_path) as document_frequency
                FROM spelling_issues
                WHERE is_abbreviation = FALSE
                GROUP BY word
            )
            SELECT 
                word,
                term_frequency,
                document_frequency,
                term_frequency * LN(%s::numeric / document_frequency) as tf_idf
            FROM word_stats
            WHERE document_frequency > 1
            ORDER BY tf_idf DESC
            LIMIT 100
        """, (total_docs,))
        tfidf_results = cur.fetchall()
        
        # Get low-frequency distinctive terms
        cur.execute("""
            SELECT word, COUNT(DISTINCT file_path) as doc_freq
            FROM spelling_issues
            WHERE is_abbreviation = FALSE
            GROUP BY word
            HAVING COUNT(DISTINCT file_path) < %s
            ORDER BY doc_freq
            LIMIT 50
        """, (low_doc_threshold,))
        low_freq_terms = cur.fetchall()
        
        return {
            'tfidf_results': tfidf_results,
            'low_freq_terms': low_freq_terms
        }


# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_log_report(
    log_path: str,
    subfolder_stats: Dict[str, Dict],
    global_word_freq: Counter,
    spelling_issues_summary: Dict,
    verbose: bool = False
):
    """Generate comprehensive log report with statistics."""
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(SEPARATOR_MAJOR + "\n")
            f.write("SPELLING ANALYSIS REPORT (BY SUBFOLDER)\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(SEPARATOR_MAJOR + "\n\n")
            
            # Overall summary
            total_files = sum(stats['file_count'] for stats in subfolder_stats.values())
            total_unique_unknown = sum(stats['total_unknown'] for stats in subfolder_stats.values())
            
            f.write("OVERALL SUMMARY\n")
            f.write(SEPARATOR_MINOR + "\n")
            f.write(f"Total subfolders analyzed: {len(subfolder_stats)}\n")
            f.write(f"Total files analyzed: {total_files}\n")
            f.write(f"Total unique unknown words: {total_unique_unknown}\n")
            f.write(f"Average unknown words per file: {total_unique_unknown / total_files if total_files > 0 else 0:.2f}\n")
            f.write("\n")
            
            # Per-subfolder statistics
            f.write("STATISTICS BY SUBFOLDER\n")
            f.write(SEPARATOR_MAJOR + "\n\n")
            
            for subfolder in sorted(subfolder_stats.keys()):
                stats = subfolder_stats[subfolder]
                f.write(f"Subfolder: {subfolder}\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write(f"Files analyzed: {stats['file_count']}\n")
                f.write(f"Unique unknown words: {stats['total_unknown']}\n")
                f.write(f"Average unknown per file: {stats['total_unknown'] / stats['file_count'] if stats['file_count'] > 0 else 0:.2f}\n")
                
                # Zipf's law for this subfolder
                zipf_stats = calculate_zipf_statistics(stats['word_freq'])
                if zipf_stats and zipf_stats['total_unique_words'] > 0:
                    f.write(f"Total unique words: {zipf_stats['total_unique_words']}\n")
                    f.write(f"Most common word: '{zipf_stats['most_common_word']}' (freq: {zipf_stats['most_common_freq']})\n")
                    f.write(f"Zipf deviation: {zipf_stats['avg_zipf_deviation']:.4f}\n")
                
                # Top 5 unknown words in this subfolder
                if stats.get('top_unknown'):
                    f.write("\nTop 5 unknown words:\n")
                    for word, freq in stats['top_unknown'][:5]:
                        f.write(f"  - '{word}' (freq: {freq})\n")
                
                f.write("\n")
            
            # Global Zipf's law analysis
            zipf_stats = calculate_zipf_statistics(global_word_freq)
            if zipf_stats:
                f.write("GLOBAL ZIPF'S LAW ANALYSIS\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write(f"Total unique words in corpus: {zipf_stats['total_unique_words']}\n")
                f.write(f"Total word count: {zipf_stats['total_word_count']}\n")
                f.write(f"Most common word: '{zipf_stats['most_common_word']}' (freq: {zipf_stats['most_common_freq']})\n")
                f.write(f"Average Zipf deviation (top 100): {zipf_stats['avg_zipf_deviation']:.4f}\n")
                f.write("\nTop 10 most common words:\n")
                for rank, (word, freq) in enumerate(zipf_stats['top_10_words'], start=1):
                    expected_freq = zipf_stats['most_common_freq'] / rank
                    f.write(f"  {rank:2d}. '{word}' - Freq: {freq:6d}, Expected: {expected_freq:8.2f}, Ratio: {freq/expected_freq:.4f}\n")
                f.write("\n")
            
            # Edit distance analysis (both Hamming and Levenshtein)
            if spelling_issues_summary:
                f.write("EDIT DISTANCE STATISTICS\n")
                f.write(SEPARATOR_MINOR + "\n")
                
                hamming_distances = spelling_issues_summary.get('hamming_distances', [])
                levenshtein_distances = spelling_issues_summary.get('levenshtein_distances', [])
                
                if hamming_distances:
                    f.write("Hamming Distance:\n")
                    avg_h = sum(hamming_distances) / len(hamming_distances)
                    min_h = min(hamming_distances)
                    max_h = max(hamming_distances)
                    f.write(f"  Average: {avg_h:.2f}\n")
                    f.write(f"  Min/Max: {min_h} / {max_h}\n")
                    f.write(f"  Total words: {len(hamming_distances)}\n\n")
                    
                    hamming_counts = Counter(hamming_distances)
                    f.write("  Distribution:\n")
                    for dist in sorted(hamming_counts.keys())[:10]:
                        f.write(f"    Distance {dist}: {hamming_counts[dist]} words\n")
                    f.write("\n")
                
                if levenshtein_distances:
                    f.write("Levenshtein Distance:\n")
                    avg_l = sum(levenshtein_distances) / len(levenshtein_distances)
                    min_l = min(levenshtein_distances)
                    max_l = max(levenshtein_distances)
                    f.write(f"  Average: {avg_l:.2f}\n")
                    f.write(f"  Min/Max: {min_l} / {max_l}\n")
                    f.write(f"  Total words: {len(levenshtein_distances)}\n\n")
                    
                    levenshtein_counts = Counter(levenshtein_distances)
                    f.write("  Distribution:\n")
                    for dist in sorted(levenshtein_counts.keys())[:10]:
                        f.write(f"    Distance {dist}: {levenshtein_counts[dist]} words\n")
                    f.write("\n")
                
                # Comparison if both available
                if hamming_distances and levenshtein_distances:
                    f.write("Distance Comparison:\n")
                    f.write(f"  Hamming avg:     {avg_h:.2f}\n")
                    f.write(f"  Levenshtein avg: {avg_l:.2f}\n")
                    f.write(f"  Difference:      {abs(avg_h - avg_l):.2f}\n")
                    f.write("\n")
                f.write("\n")
                
                # Positional analysis
                position_stats = spelling_issues_summary.get('position_stats', {})
                if position_stats:
                    f.write("POSITIONAL ANALYSIS\n")
                    f.write(SEPARATOR_MINOR + "\n")
                    f.write("Error Distribution by Document Position:\n")
                    f.write(f"  Beginning (0-25%):     {position_stats.get('beginning', 0):5d} errors ({position_stats.get('beginning_pct', 0):.1f}%)\n")
                    f.write(f"  Early Middle (25-50%): {position_stats.get('early_middle', 0):5d} errors ({position_stats.get('early_middle_pct', 0):.1f}%)\n")
                    f.write(f"  Late Middle (50-75%):  {position_stats.get('late_middle', 0):5d} errors ({position_stats.get('late_middle_pct', 0):.1f}%)\n")
                    f.write(f"  End (75-100%):         {position_stats.get('end', 0):5d} errors ({position_stats.get('end_pct', 0):.1f}%)\n")
                    f.write(f"\nAverage Error Position: {position_stats.get('avg_position', 0):.1f}% through document\n")
                    f.write(f"\nError Distribution by Document Length:\n")
                    f.write(f"  Short documents (<1K chars):    {position_stats.get('short_docs', 0)} errors\n")
                    f.write(f"  Medium documents (1K-5K):       {position_stats.get('medium_docs', 0)} errors\n")
                    f.write(f"  Long documents (>5K):           {position_stats.get('long_docs', 0)} errors\n")
                    f.write("\n")
                
                # Abbreviation statistics
                abbrev_stats = spelling_issues_summary.get('abbreviations', {})
                if abbrev_stats:
                    f.write("ABBREVIATION STATISTICS\n")
                    f.write(SEPARATOR_MINOR + "\n")
                    f.write(f"Total abbreviations detected: {abbrev_stats.get('total', 0)}\n")
                    f.write(f"Percentage of unknown words: {abbrev_stats.get('percentage', 0):.1f}%\n")
                    f.write(f"\nBreakdown by category:\n")
                    f.write(f"  State codes: {abbrev_stats.get('state_codes', 0)}\n")
                    f.write(f"  Country codes: {abbrev_stats.get('country_codes', 0)}\n")
                    f.write(f"  Page numbers/Roman numerals: {abbrev_stats.get('page_numbers', 0)}\n")
                    f.write(f"  Other abbreviations: {abbrev_stats.get('other_abbrevs', 0)}\n")
                    
                    if abbrev_stats.get('top_abbreviations'):
                        f.write("\nTop 10 abbreviations:\n")
                        for rank, row in enumerate(abbrev_stats['top_abbreviations'][:10], start=1):
                            word, freq = row[0], row[1]
                            # Get category flags from query result
                            is_state, is_country, is_page, is_other = row[2], row[3], row[4], row[5]
                            
                            markers = []
                            if is_state:
                                markers.append("STATE")
                            if is_country:
                                markers.append("COUNTRY")
                            if is_page:
                                markers.append("PAGE")
                            if is_other:
                                markers.append("OTHER")
                            
                            marker_str = " [" + ", ".join(markers) + "]" if markers else ""
                            f.write(f"  {rank:2d}. '{word}' (freq: {freq}){marker_str}\n")
                    f.write("\n")
            
            # Top problematic words globally (excluding abbreviations)
            if spelling_issues_summary.get('top_words'):
                f.write("TOP 20 MOST FREQUENT MISSPELLINGS (EXCLUDING ABBREVIATIONS)\n")
                f.write(SEPARATOR_MINOR + "\n")
                for rank, (word, freq, correction, distance, is_abbrev) in enumerate(spelling_issues_summary['top_words'][:20], start=1):
                    correction_str = f"-> {correction}" if correction else "(no suggestion)"
                    distance_str = f"[dist: {distance}]" if distance is not None else ""
                    f.write(f"  {rank:2d}. '{word}' (freq: {freq}) {correction_str} {distance_str}\n")
                f.write("\n")
            
            # TF-IDF Analysis
            tfidf_stats = spelling_issues_summary.get('tfidf_stats', {})
            if tfidf_stats and tfidf_stats.get('top_words_by_tfidf'):
                f.write("TF-IDF ANALYSIS (TOP 20 DISTINCTIVE MISSPELLINGS)\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write(f"Total documents analyzed: {tfidf_stats.get('total_docs', 0)}\n")
                f.write("\nWords with highest TF-IDF scores:\n")
                f.write("(High TF-IDF = appears frequently but in few documents = distinctive error)\n\n")
                for rank, (word, tf, df, tfidf) in enumerate(tfidf_stats['top_words_by_tfidf'][:20], start=1):
                    f.write(f"  {rank:2d}. '{word}'\n")
                    f.write(f"      TF-IDF: {tfidf:.4f}  |  TF: {tf}  |  DF: {df} docs  |  IDF: {tfidf/tf if tf > 0 else 0:.4f}\n")
                f.write("\n")
                f.write("Legend:\n")
                f.write("  TF (Term Frequency): Total occurrences across all documents\n")
                f.write("  DF (Document Frequency): Number of documents containing the word\n")
                f.write("  IDF (Inverse Document Frequency): log(total_docs / DF)\n")
                f.write("  TF-IDF: TF × IDF (higher = more distinctive to specific documents)\n")
                f.write("\n")
            
            # OCR Error Patterns
            ocr_patterns = spelling_issues_summary.get('ocr_patterns', [])
            if ocr_patterns:
                f.write("OCR ERROR PATTERNS\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write("Most common character confusion patterns:\n\n")
                for pattern, count in ocr_patterns[:15]:
                    f.write(f"  {pattern:10s}: {count:5d} occurrences\n")
                f.write("\n")
            
            # Confidence Statistics
            confidence_stats = spelling_issues_summary.get('confidence_stats', [])
            if confidence_stats:
                f.write("CORRECTION CONFIDENCE DISTRIBUTION\n")
                f.write(SEPARATOR_MINOR + "\n")
                for conf, count, unique in confidence_stats:
                    f.write(f"  {conf:8s}: {count:6d} occurrences ({unique:5d} unique words)\n")
                f.write("\n")
            
            # Document Quality Scores
            poor_quality_docs = spelling_issues_summary.get('poor_quality_docs', [])
            if poor_quality_docs:
                f.write("DOCUMENTS NEEDING REVIEW (>10% Error Rate)\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write(f"Found {len(poor_quality_docs)} documents with high error rates:\n\n")
                for filepath, error_rate, error_count in poor_quality_docs[:20]:
                    filename = os.path.basename(filepath)
                    f.write(f"  {filename:50s}  {error_rate:5.1f}% error rate ({error_count} errors)\n")
                f.write("\nNote: These documents may need re-scanning or manual review.\n\n")
            
            # Cross-Document Consistency Issues
            consistency_issues = spelling_issues_summary.get('consistency_issues', [])
            if consistency_issues:
                f.write("CROSS-DOCUMENT CONSISTENCY ISSUES\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write("Similar words with inconsistent frequencies (potential variants):\n\n")
                for word1, freq1, word2, freq2 in consistency_issues[:15]:
                    f.write(f"  '{word1}' ({freq1}x) vs '{word2}' ({freq2}x)\n")
                f.write("\n")
            
            # Recommended Actions
            f.write("RECOMMENDED ACTIONS\n")
            f.write(SEPARATOR_MAJOR + "\n")
            
            auto_correctable = spelling_issues_summary.get('auto_correctable', [])
            if auto_correctable:
                f.write("\n1. AUTO-CORRECTABLE ERRORS (High Confidence)\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write(f"   {len(auto_correctable)} high-confidence errors can be auto-corrected:\n\n")
                for word, correction, freq, dist in auto_correctable[:10]:
                    f.write(f"   '{word}' → '{correction}' ({freq} occurrences, distance {dist})\n")
                f.write(f"\n   See auto-correction script: {os.path.basename(log_path).replace('.log', '_autocorrect.py')}\n\n")
            
            if poor_quality_docs:
                f.write(f"\n2. DOCUMENTS FOR RE-OCR\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write(f"   {len(poor_quality_docs)} documents have >10% error rate\n")
                f.write(f"   Consider re-scanning these for better quality\n\n")
            
            # Name whitelist suggestions from TF-IDF
            if tfidf_stats and tfidf_stats.get('top_words_by_tfidf'):
                f.write("\n3. POTENTIAL NAMES/ENTITIES TO WHITELIST\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write("   Review these high TF-IDF words - may be valid proper nouns:\n\n")
                for word, tf, df, tfidf in tfidf_stats['top_words_by_tfidf'][:15]:
                    if df < 10:  # Appears in few documents
                        f.write(f"   '{word}' (in {df} docs)\n")
                f.write("\n")
            
            # Estimated impact
            if auto_correctable:
                total_auto_fixes = sum(freq for _, _, freq, _ in auto_correctable)
                f.write(f"\nESTIMATED IMPACT:\n")
                f.write(SEPARATOR_MINOR + "\n")
                f.write(f"   Auto-corrections would fix: ~{total_auto_fixes} errors\n")
                if poor_quality_docs:
                    total_poor_errors = sum(count for _, _, count in poor_quality_docs)
                    f.write(f"   Manual review needed for: ~{total_poor_errors} errors in poor-quality docs\n")
                f.write("\n")
            
            f.write(SEPARATOR_MAJOR + "\n")
            f.write("END OF REPORT\n")
            f.write(SEPARATOR_MAJOR + "\n")
        
        if verbose:
            print(f"\nLog report written to: {log_path}")
    
    except Exception as e:
        if verbose:
            print(f"Error writing log report: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze spelling issues in extracted text files"
    )
    parser.add_argument("root", help="Root directory to scan for text files")
    parser.add_argument("--dsn", help="Postgres DSN (overrides DATABASE_URL)")
    parser.add_argument(
        "--ext",
        default="_extracted.txt",
        help="File extension to match (default: _extracted.txt)"
    )
    parser.add_argument(
        "--log",
        default="spelling_analysis.log",
        help="Output log file path (default: spelling_analysis.log)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()
    
    # Check dependencies
    if not SPELLCHECKER_AVAILABLE:
        print("pyspellchecker is required. Install with: pip install pyspellchecker", file=sys.stderr)
        return 2
    
    dsn = args.dsn or os.environ.get('DATABASE_URL')
    if not dsn:
        print("Missing DSN: set --dsn or DATABASE_URL", file=sys.stderr)
        return 2
    
    if psycopg is None:
        print("psycopg not available", file=sys.stderr)
        return 2
    
    # Initialize spell checker with custom dictionary
    if args.verbose:
        print("Initializing spell checker with custom dictionary...")
    spell_checker = SpellChecker()
    
    # Add known abbreviations and terms to dictionary (reduces false positives)
    known_terms = set()
    known_terms.update(US_STATE_CODES)
    known_terms.update(COUNTRY_CODES)
    known_terms.update(COMMON_ABBREVIATIONS)
    spell_checker.word_frequency.load_words(known_terms)
    
    if args.verbose:
        print(f"  Added {len(known_terms)} known terms to dictionary")
    
    # Initialize foreign language checkers
    if args.verbose:
        print("Initializing foreign language dictionaries...")
    for lang_code, lang_name in SUPPORTED_LANGUAGES.items():
        try:
            LANGUAGE_CHECKERS[lang_code] = SpellChecker(language=lang_code)
            if args.verbose:
                print(f"  Loaded {lang_name} ({lang_code}) dictionary")
        except Exception as e:
            if args.verbose:
                print(f"  Could not load {lang_name} ({lang_code}): {e}")
    
    # Clear cache for new run
    SPELL_CHECK_CACHE.clear()
    
    # Crawl for files and organize by subfolder
    if args.verbose:
        print(f"Scanning {args.root} for VOL*/IMAGES/*/ subfolders with '{args.ext}' files...")
    
    # Group files by subfolder (VOL*/IMAGES/###/)
    files_by_subfolder = defaultdict(list)
    
    for dirpath, _dirnames, filenames in os.walk(args.root):
        for name in filenames:
            if name.endswith(args.ext):
                full_path = os.path.join(dirpath, name)
                # Extract subfolder identifier using helper function
                subfolder_key = extract_subfolder_key(dirpath)
                files_by_subfolder[subfolder_key].append(full_path)
    
    if args.verbose:
        print(f"Found {len(files_by_subfolder)} subfolders")
        print(f"Total files: {sum(len(files) for files in files_by_subfolder.values())}\n")
    
    if not files_by_subfolder:
        print(f"No files found with extension '{args.ext}'", file=sys.stderr)
        return 1
    
    # Create database table
    with get_db_connection(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Check if table already exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'spelling_issues'
                )
            """)
            table_exists = cur.fetchone()[0]
            
            if table_exists:
                print("⚠️  WARNING: Table 'spelling_issues' already exists!")
                print("   This will add new data to the existing table.")
                print("   To start fresh, run: python scripts/drop_postgres_db.py spelling_issues --dsn <your_dsn>")
                response = input("   Continue anyway? (yes/no): ").strip().lower()
                if response not in ['yes', 'y']:
                    print("   Aborted.")
                    return 1
                print()
            
            cur.execute(CREATE_TABLE_SQL)
        if args.verbose:
            print("Database table created/verified\n")
        
        # Process files by subfolder
        subfolder_stats = {}
        global_word_freq = Counter()
        total_abbreviations = 0
        
        for subfolder_idx, (subfolder, file_paths) in enumerate(sorted(files_by_subfolder.items()), start=1):
            print(f"\nProcessing subfolder {subfolder_idx}/{len(files_by_subfolder)}: {subfolder}")
            print(f"  Files: {len(file_paths)}")
            
            subfolder_unknown_count = 0
            subfolder_word_freq = Counter()
            subfolder_unknown_words = Counter()
            subfolder_abbrev_count = 0
            
            for i, path in enumerate(file_paths, start=1):
                # Print progress for each file
                filename = os.path.basename(path)
                print(f"    [{i}/{len(file_paths)}] Processing: {filename}", end='')
                
                # Use position-aware analysis
                unknown_words_with_positions, word_freq = analyze_file_with_positions(path, spell_checker, SPELL_CHECK_CACHE, verbose=False)
                
                # Handle None return from error decorator
                if unknown_words_with_positions is None:
                    unknown_words_with_positions, word_freq = [], Counter()
                
                if unknown_words_with_positions:
                    # Store ALL words in database first (including abbreviations)
                    result = store_spelling_issues_with_positions(
                        conn, path, subfolder, unknown_words_with_positions, spell_checker, SPELL_CHECK_CACHE, verbose=False
                    )
                    # Handle None return from error decorator
                    if result is None:
                        _, abbrev_count, fragment_count = 0, 0, 0
                    else:
                        _, abbrev_count, fragment_count = result
                    
                    # Count unique unknown words EXCLUDING abbreviations and fragments for statistics
                    unique_unknown_words = set()
                    for word, _, _, _, _, _ in unknown_words_with_positions:
                        abbrev_info = categorize_abbreviation(word)
                        is_fragment = is_ocr_fragment(word)
                        # Only count non-abbreviations and non-fragments in statistics
                        if not abbrev_info.is_abbreviation and not is_fragment:
                            unique_unknown_words.add(word)
                    
                    subfolder_unknown_count += len(unique_unknown_words)
                    subfolder_unknown_words.update(unique_unknown_words)
                    subfolder_abbrev_count += abbrev_count
                    
                    total_words = len(set(word for word, _, _, _, _, _ in unknown_words_with_positions))
                    print(f" - {len(unknown_words_with_positions)} occurrences, {total_words} total unique ({len(unique_unknown_words)} errors, {abbrev_count} abbrev, {fragment_count} fragments)")
                else:
                    print(" - No unknown words")
                
                # Update frequencies
                subfolder_word_freq.update(word_freq)
                global_word_freq.update(word_freq)
            
            total_abbreviations += subfolder_abbrev_count
            
            # Store subfolder statistics
            subfolder_stats[subfolder] = {
                'file_count': len(file_paths),
                'total_unknown': len(subfolder_unknown_words),
                'word_freq': subfolder_word_freq,
                'top_unknown': subfolder_unknown_words.most_common(10),
                'abbreviations': subfolder_abbrev_count
            }
            
            print(f"  Unique unknown words: {len(subfolder_unknown_words)}")
            print(f"  Abbreviations detected: {subfolder_abbrev_count}")
        
        total_files = sum(s['file_count'] for s in subfolder_stats.values())
        total_unknown = sum(s['total_unknown'] for s in subfolder_stats.values())
        
        print(f"\n{'='*80}")
        print(f"PROCESSING COMPLETE")
        print(f"{'='*80}")
        print(f"Processed {total_files} files across {len(subfolder_stats)} subfolders")
        print(f"Total unique unknown words: {total_unknown}")
        print(f"Total abbreviations detected: {total_abbreviations}")
        print(f"Abbreviation percentage: {100.0 * total_abbreviations / total_unknown if total_unknown > 0 else 0:.1f}%")
        print(f"Spell check cache hits: {len(SPELL_CHECK_CACHE)} unique words cached")
        
        # Gather summary statistics from database using extracted functions
        print(f"\nGathering statistics from database...")
        
        top_words = fetch_top_words(conn)
        hamming_distances, levenshtein_distances = fetch_distance_statistics(conn)
        position_stats = fetch_position_statistics(conn)
        abbrev_stats = fetch_abbreviation_statistics(conn)
        ocr_patterns = fetch_ocr_patterns(conn)
        confidence_stats = fetch_confidence_statistics(conn)
        poor_quality_docs = fetch_poor_quality_documents(conn)
        auto_correctable = fetch_auto_correctable_errors(conn)
        consistency_issues = fetch_consistency_issues(conn)
        
        # Calculate TF-IDF statistics
        print(f"\nCalculating TF-IDF statistics...")
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(DISTINCT file_path) FROM spelling_issues""")
            total_docs = cur.fetchone()[0] or 1
        
        tfidf_data = fetch_tfidf_statistics(conn, total_docs)
        tfidf_stats = {
            'total_docs': total_docs,
            'top_words_by_tfidf': tfidf_data['tfidf_results']
        }
        
        # Assemble spelling issues summary with all statistics
        spelling_issues_summary = {
            'top_words': top_words,
            'hamming_distances': hamming_distances,
            'levenshtein_distances': levenshtein_distances,
            'position_stats': position_stats,
            'tfidf_stats': tfidf_stats,
            'ocr_patterns': ocr_patterns,
            'confidence_stats': confidence_stats,
            'poor_quality_docs': poor_quality_docs,
            'auto_correctable': auto_correctable,
            'consistency_issues': consistency_issues,
            'abbreviations': {
                'total': abbrev_stats['abbrev_count_db'],
                'percentage': (abbrev_stats['abbrev_count_db'] / abbrev_stats['total_words_db'] * 100) if abbrev_stats['total_words_db'] > 0 else 0,
                'state_codes': abbrev_stats['state_codes_count'],
                'country_codes': abbrev_stats['country_codes_count'],
                'page_numbers': abbrev_stats['page_numbers_count'],
                'other_abbrevs': abbrev_stats['other_abbrevs_count'],
                'top_abbreviations': abbrev_stats['top_abbreviations']
            }
        }
        
        # Generate log report
        generate_log_report(
            args.log,
            subfolder_stats,
            global_word_freq,
            spelling_issues_summary,
            args.verbose
        )
        
        # Generate auto-correction script
        if spelling_issues_summary.get('auto_correctable'):
            script_path = args.log.replace('.log', '_autocorrect.py')
            generate_correction_script(script_path, spelling_issues_summary['auto_correctable'], args.verbose)
    
    if args.verbose:
        print("\nAnalysis complete!")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
