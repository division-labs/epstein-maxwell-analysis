#!/usr/bin/env python3
"""Enhanced Entity Disambiguation & Resolution.

Advanced techniques for identifying and merging name variants in the
Epstein-Maxwell document corpus. This module provides sophisticated
entity canonicalization using multiple complementary strategies.

Features:
    1. Phonetic matching (Soundex/Metaphone) for OCR-resistant matching
    2. Initials + Last Name clustering (G. Maxwell → Ghislaine Maxwell)
    3. Enhanced title/suffix stripping (Dr., Hon., Special Agent, etc.)
    4. Organization co-mention context clustering
    5. Document date window analysis (temporal disambiguation)
    6. Frequency-based prioritization (high-impact names first)
    7. Network-based disambiguation (zero overlap = different people)
    8. OCR error pattern library (common OCR substitutions)
    9. Auto-exclusion rules (digits, emails, ALL CAPS artifacts)
    10. Multi-factor confidence scoring

Example:
    Run all analysis methods with verbose output::

        $ python disambiguate_entities_enhanced.py --analyze-all -v

    Create the PostgreSQL canonicalization function::

        $ python disambiguate_entities_enhanced.py --create-function

Attributes:
    PHONETIC_AVAILABLE (bool): Whether the metaphone library is installed.
    LEVENSHTEIN_THRESHOLD (int): Maximum edit distance for similarity.
    HIGH_CONFIDENCE_THRESHOLD (float): Score threshold for HIGH confidence.
    MEDIUM_CONFIDENCE_THRESHOLD (float): Score threshold for MEDIUM confidence.
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import psycopg

# Force unbuffered output for real-time progress display
os.environ['PYTHONUNBUFFERED'] = '1'
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass  # Ignore if it fails in some environments


def log(message: str = "", end: str = "\n") -> None:
    """Print a message with immediate flush for real-time display.

    Args:
        message: The message to print.
        end: String appended after the message. Defaults to newline.
    """
    print(message, end=end, flush=True)


from config import (
    DEFAULT_DSN,
    OCR_PATTERNS,
    SEED_ARTIFACT_SUFFIXES,
    SEED_OCR_PATTERNS,
    SEED_TITLES,
    TITLES,
)
from db_utils import get_db_connection, table_exists

# Try to import phonetic libraries
try:
    from metaphone import doublemetaphone
    PHONETIC_AVAILABLE = True
except ImportError:
    PHONETIC_AVAILABLE = False
    print("⚠️  Warning: metaphone library not installed.")
    print("   Install with: pip install metaphone")
    print("   Phonetic matching will be disabled.\n")

# =============================================================================
# Module Constants
# =============================================================================

# Database connection - uses config.py DEFAULT_DSN
DB_CONNECTION = DEFAULT_DSN

# Disambiguation thresholds
LEVENSHTEIN_THRESHOLD = 3
MIN_SHARED_CONTEXTS = 2
HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.60

# Phonetic matching threshold (at least 50% of phonetic codes must match)
PHONETIC_MATCH_THRESHOLD = 0.5

# Temporal window for considering names as potentially same person (years)
TEMPORAL_WINDOW_YEARS = 5

# Network overlap threshold (10% minimum co-occurrence overlap)
NETWORK_OVERLAP_THRESHOLD = 0.1

# Frequency thresholds for prioritization
HIGH_FREQUENCY_THRESHOLD = 100   # 100+ mentions = high frequency
MEDIUM_FREQUENCY_THRESHOLD = 10  # 10+ mentions = medium frequency

# Note: TITLES and OCR_PATTERNS are imported from config.py
# The database table name_normalization_rules is the source of truth once
# initialized with seed data.

# Auto-exclusion patterns (regex patterns for obvious non-person entities)
AUTO_EXCLUSION_PATTERNS = [
    (r'^\d+$', 'all_digits'),                           # Pure numbers
    (r'@', 'email_address'),                            # Contains @
    (r'^[A-Z\s]{10,}$', 'all_caps_long'),               # Long ALL CAPS headers
    (r'^EFTA\d+', 'document_id'),                       # EFTA document IDs
    (r'^(Page|PAGE)\s*\d+', 'page_number'),            # Page numbers
    (r'^\d{1,2}/\d{1,2}/\d{2,4}$', 'date_string'),    # Date strings
    (r'^(VOL|Volume)\s*\d+', 'volume_reference'),      # Volume references
    (r'^\d+\s*(st|nd|rd|th)', 'ordinal_number'),       # Ordinal numbers
    (r'^(Exhibit|EXHIBIT)\s*[A-Z0-9]', 'exhibit_ref'), # Exhibit references
    (r'^\s*$', 'empty_string'),                         # Empty or whitespace only
]

# Import KNOWN_ALIASES from original script
# (In production, this would be loaded from the original file)
# For now, including a subset for demonstration
KNOWN_ALIASES = {
    # Primary defendants
    'Jeffrey Epstein': [
        # Standard name variations
        'Jeff Epstein', 'Jeffrey E. Epstein', 'JEFFREY E EPSTEIN', 'J. Epstein', 'J Epstein', 
        'Jeffery Epstein', 'JEFFREY EPSTEIN', 'JEFFREY E. EPSTEIN',
        'Epstein', 'EPSTEIN', 'Jeffrey', 'JEFFREY', 'Jeff',
        # Full name "Jeffrey Edward Epstein" variations (middle name)
        'Jeffrey Edward Epstein', 'JEFFREY EDWARD EPSTEIN', 'JEFFREY EDWARD EPSTEN',
        'Jeffrey Edward', 'JEFFREY EDWARD', 'Epstein Jeffrey Edward',
        'EPSTEIN JEFFREY EDWARD Reg', 'Jeffrey Edward Epstein DOB',
        # Alias from arrest records
        'Jeffrey Edwards',
        # OCR artifacts from prison/court records containing "Jeffrey Edward"
        'JEFFREY EDWARD Reg', 'JEFFREY EDWARD Date of Birth', 'JEFFREY EDWARD FUNCTION',
        'JEFFREY EDWARD Date', 'JEFFREY EDWARD ORG', 'JEFFREY EDWARD RSP',
        'JEFFREY EDWARD CR', 'JEFFREY EDWARD REGISTER', 'JEFFREY EDWARD Rog',
        'JEFFREY EDWARD RS', 'JEFFREY EDWARD Begin', 'JEFFREY EDWARD Dale of Birth',
        'JEFFREY EDWARD Housing Status', 'JEFFREY EDWARD iiPrisoner',
        'JEFFREY EDWARD M Facili', 'JEFFREY EDWARD Nog', 'JEFFREY EDWARD Rag',
        'JEFFREY EDWARD Scars', 'JEFFREY EDWARD Sears', 'JEFFREY EDWARD Tearn',
        'stein Jeffrey Edward Req',
        # Date-appended variations (OCR artifacts)
        'Jeff Epstein Date', 'Jeffery Epstein Date', 'Jeffrey Epstein Date',
        'Jeffrey Epstein Death Date', 'J. Epstein Date', 'Epstein Date',
        '--Jeffrey Epstein Supposedly Sealed Order Date', 'Maxwell Epstein Date'
    ],
    'Ghislaine Maxwell': [
        'Ghislaine Noelle Marion Maxwell', 'G. Maxwell', 'G Maxwell',
        'GHISLAINE MAXWELL', 'GHISLANE MAXWELL', 'Maxwell', 'MAXWELL'
    ],
    
    # Victims / Survivors
    'Virginia Giuffre': ['Virginia Roberts', 'Virginia Roberts Giuffre'],
    
    # Public figures
    'Prince Andrew': ['Andrew Windsor', 'Duke of York'],
    'Bill Clinton': [
        'William Clinton', 'William J. Clinton', 'William Jefferson Clinton',
        'Clinton', 'Billy Clinton', 'Clintons', 'ClInton'
    ],
    'Donald Trump': ['Donald J. Trump', 'Donald J Trump', 'DONALD TRUMP', 'Trump'],
    
    # Maxwell defense team
    'Bobbi Sternheim': [
        'Bobbi C. Sternheim', 'BOBBI C. STERNHEIM', 'BOBBI C STERNHEIM',
        "BOBBI C STERNHEIM'", 'Bobbi C. Stemheim', 'Bobbi Stemheim', 'Bobbi'
    ],
    'Laura Menninger': [
        'Laura A. Menninger', 'LAURA A. MENNINGER', 'Laura A. Henninger', 
        'Laura Mennin', 'Laura',
        # Firm signature block variations (previously under 'Laura A. Menninger')
        'Laura A. Menninger Haddon', 'Laura A. Menninger HADDON',
        'Laura A. Menninger HADDON MORGAN FOREMAN P.C.',
        'Laura A. Menninger HADDON MORGAN FOREMAN P.C. Mark S. Cohen Christian R. Everdell COHEN GRESSER LLP',
        'Laura A. Menninger HADDON MORGAN FOREMAN P.C. Christian R. Everdell COHEN GRESSER LLP'
    ],
    'Jeffrey Pagliuca': ['Jeff Pagliuca', 'JEFFREY PAGLIUCA', 'Jeffrey S. Pagliuca'],
    'Christian Everdell': ['Chris'],
    'Mark S. Cohen': [
        'Mark Cohen', 'Mark Stewart Cohen', 'Mark S. Cohen Cc', 
        "Mark S. Cohen'", "Mark Cohen's", 'Mark S. Cohen Mark S. Cohen', 'Mark S.Cohen'
    ],
    'Bruce Barket': ['Bruce A. Barket'],
    
    # Epstein defense team
    'Martin Weinberg': [
        'Martin G. Weinberg', 'MARTIN G. WEINBERG', 
        'Marty', "Martin G. Weinberg'", "Martin Weinberg'"
    ],
    'Reid Weingarten': ['Reid', 'Weingarten', 'Reid Cc', 'Reid Marty', "Reid Weingarten'"],
    'Jay Lefkowitz': [
        'Jay', 'Lefkowitz', 'Jay Lefkowitz Cc', 'Jay P. Lefkowitz', 
        'Ja Lefkowitz', 'Ja Lefkowitz Cc'
    ],
    'Michael C. Miller': [
        'Miller', 'Michael Miller', "Michael Miller'", 'Mike', 
        'Mike Michael C. Miller', 'Mike Michael C. Miller Partner'
    ],
    
    # Prosecutors / Judges
    'Geoffrey S. Berman': ['Geoffrey', 'Berman', 'Geoff', 'Geoffrey Berman', 'Geoff Berman'],
    'Audrey Strauss': ['Audrey', 'Strauss'],
    'Alison J. Nathan': ['J. NATHAN', 'Nathan', 'ALISON J. NATHAN'],
    'Kenneth Marra': ['Kenneth A. Marra', 'Marra'],
    'Richard M. Berman': ['Richard Berman', 'RICHARD M. BERMAN'],
    'Damian Williams': ['DAMIAN WILLIAMS United States', 'DAMIAN WILLIAMS United States Attome'],
    'Henry B. Pitman': ['Henry Pitman', 'HENRY PITMAN', 'HENRY B. PITMAN', 'Pitman'],
    'Alan Dershowitz': ['Dershowitz', 'ALAN DERSHOWITZ', 'Alan M. Dershowitz', "Alan Dershowitz's"],
    'Ken Starr': ['Kenneth Starr', 'Starr'],
    
    # Victims' attorneys
    'Sigrid McCawley': [
        'Sigrid', 'Sigrid S. McCawley', 'SIGRID STONE McCAWLEY',
        'Sigrid McCawle', 'Sigrid McCawtey', 'Sigrid MeCawley'
    ],
    'Brad Edwards': [
        'Bradley Edwards', 'Bradley J. Edwards', 'BRAD EDWARDS', 
        'BRADLEY EDWARDS', "Bradley Edwards'", 'Edwards', 'EDWARDS'
    ],
    'Gloria Allred': [],  # No aliases yet
    
    # FBI / Law Enforcement
    'William F. Sweeney Jr.': ['William Sweeney', 'WILLIAM F. SWEENEY JR.', 'William F. Sweeney', 'Sweeney'],
    
    # MCC staff (Epstein death investigation)
    'Tova Noel': ['TOVA NOEL', 'Noel', 'NOEL'],
    'Michael Thomas': ['MICHAEL THOMAS', 'THOMAS', 'Thomas'],
    
    # Other attorneys and legal figures
    'Marc A. Weinstein': ['Weinstein', 'Marc A.', 'Marc A'],
    'Lisa M. Rocchio': ['Rocchio', 'Lisa Rocchio', 'Lisa Marie Rocchio', 'L. Rocchio', 'Lisa Lisa M. Rocchio'],
    'Alex Acosta': ['Acosta', 'Alex'],
    'Robert Mueller': ['Robert Mueller III', 'Robert S. Mueller III'],
    'Jamie Gorelick': ['Jamie S. Gorelick'],
    'Jim Margolin': ['JIM MARGOLIN'],
    
    # Other named individuals
    'Joseph Nascimento': [
        'Joe Joseph E. Nascimento', 'Joe Nascimento', 'Joseph E. Nascimento'
    ],
    'Jeffrey L. Jocks': ['Jeff Jocks', 'Jeffrey L. Jocks Sondee'],
    'Christopher Dilorio': ['Chris Dilorio', 'Christopher Diiorio'],
    'Joshua Harris': ['Josh Harris'],
    'Jared Kushner': ['Kush', 'Kush Jr'],
    'Eliot Spitzer': ['ELIOT SPITZER'],
    'Alexandra Conlon': ['Alex Conlon'],
    'Chris Collins': ['Collins'],
    'Georgios Ekonomou': ['Georgio EKONOMOU', 'George Economou'],
    'Richard Kahn': ['RICHARD D. KAHN', 'Richard D. Kahn'],
    'Darren Indyke': ['DARREN K. INDYKE', 'Darren K. Indyke'],
    'Daniel Ruzumna': ['Daniel S. Ruzumna'],
    'William Barr': ['Barr', 'WILLIAM BARR', 'William P. Barr', 'WILLIAM P. BARR'],
    'Paul A. Engelmayer': ['Engelmayer', 'Paul Engelmayer'],
    'Scott Borgerson': [
        'SCOTT BORGERSON', 'SCOTT G. BORGERSON', 'SCOTT G BORGERSON',
        'G. BORGERSON', 'Borgerson', 'Scott Borgerson DOB', 'Scott Borgerson Phone',
        'SCOTT G BORGERSON DOB', 'SCOTT G BORGERSON Part', 'SCOTT G BORGERSON Name',
        'SCOTT G BORGERSON Affordability'
    ],
    
    # Legal pseudonyms (aggregated for exclusion purposes)
    'Jane Doe': ['JANE DOE', 'Jane', "Jane Doe's", 'Jane Doe No', 'Jane Doe I'],
}

# Entities to exclude from analysis (not persons or inflated by artifacts)
# These are loaded into the entity_exclusions table
# Note: Email suffixes like "Sent", "Cc" are now stripped by get_canonical_name()
EXCLUDED_ENTITIES = {
    # Email artifacts - repetition in email headers inflates counts
    'Joseph Nascimento': 'email_artifact',      # Email header repetition inflation
    'Jeffrey L. Jocks': 'email_artifact',       # Email header repetition inflation
    
    # Not persons
    'Boies Schiller': 'organization',           # Law firm name, not a person
    'Kronprindsens Gade': 'organization',       # Street address in U.S. Virgin Islands
    'Mortgagee': 'organization',                # Legal entity designation, not a person
    'Epstein FOIA': 'organization',             # FOIA request reference, not a person
    'Brown v. Maxwell': 'organization',         # Case name, not a person
    
    # Locations (misidentified as persons by NER)
    "St. Andrew's Plaza": 'location',           # SDNY office address
    "Andrew's Plaza": 'location',               # SDNY office address variant
    'Andrews Plaza': 'location',                # SDNY office address variant
    'J. Mollo Building': 'location',            # Federal courthouse building
    'J. Mono Building': 'location',             # OCR variant of J. Mollo Building
    'Mono Building': 'location',                # OCR variant of J. Mollo Building
    'Mdlo Building': 'location',                # OCR variant of J. Mollo Building
    'Mao Building': 'location',                 # OCR variant of J. Mollo Building
    'Silvio J. Mollo Building': 'location',     # Full name of J. Mollo Building
    'Alfred E. Smith Building': 'location',     # Government building
    'Master Bedroom': 'location',               # Room reference in testimony
    'Raymond Buildings': 'location',            # UK legal chambers address
    'Espirito Santo Plaza': 'location',         # Miami building
    
    # Legal terms and citations (misidentified as persons by NER)
    'Jencks Act': 'legal_term',                 # Federal statute on evidence disclosure
    'Jenks Act': 'legal_term',                  # OCR variant of Jencks Act
    'B. Jencks Act': 'legal_term',              # Section reference to Jencks Act
    'R. Civ.': 'legal_term',                    # Federal Rules of Civil Procedure citation
    'Delinquency Act': 'legal_term',            # Statute reference
    'Overt Act': 'legal_term',                  # Legal term in conspiracy charges
    'S. Ct': 'legal_term',                      # Supreme Court citation
    
    # Note: Joint name references (e.g., "Laura Menninger Jeff Pagliuca") are handled
    # by the joint_name_mappings table, which splits them into component names
    
    # Fragments and OCR artifacts
    'George': 'fragmented_name',                # First name only, multiple individuals
    'Marc': 'fragmented_name',                  # First name only, multiple individuals
    'Det': 'ocr_artifact',                      # Truncated text (Detective? Detainee?)
    'JFK': 'ocr_artifact',                      # Airport code or initials, ambiguous
    'NIOP': 'ocr_artifact',                     # OCR artifact, not a person
    'Nathan - Pursuant': 'ocr_artifact',        # Document header artifact (Judge Nathan - Pursuant to...)
    'Ghislaine Borgerson': 'duplicate',         # Maxwell's married name, use Ghislaine Maxwell
    
    # Legal pseudonyms
    'Jane Doe': 'legal_pseudonym',              # Multiple victims, not a single entity
    
    # Unrelated or unclear relevance
    'Justin Rivera': 'unrelated_case',          # Procedurally consolidated, unrelated to Epstein-Maxwell
    'Christopher Dilorio': 'pending_review',    # Substantive relevance unclear
    'Justin Rivera': 'unrelated_case',          # Procedurally consolidated, unrelated to Epstein-Maxwell
    'Christopher Dilorio': 'pending_review',    # Substantive relevance unclear
}


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein (edit) distance between two strings.

    The Levenshtein distance is the minimum number of single-character
    edits (insertions, deletions, substitutions) required to transform
    one string into another.

    Args:
        s1: First string to compare.
        s2: Second string to compare.

    Returns:
        The edit distance as a non-negative integer.
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


def normalize_name(name: str, aggressive: bool = False) -> str:
    """Normalize a name by removing titles, possessives, and extra whitespace.

    Applies a series of text transformations to create a standardized form
    of a name suitable for comparison. In aggressive mode, uses the expanded
    TITLES set from config.py.

    Args:
        name: The name string to normalize.
        aggressive: If True, applies enhanced title stripping using the
            full TITLES set. Defaults to False.

    Returns:
        The normalized name as a lowercase string with titles and
        possessives removed.
    """
    normalized = name.lower().strip()

    # Remove possessive suffixes
    if normalized.endswith("'s") or normalized.endswith("'s"):
        normalized = normalized[:-2]
    elif normalized.endswith("s'") or normalized.endswith("s'"):
        normalized = normalized[:-2]
    elif normalized.endswith("'") or normalized.endswith("'"):
        normalized = normalized[:-1]
    
    # Remove common suffixes from signature blocks
    suffix_patterns = [
        r'\s+(partner|counsel|associate|paralegal)$',
        r'\s+(date|document|defendant|documents)$',
        r'\s+(sent|cc|to|from|subject|re|fwd)$',
    ]
    for pattern in suffix_patterns:
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
    
    # Remove titles
    words = normalized.split()
    if aggressive:
        # Use expanded TITLES set
        words = [w for w in words if w.rstrip('.') not in TITLES]
    else:
        # Original basic titles only
        basic_titles = {'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 
                       'sir', 'lady', 'lord', 'the', 'hon', 'honorable'}
        words = [w for w in words if w.rstrip('.') not in basic_titles]
    
    # Remove periods after initials
    words = [w.rstrip('.') if len(w) <= 2 else w for w in words]
    
    return ' '.join(words)


def extract_phonetic_code(name: str) -> Tuple[str, str]:
    """Extract phonetic codes using the Double Metaphone algorithm.

    Normalizes the name and generates phonetic representations for each
    word, then combines them into composite codes for the full name.

    Args:
        name: The name to convert to phonetic codes.

    Returns:
        A tuple of (primary_code, secondary_code). Each code is a
        space-separated string of phonetic representations for each word.
        Returns ('', '') if phonetic library is unavailable or name is empty.
    """
    if not PHONETIC_AVAILABLE:
        return ('', '')

    # Normalize and clean the name first
    clean_name = normalize_name(name, aggressive=True)

    # Get phonetic codes for each word
    words = clean_name.split()
    if not words:
        return ('', '')

    # Combine phonetic codes for all words
    primary_codes = []
    secondary_codes = []

    for word in words:
        if word:  # Skip empty strings
            primary, secondary = doublemetaphone(word)
            if primary:
                primary_codes.append(primary)
            if secondary:
                secondary_codes.append(secondary)

    primary_combined = ' '.join(primary_codes) if primary_codes else ''
    secondary_combined = ' '.join(secondary_codes) if secondary_codes else ''

    return (primary_combined, secondary_combined)


def phonetic_similarity(name1: str, name2: str) -> float:
    """Calculate phonetic similarity between two names.

    Compares the Double Metaphone phonetic codes of two names to determine
    how similarly they sound when spoken aloud.

    Args:
        name1: First name to compare.
        name2: Second name to compare.

    Returns:
        A similarity score between 0.0 (no similarity) and 1.0 (identical
        phonetic codes). Returns 0.0 if phonetic library is unavailable.
    """
    if not PHONETIC_AVAILABLE:
        return 0.0

    p1_primary, p1_secondary = extract_phonetic_code(name1)
    p2_primary, p2_secondary = extract_phonetic_code(name2)

    # Check for exact phonetic matches
    if p1_primary and p2_primary:
        if p1_primary == p2_primary:
            return 1.0

        # Check word-by-word phonetic similarity
        words1 = p1_primary.split()
        words2 = p2_primary.split()

        if words1 and words2:
            # Count matching phonetic codes
            matches = sum(1 for w1, w2 in zip(words1, words2) if w1 == w2)
            total = max(len(words1), len(words2))
            return matches / total if total > 0 else 0.0

    return 0.0


def extract_initials_last_name(name: str) -> Optional[str]:
    """Extract a pattern of initials plus last name initial.

    Identifies the structure of a name in terms of initials and full name
    parts, useful for matching abbreviated names to full names.

    Example:
        'G. Maxwell' -> 'G M'
        'Geoffrey S. Berman' -> 'G S B'

    Args:
        name: The name to analyze.

    Returns:
        A string of uppercase initials separated by spaces, or None if
        the name doesn't contain both initials and a last name.
    """
    words = normalize_name(name, aggressive=True).split()

    if len(words) < 2:
        return None

    # Check if first words are initials (single letters)
    initials = []
    last_name_parts = []

    for word in words:
        if len(word) == 1:
            initials.append(word.upper())
        else:
            last_name_parts.append(word)

    if not initials or not last_name_parts:
        return None

    # Return pattern: initials + first letter of last name
    last_initial = last_name_parts[-1][0].upper() if last_name_parts else ''
    return ' '.join(initials) + ' ' + last_initial


def is_initials_match(name1: str, name2: str) -> bool:
    """Check if one name is an initialed form of another.

    Determines whether two names could represent the same person where
    one uses initials and the other uses full names.

    Example:
        'G. Maxwell' matches 'Ghislaine Maxwell'

    Args:
        name1: First name to compare.
        name2: Second name to compare.

    Returns:
        True if the names match with one being an initialed form of the
        other, requiring at least 2 matching parts.
    """
    n1 = normalize_name(name1, aggressive=True)
    n2 = normalize_name(name2, aggressive=True)

    words1 = n1.split()
    words2 = n2.split()

    if len(words1) != len(words2):
        shorter = words1 if len(words1) < len(words2) else words2
        longer = words2 if len(words1) < len(words2) else words1

        # Check if all words in shorter match initial or full word in longer
        matches = 0
        for i, word in enumerate(shorter):
            if i < len(longer):
                if word == longer[i] or (len(word) == 1 and
                                          word == longer[i][0]):
                    matches += 1

        # At least 2 parts must match
        return matches == len(shorter) and matches >= 2

    return False


def apply_ocr_patterns(name: str) -> List[str]:
    """Generate candidate names by applying common OCR error patterns.

    Creates variants of a name by substituting characters that are commonly
    confused during optical character recognition (e.g., 'rn' -> 'm',
    'l' -> '1').

    Args:
        name: The original name string.

    Returns:
        A deduplicated list of name variants including the original name
        and all generated OCR-corrected alternatives.
    """
    candidates = [name]

    for ocr_pattern, correct_char in OCR_PATTERNS.items():
        if ocr_pattern in name.lower():
            # Generate variant by replacing OCR error with correct character
            variant = re.sub(
                ocr_pattern, correct_char, name, flags=re.IGNORECASE
            )
            if variant != name:
                candidates.append(variant)

        # Also try the reverse (correct char might have become OCR error)
        if correct_char in name.lower():
            variant = re.sub(
                correct_char, ocr_pattern, name, flags=re.IGNORECASE
            )
            if variant != name:
                candidates.append(variant)

    return list(set(candidates))  # Remove duplicates


def should_auto_exclude(name: str) -> Optional[Tuple[str, str]]:
    """Check if a name matches auto-exclusion patterns.

    Tests the name against predefined patterns that indicate the entity
    is not a person (e.g., document IDs, dates, page numbers).

    Args:
        name: The entity name to check.

    Returns:
        A tuple of (pattern_type, reason) if the name should be excluded,
        or None if it passes all exclusion checks.
    """
    for pattern, reason in AUTO_EXCLUSION_PATTERNS:
        if re.match(pattern, name):
            return (reason, f"Matched pattern: {pattern}")
    return None


def calculate_enhanced_confidence(
    name1: str,
    name2: str,
    shared_contexts: int,
    name_frequencies: Dict[str, int],
    temporal_overlap: bool = True,
    network_overlap: float = 0.0
) -> Tuple[float, Dict[str, float]]:
    """Calculate multi-factor confidence score for name matching.

    Combines multiple signals to determine the likelihood that two names
    refer to the same person. Uses weighted scoring across edit distance,
    phonetic similarity, initials matching, shared context, temporal
    overlap, and network co-occurrence.

    Args:
        name1: First name to compare.
        name2: Second name to compare.
        shared_contexts: Number of documents where both names appear.
        name_frequencies: Dictionary mapping names to their mention counts.
        temporal_overlap: Whether names appear in overlapping time periods.
            Defaults to True.
        network_overlap: Fraction of shared co-occurrence relationships.
            Defaults to 0.0.

    Returns:
        A tuple of (overall_score, component_scores) where overall_score
        is a float between 0.0 and 1.0, and component_scores is a dict
        with individual scores for each factor.
    """
    scores = {}
    weights = {}

    # 1. Edit distance score (30% weight)
    n1 = normalize_name(name1, aggressive=True).lower()
    n2 = normalize_name(name2, aggressive=True).lower()

    lev_dist = levenshtein_distance(n1, n2)
    max_len = max(len(n1), len(n2))
    scores['edit_distance'] = 1.0 - (lev_dist / max_len) if max_len > 0 else 0.0
    weights['edit_distance'] = 0.30

    # 2. Phonetic similarity (20% weight)
    if PHONETIC_AVAILABLE:
        scores['phonetic'] = phonetic_similarity(name1, name2)
        weights['phonetic'] = 0.20
    else:
        scores['phonetic'] = 0.0
        weights['phonetic'] = 0.0

    # 3. Initials match (15% weight)
    scores['initials'] = 0.9 if is_initials_match(name1, name2) else 0.0
    weights['initials'] = 0.15

    # 4. Shared context (25% weight)
    scores['context'] = min(shared_contexts / 10.0, 1.0)
    weights['context'] = 0.25

    # 5. Temporal overlap (5% weight)
    scores['temporal'] = 1.0 if temporal_overlap else 0.0
    weights['temporal'] = 0.05

    # 6. Network overlap (5% weight)
    scores['network'] = min(network_overlap, 1.0)
    weights['network'] = 0.05

    # Calculate weighted average
    total_weight = sum(weights.values())
    if total_weight > 0:
        overall_score = sum(scores[k] * weights[k] for k in scores) / total_weight
    else:
        overall_score = scores['edit_distance']

    return overall_score, scores


def create_enhanced_tables(conn, verbose: bool = False):
    """Create enhanced entity disambiguation tables.

    Drops and recreates all disambiguation tables for a clean slate,
    including entity_aliases, name_disambiguation_queue, entity_exclusions,
    auto_exclusions_log, and name_normalization_rules.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints progress messages. Defaults to False.
    """
    log("Creating enhanced entity disambiguation tables...")
    
    with conn.cursor() as cur:
        if verbose:
            log("  Dropping existing tables...")
        
        # Drop existing tables for clean rebuild
        cur.execute("DROP TABLE IF EXISTS auto_exclusions_log CASCADE")
        cur.execute("DROP TABLE IF EXISTS name_disambiguation_queue CASCADE")
        cur.execute("DROP TABLE IF EXISTS entity_aliases CASCADE")
        cur.execute("DROP TABLE IF EXISTS entity_exclusions CASCADE")
        cur.execute("DROP TABLE IF EXISTS name_normalization_rules CASCADE")
        conn.commit()
        
        if verbose:
            log("  ✓ Dropped existing tables")
            log("  Creating new tables...")
        
        # Create entity_aliases table with enhanced columns
        cur.execute("""
            CREATE TABLE entity_aliases (
                alias_id SERIAL PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                alias_name TEXT NOT NULL,
                confidence_score FLOAT NOT NULL,
                disambiguation_method TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed BOOLEAN DEFAULT FALSE,
                phonetic_primary TEXT,
                phonetic_secondary TEXT,
                initials_pattern TEXT,
                frequency_tier TEXT,
                confidence_components JSONB,
                UNIQUE(canonical_name, alias_name)
            );
        """)
        
        # Create disambiguation queue with enhanced columns
        cur.execute("""
            CREATE TABLE name_disambiguation_queue (
                queue_id SERIAL PRIMARY KEY,
                name_variant_1 TEXT NOT NULL,
                name_variant_2 TEXT NOT NULL,
                similarity_score FLOAT NOT NULL,
                confidence_level TEXT,
                shared_contexts INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                phonetic_score FLOAT,
                initials_score FLOAT,
                temporal_overlap BOOLEAN,
                network_overlap_score FLOAT,
                priority_score FLOAT,
                confidence_components JSONB,
                user_approved BOOLEAN DEFAULT FALSE,
                reviewer_notes TEXT,
                CHECK (status IN ('pending', 'merged', 'rejected')),
                CHECK (confidence_level IN ('HIGH', 'MEDIUM', 'LOW')),
                UNIQUE(name_variant_1, name_variant_2)
            );
        """)
        
        # Create entity exclusions table
        cur.execute("""
            CREATE TABLE entity_exclusions (
                exclusion_id SERIAL PRIMARY KEY,
                entity_name TEXT NOT NULL UNIQUE,
                exclusion_reason TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                CHECK (exclusion_reason IN (
                    'email_artifact',
                    'organization',
                    'fragmented_name',
                    'legal_pseudonym',
                    'unrelated_case',
                    'pending_review',
                    'ocr_artifact',
                    'duplicate',
                    'location',
                    'legal_term',
                    'joint_name_artifact'
                ))
            );
        """)
        
        # Create auto-exclusions log table
        cur.execute("""
            CREATE TABLE auto_exclusions_log (
                log_id SERIAL PRIMARY KEY,
                entity_name TEXT NOT NULL,
                exclusion_pattern TEXT NOT NULL,
                exclusion_reason TEXT NOT NULL,
                detected_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Create name normalization rules table
        # This is the dynamic, growing source of truth for:
        # - titles to strip (mr, mrs, judge, etc.)
        # - OCR error patterns (rn→m, 0→o, etc.)
        # - artifact suffixes (mailto, sent, date, etc.)
        cur.execute("""
            CREATE TABLE name_normalization_rules (
                rule_id SERIAL PRIMARY KEY,
                rule_type TEXT NOT NULL,
                pattern TEXT NOT NULL,
                replacement TEXT,
                notes TEXT,
                source TEXT DEFAULT 'seed',
                created_at TIMESTAMP DEFAULT NOW(),
                enabled BOOLEAN DEFAULT TRUE,
                UNIQUE(rule_type, pattern),
                CHECK (rule_type IN ('title', 'ocr_pattern', 'artifact_suffix', 'auto_exclusion_pattern'))
            );
        """)
        
        # Create indexes
        cur.execute("CREATE INDEX idx_entity_aliases_canonical ON entity_aliases(canonical_name)")
        cur.execute("CREATE INDEX idx_entity_aliases_alias ON entity_aliases(alias_name)")
        cur.execute("CREATE INDEX idx_entity_aliases_alias_lower ON entity_aliases(LOWER(alias_name))")
        cur.execute("CREATE INDEX idx_entity_aliases_canonical_lower ON entity_aliases(LOWER(canonical_name))")
        cur.execute("CREATE INDEX idx_disambiguation_queue_status ON name_disambiguation_queue(status)")
        cur.execute("CREATE INDEX idx_disambiguation_queue_confidence ON name_disambiguation_queue(confidence_level)")
        cur.execute("CREATE INDEX idx_disambiguation_queue_priority ON name_disambiguation_queue(priority_score DESC NULLS LAST)")
        cur.execute("CREATE INDEX idx_disambiguation_queue_phonetic ON name_disambiguation_queue(phonetic_score DESC NULLS LAST)")
        cur.execute("CREATE INDEX idx_entity_exclusions_reason ON entity_exclusions(exclusion_reason)")
        cur.execute("CREATE INDEX idx_normalization_rules_type ON name_normalization_rules(rule_type)")
        cur.execute("CREATE INDEX idx_normalization_rules_enabled ON name_normalization_rules(rule_type, enabled) WHERE enabled = TRUE")
        
        conn.commit()
        log("✓ Enhanced tables created (clean rebuild)")


def load_known_aliases(conn, verbose: bool = False):
    """Load predefined known aliases into the entity_aliases table.

    Populates the database with manually curated canonical name mappings
    from the KNOWN_ALIASES dictionary. Each canonical name is also
    stored as an alias to itself.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints progress every 10 entities. Defaults to False.
    """
    log("\nLoading known aliases...")
    
    with conn.cursor() as cur:
        count = 0
        total_entities = len(KNOWN_ALIASES)
        entities_processed = 0
        
        for canonical, aliases in KNOWN_ALIASES.items():
            entities_processed += 1
            if verbose and entities_processed % 10 == 0:
                log(f"  Processing entity {entities_processed}/{total_entities}...")
            
            # First, store the canonical name as an alias to itself
            try:
                cur.execute("""
                    INSERT INTO entity_aliases 
                    (canonical_name, alias_name, confidence_score, disambiguation_method, reviewed)
                    VALUES (%s, %s, %s, %s, %s)
                """, (canonical, canonical, 1.0, 'manual', True))
                count += 1
            except Exception:
                pass  # Skip duplicates silently
            
            # Then store all aliases
            for alias in aliases:
                try:
                    cur.execute("""
                        INSERT INTO entity_aliases 
                        (canonical_name, alias_name, confidence_score, disambiguation_method, reviewed)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (canonical, alias, 1.0, 'manual', True))
                    count += 1
                except Exception:
                    pass  # Skip duplicates silently
        
        conn.commit()
        log(f"✓ Loaded {count} known aliases ({total_entities} entities)")


def load_excluded_entities(conn, verbose: bool = False):
    """Load excluded entities into the entity_exclusions table.

    Populates the database with entities that should be excluded from
    person analysis (organizations, locations, legal terms, etc.)
    from the EXCLUDED_ENTITIES dictionary.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints progress messages. Defaults to False.
    """
    log("\nLoading excluded entities...")
    
    with conn.cursor() as cur:
        count = 0
        total = len(EXCLUDED_ENTITIES)
        
        for entity_name, reason in EXCLUDED_ENTITIES.items():
            try:
                cur.execute("""
                    INSERT INTO entity_exclusions (entity_name, exclusion_reason)
                    VALUES (%s, %s)
                """, (entity_name, reason))
                count += 1
            except Exception:
                pass  # Skip duplicates silently
        
        conn.commit()
        log(f"✓ Loaded {count} entity exclusions")


def load_normalization_rules(conn, verbose: bool = False):
    """Load seed normalization rules into the name_normalization_rules table.

    Populates the database with initial normalization patterns that can
    grow dynamically as new patterns are discovered. Rules are organized
    by type:

    - titles: Words to strip from name beginnings (mr, mrs, judge, etc.)
    - ocr_pattern: Character substitutions (rn→m, 0→o, etc.)
    - artifact_suffix: Words to strip from name endings (mailto, sent, etc.)

    Seed data is loaded from config.py constants: SEED_TITLES,
    SEED_OCR_PATTERNS, and SEED_ARTIFACT_SUFFIXES.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints progress messages. Defaults to False.
    """
    log("\nLoading name normalization rules...")
    
    with conn.cursor() as cur:
        
        count = 0
        
        # Load titles from SEED_TITLES
        for title in SEED_TITLES:
            try:
                cur.execute("""
                    INSERT INTO name_normalization_rules (rule_type, pattern, replacement, notes, source)
                    VALUES ('title', %s, '', 'Strip from beginning of name', 'seed')
                """, (title,))
                count += 1
            except Exception:
                pass  # Ignore duplicates
        
        # Load OCR patterns from SEED_OCR_PATTERNS
        for pattern, replacement in SEED_OCR_PATTERNS.items():
            try:
                cur.execute("""
                    INSERT INTO name_normalization_rules (rule_type, pattern, replacement, notes, source)
                    VALUES ('ocr_pattern', %s, %s, 'Common OCR character confusion', 'seed')
                """, (pattern, replacement))
                count += 1
            except Exception:
                pass
        
        # Load artifact suffixes from SEED_ARTIFACT_SUFFIXES
        for suffix in SEED_ARTIFACT_SUFFIXES:
            try:
                cur.execute("""
                    INSERT INTO name_normalization_rules (rule_type, pattern, replacement, notes, source)
                    VALUES ('artifact_suffix', %s, '', 'OCR artifact suffix', 'seed')
                """, (suffix,))
                count += 1
            except Exception:
                pass
        
        conn.commit()
        log(f"✓ Loaded {count} normalization rules")


def get_normalization_rules(conn) -> Dict[str, any]:
    """Load normalization rules from database for use in name processing.

    Retrieves all enabled normalization rules from the database, allowing
    rules to grow dynamically without requiring code changes.

    Args:
        conn: Active psycopg database connection.

    Returns:
        A dictionary with keys:
            - 'titles': Set of title words to strip.
            - 'ocr_patterns': Dict mapping OCR errors to corrections.
            - 'artifact_suffixes': Set of suffix words to strip.
    """
    rules = {
        'titles': set(),
        'ocr_patterns': {},
        'artifact_suffixes': set()
    }
    
    with conn.cursor() as cur:
        # Load titles
        cur.execute("""
            SELECT pattern FROM name_normalization_rules 
            WHERE rule_type = 'title' AND enabled = TRUE
        """)
        rules['titles'] = {row[0].lower() for row in cur.fetchall()}
        
        # Load OCR patterns
        cur.execute("""
            SELECT pattern, replacement FROM name_normalization_rules 
            WHERE rule_type = 'ocr_pattern' AND enabled = TRUE
        """)
        rules['ocr_patterns'] = {row[0]: row[1] for row in cur.fetchall()}
        
        # Load artifact suffixes
        cur.execute("""
            SELECT pattern FROM name_normalization_rules 
            WHERE rule_type = 'artifact_suffix' AND enabled = TRUE
        """)
        rules['artifact_suffixes'] = {row[0].lower() for row in cur.fetchall()}
    
    return rules


def add_normalization_rule(
    conn,
    rule_type: str,
    pattern: str,
    replacement: str = '',
    notes: str = '',
    source: str = 'discovered'
) -> bool:
    """Add a new normalization rule to the database.

    Dynamically extends the normalization rules as new patterns are
    discovered during analysis. Rule types include titles, OCR patterns,
    and artifact suffixes.

    Args:
        conn: Active psycopg database connection.
        rule_type: Category of rule ('title', 'ocr_pattern', 'artifact_suffix').
        pattern: The pattern to match (case-insensitive).
        replacement: The replacement text. Defaults to empty string.
        notes: Optional description of why this rule was added.
        source: Origin of the rule ('seed', 'discovered', 'manual').
            Defaults to 'discovered'.

    Returns:
        True if the rule was successfully added, False if it already exists
        or an error occurred.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO name_normalization_rules
                    (rule_type, pattern, replacement, notes, source)
                VALUES (%s, %s, %s, %s, %s)
            """, (rule_type, pattern.lower(), replacement, notes, source))
            conn.commit()
            return True
    except Exception:
        conn.rollback()
        return False


def analyze_phonetic_matches(
    conn,
    name_contexts: Dict[str, Set[str]],
    name_frequencies: Dict[str, int],
    canonical_lookup: Dict[str, str],
    verbose: bool = False,
    limit: Optional[int] = None
):
    """Find potential name matches using phonetic similarity.

    Uses the Double Metaphone algorithm to identify names that sound
    similar when spoken, which helps catch spelling variations and
    transliterations.

    Args:
        conn: Active psycopg database connection.
        name_contexts: Dict mapping names to sets of document IDs.
        name_frequencies: Dict mapping names to mention counts.
        canonical_lookup: Dict mapping aliases to canonical names.
        verbose: If True, prints progress during analysis. Defaults to False.
        limit: Maximum number of names to analyze. If None, analyzes all.
            Names are prioritized by frequency.
    """
    if not PHONETIC_AVAILABLE:
        log("⚠️  Phonetic matching requires 'metaphone' library")
        log("  Install with: pip install metaphone")
        return

    log("\n🔊 Analyzing phonetic matches...")
    
    names = list(name_contexts.keys())
    if limit:
        # Prioritize high-frequency names
        names = sorted(names, key=lambda n: name_frequencies.get(n, 0), reverse=True)[:limit]
    
    # Build phonetic index with progress
    phonetic_index = defaultdict(list)
    total_names = len(names)
    progress_interval = max(1, total_names // 10)
    if verbose:
        log(f"  Building phonetic index for {total_names:,} names...")
    for i, name in enumerate(names):
        if (i + 1) % progress_interval == 0:
            pct = ((i + 1) / total_names) * 100
            log(f"    Indexing: {i + 1:,}/{total_names:,} ({pct:.0f}%)")
        primary, secondary = extract_phonetic_code(name)
        if primary:
            phonetic_index[primary].append(name)
        if secondary and secondary != primary:
            phonetic_index[secondary].append(name)
    
    log(f"  ✓ Built phonetic index for {len(names):,} names ({len(phonetic_index):,} codes)")
    
    candidates = []
    groups_processed = 0
    total_groups = sum(1 for m in phonetic_index.values() if len(m) >= 2)
    progress_interval = max(1, total_groups // 10)
    
    if verbose:
        log(f"  Comparing {total_groups:,} phonetic groups with 2+ names...")
    
    for phonetic_code, matching_names in phonetic_index.items():
        if len(matching_names) < 2:
            continue
        
        groups_processed += 1
        if groups_processed % progress_interval == 0:
            pct = (groups_processed / total_groups) * 100
            log(f"    Comparing: {groups_processed:,}/{total_groups:,} ({pct:.0f}%)")
        
        # Compare all pairs within this phonetic group
        for i, name1 in enumerate(matching_names):
            for name2 in matching_names[i+1:]:
                # Skip if normalized names are identical
                if normalize_name(name1) == normalize_name(name2):
                    continue
                
                shared = len(name_contexts[name1] & name_contexts[name2])
                
                # Calculate phonetic similarity score for this method
                phon_score = phonetic_similarity(name1, name2)
                
                # Collect ALL phonetic matches - no threshold filtering
                # Final holistic score calculated after all analyses complete
                candidates.append({
                    'name1': name1,
                    'name2': name2,
                    'score': phon_score,  # Method-specific score only
                    'shared': shared,
                    'phonetic_score': phon_score,
                    'method': 'phonetic'
                })
    
    log(f"  ✓ Found {len(candidates):,} phonetic match candidates")
    
    insert_candidates_to_queue(conn, candidates, canonical_lookup, verbose)


def analyze_initials_matches(
    conn,
    name_contexts: Dict[str, Set[str]],
    name_frequencies: Dict[str, int],
    canonical_lookup: Dict[str, str],
    verbose: bool = False,
    limit: Optional[int] = None
):
    """Find matches between initialed names and full names.

    Identifies potential matches where one name uses initials and another
    uses full names (e.g., 'G. Maxwell' vs 'Ghislaine Maxwell').

    Args:
        conn: Active psycopg database connection.
        name_contexts: Dict mapping names to sets of document IDs.
        name_frequencies: Dict mapping names to mention counts.
        canonical_lookup: Dict mapping aliases to canonical names.
        verbose: If True, prints progress during analysis. Defaults to False.
        limit: Maximum number of names to analyze. If None, analyzes all.
    """
    log("\n🔤 Analyzing initials + last name matches...")
    
    names = list(name_contexts.keys())
    if limit:
        names = sorted(names, key=lambda n: name_frequencies.get(n, 0), reverse=True)[:limit]
    
    # Separate names into initials-only and full names
    initials_names = []
    full_names = []
    
    total_names = len(names)
    progress_interval = max(1, total_names // 10)
    log(f"  Categorizing {total_names:,} names...")
    for i, name in enumerate(names):
        if (i + 1) % progress_interval == 0:
            pct = ((i + 1) / total_names) * 100
            log(f"    Categorizing: {i + 1:,}/{total_names:,} ({pct:.0f}%)")
        words = normalize_name(name, aggressive=True).split()
        if len(words) >= 2 and len(words[0]) == 1:  # First word is initial
            initials_names.append(name)
        elif len(words) >= 2:  # Has first and last name
            full_names.append(name)
    
    log(f"  ✓ Found {len(initials_names):,} names with initials, {len(full_names):,} full names")
    
    candidates = []
    total_initials = len(initials_names)
    progress_interval = max(1, total_initials // 10)
    log(f"  Matching {total_initials:,} initialed names against {len(full_names):,} full names...")
    for idx, initial_name in enumerate(initials_names):
        if (idx + 1) % progress_interval == 0:
            pct = ((idx + 1) / total_initials) * 100
            log(f"    Matching: {idx + 1:,}/{total_initials:,} ({pct:.0f}%)")
        
        initial_words = normalize_name(initial_name, aggressive=True).split()
        
        for full_name in full_names:
            full_words = normalize_name(full_name, aggressive=True).split()
            
            # Check if they could match (same last name)
            if len(initial_words) == len(full_words):
                # Check if last names match and initials match
                if (initial_words[-1] == full_words[-1] and 
                    all(iw[0] == fw[0] for iw, fw in zip(initial_words[:-1], full_words[:-1]))):
                    
                    shared = len(name_contexts[initial_name] & name_contexts[full_name])
                    
                    # Initials match = high confidence for this signal
                    initials_score = 0.9
                    
                    # Collect ALL initials matches - no threshold filtering
                    # Final holistic score calculated after all analyses complete
                    candidates.append({
                        'name1': initial_name,
                        'name2': full_name,
                        'score': initials_score,  # Method-specific score only
                        'shared': shared,
                        'initials_score': initials_score,
                        'method': 'initials'
                    })
    
    log(f"  ✓ Found {len(candidates):,} initials match candidates")
    
    insert_candidates_to_queue(conn, candidates, canonical_lookup, verbose)


def analyze_context_clustering(
    conn,
    name_contexts: Dict[str, Set[str]],
    name_frequencies: Dict[str, int],
    canonical_lookup: Dict[str, str],
    verbose: bool = False
):
    """Cluster names by organizational co-mention context.

    Uses co-occurrence with organization names to help disambiguate
    common names like 'Michael Miller' by identifying which organizations
    each name variant is associated with.

    Args:
        conn: Active psycopg database connection.
        name_contexts: Dict mapping names to sets of document IDs.
        name_frequencies: Dict mapping names to mention counts.
        canonical_lookup: Dict mapping aliases to canonical names.
        verbose: If True, prints progress during analysis. Defaults to False.
    """
    log("\n🏢 Analyzing organizational context clustering...")
    
    # Get organization mentions from extracted_names
    log("  Querying organization names from database...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT name_string
            FROM extracted_names
            WHERE name_string ~* '(LLC|Inc|Corp|Company|Firm|Partners|LLP|P\\.?C\\.?|Foundation|Trust)'
            AND LENGTH(name_string) > 3
        """)
        org_names = {row[0] for row in cur.fetchall()}
    
    log(f"  ✓ Identified {len(org_names):,} organization names")
    
    # For each person name, find which organizations they co-occur with
    person_org_contexts = {}
    total_names = len(name_contexts)
    processed = 0
    progress_interval = max(1, total_names // 10)
    
    log(f"  Mapping organizational contexts for {total_names:,} names...")
    for name in name_contexts:
        processed += 1
        if processed % progress_interval == 0:
            pct = (processed / total_names) * 100
            log(f"    Mapping: {processed:,}/{total_names:,} ({pct:.0f}%)")
        
        if name in org_names:
            continue  # Skip organizations themselves
        
        # Find organizations mentioned in same documents
        name_docs = name_contexts[name]
        org_cooccurrences = []
        
        for org in org_names:
            if org in name_contexts:
                org_docs = name_contexts[org]
                shared = name_docs & org_docs
                if shared:
                    org_cooccurrences.append((org, len(shared)))
        
        if org_cooccurrences:
            person_org_contexts[name] = org_cooccurrences
    
    log(f"  ✓ Mapped {len(person_org_contexts):,} people to organizational contexts")
    
    # Now find names that might be the same person based on org context overlap
    candidates = []
    names_list = list(person_org_contexts.keys())
    total_to_compare = len(names_list)
    progress_interval = max(1, total_to_compare // 10)
    
    log(f"  Comparing context overlap for {total_to_compare:,} names...")
    for i, name1 in enumerate(names_list):
        if (i + 1) % progress_interval == 0:
            pct = ((i + 1) / total_to_compare) * 100
            log(f"    Comparing: {i + 1:,}/{total_to_compare:,} ({pct:.0f}%)")
        
        for name2 in names_list[i+1:]:
            # Only compare if names are similar enough to be confused
            if levenshtein_distance(normalize_name(name1), normalize_name(name2)) > 5:
                continue
            
            orgs1 = set(org for org, count in person_org_contexts[name1])
            orgs2 = set(org for org, count in person_org_contexts[name2])
            
            if not orgs1 or not orgs2:
                continue
            
            # Calculate org context overlap
            overlap = len(orgs1 & orgs2)
            union = len(orgs1 | orgs2)
            overlap_ratio = overlap / union if union > 0 else 0
            
            # Collect ALL pairs with any org context overlap
            # No threshold filtering - let holistic scoring decide
            if overlap_ratio > 0:  # Any overlap at all
                shared_docs = len(name_contexts[name1] & name_contexts[name2])
                
                # Collect candidate with context-specific data
                # Final holistic score calculated after all analyses complete
                candidates.append({
                    'name1': name1,
                    'name2': name2,
                    'score': overlap_ratio,  # Method-specific score only
                    'shared': shared_docs,
                    'network_overlap_score': overlap_ratio,
                    'method': 'org_context'
                })
    
    log(f"  ✓ Found {len(candidates):,} context clustering candidates")
    
    insert_candidates_to_queue(conn, candidates, canonical_lookup, verbose)


def analyze_temporal_windows(
    conn,
    name_contexts: Dict[str, Set[str]],
    name_frequencies: Dict[str, int],
    verbose: bool = False
):
    """Analyze temporal overlap between name mentions.

    Determines whether two name variants appear in overlapping time
    periods. Names appearing in non-overlapping time periods are more
    likely to refer to different people.

    Args:
        conn: Active psycopg database connection.
        name_contexts: Dict mapping names to sets of document IDs.
        name_frequencies: Dict mapping names to mention counts.
        verbose: If True, prints progress during analysis. Defaults to False.
    """
    log("\n📅 Analyzing temporal windows...")
    
    # Get document dates for each name
    name_dates = {}
    
    log("  Loading document dates from database...")
    with conn.cursor() as cur:
        # Get dates for documents where each name appears
        cur.execute("""
            SELECT en.name_string, ed.date_datetime
            FROM extracted_names en
            JOIN extracted_dates ed ON en.file_path = ed.file_path
            WHERE ed.date_datetime IS NOT NULL
        """)
        
        for name, date in cur:
            if name not in name_dates:
                name_dates[name] = []
            name_dates[name].append(date)
    
    log(f"  ✓ Loaded dates for {len(name_dates):,} names")
    
    # Calculate temporal ranges for each name
    name_temporal_ranges = {}
    for name, dates in name_dates.items():
        if dates:
            min_date = min(dates)
            max_date = max(dates)
            name_temporal_ranges[name] = (min_date, max_date)
    
    log(f"  ✓ Calculated temporal ranges for {len(name_temporal_ranges):,} names")
    
    # Analyze candidate pairs for temporal overlap
    # This updates existing candidates in the queue rather than creating new ones
    with conn.cursor() as cur:
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2
            FROM name_disambiguation_queue
            WHERE status = 'pending'
        """)
        
        pending_candidates = cur.fetchall()
        total_candidates = len(pending_candidates)
        progress_interval = max(1, total_candidates // 10)
        
        log(f"  Analyzing temporal overlap for {total_candidates:,} pending candidates...")
        
        update_count = 0
        for idx, (queue_id, name1, name2) in enumerate(pending_candidates):
            if (idx + 1) % progress_interval == 0:
                pct = ((idx + 1) / total_candidates) * 100
                log(f"    Analyzing: {idx + 1:,}/{total_candidates:,} ({pct:.0f}%)")
            
            if name1 in name_temporal_ranges and name2 in name_temporal_ranges:
                range1 = name_temporal_ranges[name1]
                range2 = name_temporal_ranges[name2]
                
                # Check for temporal overlap
                overlap = not (range1[1] < range2[0] or range2[1] < range1[0])
                
                # Calculate gap if no overlap
                if not overlap:
                    gap_years = abs((range1[0] - range2[1]).days / 365.25)
                    overlap = gap_years <= TEMPORAL_WINDOW_YEARS
                
                # Update queue entry
                cur.execute("""
                    UPDATE name_disambiguation_queue
                    SET temporal_overlap = %s
                    WHERE queue_id = %s
                """, (overlap, queue_id))
                update_count += 1
        
        conn.commit()
        
        log(f"  ✓ Updated temporal overlap for {update_count:,} candidates")


def analyze_network_disambiguation(
    conn,
    name_contexts: Dict[str, Set[str]],
    name_frequencies: Dict[str, int],
    verbose: bool = False
):
    """Use network co-occurrence patterns to disambiguate names.

    Calculates the overlap in co-occurrence patterns between name variants.
    If two mentions of 'John Smith' have zero overlapping co-occurrences
    with other people, they're likely different individuals.

    Args:
        conn: Active psycopg database connection.
        name_contexts: Dict mapping names to sets of document IDs.
        name_frequencies: Dict mapping names to mention counts.
        verbose: If True, prints progress during analysis. Defaults to False.
    """
    log("\n🕸️  Analyzing network-based disambiguation...")
    
    # Get co-occurrence data for each name
    name_cooccurrences = {}
    total_names = len(name_contexts)
    progress_interval = max(1, total_names // 10)
    processed = 0
    
    log(f"  Calculating co-occurrences for {total_names:,} names...")
    for name in name_contexts:
        processed += 1
        if processed % progress_interval == 0:
            pct = (processed / total_names) * 100
            log(f"    Calculating: {processed:,}/{total_names:,} ({pct:.0f}%)")
        
        # Find which other names appear in same documents
        name_docs = name_contexts[name]
        cooccurring_names = set()
        
        for other_name, other_docs in name_contexts.items():
            if other_name == name:
                continue
            if name_docs & other_docs:  # Shared documents
                cooccurring_names.add(other_name)
        
        name_cooccurrences[name] = cooccurring_names
    
    log(f"  ✓ Calculated co-occurrences for {len(name_cooccurrences):,} names")
    
    # Update disambiguation queue with network overlap scores
    with conn.cursor() as cur:
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2
            FROM name_disambiguation_queue
            WHERE status = 'pending'
        """)
        
        pending_candidates = cur.fetchall()
        total_candidates = len(pending_candidates)
        progress_interval = max(1, total_candidates // 10)
        
        log(f"  Analyzing network overlap for {total_candidates:,} candidates...")
        
        update_count = 0
        for idx, (queue_id, name1, name2) in enumerate(pending_candidates):
            if (idx + 1) % progress_interval == 0:
                pct = ((idx + 1) / total_candidates) * 100
                log(f"    Analyzing: {idx + 1:,}/{total_candidates:,} ({pct:.0f}%)")
            
            if name1 in name_cooccurrences and name2 in name_cooccurrences:
                cooc1 = name_cooccurrences[name1]
                cooc2 = name_cooccurrences[name2]
                
                if cooc1 and cooc2:
                    overlap = len(cooc1 & cooc2)
                    union = len(cooc1 | cooc2)
                    overlap_ratio = overlap / union if union > 0 else 0.0
                    
                    cur.execute("""
                        UPDATE name_disambiguation_queue
                        SET network_overlap_score = %s
                        WHERE queue_id = %s
                    """, (overlap_ratio, queue_id))
                    update_count += 1
        
        conn.commit()
        
        log(f"  ✓ Updated network overlap for {update_count:,} candidates")


def prioritize_queue_by_frequency(
    conn,
    name_frequencies: Dict[str, int],
    verbose: bool = False
):
    """Calculate priority scores for disambiguation queue based on frequency.

    Assigns priority scores to pending candidates so high-frequency names
    are reviewed first. Merging high-frequency aliases has greater impact
    on the overall analysis.

    Args:
        conn: Active psycopg database connection.
        name_frequencies: Dict mapping names to mention counts.
        verbose: If True, prints progress and distribution. Defaults to False.
    """
    if verbose:
        log("\n📊 Calculating priority scores based on frequency...")
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2, similarity_score
            FROM name_disambiguation_queue
            WHERE status = 'pending'
        """)
        
        candidates = cur.fetchall()
        
        if verbose:
            log(f"  Calculating priorities for {len(candidates):,} candidates...")
        
        update_count = 0
        for queue_id, name1, name2, sim_score in candidates:
            freq1 = name_frequencies.get(name1, 0)
            freq2 = name_frequencies.get(name2, 0)
            
            # Priority score combines frequency and similarity
            # Higher frequency = higher impact if merged
            max_freq = max(freq1, freq2)
            
            # Assign frequency tier
            if max_freq >= HIGH_FREQUENCY_THRESHOLD:
                freq_multiplier = 3.0
                tier = 'HIGH'
            elif max_freq >= MEDIUM_FREQUENCY_THRESHOLD:
                freq_multiplier = 2.0
                tier = 'MEDIUM'
            else:
                freq_multiplier = 1.0
                tier = 'LOW'
            
            priority_score = sim_score * freq_multiplier
            
            cur.execute("""
                UPDATE name_disambiguation_queue
                SET priority_score = %s
                WHERE queue_id = %s
            """, (priority_score, queue_id))
            update_count += 1
        
        conn.commit()
        
        if verbose:
            log(f"  ✓ Updated priority scores for {update_count:,} candidates")
            
            # Show distribution
            cur.execute("""
                SELECT 
                    CASE 
                        WHEN priority_score >= 2.5 THEN 'HIGH'
                        WHEN priority_score >= 1.2 THEN 'MEDIUM'
                        ELSE 'LOW'
                    END as priority_tier,
                    COUNT(*)
                FROM name_disambiguation_queue
                WHERE status = 'pending'
                GROUP BY priority_tier
                ORDER BY priority_tier
            """)
            
            log("\n  Priority distribution:")
            for tier, count in cur:
                log(f"    {tier}: {count:,}")


def rescore_queue_entries(
    conn,
    name_contexts: Dict[str, Set[str]],
    name_frequencies: Dict[str, int],
    verbose: bool = False
):
    """Calculate holistic confidence scores for all pending queue entries.

    This is the FINAL scoring pass that combines ALL signals gathered
    from different analysis methods (phonetic, initials, context, temporal,
    network) into a single holistic confidence score.

    Should be run AFTER all analysis methods have populated their
    respective score fields in the queue.

    Args:
        conn: Active psycopg database connection.
        name_contexts: Dict mapping names to sets of document IDs.
        name_frequencies: Dict mapping names to mention counts.
        verbose: If True, prints progress during rescoring. Defaults to False.
    """
    log("\n🔄 Calculating holistic confidence scores...")
    
    with conn.cursor() as cur:
        # Retrieve ALL available signals for holistic scoring
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2, shared_contexts,
                   phonetic_score, initials_score, temporal_overlap, network_overlap_score
            FROM name_disambiguation_queue
            WHERE status = 'pending'
        """)
        
        candidates = cur.fetchall()
        
        if verbose:
            log(f"  Scoring {len(candidates):,} candidates holistically...")
        
        update_count = 0
        progress_interval = max(1, len(candidates) // 10)
        
        for idx, (queue_id, name1, name2, shared, phon_score, init_score, 
                  temp_overlap, net_overlap) in enumerate(candidates):
            
            if verbose and (idx + 1) % progress_interval == 0:
                pct = ((idx + 1) / len(candidates)) * 100
                log(f"    Scoring: {idx + 1:,}/{len(candidates):,} ({pct:.0f}%)")
            
            # Use stored scores from analysis phases, default to 0 if not analyzed
            phonetic = phon_score if phon_score is not None else 0.0
            initials = init_score if init_score is not None else 0.0
            temp_overlap = temp_overlap if temp_overlap is not None else True
            net_overlap = net_overlap if net_overlap is not None else 0.0
            shared = shared if shared is not None else 0
            
            # Calculate edit distance score
            n1 = normalize_name(name1, aggressive=True).lower()
            n2 = normalize_name(name2, aggressive=True).lower()
            lev_dist = levenshtein_distance(n1, n2)
            max_len = max(len(n1), len(n2))
            edit_score = 1.0 - (lev_dist / max_len) if max_len > 0 else 0.0
            
            # Holistic scoring with proper weights
            # Each signal contributes based on whether it was actually measured
            weights = {
                'edit_distance': 0.25,
                'phonetic': 0.20 if phonetic > 0 else 0.0,
                'initials': 0.15 if initials > 0 else 0.0,
                'context': 0.20,
                'temporal': 0.10 if temp_overlap is not None else 0.0,
                'network': 0.10 if net_overlap > 0 else 0.0,
            }
            
            scores = {
                'edit_distance': edit_score,
                'phonetic': phonetic,
                'initials': initials,
                'context': min(shared / 10.0, 1.0),
                'temporal': 1.0 if temp_overlap else 0.3,  # Penalize but don't zero out
                'network': min(net_overlap, 1.0),
            }
            
            # Normalize weights to sum to 1.0
            total_weight = sum(weights.values())
            if total_weight > 0:
                holistic_score = sum(scores[k] * weights[k] for k in scores) / total_weight
            else:
                holistic_score = edit_score  # Fallback to edit distance only
            
            # Determine confidence level based on holistic score
            if holistic_score >= HIGH_CONFIDENCE_THRESHOLD:
                confidence = 'HIGH'
            elif holistic_score >= MEDIUM_CONFIDENCE_THRESHOLD:
                confidence = 'MEDIUM'
            else:
                confidence = 'LOW'
            
            # Store component breakdown for transparency
            components = {
                'edit_distance': edit_score,
                'phonetic': phonetic,
                'initials': initials,
                'context': scores['context'],
                'temporal': scores['temporal'],
                'network': net_overlap,
                'weights': weights,
                'holistic_score': holistic_score
            }
            
            # Update with holistic scores
            cur.execute("""
                UPDATE name_disambiguation_queue
                SET 
                    similarity_score = %s,
                    confidence_level = %s,
                    confidence_components = %s
                WHERE queue_id = %s
            """, (holistic_score, confidence, psycopg.types.json.Json(components), queue_id))
            update_count += 1
        
        conn.commit()
        
        # Show distribution
        cur.execute("""
            SELECT confidence_level, COUNT(*) 
            FROM name_disambiguation_queue 
            WHERE status = 'pending'
            GROUP BY confidence_level
        """)
        dist = dict(cur.fetchall())
        
        log(f"  ✓ Scored {update_count:,} candidates")
        log(f"    • HIGH confidence: {dist.get('HIGH', 0):,}")
        log(f"    • MEDIUM confidence: {dist.get('MEDIUM', 0):,}")
        log(f"    • LOW confidence: {dist.get('LOW', 0):,}")


def apply_auto_exclusions(conn, verbose: bool = False):
    """Apply auto-exclusion rules to identify obvious non-person entities.

    Scans all extracted names against predefined regex patterns that
    identify non-person entities (page numbers, dates, document IDs, etc.)
    and logs them to the exclusions tables.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints progress and exclusion breakdown.
            Defaults to False.
    """
    if verbose:
        log("\n🚫 Applying auto-exclusion rules...")
    
    with conn.cursor() as cur:
        # Get all unique names
        cur.execute("SELECT DISTINCT name_string FROM extracted_names")
        all_names = [row[0] for row in cur.fetchall()]
        
        if verbose:
            log(f"  Checking {len(all_names):,} unique names against exclusion patterns...")
        
        excluded_count = 0
        for name in all_names:
            result = should_auto_exclude(name)
            if result:
                reason_code, description = result
                
                try:
                    # Add to exclusions
                    cur.execute("""
                        INSERT INTO entity_exclusions (entity_name, exclusion_reason, notes)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (entity_name) DO NOTHING
                    """, (name, reason_code, description))
                    
                    # Log the exclusion
                    cur.execute("""
                        INSERT INTO auto_exclusions_log 
                        (entity_name, exclusion_pattern, exclusion_reason)
                        VALUES (%s, %s, %s)
                    """, (name, reason_code, description))
                    
                    excluded_count += 1
                except Exception as e:
                    if verbose:
                        log(f"  Warning: Could not exclude {name}: {e}")
        
        conn.commit()
        
        if verbose:
            log(f"  ✓ Auto-excluded {excluded_count:,} entities")
            
            # Show breakdown
            cur.execute("""
                SELECT exclusion_pattern, COUNT(*)
                FROM auto_exclusions_log
                GROUP BY exclusion_pattern
                ORDER BY COUNT(*) DESC
            """)
            
            log("\n  Exclusion breakdown:")
            for pattern, count in cur:
                log(f"    {pattern}: {count:,}")


def build_canonical_lookup(conn, verbose: bool = False) -> Dict[str, str]:
    """Build reverse lookup mapping alias names to canonical names.

    Loads all reviewed aliases from the entity_aliases table to create
    a dictionary for normalizing name variants to their canonical forms.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints count of loaded mappings. Defaults to False.

    Returns:
        Dict mapping lowercase alias names to their canonical name strings.
    """
    canonical_lookup = {}

    with conn.cursor() as cur:
        cur.execute("""
            SELECT canonical_name, alias_name
            FROM entity_aliases
            WHERE reviewed = TRUE
        """)

        for canonical, alias in cur:
            # Map alias to its canonical form
            canonical_lookup[alias.lower()] = canonical
            # Also map canonical to itself (for consistency)
            canonical_lookup[canonical.lower()] = canonical

    if verbose:
        log(f"  Loaded {len(canonical_lookup):,} canonical mappings from database")

    return canonical_lookup


# Email and signature artifact suffixes to strip before canonical lookup.
# These are runtime defaults; the database table name_normalization_rules
# is the authoritative source once initialized.
ARTIFACT_SUFFIXES = [
    'mailto', 'sent', 'cc', 'to', 'from', 'subject', 're', 'fwd',
    'partner', 'counsel', 'associate', 'paralegal',
    'date', 'document', 'defendant', 'documents',
]


def strip_artifact_suffixes(name: str) -> str:
    """Strip email and signature artifact suffixes from a name.

    Removes common suffixes that appear in email headers and signature
    blocks (e.g., 'mailto', 'sent', 'cc', 'partner') to improve
    canonical lookup accuracy.

    Args:
        name: The name string to clean.

    Returns:
        The name with artifact suffixes removed and whitespace trimmed.
    """
    stripped = name.strip()
    lower = stripped.lower()

    for suffix in ARTIFACT_SUFFIXES:
        if lower.endswith(' ' + suffix):
            stripped = stripped[:-len(suffix) - 1].strip()
            lower = stripped.lower()

    return stripped


def normalize_candidate_pair(
    name1: str,
    name2: str,
    canonical_lookup: Dict[str, str]
) -> Optional[Tuple[str, str]]:
    """Normalize a candidate pair to ensure ONLY canonical names are first.

    Orders the names so that known canonical names appear as name_variant_1.
    If neither name is a known canonical, returns None - the pair cannot
    be queued until one of the names has been reviewed and established
    as canonical.

    Priority order:
        1. Strip artifact suffixes, then check canonical_lookup
        2. If either name maps to canonical, use that as name_variant_1
        3. If both are canonical, use alphabetical order
        4. If neither is canonical, return None (pair cannot be queued)

    Args:
        name1: First name in the candidate pair.
        name2: Second name in the candidate pair.
        canonical_lookup: Dict mapping aliases to canonical names.

    Returns:
        A tuple of (canonical_name, variant_name) if at least one name
        is a known canonical, or None if neither is canonical.
    """
    # Strip artifact suffixes for lookup
    name1_clean = strip_artifact_suffixes(name1)
    name2_clean = strip_artifact_suffixes(name2)

    name1_lower = name1_clean.lower()
    name2_lower = name2_clean.lower()

    # Check if either is already known (using cleaned names)
    name1_canonical = canonical_lookup.get(name1_lower)
    name2_canonical = canonical_lookup.get(name2_lower)

    # If name1 is canonical (or maps to canonical), it goes first
    if name1_canonical and not name2_canonical:
        return (name1_canonical, name2)

    # If name2 is canonical (or maps to canonical), it goes first
    if name2_canonical and not name1_canonical:
        return (name2_canonical, name1)

    # If both are canonical, use alphabetical order for consistency
    if name1_canonical and name2_canonical:
        if name1_canonical < name2_canonical:
            return (name1_canonical, name2)
        else:
            return (name2_canonical, name1)

    # Neither is canonical - cannot queue without a canonical anchor
    # These pairs need one name to be established as canonical first
    return None


def find_best_canonical_match(
    name: str,
    canonical_names: Set[str],
    cache: Dict[str, Tuple[str, float]] = None
) -> Tuple[str, float]:
    """Find the best matching canonical name for an unknown name.

    Searches through all known canonical names to find the closest match
    based on normalized edit distance. Uses caching to avoid recomputation.
    Always returns the best match regardless of score.

    Args:
        name: The unknown name to match.
        canonical_names: Set of known canonical names.
        cache: Optional dict to cache results for repeated lookups.

    Returns:
        Tuple of (canonical_name, similarity_score). Always returns the
        best match found, even if the score is low.
    """
    if not canonical_names:
        # Fallback: return the name itself with zero confidence
        return (name, 0.0)

    name_normalized = normalize_name(name, aggressive=True).lower()

    # Check cache first
    if cache is not None and name_normalized in cache:
        return cache[name_normalized]

    best_match = None
    best_score = 0.0

    for canonical in canonical_names:
        canonical_normalized = normalize_name(canonical, aggressive=True).lower()

        max_len = max(len(name_normalized), len(canonical_normalized))
        if max_len == 0:
            continue

        edit_dist = levenshtein_distance(name_normalized, canonical_normalized)
        similarity = 1.0 - (edit_dist / max_len)

        if similarity > best_score:
            best_score = similarity
            best_match = canonical
            # Early exit if we find a very high match
            if best_score >= 0.95:
                break

    # Always return something - use first canonical as fallback
    if best_match is None:
        best_match = next(iter(canonical_names))
        best_score = 0.0

    result = (best_match, best_score)

    # Cache the result
    if cache is not None:
        cache[name_normalized] = result

    return result


def normalize_candidate_pair_with_fallback(
    name1: str,
    name2: str,
    canonical_lookup: Dict[str, str],
    canonical_names: Set[str],
    fuzzy_cache: Dict[str, Optional[Tuple[str, float]]] = None
) -> Optional[Tuple[str, str, float, bool]]:
    """Normalize a candidate pair, always anchoring to a canonical name.

    First checks if either name is already a known canonical/alias.
    If not, searches for the best matching canonical name.

    Args:
        name1: First name in the candidate pair.
        name2: Second name in the candidate pair.
        canonical_lookup: Dict mapping aliases to canonical names.
        canonical_names: Set of all known canonical names.
        fuzzy_cache: Optional cache for fuzzy match results.

    Returns:
        Tuple of (canonical_name, variant_name, confidence_adjustment, is_direct_match)
        or None if no suitable canonical anchor can be found.

        - confidence_adjustment: 1.0 for direct matches, lower for fuzzy matches
        - is_direct_match: True if one of the names was directly canonical
    """
    # Strip artifact suffixes for lookup
    name1_clean = strip_artifact_suffixes(name1)
    name2_clean = strip_artifact_suffixes(name2)

    name1_lower = name1_clean.lower()
    name2_lower = name2_clean.lower()

    # Check if either is already known (using cleaned names)
    name1_canonical = canonical_lookup.get(name1_lower)
    name2_canonical = canonical_lookup.get(name2_lower)

    # If name1 is canonical (or maps to canonical), it goes first
    if name1_canonical and not name2_canonical:
        return (name1_canonical, name2, 1.0, True)

    # If name2 is canonical (or maps to canonical), it goes first
    if name2_canonical and not name1_canonical:
        return (name2_canonical, name1, 1.0, True)

    # If both are canonical, use alphabetical order for consistency
    if name1_canonical and name2_canonical:
        if name1_canonical < name2_canonical:
            return (name1_canonical, name2, 1.0, True)
        else:
            return (name2_canonical, name1, 1.0, True)

    # Neither is canonical - find best matching canonical for each
    # Always returns a match (never None)
    match1 = find_best_canonical_match(name1_clean, canonical_names, cache=fuzzy_cache)
    match2 = find_best_canonical_match(name2_clean, canonical_names, cache=fuzzy_cache)

    # Use the better match as the canonical anchor
    if match1[1] >= match2[1]:
        # name1 has better match - use its canonical, name2 as variant
        return (match1[0], name2, match1[1], False)
    else:
        # name2 has better match - use its canonical, name1 as variant
        return (match2[0], name1, match2[1], False)


def insert_candidates_to_queue(
    conn,
    candidates: List[Dict],
    canonical_lookup: Dict[str, str] = None,
    verbose: bool = False
):
    """Insert candidate pairs into the disambiguation queue.

    Always anchors name_variant_1 to a known canonical name. If neither
    name in a pair is directly canonical, finds the best matching
    canonical and adjusts confidence accordingly.

    Args:
        conn: Active psycopg database connection.
        candidates: List of candidate dicts with keys: name1, name2, score,
            shared, and optional phonetic_score, initials_score, etc.
        canonical_lookup: Dict mapping aliases to canonical names. If None,
            will be built from the database.
        verbose: If True, prints insertion progress. Defaults to False.
    """
    if not candidates:
        if verbose:
            log("  ⚠️  No candidates to insert")
        return

    if verbose:
        log(f"\n  Processing {len(candidates):,} candidates...")

    # Build canonical lookup if not provided
    if canonical_lookup is None:
        canonical_lookup = build_canonical_lookup(conn, verbose=False)

    # Get set of all canonical names for fuzzy matching
    canonical_names = set(canonical_lookup.values())

    # Cache for fuzzy match results to avoid recomputation
    fuzzy_cache: Dict[str, Tuple[str, float]] = {}

    total_candidates = len(candidates)
    progress_interval = max(1, total_candidates // 20)  # Update ~20 times

    with conn.cursor() as cur:
        insert_count = 0
        direct_matched = 0
        fuzzy_matched = 0

        for idx, candidate in enumerate(candidates):
            # Progress feedback (flush to ensure immediate display)
            if verbose and idx % progress_interval == 0:
                pct = (idx / total_candidates) * 100
                log(f"    Processing: {idx:,}/{total_candidates:,} ({pct:.0f}%) "
                    f"[cache: {len(fuzzy_cache):,}]")

            try:
                # Anchor to canonical - always returns a result (never None)
                result = normalize_candidate_pair_with_fallback(
                    candidate['name1'],
                    candidate['name2'],
                    canonical_lookup,
                    canonical_names,
                    fuzzy_cache
                )

                name1, name2, confidence_adj, is_direct = result

                if is_direct:
                    direct_matched += 1
                else:
                    fuzzy_matched += 1

                # Store the method-specific score (NOT a holistic score yet)
                # Holistic scoring happens in rescore_queue_entries after all analyses
                method_score = candidate['score']
                adjusted_score = method_score * confidence_adj

                # Don't assign confidence level yet - that happens in holistic rescoring
                # For now, mark as 'LOW' as placeholder (will be recalculated)
                confidence = 'LOW'

                # Prepare optional fields - these accumulate across methods
                phonetic_score = candidate.get('phonetic_score')
                initials_score = candidate.get('initials_score')
                network_overlap = candidate.get('network_overlap_score')
                
                # Track which method found this candidate
                components = {
                    'discovery_method': candidate.get('method', 'unknown'),
                    'canonical_match_type': 'direct' if is_direct else 'fuzzy',
                    'canonical_confidence': confidence_adj
                }

                cur.execute("""
                    INSERT INTO name_disambiguation_queue
                    (name_variant_1, name_variant_2, similarity_score, confidence_level,
                     shared_contexts, phonetic_score, initials_score, network_overlap_score,
                     confidence_components)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name_variant_1, name_variant_2) DO UPDATE SET
                        shared_contexts = GREATEST(name_disambiguation_queue.shared_contexts, EXCLUDED.shared_contexts),
                        phonetic_score = COALESCE(EXCLUDED.phonetic_score, name_disambiguation_queue.phonetic_score),
                        initials_score = COALESCE(EXCLUDED.initials_score, name_disambiguation_queue.initials_score),
                        network_overlap_score = COALESCE(EXCLUDED.network_overlap_score, name_disambiguation_queue.network_overlap_score)
                """, (
                    name1, name2, adjusted_score, confidence,
                    candidate['shared'], phonetic_score, initials_score, network_overlap,
                    psycopg.types.json.Json(components)
                ))
                insert_count += 1
            except Exception as e:
                if verbose:
                    log(f"  Warning: Could not insert candidate: {e}")

        conn.commit()
        if verbose:
            direct_count = insert_count - fuzzy_matched
            log(f"  ✓ Inserted {insert_count:,} candidates")
            log(f"    • {direct_count:,} direct canonical matches")
            log(f"    • {fuzzy_matched:,} fuzzy matched to canonical")


def show_enhanced_statistics(conn, verbose: bool = False):
    """Display comprehensive entity disambiguation statistics.

    Shows counts of names, aliases, exclusions, queue status, confidence
    distributions, and normalization rules. In verbose mode, includes
    additional breakdowns and sample data.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, shows additional details and samples.
            Defaults to False.
    """
    log("\n" + "=" * 80)
    log("ENHANCED ENTITY DISAMBIGUATION STATISTICS")
    log("=" * 80)
    
    with conn.cursor() as cur:
        # Basic stats
        cur.execute("SELECT COUNT(DISTINCT name_string) FROM extracted_names")
        total_names = cur.fetchone()[0]
        log(f"\n📊 Total unique names: {total_names:,}")
        
        cur.execute("SELECT COUNT(*) FROM entity_aliases")
        alias_count = cur.fetchone()[0]
        log(f"📋 Defined aliases: {alias_count:,}")
        
        # Verbose: show top canonical entities by alias count
        if verbose:
            cur.execute("""
                SELECT canonical_name, COUNT(*) as alias_count
                FROM entity_aliases
                GROUP BY canonical_name
                ORDER BY alias_count DESC
                LIMIT 10
            """)
            log("\n  Top entities by alias count:")
            for name, count in cur.fetchall():
                log(f"    • {name}: {count} aliases")
        
        cur.execute("SELECT COUNT(*) FROM entity_exclusions")
        exclusion_count = cur.fetchone()[0]
        log(f"🚫 Excluded entities: {exclusion_count:,}")
        
        # Verbose: show exclusions by reason
        if verbose:
            cur.execute("""
                SELECT exclusion_reason, COUNT(*) 
                FROM entity_exclusions 
                GROUP BY exclusion_reason 
                ORDER BY COUNT(*) DESC
            """)
            log("\n  Exclusions by reason:")
            for reason, count in cur.fetchall():
                log(f"    • {reason}: {count}")
        
        # Queue stats with enhanced fields
        cur.execute("""
            SELECT COUNT(*)
            FROM name_disambiguation_queue
            WHERE status = 'pending'
        """)
        pending = cur.fetchone()[0]
        log(f"\n📋 Pending in queue: {pending:,}")
        
        # Confidence distribution
        cur.execute("""
            SELECT confidence_level, COUNT(*)
            FROM name_disambiguation_queue
            WHERE status = 'pending'
            GROUP BY confidence_level
            ORDER BY 
                CASE confidence_level
                    WHEN 'HIGH' THEN 1
                    WHEN 'MEDIUM' THEN 2
                    WHEN 'LOW' THEN 3
                END
        """)
        log("\n  Confidence levels:")
        for level, count in cur:
            emoji = "⚡" if level == "HIGH" else "📊" if level == "MEDIUM" else "⚠️"
            log(f"    {emoji} {level}: {count:,}")
        
        # Verbose: show top pending queue entries
        if verbose and pending > 0:
            cur.execute("""
                SELECT name_variant_1, name_variant_2, similarity_score, confidence_level
                FROM name_disambiguation_queue
                WHERE status = 'pending'
                ORDER BY similarity_score DESC
                LIMIT 5
            """)
            log("\n  Top pending candidates:")
            for n1, n2, score, conf in cur.fetchall():
                log(f"    • {n1} ↔ {n2} ({score:.3f}, {conf})")
        
        # Priority distribution (if calculated)
        cur.execute("""
            SELECT COUNT(*)
            FROM name_disambiguation_queue
            WHERE priority_score IS NOT NULL
        """)
        prioritized = cur.fetchone()[0]
        if prioritized > 0:
            log(f"\n  Prioritized candidates: {prioritized:,}")
        
        # Phonetic matching stats (if available)
        if PHONETIC_AVAILABLE:
            cur.execute("""
                SELECT COUNT(*)
                FROM name_disambiguation_queue
                WHERE phonetic_score IS NOT NULL AND phonetic_score > 0.5
            """)
            phonetic_matches = cur.fetchone()[0]
            log(f"\n🔊 Strong phonetic matches: {phonetic_matches:,}")
        
        # Initials matching stats
        cur.execute("""
            SELECT COUNT(*)
            FROM name_disambiguation_queue
            WHERE initials_score IS NOT NULL AND initials_score > 0.5
        """)
        initials_matches = cur.fetchone()[0]
        log(f"🔤 Strong initials matches: {initials_matches:,}")
        
        # Network overlap stats
        cur.execute("""
            SELECT COUNT(*)
            FROM name_disambiguation_queue
            WHERE network_overlap_score IS NOT NULL AND network_overlap_score < 0.1
        """)
        low_overlap = cur.fetchone()[0]
        if low_overlap > 0:
            log(f"⚠️  Low network overlap (likely different people): {low_overlap:,}")
        
        # Normalization rules stats
        cur.execute("""
            SELECT rule_type, COUNT(*), SUM(CASE WHEN enabled THEN 1 ELSE 0 END)
            FROM name_normalization_rules
            GROUP BY rule_type
            ORDER BY rule_type
        """)
        rules = cur.fetchall()
        if rules:
            log(f"\n📏 Normalization rules:")
            for rule_type, total, enabled in rules:
                log(f"    {rule_type}: {enabled:,} enabled / {total:,} total")
        
        # Verbose: show sample rules for each type
        if verbose and rules:
            for rule_type, _, _ in rules:
                cur.execute("""
                    SELECT pattern, replacement 
                    FROM name_normalization_rules 
                    WHERE rule_type = %s AND enabled = TRUE
                    LIMIT 5
                """, (rule_type,))
                samples = cur.fetchall()
                if samples:
                    log(f"\n      Sample {rule_type} rules:")
                    for pattern, replacement in samples:
                        if replacement:
                            log(f"        '{pattern}' → '{replacement}'")
                        else:
                            log(f"        '{pattern}'")


def create_canonicalization_function(conn, verbose: bool = False):
    """Create PostgreSQL function to canonicalize names using entity_aliases.

    Dynamically reads artifact suffixes from the name_normalization_rules
    table to build the canonicalization regex, allowing rules to grow
    without code changes.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints progress messages. Defaults to False.
    """
    if verbose:
        log("\nCreating name canonicalization function...")
    
    # Check if name_normalization_rules table exists
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'name_normalization_rules'
            )
        """)
        has_rules_table = cur.fetchone()[0]
    
    # Build suffix patterns from database if table exists, otherwise use defaults
    suffixes = None
    if has_rules_table:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pattern FROM name_normalization_rules 
                WHERE rule_type = 'artifact_suffix' AND enabled = TRUE
            """)
            suffixes = [row[0] for row in cur.fetchall()]
        
        if suffixes:
            # Build case-insensitive regex pattern from database
            suffix_pattern = '|'.join(re.escape(s) for s in suffixes)
            if verbose:
                log(f"  Loaded {len(suffixes)} artifact suffixes from database")
        else:
            suffix_pattern = 'Sent|Cc|To|From|Subject|Re|Fwd|Partner|Counsel|Associate|Date|DOCUMENT|Document|Defendant|Documents|mailto'
            if verbose:
                log("  Using default artifact suffixes (no rules in database)")
    else:
        suffix_pattern = 'Sent|Cc|To|From|Subject|Re|Fwd|Partner|Counsel|Associate|Date|DOCUMENT|Document|Defendant|Documents|mailto'
        if verbose:
            log("  Using default artifact suffixes (name_normalization_rules table not found)")
    
    with conn.cursor() as cur:
        # Create a function that looks up canonical names and strips possessives
        # The suffix_pattern is dynamically built from name_normalization_rules table
        cur.execute(f"""
            CREATE OR REPLACE FUNCTION get_canonical_name(input_name TEXT)
            RETURNS TEXT AS $$
            DECLARE
                canonical TEXT;
                normalized_input TEXT;
            BEGIN
                normalized_input := input_name;
                
                -- Strip artifact suffixes (from name_normalization_rules table)
                IF normalized_input ~* ' ({suffix_pattern})$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, ' ({suffix_pattern})$', '', 'i');
                END IF;
                
                -- Strip possessive suffixes ('s, s', 's, s')
                IF normalized_input ~ '['']s$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, '['']s$', '');
                ELSIF normalized_input ~ 's['']$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, 's['']$', 's');
                ELSIF normalized_input ~ '['']$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, '['']$', '');
                END IF;
                
                -- Check if this name appears as an alias
                SELECT canonical_name INTO canonical
                FROM entity_aliases
                WHERE LOWER(alias_name) = LOWER(normalized_input)
                LIMIT 1;
                
                IF canonical IS NOT NULL THEN
                    RETURN canonical;
                END IF;
                
                -- Check if this name IS a canonical name
                SELECT canonical_name INTO canonical
                FROM entity_aliases
                WHERE LOWER(canonical_name) = LOWER(normalized_input)
                LIMIT 1;
                
                IF canonical IS NOT NULL THEN
                    RETURN canonical;
                END IF;
                
                -- Return normalized name
                RETURN normalized_input;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
        """)
        
        # Create indexes for fast lookups
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_aliases_alias_lower 
            ON entity_aliases(LOWER(alias_name));
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_aliases_canonical_lower 
            ON entity_aliases(LOWER(canonical_name));
        """)
        
        conn.commit()
        if verbose:
            log("✓ Created get_canonical_name() function")
            log(f"  • Strips {len(suffixes) if suffixes else 'default'} artifact suffixes from database")
            log("  • Strips possessive forms ('s, s')")
            log("  • Add new rules: INSERT INTO name_normalization_rules ...")


def update_views_for_canonicalization(conn, verbose: bool = False):
    """Update database views to use canonical names.

    Creates views that apply name canonicalization for accurate
    co-occurrence analysis. Handles joint name splitting and
    entity exclusions.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, prints progress messages. Defaults to False.
    """
    if verbose:
        log("\nUpdating views to use canonical names...")
    
    with conn.cursor() as cur:
        # Create a clean entity counts view that filters exclusions and splits joint names
        cur.execute("""
            CREATE OR REPLACE VIEW v_entity_mentions AS
            WITH base_names AS (
                -- Regular names (not joint names)
                SELECT 
                    get_canonical_name(name_string) AS entity_name,
                    occurrence_count,
                    file_path
                FROM extracted_names
                WHERE name_string IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM joint_name_mappings jnm 
                    WHERE jnm.joint_name = name_string
                )
                
                UNION ALL
                
                -- Split joint names into their component parts
                SELECT 
                    jnm.component_name AS entity_name,
                    en.occurrence_count,
                    en.file_path
                FROM extracted_names en
                INNER JOIN joint_name_mappings jnm 
                    ON en.name_string = jnm.joint_name
                WHERE en.name_string IS NOT NULL
            ),
            canonical_counts AS (
                SELECT 
                    get_canonical_name(entity_name) AS entity_name,
                    SUM(occurrence_count) AS total_mentions,
                    COUNT(DISTINCT file_path) AS document_count
                FROM base_names
                GROUP BY get_canonical_name(entity_name)
            )
            SELECT 
                cc.entity_name,
                cc.total_mentions,
                cc.document_count
            FROM canonical_counts cc
            -- Exclude entities in the exclusions table
            WHERE NOT EXISTS (
                SELECT 1 FROM entity_exclusions ee 
                WHERE ee.entity_name = cc.entity_name
            )
            ORDER BY cc.total_mentions DESC;
        """)
        
        if verbose:
            log("✓ Created v_entity_mentions view")
        
        # Update person co-occurrence view
        cur.execute("""
            CREATE OR REPLACE VIEW v_person_cooccurrence AS
            WITH base_names AS (
                SELECT 
                    file_path,
                    get_canonical_name(name_string) AS canonical_name
                FROM extracted_names
                WHERE name_string IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM joint_name_mappings jnm 
                    WHERE jnm.joint_name = name_string
                )
                
                UNION ALL
                
                SELECT 
                    en.file_path,
                    jnm.component_name AS canonical_name
                FROM extracted_names en
                INNER JOIN joint_name_mappings jnm 
                    ON en.name_string = jnm.joint_name
                WHERE en.name_string IS NOT NULL
            ),
            canonical_names AS (
                SELECT DISTINCT
                    file_path,
                    get_canonical_name(canonical_name) AS canonical_name
                FROM base_names
            ),
            filtered_names AS (
                SELECT 
                    cn.file_path,
                    cn.canonical_name
                FROM canonical_names cn
                WHERE cn.canonical_name IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM entity_exclusions ee 
                    WHERE ee.entity_name = cn.canonical_name
                )
                AND (
                    cn.canonical_name LIKE '%% %%'
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
                FROM filtered_names fn1
                INNER JOIN filtered_names fn2 
                    ON fn1.file_path = fn2.file_path 
                    AND fn1.canonical_name < fn2.canonical_name
                INNER JOIN file_catalog fc
                    ON fn1.file_path = fc.path
                WHERE fn1.canonical_name != fn2.canonical_name
            )
            SELECT 
                person_1,
                person_2,
                COUNT(DISTINCT file_path) AS shared_documents,
                STRING_AGG(DISTINCT file_name, ', ' ORDER BY file_name) AS document_list
            FROM name_pairs
            GROUP BY person_1, person_2
            HAVING COUNT(DISTINCT file_path) >= 2
            ORDER BY shared_documents DESC;
        """)
        
        conn.commit()
        if verbose:
            log("✓ Updated v_person_cooccurrence view")


def verify_integrity(conn, verbose: bool = False) -> bool:
    """Verify consistency between code, database, and documentation.

    Performs integrity checks to ensure that the Python code constants
    match the database state. Useful for catching drift between seed
    data and runtime state.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, shows additional diagnostic info. Defaults to False.

    Returns:
        True if all integrity checks pass, False otherwise.
    """
    log("\n" + "=" * 80)
    log("INTEGRITY VERIFICATION")
    log("=" * 80)

    all_passed = True
    
    # Check 1: Code ↔ Database Consistency
    log("\n[1] CODE ↔ DATABASE CONSISTENCY")
    log("-" * 40)
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT canonical_name, COUNT(*) as alias_count
            FROM entity_aliases
            GROUP BY canonical_name
        """)
        db_counts = {row[0]: row[1] for row in cur.fetchall()}
    
    code_counts = {canonical: len(aliases) + 1 for canonical, aliases in KNOWN_ALIASES.items()}
    
    mismatches = []
    for name in sorted(set(code_counts.keys()) | set(db_counts.keys())):
        code_ct = code_counts.get(name, 0)
        db_ct = db_counts.get(name, 0)
        if code_ct != db_ct:
            mismatches.append((name, code_ct, db_ct))
    
    if mismatches:
        log("✗ MISMATCH DETECTED:")
        for name, code_ct, db_ct in mismatches[:5]:
            log(f"    {name}: code={code_ct}, db={db_ct}")
        all_passed = False
    else:
        log("✓ Code and database are consistent")
    
    log(f"\n  Code:     {len(code_counts)} entities, {sum(code_counts.values())} aliases")
    log(f"  Database: {len(db_counts)} entities, {sum(db_counts.values())} aliases")
    
    # Check 2: Canonicalization Function
    log("\n[2] CANONICALIZATION FUNCTION")
    log("-" * 40)
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'get_canonical_name')
        """)
        function_exists = cur.fetchone()[0]
        
        if not function_exists:
            log("✗ get_canonical_name() function does not exist")
            log("  Run: --create-function")
            all_passed = False
        else:
            # Test a few aliases
            errors = []
            for canonical, aliases in list(KNOWN_ALIASES.items())[:5]:
                cur.execute("SELECT get_canonical_name(%s)", (canonical,))
                result = cur.fetchone()[0]
                if result != canonical:
                    errors.append((canonical, canonical, result))
                for alias in aliases[:2]:
                    cur.execute("SELECT get_canonical_name(%s)", (alias,))
                    result = cur.fetchone()[0]
                    if result != canonical:
                        errors.append((canonical, alias, result))
            
            if errors:
                log(f"✗ {len(errors)} canonicalization errors")
                all_passed = False
            else:
                log("✓ get_canonical_name() works correctly")
    
    # Check 3: Exclusions
    log("\n[3] ENTITY EXCLUSIONS")
    log("-" * 40)
    
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM entity_exclusions")
        db_count = cur.fetchone()[0]
        code_count = len(EXCLUDED_ENTITIES)
        
        if code_count != db_count:
            log(f"✗ Mismatch: code={code_count}, db={db_count}")
            all_passed = False
        else:
            log(f"✓ {code_count} entities excluded")
    
    # Check 4: Normalization Rules
    log("\n[4] NORMALIZATION RULES")
    log("-" * 40)
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT rule_type, COUNT(*) 
            FROM name_normalization_rules 
            WHERE enabled = TRUE 
            GROUP BY rule_type
        """)
        for rule_type, count in cur.fetchall():
            log(f"  {rule_type}: {count} rules")
    
    return all_passed


