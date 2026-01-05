#!/usr/bin/env python3
"""Crawl a folder and catalog files into a Postgres database.

Creates a `file_catalog` table (if missing) and upserts one row per file
with metadata: path, name, mime type, size, modification time, page count
(for PDFs) and optional extracted text path.

Usage examples:
  export DATABASE_URL='postgresql://user:pass@localhost:5432/dbname'
  python3 scripts/catalog_to_postgres.py "/path/to/root" --extract --ext _extracted.txt --verbose

Or pass a DSN with `--dsn` instead of using `DATABASE_URL`.
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple

try:
    import psycopg
except Exception:
    psycopg = None  # type: ignore

try:
    from dateutil.parser import parse
except Exception:
    parse = None  # type: ignore

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore

try:
    import spacy
    try:
        nlp = spacy.load("en_core_web_md")
        # Increase max_length to handle large documents (5MB)
        nlp.max_length = 5_000_000
    except:
        print("Downloading spaCy medium model...")
        from spacy.cli import download
        download("en_core_web_md")
        nlp = spacy.load("en_core_web_md")
        nlp.max_length = 5_000_000
except Exception:
    nlp = None

print(f"spaCy loaded: {nlp is not None}")

# Import shared database utilities (optional - uses fallback if not available)
try:
    from db_utils import table_exists, get_db_connection
    HAS_DB_UTILS = True
except ImportError:
    HAS_DB_UTILS = False


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS file_catalog (
    path TEXT PRIMARY KEY,
    file_name TEXT,
    file_type TEXT,
    size_bytes BIGINT,
    page_count INTEGER,
    mtime TIMESTAMP,
    ctime TIMESTAMP
);
"""

CREATE_TABLE_DATES_SQL = """
CREATE TABLE IF NOT EXISTS extracted_dates (
    file_path TEXT,
    date_string TEXT,
    date_datetime TIMESTAMP,
    occurrence_count INTEGER DEFAULT 1,
    PRIMARY KEY (file_path, date_string)
);
"""

CREATE_TABLE_NAMES_SQL = """
CREATE TABLE IF NOT EXISTS extracted_names (
    file_path TEXT,
    name_string TEXT,
    occurrence_count INTEGER DEFAULT 1,
    PRIMARY KEY (file_path, name_string)
);
"""

CREATE_TABLE_LOCATIONS_SQL = """
CREATE TABLE IF NOT EXISTS extracted_locations (
    file_path TEXT,
    location_string TEXT,
    occurrence_count INTEGER DEFAULT 1,
    PRIMARY KEY (file_path, location_string)
);
"""


def get_mime_type(path: str) -> str:
    """Determine the MIME type of a file.
    
    Args:
        path: File path to analyze.
        
    Returns:
        MIME type string, or 'application/octet-stream' if unknown.
    """
    mt, _ = mimetypes.guess_type(path)
    return mt or "application/octet-stream"


def get_pdf_page_count(path: str) -> Optional[int]:
    """Count the number of pages in a PDF file.
    
    Args:
        path: Path to the PDF file.
        
    Returns:
        Number of pages in the PDF, or None if unavailable or error.
    """
    if PdfReader is None:
        return None
    try:
        reader = PdfReader(path)
        return len(reader.pages)
    except Exception:
        return None


# Stop words to filter out - document structure, common words, abbreviations
NAME_STOP_WORDS = {
    'To', 'From', 'Date', 'Subject', 'Re', 'Cc', 'Bcc',
    'Dear', 'Sincerely', 'Regards', 'Best', 'Thanks', 'Thank',
    'Page', 'Pages', 'Document', 'File', 'Exhibit', 'Attachment',
    'DATE', 'CASE', 'PHOTOGRAPHER', 'LOCATION', 'FBI', 'ID',
    'The', 'This', 'That', 'These', 'Those', 'There', 'Here',
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
    'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun',  # Day abbreviations
    'January', 'February', 'March', 'April', 'May', 'June', 'July', 
    'August', 'September', 'October', 'November', 'December',
    'Mr', 'Mrs', 'Ms', 'Dr', 'Prof', 'Sir', 'Madam',
    'Yes', 'No', 'Not', 'All', 'None', 'Some', 'Any', 'Every',
    'About', 'Above', 'Below', 'After', 'Before', 'During', 'Since',
    'Please', 'Note', 'Notes', 'See', 'Also', 'However', 'Therefore', 'Thus',
    'Very', 'More', 'Most', 'Less', 'Least', 'Much', 'Many',
    'First', 'Second', 'Third', 'Last', 'Next', 'Previous',
    'Copy', 'Original', 'Draft', 'Final', 'Revised', 'Version',
    'Confidential', 'Private', 'Public', 'Secret', 'Classified',
    'Meeting', 'Call', 'Email', 'Letter', 'Memo', 'Report', 'Summary',
    'Information', 'Description', 'Details', 'Contents', 'Overview',
    'Statement', 'Testimony', 'Deposition', 'Important', 'Urgent',
    'Received', 'Sent', 'Send', 'Regarding', 'Matter', 'Matters',
    'Contact', 'Message', 'Messages', 'Provide', 'Provided',
    'Of', 'OF', 'By', 'BY', 'For', 'FOR', 'With', 'WITH', 'And', 'AND',
    'Or', 'OR', 'In', 'IN', 'On', 'ON', 'At', 'AT',
    'Plaintiff', 'PLAINTIFF', 'Defendant', 'DEFENDANT', 'Witness', 'WITNESS',
    'Attorney', 'ATTORNEY', 'Judge', 'JUDGE', 'Court', 'COURT',
    'Attendees', 'Participants', 'Members', 'Staff', 'Personnel',
    'According', 'Confirms', 'Indicates', 'Reveals', 'Shows', 'States',
    'Both', 'Either', 'Neither', 'Each', 'Another', 'Other', 'Others',
    'CEO', 'CFO', 'CTO', 'COO', 'President', 'Director', 'Manager',
    'III', 'II', 'IV', 'Jr', 'Sr', 'Esq',
    'Said', 'Says', 'Told', 'Asked', 'Replied', 'Answered', 'Agreed',
    'Records', 'Record', 'Evidence', 'Testimony', 'Testified', 'Testifies',
    'Was', 'Were', 'Been', 'Being', 'Has', 'Have', 'Had', 'Will', 'Would', 'Should',
    'Warden', 'Item', 'Conn', 'Dkt',  # Document structure words
}


# Entity canonicalization mappings for data quality
ENTITY_CANONICAL_MAPPINGS = {
    # Date artifacts (OCR concatenation errors)
    'Jeffrey Epstein Date': 'Jeffrey Epstein',
    'Epstein Date': 'Jeffrey Epstein',
    'Jeffrey Epstein Death Date': 'Jeffrey Epstein',
    'Jeff Epstein Date': 'Jeffrey Epstein',
    'Maxwell Epstein Date': 'Jeffrey Epstein',
    'J. Epstein Date': 'Jeffrey Epstein',
    'Jeffery Epstein Date': 'Jeffrey Epstein',
    '--Jeffrey Epstein Supposedly Sealed Order Date': 'Jeffrey Epstein',
    
    # Surname-only extractions (high impact - consolidate with full names)
    'Epstein': 'Jeffrey Epstein',
    'EPSTEIN': 'Jeffrey Epstein',
    'Maxwell': 'Ghislaine Maxwell',
    'MAXWELL': 'Ghislaine Maxwell',
    
    # All-caps name variants (should be proper case)
    'JEFFREY EPSTEIN': 'Jeffrey Epstein',
    'GHISLAINE MAXWELL': 'Ghislaine Maxwell',
    
    # Incomplete names (surname-only or nickname variants)
    'Nathan': 'Alison J. Nathan',
    'Jeffrey': 'Jeffrey Epstein',
    'JEFFREY': 'Jeffrey Epstein',
    'Jeff': 'Jeffrey Epstein',
    'Strauss': 'Audrey Strauss',
    'Alex': 'Alex Acosta',
    'Acosta': 'Alex Acosta',
    'Chris': 'Christian Everdell',
    'Berman': 'Geoffrey S. Berman',
    'G.S.': 'Geoffrey S. Berman',
    'G. S.': 'Geoffrey S. Berman',
    
    # First name only extractions
    'Joe': 'Joe Nascimento',
    'Tartaglione': 'Nicholas Tartaglione',
    'NOEL': 'Tova Noel',
    'Noel': 'Tova Noel',
    'Rivera': 'Justin Rivera',
    'McMahon': 'Colleen McMahon',
    
    # Additional surname-only that need full names
    'Weinstein': 'Marc A. Weinstein',  # Attorney, partner at Hughes Hubbard
    'Geoffrey': 'Geoffrey S. Berman',  # US Attorney, SDNY
    'Collins': 'Chris Collins',  # Rep. Chris Collins (R-NY)
    'Brown': 'Brown v. Maxwell',  # Legal case citation, not a person
    
    # Surname-only that should be full names
    'Trump': 'Donald Trump',
    'Marra': 'Kenneth Marra',
    
    # Case normalization (all-caps to proper case)
    'TOVA NOEL': 'Tova Noel',
    'JIM MARGOLIN': 'Jim Margolin',
    
    # OCR errors including firm names or titles
    'Laura A. Menninger Haddon': 'Laura A. Menninger',
    'Laura A. Menninger HADDON': 'Laura A. Menninger',
    'Laura A. Menninger HADDON MORGAN FOREMAN P.C. Mark S. Cohen Christian R. Everdell COHEN GRESSER LLP': 'Laura A. Menninger',
    'Laura A. Menninger HADDON MORGAN FOREMAN P.C. Christian R. Everdell COHEN GRESSER LLP': 'Laura A. Menninger',
    'Laura A. Menninger HADDON MORGAN FOREMAN P.C.': 'Laura A. Menninger',
    'DAMIAN WILLIAMS United States': 'Damian Williams',
    'DAMIAN WILLIAMS United States Attome': 'Damian Williams',
    
    # Name variants consolidation
    'Mark Cohen': 'Mark S. Cohen',
    'Mark Stewart Cohen': 'Mark S. Cohen',
    'Mark S. Cohen Cc': 'Mark S. Cohen',
    "Mark S. Cohen'": 'Mark S. Cohen',
    "Mark Cohen's": 'Mark S. Cohen',
    'Mark S. Cohen Mark S. Cohen': 'Mark S. Cohen',
    'Mark S.Cohen': 'Mark S. Cohen',
    
    # First name fragments (should not be standalone)
    'Laura': 'Laura A. Menninger',
    'Bobbi': 'Bobbi Sternheim',
    'Audrey': 'Audrey Strauss',
    
    # Name fragment that's part of full name
    'J. NATHAN': 'Alison J. Nathan',
    
    # Attorney name fragments and variants (Epstein defense team)
    'Miller': 'Michael C. Miller',  # Defense attorney (Michael Miller)
    'Reid': 'Reid Weingarten',  # Defense attorney
    'Weingarten': 'Reid Weingarten',
    'Marty': 'Martin G. Weinberg',  # Defense attorney (Martin G. Weinberg)
    'Mike': 'Michael C. Miller',  # Nickname for Michael Miller (in defense context)
    'Michael Miller': 'Michael C. Miller',  # Full name with middle initial
    'Mike Michael C. Miller': 'Michael C. Miller',
    'Mike Michael C. Miller Partner': 'Michael C. Miller',
    "Michael Miller'": 'Michael C. Miller',
    
    # Reid Weingarten variants
    'Reid Cc': 'Reid Weingarten',
    'Reid Marty': 'Reid Weingarten',
    "Reid Weingarten'": 'Reid Weingarten',
    
    # Martin Weinberg variants
    'Martin Weinberg': 'Martin G. Weinberg',
    "Martin G. Weinberg'": 'Martin G. Weinberg',
    "Martin Weinberg'": 'Martin G. Weinberg',
    
    # Jay Lefkowitz (attorney for Acosta/DOJ)
    'Jay': 'Jay Lefkowitz',
    'Lefkowitz': 'Jay Lefkowitz',
    'Jay Lefkowitz Cc': 'Jay Lefkowitz',
    'Jay P. Lefkowitz': 'Jay Lefkowitz',
    'Ja Lefkowitz': 'Jay Lefkowitz',
    'Ja Lefkowitz Cc': 'Jay Lefkowitz',
    
    # Jane Doe variants
    'Jane': 'Jane Doe',
    "Jane Doe's": 'Jane Doe',
    'Jane Doe No': 'Jane Doe',
    'Jane Doe I': 'Jane Doe',
}