def review_disambiguation_queue(conn, limit: int = 50, verbose: bool = False):
    """Review pending entries in the disambiguation queue.

    Displays pending queue entries sorted by confidence level and score,
    allowing human review of potential name matches.

    Args:
        conn: Active psycopg database connection.
        limit: Maximum number of entries to display. Defaults to 50.
        verbose: If True, shows additional details. Defaults to False.
    """
    log("\n" + "=" * 80)
    log("DISAMBIGUATION QUEUE REVIEW")
    log("=" * 80)
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2, 
                   similarity_score, confidence_level, shared_contexts
            FROM name_disambiguation_queue
            WHERE status = 'pending'
            ORDER BY 
                CASE confidence_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                similarity_score DESC
            LIMIT %s
        """, (limit,))
        
        entries = cur.fetchall()
        
        if not entries:
            log("\n✓ No pending entries in queue")
            return
        
        log(f"\nShowing {len(entries)} pending entries (sorted by confidence):\n")
        
        for queue_id, name1, name2, score, confidence, shared in entries:
            emoji = "⚡" if confidence == "HIGH" else "📊" if confidence == "MEDIUM" else "⚠️"
            log(f"{emoji} [{queue_id}] {name1}")
            log(f"       ↔ {name2}")
            log(f"       Score: {score:.3f} | Confidence: {confidence} | Shared docs: {shared or 0}")
            log("")


def merge_approved_aliases(
    conn,
    dry_run: bool = False,
    confirm: bool = False,
    verbose: bool = False
):
    """Merge user-approved or high-confidence queue entries into entity_aliases.

    Processes entries where user_approved = TRUE or confidence_level = 'HIGH',
    adding them as approved aliases and marking them as merged in the queue.
    
    In DataGrip, set user_approved = TRUE on entries you want to merge,
    then run: python disambiguate_entities_enhanced.py --merge

    Args:
        conn: Active psycopg database connection.
        dry_run: If True, shows what would be merged without making changes.
            Defaults to False.
        confirm: If True, skips the confirmation prompt. Defaults to False.
        verbose: If True, shows error details. Defaults to False.
    """
    log("\n" + "=" * 80)
    log("MERGE APPROVED ALIASES")
    log("=" * 80)
    
    with conn.cursor() as cur:
        # Merge entries that are either user-approved OR high-confidence
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2, 
                   similarity_score, confidence_level, user_approved
            FROM name_disambiguation_queue
            WHERE status = 'pending' 
              AND (user_approved = TRUE OR confidence_level = 'HIGH')
            ORDER BY user_approved DESC, similarity_score DESC
        """)
        
        entries = cur.fetchall()
        
        if not entries:
            log("\n✓ No approved entries to merge")
            return
        
        # Count user-approved vs auto-high
        user_approved_count = sum(1 for e in entries if e[5])  # user_approved is index 5
        auto_high_count = len(entries) - user_approved_count
        
        log(f"\nFound {len(entries)} entries to merge:")
        if user_approved_count:
            log(f"  • {user_approved_count} user-approved (from DataGrip)")
        if auto_high_count:
            log(f"  • {auto_high_count} HIGH confidence (automatic)")
        
        if dry_run:
            log("\n⚠️  DRY RUN - No changes will be made")
            log("\nWould merge:")
            for queue_id, name1, name2, score, conf, approved in entries[:10]:
                marker = "✓" if approved else "⚡"
                canonical = name1 if len(name1) >= len(name2) else name2
                alias = name2 if canonical == name1 else name1
                log(f"  {marker} {alias} → {canonical} (score: {score:.3f})")
            if len(entries) > 10:
                log(f"  ... and {len(entries) - 10} more")
            return
        
        if not confirm:
            response = input("\nProceed with merge? [Y/N]: ")
            if response.lower() != 'y':
                log("Cancelled.")
                return
        
        merged = 0
        for queue_id, name1, name2, score, conf, approved in entries:
            try:
                # name1 is always the canonical (reviewed/approved) name, name2 is the alias/variant
                canonical = name1
                alias = name2
                method = 'user_approved' if approved else 'automatic_merge'
                cur.execute("""
                    INSERT INTO entity_aliases 
                    (canonical_name, alias_name, confidence_score, disambiguation_method, reviewed)
                    VALUES (%s, %s, %s, %s, TRUE)
                    ON CONFLICT (canonical_name, alias_name) DO NOTHING
                """, (canonical, alias, score, method))
                cur.execute("""
                    UPDATE name_disambiguation_queue
                    SET status = 'merged', reviewed_at = NOW()
                    WHERE queue_id = %s
                """, (queue_id,))
                merged += 1
            except Exception as e:
                if verbose:
                    log(f"  Error: {e}")
        conn.commit()
        log(f"\n✓ Merged {merged} aliases")