# Entities that should be excluded (non-person entities)
NON_PERSON_ENTITIES = {
    'Replies',  # Email system text
    'Cir',      # Legal abbreviation for "Circuit"
    'Se',       # Legal abbreviation
    'Tuesda',   # OCR error (truncated "Tuesday")
    'Frida',    # OCR error (truncated "Friday")
    'Bates',    # Document numbering system ("Bates numbers")
    'SHU OBS',  # Special Housing Unit Observation (prison term)
    'SHU',      # Special Housing Unit (prison term, not a person)
    'F. Supp',  # Legal abbreviation (Federal Supplement case reporter)
    'F.Supp',   # Variant without space
    'R. Crim',  # Legal abbreviation (Federal Rules of Criminal Procedure)
    'R.Crim',   # Variant without space
    'R. Evid',  # Legal abbreviation (Federal Rules of Evidence)
    'R.Evid',   # Variant without space
    'Brady',    # Legal term (Brady v. Maryland disclosure requirement)
    'JEFFREY EPSTEIN - VICTIM',  # Document label/heading
    'GEOFFREY S. BERMAN United States',  # OCR concatenation error
    'ROSS AMSEL RABEN NASCIMENTO',  # Law firm name (not a person)
    'Law',      # Law Library (facility term, not a person)
    'Li',       # Operations lieutenant abbreviation (Ops Li)
    'Cap',      # Company name abbreviation (Alpha Cap)
    'Si',       # Prison position code (CONTROL Si, SEC OFFICER Si, SHU Si)
    'Ye',       # OCR error from document forms ("Yes" checkboxes)
    'al',       # Legal citation fragment ("et al.")
    'sjzi',     # OCR garbage from document artifacts
    'Pme',      # OCR garbage from document artifacts
    'Ghislaine Maxwell Indictment.pdf',  # File name extracted as person name
    'Haddon Mor',  # Law firm name fragment (Haddon Morgan)
    'Nicole Simmons Haddon',  # OCR error combining person + firm name
    'Davis',  # Primarily law firms (Davis Polk, Davis Wright) and university (UC Davis)
    'UC Davis',  # University, not a person
    'Davis Polk',  # Law firm
    'Davis Wright Tremaine',  # Law firm
    'Christian R. Everdell COHEN GRESSER LLP',  # OCR error with firm name
    'Michael',  # Too ambiguous - could be Michael Thomas, Michael Bachner, Michael Miller, etc.
}

# Location entities misclassified as person names
# These will be removed from names and added to locations
LOCATION_ENTITIES = {
    'Saint Andrew',
    "Saint Andrew's",
    'Saint Andrews',
    'St Thomas',   # Location (US Virgin Islands)
    'Thomas',      # Ambiguous but primarily refers to location in context
}


def apply_entity_corrections(entity_name: str, entity_type: str = 'name') -> Tuple[Optional[str], str]:
    """Apply data quality corrections to entity names before database insertion.
    
    Handles:
    - OCR date concatenation artifacts (e.g., "Jeffrey Epstein Date" → "Jeffrey Epstein")
    - Incomplete name canonicalization (e.g., "Nathan" → "Alison J. Nathan")
    - Non-person entity filtering (e.g., "Replies", "Cir", "Tuesda")
    - Location reclassification (e.g., "Saint Andrew" → location)
    
    Args:
        entity_name: The entity name to correct.
        entity_type: Either 'name' or 'location'.
        
    Returns:
        Tuple of (corrected_name, corrected_type) where:
        - corrected_name is None if entity should be excluded
        - corrected_type indicates whether to treat as 'name' or 'location'
    """
    # Apply canonical mappings
    if entity_name in ENTITY_CANONICAL_MAPPINGS:
        return (ENTITY_CANONICAL_MAPPINGS[entity_name], entity_type)
    
    # Filter out non-person entities
    if entity_name in NON_PERSON_ENTITIES:
        return (None, entity_type)
    
    # Reclassify location entities
    if entity_type == 'name' and entity_name in LOCATION_ENTITIES:
        # Convert to location-appropriate format
        location_name = entity_name.replace('Saint Andrew', 'One Saint Andrew\'s Plaza')
        return (location_name, 'location')
    
    # No corrections needed
    return (entity_name, entity_type)


def clean_name(name: str) -> str:
    """Clean a name by removing extra whitespace and special characters.
    
    Removes:
    - Leading/trailing whitespace
    - Multiple consecutive spaces
    - Special characters and punctuation (except hyphens, apostrophes, periods in names)
    - Control characters
    
    Args:
        name: The name string to clean.
        
    Returns:
        Cleaned name string with normalized whitespace.
    """
    import re
    
    # Strip leading/trailing whitespace
    name = name.strip()
    
    # Remove control characters and non-printable characters
    name = ''.join(char for char in name if char.isprintable())
    
    # Remove punctuation except hyphens, apostrophes, and periods (which can be in names)
    # Keep: letters, spaces, hyphens, apostrophes, periods
    name = re.sub(r'[^\w\s\-\'\.]', '', name)
    
    # Collapse multiple spaces into single space
    name = re.sub(r'\s+', ' ', name)
    
    # Strip again after cleaning
    name = name.strip()
    
    return name

def clean_location(location: str) -> str:
    """Clean a location by removing extra whitespace and special characters.
    
    Removes:
    - Leading/trailing whitespace
    - Multiple consecutive spaces
    - Special characters and punctuation (except common location punctuation)
    - Control characters
    - Single stray characters (except valid state/country codes)
    
    Args:
        location: The location string to clean.
        
    Returns:
        Cleaned location string with normalized whitespace.
    """
    import re
    
    # Valid state and country codes (case-insensitive)
    VALID_CODES = {
        'ny', 'us', 'uk', 'ca', 'fl', 'tx', 'dc', 'ma', 'pa', 'il', 'oh', 'ga', 
        'nc', 'mi', 'nj', 'va', 'wa', 'az', 'tn', 'in', 'mo', 'md', 'wi', 'mn',
        'co', 'al', 'sc', 'la', 'ky', 'or', 'ok', 'ct', 'ia', 'ms', 'ar', 'ks',
        'ut', 'nv', 'nm', 'ne', 'wv', 'id', 'hi', 'nh', 'me', 'ri', 'mt', 'de',
        'sd', 'nd', 'ak', 'vt', 'wy'
    }
    
    # Strip leading/trailing whitespace
    location = location.strip()
    
    # Remove control characters and non-printable characters
    location = ''.join(char for char in location if char.isprintable())
    
    # Remove punctuation except periods, commas, hyphens (which can be in locations)
    # Keep: letters, spaces, numbers, periods, commas, hyphens
    location = re.sub(r'[^\w\s\.\,\-]', '', location)
    
    # Collapse multiple spaces into single space
    location = re.sub(r'\s+', ' ', location)
    
    # Strip again after cleaning
    location = location.strip()
    
    # Remove single stray characters at beginning, middle, or end
    # Split by spaces and filter out single character words (unless valid codes)
    words = location.split()
    if len(words) > 1:
        filtered_words = []
        for i, word in enumerate(words):
            # Keep word if it's more than one character
            if len(word) > 1:
                filtered_words.append(word)
            # Or if it's a valid state/country code (case-insensitive)
            elif word.lower() in VALID_CODES:
                filtered_words.append(word)
            # Keep single character if it's the only word left
            elif len(words) == 1:
                filtered_words.append(word)
        
        location = ' '.join(filtered_words)
    
    return location

def is_valid_name(name: str) -> bool:
    """Check if a name is valid (not a stop word or noise).
    
    Filters out:
    - Stop words (To, From, Date, etc.)
    - Single letters with periods (Q., I.)
    - Two-letter uppercase codes (MM, VI)
    - Names with numbers (except "Jane Doe" references)
    - Special characters (except hyphens, apostrophes, periods)
    - Possessive forms
    
    Args:
        name: The name string to validate.
        
    Returns:
        True if the name is valid, False otherwise.
    """
    if not name or len(name) <= 1:
        return False
    
    # Remove trailing colons and possessive forms
    clean_name = name.rstrip(':').rstrip("'s")
    
    # Filter out single letters with periods (Q., I., M.)
    if len(clean_name) <= 2 and '.' in clean_name:
        return False
    
    # Filter out single letters or two-letter codes that look like initials
    if len(clean_name) == 2:
        # Allow actual two-letter names, but filter patterns like "MM", "Q.", "VI"
        if clean_name.isupper() or clean_name.isdigit():
            return False
    
    # Filter out names containing numbers (except for legitimate Jane Doe references)
    if any(char.isdigit() for char in clean_name):
        # Allow "Jane Doe" followed by numbers
        if not clean_name.startswith('Jane Doe'):
            return False
    
    # Filter out strings with special characters (except hyphens, apostrophes, periods)
    import re
    if re.search(r'[^a-zA-Z\s\-\'\.]', clean_name):
        return False
    
    # Case-insensitive check against stop words (handles UPPERCASE, lowercase, and Title Case)
    if clean_name in NAME_STOP_WORDS or clean_name.lower() in {w.lower() for w in NAME_STOP_WORDS}:
        return False
    
    # For multi-word names, check if first word is a stop word (e.g., "Dear Ghislaine")
    first_word = clean_name.split()[0] if ' ' in clean_name else clean_name
    if first_word in NAME_STOP_WORDS or first_word.lower() in {w.lower() for w in NAME_STOP_WORDS}:
        return False
    
    return True

def find_names_simple(text: str) -> List[str]:
    """Extract person names using simple regex patterns.
    
    Extracts names from:
    - PHOTOGRAPHER metadata lines
    - Capitalized word patterns (John Smith)
    - All uppercase patterns (JOHN SMITH)
    - Lowercase names after specific keywords (by, from, to)
    
    Args:
        text: Text content to analyze.
        
    Returns:
        List of extracted names.
    """
    names = []
    # From PHOTOGRAPHER lines
    for line in text.split('\n'):
        line = line.strip()
        if line.upper().startswith('PHOTOGRAPHER'):
            name = line[len('PHOTOGRAPHER'):].strip()
            if is_valid_name(name):
                names.append(name)
    # Find person's names: match various capitalizations
    import re
    # Pattern 1: Normal capitalized words (John Smith)
    name_patterns = re.findall(r'\b[A-Z][a-z]+(?: [A-Z][a-z]+)*\b', text)
    # Pattern 2: All uppercase names (JOHN SMITH, MAXWELL)
    uppercase_patterns = re.findall(r'\b[A-Z]{2,}(?: [A-Z]{2,})*\b', text)
    # Pattern 3: lowercase names after by/from/to/what/both - capture up to 2 words
    lowercase_patterns = re.findall(r'(?:by|from|to|what|both)\s+([a-z]+)\s+([a-z]+)\b', text, re.IGNORECASE)
    lowercase_single = re.findall(r'(?:by|from|to|what|both)\s+([a-z]+)\b', text, re.IGNORECASE)
    
    # Combine all patterns
    all_patterns = name_patterns + uppercase_patterns + lowercase_single
    
    # Add two-word lowercase patterns
    for first, second in lowercase_patterns:
        all_patterns.extend([first, second])
    
    for pattern in all_patterns:
        # Filter using is_valid_name
        if is_valid_name(pattern) and pattern not in names:
            names.append(pattern)
    return names