def main():
    """Main entry point for the enhanced entity disambiguation script.

    Parses command-line arguments and orchestrates the disambiguation
    workflow including table creation, alias loading, analysis, and
    queue management.
    """
    parser = argparse.ArgumentParser(
        description="Enhanced Entity Disambiguation with Advanced Techniques",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Analysis commands
    parser.add_argument('--analyze', action='store_true',
                       help='Basic similarity analysis (original method)')
    parser.add_argument('--analyze-phonetic', action='store_true',
                       help='Phonetic matching analysis')
    parser.add_argument('--analyze-initials', action='store_true',
                       help='Initials + last name analysis')
    parser.add_argument('--analyze-context', action='store_true',
                       help='Organizational context clustering')
    parser.add_argument('--analyze-temporal', action='store_true',
                       help='Temporal window analysis')
    parser.add_argument('--analyze-network', action='store_true',
                       help='Network-based disambiguation')
    parser.add_argument('--analyze-all', action='store_true',
                       help='Run all analysis methods')
    
    # Processing commands
    parser.add_argument('--prioritize', action='store_true',
                       help='Calculate priority scores based on frequency')
    parser.add_argument('--rescore', action='store_true',
                       help='Recalculate confidence scores with enhanced method')
    parser.add_argument('--auto-exclude', action='store_true',
                       help='Apply auto-exclusion rules')
    
    # Standard commands
    parser.add_argument('--stats', action='store_true',
                       help='Show enhanced statistics')
    parser.add_argument('--create-function', action='store_true',
                       help='Create canonicalization function')
    parser.add_argument('--update-views', action='store_true',
                       help='Update views to use canonical names')
    parser.add_argument('--verify', action='store_true',
                       help='Verify code/database/documentation integrity')
    parser.add_argument('--review', action='store_true',
                       help='Review pending disambiguation queue entries')
    parser.add_argument('--merge', action='store_true',
                       help='Merge approved aliases into entity_aliases table')
    
    # Options
    parser.add_argument('--dsn', default=DEFAULT_DSN,
                       help='PostgreSQL connection string')
    parser.add_argument('--limit', type=int,
                       help='Limit number of names to analyze')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--confirm', action='store_true',
                       help='Confirm merge operations without prompting')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    
    args = parser.parse_args()
    
    # Require at least one action
    if not any([args.analyze, args.analyze_phonetic, args.analyze_initials,
                args.analyze_context, args.analyze_temporal, args.analyze_network,
                args.analyze_all, args.prioritize, args.rescore, args.auto_exclude,
                args.stats, args.create_function, args.update_views, args.verify,
                args.review, args.merge]):
        parser.print_help()
        return
    
    # Connect to database
    try:
        with get_db_connection(args.dsn) as conn:
            log("\n" + "=" * 60)
            log("🚀 STARTING ENTITY DISAMBIGUATION PROCESS")
            log("=" * 60)
            
            # Determine if we need full setup (table creation + data loading)
            # Read-only operations like --stats, --review, --merge skip setup
            # --merge only processes existing queue entries, should NOT recreate tables
            needs_setup = any([args.analyze, args.analyze_phonetic, args.analyze_initials,
                              args.analyze_context, args.analyze_temporal, args.analyze_network,
                              args.analyze_all, args.prioritize, args.rescore, args.auto_exclude,
                              args.create_function, args.update_views])
            
            if needs_setup:
                # Create enhanced tables (drops and rebuilds for clean slate)
                log("\n📋 Step 1/5: Creating enhanced tables...")
                create_enhanced_tables(conn, args.verbose)
                
                # Load KNOWN_ALIASES and EXCLUDED_ENTITIES into database
                log("\n📋 Step 2/5: Loading known aliases...")
                load_known_aliases(conn, args.verbose)
                load_excluded_entities(conn, args.verbose)
                
                # Load normalization rules (titles, OCR patterns, artifact suffixes)
                log("\n📋 Step 3/5: Loading normalization rules...")
                load_normalization_rules(conn, args.verbose)
            
            # Build canonical lookup from database (dynamically loads all approved aliases)
            canonical_lookup = None
            if any([args.analyze, args.analyze_phonetic, args.analyze_initials,
                   args.analyze_context, args.analyze_temporal, args.analyze_network,
                   args.analyze_all]):
                log("\n📋 Step 4/5: Building canonical name lookup from database...")
                canonical_lookup = build_canonical_lookup(conn, args.verbose)
            
            # Load name contexts and frequencies (needed for most operations)
            if any([args.analyze, args.analyze_phonetic, args.analyze_initials,
                   args.analyze_context, args.analyze_temporal, args.analyze_network,
                   args.analyze_all, args.prioritize, args.rescore]):
                
                log("\n📋 Step 5/5: Loading name contexts and frequencies...")
                
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM extracted_names WHERE name_string IS NOT NULL")
                    total_rows = cur.fetchone()[0]
                    
                    log(f"  Total rows to load: {total_rows:,}")
                    
                    cur.execute("""
                        SELECT name_string, file_path
                        FROM extracted_names
                        WHERE name_string IS NOT NULL
                    """)
                    
                    name_contexts = defaultdict(set)
                    name_frequencies = Counter()
                    
                    processed = 0
                    progress_interval = max(1, total_rows // 20)
                    for name, file_path in cur:
                        processed += 1
                        if processed % progress_interval == 0:
                            pct = (processed / total_rows) * 100
                            log(f"    Loading: {processed:,}/{total_rows:,} ({pct:.0f}%)")
                        name_contexts[name].add(file_path)
                        name_frequencies[name] += 1
                
                name_contexts = dict(name_contexts)
                
                log(f"  ✓ Loaded {len(name_contexts):,} unique names ({sum(name_frequencies.values()):,} total mentions)")
            
            # Run analyses
            if args.analyze_all:
                log("\n" + "=" * 60)
                log("🔬 RUNNING ALL ANALYSIS METHODS")
                log("=" * 60)
                args.analyze_phonetic = True
                args.analyze_initials = True
                args.analyze_context = True
                args.analyze_temporal = True
                args.analyze_network = True
                # Always rescore after running all analyses for holistic scoring
                args.rescore = True
            
            if args.analyze_phonetic:
                log("\n📊 Analysis 1/5: Phonetic matching...")
                analyze_phonetic_matches(conn, name_contexts, name_frequencies, 
                                       canonical_lookup, args.verbose, args.limit)
            
            if args.analyze_initials:
                log("\n📊 Analysis 2/5: Initials matching...")
                analyze_initials_matches(conn, name_contexts, name_frequencies,
                                       canonical_lookup, args.verbose, args.limit)
            
            if args.analyze_context:
                log("\n📊 Analysis 3/5: Context clustering...")
                analyze_context_clustering(conn, name_contexts, name_frequencies,
                                          canonical_lookup, args.verbose)
            
            if args.analyze_temporal:
                log("\n📊 Analysis 4/5: Temporal windows...")
                analyze_temporal_windows(conn, name_contexts, name_frequencies,
                                        args.verbose)
            
            if args.analyze_network:
                log("\n📊 Analysis 5/5: Network disambiguation...")
                analyze_network_disambiguation(conn, name_contexts, name_frequencies,
                                              args.verbose)
            
            if args.prioritize:
                log("\n⚡ Prioritizing queue by frequency...")
                prioritize_queue_by_frequency(conn, name_frequencies, args.verbose)
            
            if args.rescore:
                log("\n🔄 Rescoring queue entries...")
                rescore_queue_entries(conn, name_contexts, name_frequencies, args.verbose)
            
            if args.auto_exclude:
                log("\n🚫 Applying auto-exclusions...")
                apply_auto_exclusions(conn, args.verbose)
            
            if args.stats:
                log("\n📈 Showing statistics...")
                show_enhanced_statistics(conn, args.verbose)
            
            if args.create_function:
                log("\n🔧 Creating canonicalization function...")
                # Create canonicalization function (uses rules from name_normalization_rules)
                create_canonicalization_function(conn, args.verbose)
            
            if args.update_views:
                log("\n🔄 Updating views...")
                update_views_for_canonicalization(conn, args.verbose)
            
            if args.verify:
                log("\n✓ Verifying integrity...")
                verify_integrity(conn, args.verbose)
            
            if args.review:
                log("\n📋 Reviewing disambiguation queue...")
                review_disambiguation_queue(conn, args.limit or 50, args.verbose)
            
            if args.merge:
                log("\n🔀 Merging approved aliases...")
                merge_approved_aliases(conn, args.dry_run, args.confirm, args.verbose)
            
            log("\n" + "=" * 60)
            log("✅ ENTITY DISAMBIGUATION COMPLETE!")
            log("=" * 60 + "\n")
    
    except Exception as e:
        log(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