def is_valid_location(location: str) -> bool:
    """Check if a location is valid (not abbreviations, titles, or noise).
    
    Filters out:
    - Corporate/legal suffixes (Esq, LLC, P.C.)
    - Tech/product names (INTL, iPhone)
    - Job titles
    - Invalid two-character codes (except common state codes)
    - Numbers (except valid zip codes and street addresses)
    
    Args:
        location: The location string to validate.
        
    Returns:
        True if the location is valid, False otherwise.
    """
    if not location or len(location) <= 1:
        return False
    
    # Filter out common abbreviations that aren't meaningful locations
    LOCATION_STOP_WORDS = {
        'Esq', 'LLC', 'P.C.', 'Inc', 'Corp', 'Ltd',  # Corporate/legal suffixes
        'INTL', 'iPhone',  # Tech/product names
        'Assistant United States',  # Job titles
        'Conn', 'Conn.',  # Connecticut abbreviation in legal context
    }
    
    if location in LOCATION_STOP_WORDS:
        return False
    
    # Filter out locations with numbers (except valid ones like "New York 10007")
    import re
    if re.search(r'[0-9]', location):
        # Allow city + zip code patterns
        if not re.match(r'^[A-Za-z\s]+\d{5}$', location):
            # Also allow street addresses with ordinals (e.g., "S.W. 3rd")
            if not re.search(r'\b(\d+(st|nd|rd|th|ST|ND|RD|TH))\b', location):
                return False
    
    # Filter out very short strings (2 chars) unless they're common state codes
    VALID_STATE_CODES = {'NY', 'US', 'UK', 'CA', 'FL', 'TX', 'DC'}
    if len(location) == 2 and location.upper() not in VALID_STATE_CODES:
        return False
    
    # Filter out single character or special characters
    if re.search(r'^[^a-zA-Z\s]', location):
        return False
    
    return True

def find_locations_simple(text: str) -> List[str]:
    """Extract locations using simple pattern matching.
    
    Extracts locations from LOCATION metadata lines.
    
    Args:
        text: Text content to analyze.
        
    Returns:
        List of extracted locations.
    """
    locations = []
    for line in text.split('\n'):
        line = line.strip()
        if line.upper().startswith('LOCATION'):
            loc = line[len('LOCATION'):].strip()
            if loc and loc != '-' and is_valid_location(loc):
                locations.append(loc)
    return locations


def correct_date_year(dt: datetime) -> datetime:
    """Correct common OCR and typo errors in datetime years.
    
    Corrects patterns found in the Epstein-Maxwell document corpus:
    - Years < 1000: Add missing leading digits (200→2000, 006→2006)
    - Years > 2025: Fix transposition/typo errors (3030→2020, 7005→2005, 29XX→20XX)
    
    Args:
        dt: The datetime object to correct.
        
    Returns:
        Corrected datetime object, or None if unable to correct.
    """
    if dt is None:
        return None
    
    year = dt.year
    
    # Year is already in valid range
    if 1990 <= year <= 2025:
        return dt
    
    corrected_year = None
    
    # Handle years < 1000: missing leading digits
    if year < 1000:
        if year == 200:  # Special case: year 200 → 2000
            corrected_year = 2000
        elif 200 <= year <= 999:  # 3-digit year: assume it's 20XX
            # e.g., 205 → 2005 (extract last 2 digits)
            last_two = year % 100
            corrected_year = 2000 + last_two
        elif 0 <= year <= 99:   # 2-digit year: add leading "20"
            corrected_year = 2000 + year
    
    # Handle years > 2025: transposition and typo errors
    elif year > 2025:
        year_str = str(year)
        
        if len(year_str) == 4:
            # Try multiple correction patterns
            first, second, third, fourth = year_str[0], year_str[1], year_str[2], year_str[3]
            
            # Pattern 1: Replace 3 with 2 (keyboard adjacent, 3030 → 2020)
            if '3' in year_str:
                with_2s = int(year_str.replace('3', '2'))
                if 1990 <= with_2s <= 2025:
                    corrected_year = with_2s
            
            # Pattern 2: Swap positions 0 and 2 for transpositions
            if corrected_year is None:
                swap_0_2 = int(third + second + first + fourth)
                if 1990 <= swap_0_2 <= 2025:
                    corrected_year = swap_0_2
            
            # Pattern 3: Swap first two digits
            if corrected_year is None:
                transposed = int(second + first + year_str[2:])
                if 1990 <= transposed <= 2025:
                    corrected_year = transposed
            
            # Pattern 4: Replace first digit with '2' (7005 → 2005)
            if corrected_year is None and year_str[0] != '2':
                with_2 = int('2' + year_str[1:])
                if 1990 <= with_2 <= 2025:
                    corrected_year = with_2
            
            # Pattern 5: Fix 26XX, 28XX, 29XX, 23XX, 21XX → 20XX pattern
            if corrected_year is None and year_str[:2] in ['26', '28', '29', '23', '21']:
                corrected_year = int('20' + year_str[2:])
    
    # Return corrected datetime or None if correction failed
    if corrected_year and 1990 <= corrected_year <= 2025:
        return dt.replace(year=corrected_year)
    
    return None


def find_dates(text: str) -> List[Tuple[str, datetime]]:
    """Extract dates from text using multiple pattern matchers.
    
    Recognizes:
    - Date/time combinations (04/11/2005 12:00:00)
    - Dates without time (04/11/2005, 3/10/200)
    - Day month year (11 April 2005, April 11, 2005)
    - ISO datetime formats (2005-04-11T12:00:00)
    
    Automatically corrects common OCR and typo errors:
    - Missing leading digits: 200→2000, 006→2006
    - Keyboard typos: 3030→2020 (3 adjacent to 2)
    - First digit errors: 7005→2005
    - Digit transpositions: 29XX→20XX, 28XX→20XX, 26XX→20XX, 23XX→20XX, 21XX→20XX
    
    Rejects dates that cannot be corrected to valid range (1990-2025).
    
    Note: Returns ALL occurrences, including duplicates, so the calling
    code can count them with Counter.
    
    Args:
        text: Text content to analyze.
        
    Returns:
        List of tuples containing (date_string, datetime_object).
    """
    dates = []
    import re
    # Find date and time combinations (e.g., "04/11/2005 12:00:00", "2005-04-11 14:30")
    datetime_patterns = re.findall(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4} \d{1,2}:\d{2}(?::\d{2})?\b', text)
    for pattern in datetime_patterns:
        try:
            dt = parse(pattern)
            corrected_dt = correct_date_year(dt)
            if corrected_dt:
                dates.append((pattern, corrected_dt))
        except Exception:
            pass
    # Find dates without time (e.g., "04/11/2005", "4/11/05", "3/10/200")
    date_only_patterns = re.findall(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', text)
    for pattern in date_only_patterns:
        try:
            dt = parse(pattern)
            corrected_dt = correct_date_year(dt)
            if corrected_dt:
                dates.append((pattern, corrected_dt))
        except Exception:
            pass
    # Find day month year (e.g., "11 April 2005", "April 11, 2005")
    month_names = (
        r'(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December|'
        r'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    )
    day_month_year_patterns = re.findall(
        r'\b\d{1,2} ' + month_names + r' \d{4}\b',
        text,
        re.IGNORECASE
    )
    for pattern in day_month_year_patterns:
        try:
            dt = parse(pattern)
            corrected_dt = correct_date_year(dt)
            if corrected_dt:
                dates.append((pattern, corrected_dt))
        except Exception:
            pass
    # Also find month day year (e.g., "April 11, 2005")
    month_day_year_patterns = re.findall(
        r'\b' + month_names + r' \d{1,2},? \d{4}\b',
        text,
        re.IGNORECASE
    )
    for pattern in month_day_year_patterns:
        try:
            dt = parse(pattern)
            corrected_dt = correct_date_year(dt)
            if corrected_dt:
                dates.append((pattern, corrected_dt))
        except Exception:
            pass
    # Find ISO-like dates with time (e.g., "2005-04-11T12:00:00")
    iso_datetime_patterns = re.findall(
        r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?\b',
        text
    )
    for pattern in iso_datetime_patterns:
        try:
            dt = parse(pattern)
            corrected_dt = correct_date_year(dt)
            if corrected_dt:
                dates.append((pattern, corrected_dt))
        except Exception:
            pass
    return dates


def extract_pdf(path: str, out_path: str) -> bool:
    """Extract text content from a PDF file.
    
    Args:
        path: Path to the PDF file.
        out_path: Path where extracted text will be saved.
        
    Returns:
        True if extraction succeeded, False otherwise.
    """
    if PdfReader is None:
        return False
    try:
        reader = PdfReader(path)
        parts = []
        for p in reader.pages:
            parts.append(p.extract_text() or "")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))
        return True
    except Exception:
        return False


def upsert_record(conn, rec: dict):
    """Insert or update a file catalog record.
    
    Uses UPSERT (INSERT ... ON CONFLICT DO UPDATE) to handle duplicates.
    
    Args:
        conn: Database connection.
        rec: Dictionary containing file metadata (path, file_name, file_type,
             size_bytes, page_count, extracted_text_path, mtime, ctime).
    """
    sql = """
    INSERT INTO file_catalog (
        path, file_name, file_type, size_bytes, page_count,
        extracted_text_path, mtime, ctime
    )
    VALUES (
        %(path)s, %(file_name)s, %(file_type)s, %(size_bytes)s,
        %(page_count)s, %(extracted_text_path)s, %(mtime)s, %(ctime)s
    )
    ON CONFLICT (path) DO UPDATE SET
        file_name = EXCLUDED.file_name,
        file_type = EXCLUDED.file_type,
        size_bytes = EXCLUDED.size_bytes,
        page_count = EXCLUDED.page_count,
        extracted_text_path = EXCLUDED.extracted_text_path,
        mtime = EXCLUDED.mtime,
        ctime = EXCLUDED.ctime;
    """
    conn.execute(sql, rec)


def connect(dsn: Optional[str], create_db: bool = False):
    """Establish a connection to PostgreSQL database.
    
    Args:
        dsn: Database connection string (postgresql://user:pass@host:port/db).
             If None, uses DATABASE_URL environment variable via db_utils.
        create_db: If True, creates the database if it doesn't exist.
        
    Returns:
        psycopg connection object with autocommit enabled.
        
    Raises:
        SystemExit: If psycopg is not installed or connection fails.
    """
    from db_utils import get_dsn
    
    if psycopg is None:
        print("psycopg not installed. Add it to requirements and pip install.")
        sys.exit(1)
    
    # Resolve DSN using centralized utility
    connection_dsn = get_dsn(dsn)
    
    if create_db:
        # Parse DSN: postgresql://user:pass@host:port/dbname
        if not connection_dsn.startswith('postgresql://'):
            print("DSN must start with postgresql://")
            sys.exit(1)
        after_proto = connection_dsn[14:]
        parts = after_proto.split('/')
        if len(parts) != 2:
            print("Invalid DSN format")
            sys.exit(1)
        dbname = parts[1]
        temp_dsn = 'postgresql://' + parts[0] + '/postgres'
        try:
            with psycopg.connect(temp_dsn) as temp_conn:
                temp_conn.execute(f"CREATE DATABASE {dbname}")
        except Exception as e:
            print(f"Failed to create database: {e}")
            sys.exit(1)
    
    conn = psycopg.connect(connection_dsn)
    conn.autocommit = True
    return conn


def crawl_and_catalog(
    root: str,
    conn,
    extract: bool,
    ext: str,
    verbose: bool,
    dsn: Optional[str] = None
):
    """Crawl directory tree and catalog files into PostgreSQL.
    
    Walks through the directory tree starting at root, catalogs all files
    into the file_catalog table, optionally extracts PDF text, and extracts
    entities (names, locations, dates) from text files using spaCy NER.
    
    Args:
        root: Root directory to crawl.
        conn: Database connection.
        extract: If True, extract text from PDFs.
        ext: File extension for extracted text files (e.g., '_extracted.txt').
        verbose: If True, print detailed progress information.
        dsn: Database connection string (for reconnection if needed).
    """
    root = os.path.abspath(root)
    with conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_TABLE_DATES_SQL)
        conn.execute(CREATE_TABLE_NAMES_SQL)
        conn.execute(CREATE_TABLE_LOCATIONS_SQL)

    # Progress tracking
    import time
    start_time = time.time()
    
    # Count total extracted files to process
    print("Counting files to extract...")
    total_extracted_files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith('_extracted.txt'):
                total_extracted_files += 1
    
    print(f"Found {total_extracted_files:,} extracted text files to process")
    print()
    
    files_processed = 0
    extracted_files_processed = 0
    total_names = 0
    total_locations = 0
    total_dates = 0
    
    print("="*80)
    print("STARTING EXTRACTION PROCESS")
    print("="*80)
    print()

    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            if conn.closed:
                conn = connect(dsn, False)
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            mime = get_mime_type(path)
            size = os.path.getsize(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            ctime = datetime.fromtimestamp(os.path.getctime(path))

            page_count = None
            extracted_path = None

            if mime == "application/pdf" or name.lower().endswith(".pdf"):
                page_count = get_pdf_page_count(path)
                if extract:
                    base = name.rsplit(".", 1)[0]
                    out_name = base + ext
                    out_path = os.path.join(dirpath, out_name)
                    ok = extract_pdf(path, out_path)
                    if ok:
                        extracted_path = out_path
                    elif verbose:
                        print(f"Failed to extract text for {path}")

            rec = {
                "path": rel,
                "file_name": name,
                "file_type": mime,
                "size_bytes": size,
                "page_count": page_count,
                "extracted_text_path": os.path.relpath(extracted_path, root) if extracted_path else None,
                "mtime": mtime,
                "ctime": ctime,
            }

            try:
                with conn:
                    upsert_record(conn, rec)
                files_processed += 1
            except Exception as e:
                print(f"DB error for {rel}: {e}", file=sys.stderr)

            if name.endswith('_extracted.txt'):
                extracted_files_processed += 1
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    # Limit text size for performance (first 2MB to be safe)
                    MAX_TEXT_SIZE = 2_000_000
                    if len(text) > MAX_TEXT_SIZE:
                        text = text[:MAX_TEXT_SIZE]
                    
                    dates = find_dates(text)
                    # Batch insert dates with counts (UPSERT)
                    if dates:
                        from collections import Counter
                        # Track date_string -> (date_datetime, count)
                        dates_dict = {}
                        for date_str, dt in dates:
                            if date_str not in dates_dict:
                                dates_dict[date_str] = (dt, 1)
                            else:
                                prev_dt, prev_count = dates_dict[date_str]
                                dates_dict[date_str] = (prev_dt, prev_count + 1)
                        
                        if conn.closed:
                            conn = connect(dsn, False)
                        with conn:
                            with conn.cursor() as cur:
                                cur.executemany(
                                    """INSERT INTO extracted_dates (
                                           file_path, date_string, date_datetime,
                                           occurrence_count
                                       )
                                       VALUES (%s, %s, %s, %s)
                                       ON CONFLICT (file_path, date_string)
                                       DO UPDATE SET
                                           occurrence_count = EXCLUDED.occurrence_count,
                                           date_datetime = EXCLUDED.date_datetime
                                    """,
                                    [
                                        (rel, date_str, dt, count)
                                        for date_str, (dt, count)
                                        in dates_dict.items()
                                    ]
                                )
                        total_dates += len(dates_dict)
                    
                    if nlp:
                        doc = nlp(text)
                        if verbose:
                            print(f"Processing {rel}: {len(doc.ents)} entities found")
                        
                        # Batch collect entities with counts
                        from collections import Counter
                        names_list = []
                        locations_list = []
                        for ent in doc.ents:
                            if ent.label_ == 'PERSON':
                                cleaned_name = clean_name(ent.text)
                                if cleaned_name and is_valid_name(cleaned_name):
                                    # Apply data quality corrections
                                    corrected_name, corrected_type = apply_entity_corrections(
                                        cleaned_name, 'name'
                                    )
                                    if corrected_name:  # Skip if None (filtered out)
                                        if corrected_type == 'location':
                                            locations_list.append(corrected_name)
                                        else:
                                            names_list.append(corrected_name)
                            elif ent.label_ in ('GPE', 'LOC'):
                                cleaned_location = clean_location(ent.text)
                                if cleaned_location and is_valid_location(cleaned_location):
                                    # Apply corrections (in case of reclassified entities)
                                    corrected_loc, corrected_type = apply_entity_corrections(
                                        cleaned_location, 'location'
                                    )
                                    if corrected_loc:
                                        locations_list.append(corrected_loc)
                        
                        # Count occurrences
                        names_counts = Counter(names_list)
                        locations_counts = Counter(locations_list)
                        
                        # Batch insert all names with counts (UPSERT)
                        if names_counts:
                            if conn.closed:
                                conn = connect(dsn, False)
                            with conn:
                                with conn.cursor() as cur:
                                    cur.executemany(
                                        """INSERT INTO extracted_names (
                                               file_path, name_string, occurrence_count
                                           )
                                           VALUES (%s, %s, %s)
                                           ON CONFLICT (file_path, name_string)
                                           DO UPDATE SET
                                               occurrence_count = EXCLUDED.occurrence_count
                                        """,
                                        [
                                            (rel, name, count)
                                            for name, count in names_counts.items()
                                        ]
                                    )
                            total_names += len(names_counts)
                        
                        # Batch insert all locations with counts (UPSERT)
                        if locations_counts:
                            if conn.closed:
                                conn = connect(dsn, False)
                            with conn:
                                with conn.cursor() as cur:
                                    cur.executemany(
                                        """INSERT INTO extracted_locations (
                                               file_path, location_string, occurrence_count
                                           )
                                           VALUES (%s, %s, %s)
                                           ON CONFLICT (file_path, location_string)
                                           DO UPDATE SET
                                               occurrence_count = EXCLUDED.occurrence_count
                                        """,
                                        [
                                            (rel, loc, count)
                                            for loc, count in locations_counts.items()
                                        ]
                                    )
                            total_locations += len(locations_counts)
                        
                        # Progress reporting every 100 extracted files
                        if extracted_files_processed % 100 == 0:
                            elapsed = time.time() - start_time
                            rate = extracted_files_processed / elapsed
                            remaining = (
                                total_extracted_files - extracted_files_processed
                            )
                            eta_seconds = remaining / rate if rate > 0 else 0
                            print(
                                f"Progress: {extracted_files_processed:,}/"
                                f"{total_extracted_files:,} extracted files | "
                                f"Names: {total_names:,} | "
                                f"Locations: {total_locations:,} | "
                                f"Dates: {total_dates:,} | "
                                f"Rate: {rate:.1f}/s | "
                                f"ETA: {eta_seconds/60:.0f}m"
                            )
                    else:
                        # Fallback simple parsing
                        from collections import Counter
                        names = find_names_simple(text)
                        
                        # Apply corrections to simple-extracted names
                        corrected_names = []
                        for name in names:
                            corrected_name, corrected_type = apply_entity_corrections(name, 'name')
                            if corrected_name and corrected_type == 'name':
                                corrected_names.append(corrected_name)
                        
                        names_counts = Counter(corrected_names)
                        if names_counts:
                            if conn.closed:
                                conn = connect(dsn, False)
                            with conn:
                                with conn.cursor() as cur:
                                    cur.executemany(
                                        """INSERT INTO extracted_names (
                                               file_path, name_string, occurrence_count
                                           )
                                           VALUES (%s, %s, %s)
                                           ON CONFLICT (file_path, name_string)
                                           DO UPDATE SET
                                               occurrence_count = EXCLUDED.occurrence_count
                                        """,
                                        [
                                            (rel, name, count)
                                            for name, count in names_counts.items()
                                        ]
                                    )
                            total_names += len(names_counts)
                        
                        locations = find_locations_simple(text)
                        
                        # Apply corrections to simple-extracted locations
                        corrected_locations = []
                        for loc in locations:
                            corrected_loc, corrected_type = apply_entity_corrections(loc, 'location')
                            if corrected_loc:
                                corrected_locations.append(corrected_loc)
                        
                        locations_counts = Counter(corrected_locations)
                        if locations_counts:
                            if conn.closed:
                                conn = connect(dsn, False)
                            with conn:
                                with conn.cursor() as cur:
                                    cur.executemany(
                                        """INSERT INTO extracted_locations (
                                               file_path, location_string, occurrence_count
                                           )
                                           VALUES (%s, %s, %s)
                                           ON CONFLICT (file_path, location_string)
                                           DO UPDATE SET
                                               occurrence_count = EXCLUDED.occurrence_count
                                        """,
                                        [
                                            (rel, loc, count)
                                            for loc, count in locations_counts.items()
                                        ]
                                    )
                            total_locations += len(locations_counts)
                        
                        # Progress reporting every 100 extracted files
                        if extracted_files_processed % 100 == 0:
                            elapsed = time.time() - start_time
                            rate = extracted_files_processed / elapsed
                            remaining = (
                                total_extracted_files - extracted_files_processed
                            )
                            eta_seconds = remaining / rate if rate > 0 else 0
                            print(
                                f"Progress: {extracted_files_processed:,}/"
                                f"{total_extracted_files:,} extracted files | "
                                f"Names: {total_names:,} | "
                                f"Locations: {total_locations:,} | "
                                f"Dates: {total_dates:,} | "
                                f"Rate: {rate:.1f}/s | "
                                f"ETA: {eta_seconds/60:.0f}m"
                            )
                except Exception as e:
                    print(f"Error parsing {rel}: {e}", file=sys.stderr)
    
    # Final summary
    elapsed = time.time() - start_time
    print()
    print("="*80)
    print("EXTRACTION COMPLETE")
    print("="*80)
    print(f"Total files cataloged: {files_processed:,}")
    print(f"Extracted text files processed: {extracted_files_processed:,}")
    print(f"Total names extracted: {total_names:,}")
    print(f"Total locations extracted: {total_locations:,}")
    print(f"Total dates extracted: {total_dates:,}")
    print(f"Total time: {elapsed/60:.1f} minutes")
    print(f"Average rate: {extracted_files_processed/elapsed:.1f} files/second")
    print("="*80)


def main() -> int:
    """Main entry point for the catalog_to_postgres script.
    
    Parses command-line arguments, establishes database connection,
    and initiates the file cataloging process.
    
    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(
        description="Catalog files into Postgres"
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root folder to crawl"
    )
    parser.add_argument(
        "--dsn",
        help="Postgres DSN (overrides DATABASE_URL env var)"
    )
    parser.add_argument(
        "--create-db",
        action="store_true",
        help="Create the database if it doesn't exist"
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract PDF text alongside cataloging"
    )
    parser.add_argument(
        "--ext",
        default="_extracted.txt",
        help="Suffix for extracted text files"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()

    conn = connect(args.dsn, args.create_db)
    try:
        crawl_and_catalog(
            args.root, conn, args.extract, args.ext, args.verbose, args.dsn
        )
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())