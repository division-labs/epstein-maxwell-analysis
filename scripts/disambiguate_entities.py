#!/usr/bin/env python3
"""
Entity Disambiguation & Resolution
Identifies and merges name variants and aliases to canonical entities.

Features:
- Levenshtein distance similarity matching
- Context-based disambiguation (shared documents)
- Title and initial variations handling
- Confidence scoring for matches (HIGH/MEDIUM/LOW)
- Review queue for manual verification
- Batch merging of confirmed aliases
- PostgreSQL canonicalization function for unified names
- Automatic view updates for accurate co-occurrence analysis
- Integrity verification between code, database, and documentation

Usage:
    python disambiguate_entities.py --analyze          # Find potential aliases
    python disambiguate_entities.py --review           # Review disambiguation queue
    python disambiguate_entities.py --merge            # Apply approved merges
    python disambiguate_entities.py --stats            # Show statistics
    python disambiguate_entities.py --create-function  # Create canonicalization function
    python disambiguate_entities.py --update-views     # Update views with canonical names
    python disambiguate_entities.py --verify           # Verify code/DB/doc integrity
    
Workflow:
    1. Analyze: Find similar names and populate queue
    2. Review: Examine high-confidence matches
    3. Merge: Add approved aliases to entity_aliases table
    4. Create Function: Set up PostgreSQL canonicalization
    5. Update Views: Unify names in co-occurrence views
    6. Verify: Check integrity between code, database, and documentation
    
IMPORTANT: After any changes to KNOWN_ALIASES, run:
    python disambiguate_entities.py --create-function --update-views --verify -v
"""

import psycopg
import re
import sys
from typing import List, Tuple, Dict, Set
from datetime import datetime
import argparse

# Import shared database utilities
from db_utils import table_exists, get_db_connection
from config import DEFAULT_DSN

# Database connection - uses config.py DEFAULT_DSN
DB_CONNECTION = DEFAULT_DSN

# Disambiguation thresholds
LEVENSHTEIN_THRESHOLD = 3
MIN_SHARED_CONTEXTS = 2  # Minimum shared documents for context-based matching
HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.60

# Common titles to strip
TITLES = {
    'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 
    'sir', 'lady', 'lord', 'the', 'hon', 'honorable'
}

# Known entity aliases (high confidence matches)
# NOTE: This dictionary is the source of truth for entity_aliases table.
# Run --load-aliases to sync this dictionary to the database.
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
}


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings."""
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


def normalize_name(name: str) -> str:
    """Normalize name by removing titles, possessives, extra spaces, and standardizing format."""
    # Convert to lowercase for comparison
    normalized = name.lower().strip()
    
    # Remove possessive suffixes ('s or s' or 's or s')
    # Handle both straight (') and curly (') apostrophes
    if normalized.endswith("'s") or normalized.endswith("'s"):
        normalized = normalized[:-2]
    elif normalized.endswith("s'") or normalized.endswith("s'"):
        normalized = normalized[:-2]
    elif normalized.endswith("'") or normalized.endswith("'"):
        normalized = normalized[:-1]
    
    # Remove common titles
    words = normalized.split()
    words = [w.rstrip('.') not in TITLES and w or '' for w in words]
    words = [w for w in words if w]  # Remove empty strings
    
    # Remove periods after initials
    words = [w.rstrip('.') if len(w) <= 2 else w for w in words]
    
    return ' '.join(words)


def extract_initials(name: str) -> str:
    """Extract initials from a name (e.g., 'Jeffrey Epstein' -> 'J E')."""
    words = name.split()
    return ' '.join([w[0].upper() for w in words if w])


def is_initial_match(name1: str, name2: str) -> bool:
    """Check if one name is an initial form of another."""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    
    words1 = n1.split()
    words2 = n2.split()
    
    # Check if shorter name matches initials + last name
    if len(words1) != len(words2):
        shorter = words1 if len(words1) < len(words2) else words2
        longer = words2 if len(words1) < len(words2) else words1
        
        # Check if all words in shorter match either initial or full word in longer
        matches = 0
        for i, word in enumerate(shorter):
            if i < len(longer):
                if word == longer[i] or (len(word) == 1 and word == longer[i][0]):
                    matches += 1
        
        return matches == len(shorter)
    
    return False


def calculate_similarity_score(name1: str, name2: str, shared_contexts: int) -> float:
    """
    Calculate similarity score between two names (case-insensitive).
    Returns a value between 0.0 and 1.0.
    """
    # Normalize and lowercase for case-insensitive comparison
    n1 = normalize_name(name1).lower()
    n2 = normalize_name(name2).lower()
    
    # Exact match (case-insensitive)
    if n1 == n2:
        return 1.0
    
    # Initial match check
    if is_initial_match(name1, name2):
        return 0.9 if shared_contexts >= MIN_SHARED_CONTEXTS else 0.7
    
    # Levenshtein distance (on lowercase normalized names)
    lev_dist = levenshtein_distance(n1, n2)
    max_len = max(len(n1), len(n2))
    lev_score = 1.0 - (lev_dist / max_len)
    
    # Boost score if names share contexts (documents)
    context_boost = min(shared_contexts / 10.0, 0.3) if shared_contexts > 0 else 0
    
    return min(lev_score + context_boost, 1.0)


def create_tables(conn, verbose: bool = False):
    """Create entity disambiguation tables if they don't exist."""
    with conn.cursor() as cur:
        if verbose:
            print("Creating entity disambiguation tables...")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entity_aliases (
                alias_id SERIAL PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                alias_name TEXT NOT NULL,
                confidence_score FLOAT NOT NULL,
                disambiguation_method TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed BOOLEAN DEFAULT FALSE,
                UNIQUE(canonical_name, alias_name)
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS name_disambiguation_queue (
                queue_id SERIAL PRIMARY KEY,
                name_variant_1 TEXT NOT NULL,
                name_variant_2 TEXT NOT NULL,
                similarity_score FLOAT NOT NULL,
                confidence_level TEXT,
                shared_contexts INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                CHECK (status IN ('pending', 'merged', 'rejected')),
                CHECK (confidence_level IN ('HIGH', 'MEDIUM', 'LOW')),
                UNIQUE(name_variant_1, name_variant_2)
            );
        """)
        
        # Entity exclusions table - entities to filter from analysis
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entity_exclusions (
                exclusion_id SERIAL PRIMARY KEY,
                entity_name TEXT NOT NULL UNIQUE,
                exclusion_reason TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                CHECK (exclusion_reason IN (
                    'email_artifact',      -- Email header repetition inflation
                    'organization',        -- Not a person (company, firm, etc.)
                    'fragmented_name',     -- Incomplete name (first name only, etc.)
                    'legal_pseudonym',     -- Jane Doe, etc. (represents multiple individuals)
                    'unrelated_case',      -- Procedurally related but not substantively
                    'pending_review',      -- Not yet investigated
                    'ocr_artifact',        -- OCR error, not a real entity
                    'duplicate',           -- Duplicate of another entity
                    'location',            -- Physical location misidentified as person
                    'legal_term',          -- Legal term/statute misidentified as person
                    'joint_name_artifact'  -- OCR artifact joining two names
                ))
            );
        """)
        
        # Create indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_aliases_canonical 
            ON entity_aliases(canonical_name);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_aliases_alias 
            ON entity_aliases(alias_name);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_disambiguation_queue_status 
            ON name_disambiguation_queue(status);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_disambiguation_queue_confidence 
            ON name_disambiguation_queue(confidence_level);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_exclusions_reason
            ON entity_exclusions(exclusion_reason);
        """)
        
        conn.commit()
        if verbose:
            print("✓ Tables created successfully")


def load_known_aliases(conn, verbose: bool = False):
    """Load known aliases into the entity_aliases table.
    
    Also stores the canonical name itself as an alias (mapping to itself)
    to ensure get_canonical_name() returns the proper casing.
    """
    with conn.cursor() as cur:
        if verbose:
            print("\nLoading known aliases...")
        count = 0
        
        for canonical, aliases in KNOWN_ALIASES.items():
            # First, store the canonical name as an alias to itself
            # This ensures consistent casing in lookups
            try:
                cur.execute("""
                    INSERT INTO entity_aliases 
                    (canonical_name, alias_name, confidence_score, disambiguation_method, reviewed)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (canonical_name, alias_name) DO NOTHING
                """, (canonical, canonical, 1.0, 'manual', True))
                count += 1
            except Exception as e:
                if verbose:
                    print(f"  Warning: Could not insert canonical {canonical}: {e}")
            
            # Then store all aliases
            for alias in aliases:
                try:
                    cur.execute("""
                        INSERT INTO entity_aliases 
                        (canonical_name, alias_name, confidence_score, disambiguation_method, reviewed)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (canonical_name, alias_name) DO NOTHING
                    """, (canonical, alias, 1.0, 'manual', True))
                    count += 1
                except Exception as e:
                    if verbose:
                        print(f"  Warning: Could not insert {alias}: {e}")
        
        conn.commit()
        if verbose:
            print(f"✓ Loaded {count} known aliases")


def load_excluded_entities(conn, verbose: bool = False):
    """Load excluded entities into the entity_exclusions table."""
    with conn.cursor() as cur:
        if verbose:
            print("\nLoading excluded entities...")
        count = 0
        
        for entity_name, reason in EXCLUDED_ENTITIES.items():
            try:
                cur.execute("""
                    INSERT INTO entity_exclusions (entity_name, exclusion_reason)
                    VALUES (%s, %s)
                    ON CONFLICT (entity_name) DO UPDATE SET exclusion_reason = %s
                """, (entity_name, reason, reason))
                count += 1
            except Exception as e:
                if verbose:
                    print(f"  Warning: Could not insert exclusion {entity_name}: {e}")
        
        conn.commit()
        if verbose:
            print(f"✓ Loaded {count} entity exclusions")


def get_name_contexts(conn, verbose: bool = False) -> Dict[str, Set[str]]:
    """Get document contexts for each name (which documents mention each name)."""
    if verbose:
        print("\nLoading name contexts from database...")
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT name_string, file_path
            FROM extracted_names
            WHERE name_string IS NOT NULL
        """)
        
        name_contexts = {}
        for name, file_path in cur:
            if name not in name_contexts:
                name_contexts[name] = set()
            name_contexts[name].add(file_path)
    
    if verbose:
        print(f"✓ Loaded contexts for {len(name_contexts):,} unique names")
    return name_contexts


def find_similar_names(conn, name_contexts: Dict[str, Set[str]], verbose: bool = False):
    """Find similar names and add to disambiguation queue."""
    if verbose:
        print("\nAnalyzing name similarities...")
    
    # Get unique names
    names = list(name_contexts.keys())
    
    # Filter out obvious non-person names (single words, very short, common words)
    filtered_names = []
    for name in names:
        # Skip single character names
        if len(name) <= 1:
            continue
        # Skip very common words that are clearly not names
        if name.lower() in {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}:
            continue
        filtered_names.append(name)
    
    names = filtered_names
    names.sort()  # Sort for consistent processing
    
    if verbose:
        print(f"Analyzing {len(names):,} unique names...")
        print(f"\u26a0\ufe0f  This will do ~{len(names) * (len(names) - 1) // 2:,} comparisons")
        print("This may take 10-30 minutes depending on your system...")
        print("Optimization: Only comparing names with similar characteristics\n")
    
    # Group names by first letter (case-insensitive) and similar length for faster comparison
    from collections import defaultdict
    name_groups = defaultdict(list)
    for name in names:
        # Group by first letter (normalized and lowercase) and length bucket
        normalized = normalize_name(name).lower()
        first_letter = normalized[0] if normalized else 'other'
        length_bucket = len(name) // 5  # Group by length buckets of 5
        key = (first_letter, length_bucket)
        name_groups[key].append(name)
    
    if verbose:
        print(f"Grouped names into {len(name_groups)} groups for efficient comparison")
    
    candidates = []
    total_comparisons = 0
    processed_names = 0
    
    # Compare names within same groups and adjacent groups
    for (letter, length_bucket), group_names in sorted(name_groups.items()):
        # Compare within group
        for i, name1 in enumerate(group_names):
            processed_names += 1
            if verbose and processed_names % 1000 == 0:
                print(f"  Progress: {processed_names:,}/{len(names):,} names processed, {len(candidates):,} candidates found...")
            
            # Compare with rest of same group
            for name2 in group_names[i+1:]:
                total_comparisons += 1
                
                # Quick length check
                if abs(len(name1) - len(name2)) > 10:
                    continue
                
                # Calculate shared contexts
                shared = len(name_contexts[name1] & name_contexts[name2])
                
                # Calculate similarity score
                score = calculate_similarity_score(name1, name2, shared)
                
                # Add to candidates if score is high enough
                if score >= MEDIUM_CONFIDENCE_THRESHOLD:
                    candidates.append({
                        'name1': name1,
                        'name2': name2,
                        'score': score,
                        'shared': shared
                    })
            
            # Also compare with adjacent length buckets (same letter)
            for adj_bucket in [length_bucket - 1, length_bucket + 1]:
                adj_key = (letter, adj_bucket)
                if adj_key in name_groups:
                    for name2 in name_groups[adj_key]:
                        total_comparisons += 1
                        
                        # Quick length check
                        if abs(len(name1) - len(name2)) > 10:
                            continue
                        
                        # Calculate shared contexts
                        shared = len(name_contexts[name1] & name_contexts[name2])
                        
                        # Calculate similarity score
                        score = calculate_similarity_score(name1, name2, shared)
                        
                        # Add to candidates if score is high enough
                        if score >= MEDIUM_CONFIDENCE_THRESHOLD:
                            # Avoid duplicates
                            if name1 < name2:  # Consistent ordering
                                candidates.append({
                                    'name1': name1,
                                    'name2': name2,
                                    'score': score,
                                    'shared': shared
                                })
    
    if verbose:
        print(f"✓ Completed {total_comparisons:,} comparisons")
        print(f"✓ Found {len(candidates):,} potential aliases")
    
    # Insert candidates into queue
    if candidates:
        if verbose:
            print("\nInserting candidates into disambiguation queue...")
        with conn.cursor() as cur:
            for candidate in candidates:
                try:
                    # Determine confidence level based on similarity score
                    score = candidate['score']
                    if score > 0.85:
                        confidence = 'HIGH'
                    elif score >= 0.60:
                        confidence = 'MEDIUM'
                    else:
                        confidence = 'LOW'
                    
                    cur.execute("""
                        INSERT INTO name_disambiguation_queue 
                        (name_variant_1, name_variant_2, similarity_score, confidence_level, shared_contexts)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        candidate['name1'],
                        candidate['name2'],
                        candidate['score'],
                        confidence,
                        candidate['shared']
                    ))
                except Exception as e:
                    if verbose:
                        print(f"  Warning: Could not insert candidate: {e}")
        
        conn.commit()
        if verbose:
            print(f"✓ Inserted {len(candidates):,} candidates into queue")


def show_statistics(conn, verbose: bool = False):
    """Display statistics about entity disambiguation."""
    print("\n" + "=" * 80)
    print("ENTITY DISAMBIGUATION STATISTICS")
    print("=" * 80)
    
    with conn.cursor() as cur:
        # Total unique names
        cur.execute("SELECT COUNT(DISTINCT name_string) FROM extracted_names")
        total_names = cur.fetchone()[0]
        print(f"\n📊 Total unique names in database: {total_names:,}")
        
        # Aliases defined
        cur.execute("SELECT COUNT(*) FROM entity_aliases")
        alias_count = cur.fetchone()[0]
        print(f"📋 Defined aliases: {alias_count:,}")
        
        # Aliases by method
        cur.execute("""
            SELECT disambiguation_method, COUNT(*) 
            FROM entity_aliases 
            GROUP BY disambiguation_method 
            ORDER BY COUNT(*) DESC
        """)
        print(f"\n  Aliases by method:")
        for method, count in cur:
            print(f"    • {method}: {count:,}")
        
        # Reviewed vs unreviewed
        cur.execute("""
            SELECT reviewed, COUNT(*) 
            FROM entity_aliases 
            GROUP BY reviewed
        """)
        print(f"\n  Review status:")
        for reviewed, count in cur:
            status = "Reviewed" if reviewed else "Pending review"
            print(f"    • {status}: {count:,}")
        
        # Queue statistics
        cur.execute("""
            SELECT status, COUNT(*) 
            FROM name_disambiguation_queue 
            GROUP BY status 
            ORDER BY COUNT(*) DESC
        """)
        print(f"\n📋 Disambiguation queue:")
        for status, count in cur:
            print(f"    • {status}: {count:,}")
        
        # Confidence level breakdown
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
        print(f"\n📊 Confidence level breakdown:")
        for conf_level, count in cur:
            if conf_level == 'HIGH':
                print(f"    ⚡ {conf_level}: {count:,}")
            elif conf_level == 'MEDIUM':
                print(f"    📊 {conf_level}: {count:,}")
            else:
                print(f"    ⚠️ {conf_level}: {count:,}")


def show_review_queue(conn, limit: int = 20, verbose: bool = False):
    """Show pending disambiguation candidates for review."""
    print("\n" + "=" * 80)
    print("DISAMBIGUATION REVIEW QUEUE (Top matches)")
    print("=" * 80)
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2, 
                   similarity_score, confidence_level, shared_contexts, created_at
            FROM name_disambiguation_queue
            WHERE status = 'pending'
            ORDER BY similarity_score DESC, shared_contexts DESC
            LIMIT %s
        """, (limit,))
        
        results = cur.fetchall()
        
        if not results:
            print("\n✓ No pending items in queue")
            return
        
        print(f"\nShowing top {len(results)} candidates:\n")
        
        for queue_id, name1, name2, score, confidence, shared, created in results:
            conf_emoji = "⚡" if confidence == "HIGH" else "📊" if confidence == "MEDIUM" else "⚠️"
            print(f"ID: {queue_id}")
            print(f"  Name 1: {name1}")
            print(f"  Name 2: {name2}")
            print(f"  Similarity: {score:.3f} ({conf_emoji} {confidence} confidence)")
            print(f"  Shared documents: {shared}")
            print(f"  Created: {created.strftime('%Y-%m-%d %H:%M')}")
            print()


def create_canonicalization_function(conn, verbose: bool = False):
    """Create PostgreSQL function to canonicalize names using entity_aliases table."""
    if verbose:
        print("\nCreating name canonicalization function...")
    
    with conn.cursor() as cur:
        # Create a function that looks up canonical names and strips possessives
        cur.execute("""
            CREATE OR REPLACE FUNCTION get_canonical_name(input_name TEXT)
            RETURNS TEXT AS $$
            DECLARE
                canonical TEXT;
                normalized_input TEXT;
            BEGIN
                normalized_input := input_name;
                
                -- Strip email header suffixes (Sent, Cc, To, From, Subject, Re, Fwd)
                -- These appear when OCR captures email headers attached to names
                IF normalized_input ~ ' (Sent|Cc|To|From|Subject|Re|Fwd)$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, ' (Sent|Cc|To|From|Subject|Re|Fwd)$', '');
                END IF;
                
                -- Strip law firm signature artifacts (Partner, Counsel, Associate)
                -- These appear when OCR captures signature blocks
                IF normalized_input ~ ' (Partner|Counsel|Associate)$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, ' (Partner|Counsel|Associate)$', '');
                END IF;
                
                -- Strip document/form field suffixes (Date, DOCUMENT, Defendant, Documents)
                -- These appear when OCR captures form field labels attached to names
                IF normalized_input ~ ' (Date|DOCUMENT|Document|Defendant|Documents)$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, ' (Date|DOCUMENT|Document|Defendant|Documents)$', '');
                END IF;
                
                -- Strip possessive suffixes ('s or s' or 's or s')
                -- Handle both straight and curly apostrophes
                IF normalized_input ~ '['']s$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, '['']s$', '');
                ELSIF normalized_input ~ 's['']$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, 's['']$', 's');
                ELSIF normalized_input ~ '['']$' THEN
                    normalized_input := REGEXP_REPLACE(normalized_input, '['']$', '');
                END IF;
                
                -- First check if this name appears as an alias
                SELECT canonical_name INTO canonical
                FROM entity_aliases
                WHERE LOWER(alias_name) = LOWER(normalized_input)
                LIMIT 1;
                
                -- If found, return canonical name
                IF canonical IS NOT NULL THEN
                    RETURN canonical;
                END IF;
                
                -- Check if this name IS a canonical name with aliases
                SELECT canonical_name INTO canonical
                FROM entity_aliases
                WHERE LOWER(canonical_name) = LOWER(normalized_input)
                LIMIT 1;
                
                -- If found, return it (normalized)
                IF canonical IS NOT NULL THEN
                    RETURN canonical;
                END IF;
                
                -- Otherwise return normalized name (without possessive)
                RETURN normalized_input;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
        """)
        
        # Create an index to speed up lookups
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
            print("✓ Created get_canonical_name() function and indexes")
            print("  • Function strips email suffixes (Sent, Cc, To, From, Subject, Re, Fwd)")
            print("  • Function strips signature suffixes (Partner, Counsel, Associate)")
            print("  • Function strips document suffixes (Date, DOCUMENT, Document, Defendant, Documents)")
            print("  • Function strips possessive forms ('s, s', 's, s')")


def update_views_for_canonicalization(conn, verbose: bool = False):
    """Update views to use canonical names for accurate co-occurrence analysis."""
    if verbose:
        print("\nUpdating views to use canonical names...")
    
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
            -- Exclude email header artifacts (pattern-based)
            AND cc.entity_name !~ ' (Sent|Cc|To|From|Subject)$'
            ORDER BY cc.total_mentions DESC;
        """)
        
        if verbose:
            print("✓ Created v_entity_mentions view (with exclusion filtering and joint name splitting)")
        
        # Update person co-occurrence view to use canonical names, filter exclusions, and split joint names
        cur.execute("""
            CREATE OR REPLACE VIEW v_person_cooccurrence AS
            WITH base_names AS (
                -- Regular names (not joint names)
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
                
                -- Split joint names into their component parts
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
            -- Filter to only include multi-word names or names that resolve via aliases
            -- AND exclude entities in the exclusions table
            filtered_names AS (
                SELECT 
                    cn.file_path,
                    cn.canonical_name
                FROM 
                    canonical_names cn
                WHERE 
                    cn.canonical_name IS NOT NULL
                    -- Exclude entities marked for exclusion
                    AND NOT EXISTS (
                        SELECT 1 FROM entity_exclusions ee 
                        WHERE ee.entity_name = cn.canonical_name
                    )
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
        """)
        
        conn.commit()
        if verbose:
            print("✓ Updated v_person_cooccurrence to use canonical names (with exclusion filtering and joint name splitting)")
        
        # Show example of improvement
        if verbose:
            cur.execute("""
                SELECT person_1, person_2, shared_documents
                FROM v_person_cooccurrence
                WHERE person_1 ILIKE '%epstein%' OR person_2 ILIKE '%epstein%'
                ORDER BY shared_documents DESC
                LIMIT 5;
            """)
            
            results = cur.fetchall()
            if results:
                print("\nExample co-occurrences with Epstein (now unified):")
                for p1, p2, count in results:
                    print(f"  • {p1} \u2194 {p2}: {count} documents")


def auto_merge_high_confidence(conn, dry_run: bool = True, verbose: bool = False):
    """Automatically merge high-confidence matches."""
    print("\n" + "=" * 80)
    print("AUTO-MERGE HIGH CONFIDENCE MATCHES")
    print("=" * 80)
    
    with conn.cursor() as cur:
        # Get high confidence matches
        cur.execute("""
            SELECT queue_id, name_variant_1, name_variant_2, 
                   similarity_score, shared_contexts
            FROM name_disambiguation_queue
            WHERE status = 'pending'
            AND confidence_level = 'HIGH'
            ORDER BY similarity_score DESC
        """)
        
        matches = cur.fetchall()
        
        if not matches:
            print("\n✓ No high-confidence matches to merge")
            return
        
        print(f"\nFound {len(matches):,} high-confidence matches")
        
        if dry_run:
            print("\n⚠️  DRY RUN MODE - No changes will be made")
            print("\nWould merge:")
            for queue_id, name1, name2, score, shared in matches[:10]:
                print(f"  • {name1} → {name2} (score: {score:.3f}, shared: {shared})")
            if len(matches) > 10:
                print(f"  ... and {len(matches) - 10} more")
        else:
            print("\nMerging aliases...")
            merged = 0
            
            for queue_id, name1, name2, score, shared in matches:
                try:
                    # Choose canonical name (longer name or name1)
                    canonical = name1 if len(name1) >= len(name2) else name2
                    alias = name2 if canonical == name1 else name1
                    
                    # Insert into entity_aliases
                    cur.execute("""
                        INSERT INTO entity_aliases 
                        (canonical_name, alias_name, confidence_score, disambiguation_method)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (canonical_name, alias_name) DO NOTHING
                    """, (canonical, alias, score, 'automatic'))
                    
                    # Mark as merged in queue
                    cur.execute("""
                        UPDATE name_disambiguation_queue
                        SET status = 'merged', reviewed_at = NOW()
                        WHERE queue_id = %s
                    """, (queue_id,))
                    
                    merged += 1
                    
                except Exception as e:
                    print(f"  Error merging {name1}/{name2}: {e}")
            
            conn.commit()
            print(f"✓ Merged {merged:,} aliases")


def verify_integrity(conn, verbose: bool = False) -> bool:
    """Verify consistency between code, database, and documentation.
    
    Checks:
    1. KNOWN_ALIASES (code) matches entity_aliases table (database)
    2. get_canonical_name() function works for all aliases
    3. Reports expected counts for documentation validation
    
    Returns True if all checks pass, False otherwise.
    """
    import os
    
    print("\n" + "=" * 80)
    print("INTEGRITY VERIFICATION")
    print("=" * 80)
    
    all_passed = True
    
    # ─────────────────────────────────────────────────────────────────────────────
    # CHECK 1: Code ↔ Database Consistency
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n[1] CODE ↔ DATABASE CONSISTENCY")
    print("-" * 40)
    
    with conn.cursor() as cur:
        # Get database counts per entity
        cur.execute("""
            SELECT canonical_name, COUNT(*) as alias_count
            FROM entity_aliases
            GROUP BY canonical_name
            ORDER BY canonical_name
        """)
        db_counts = {row[0]: row[1] for row in cur.fetchall()}
    
    # Calculate code counts (canonical name + all aliases)
    code_counts = {canonical: len(aliases) + 1 for canonical, aliases in KNOWN_ALIASES.items()}
    
    # Find mismatches
    mismatches = []
    all_entities = sorted(set(code_counts.keys()) | set(db_counts.keys()))
    
    for name in all_entities:
        code_ct = code_counts.get(name, 0)
        db_ct = db_counts.get(name, 0)
        if code_ct != db_ct:
            mismatches.append((name, code_ct, db_ct))
    
    code_total_entities = len(code_counts)
    code_total_aliases = sum(code_counts.values())
    db_total_entities = len(db_counts)
    db_total_aliases = sum(db_counts.values())
    
    if mismatches:
        print("✗ MISMATCH DETECTED:")
        for name, code_ct, db_ct in mismatches:
            diff = code_ct - db_ct
            print(f"    {name}: code={code_ct}, db={db_ct} (diff={diff:+d})")
        all_passed = False
    else:
        print("✓ Code and database are consistent")
    
    print(f"\n  Code:     {code_total_entities} entities, {code_total_aliases} aliases")
    print(f"  Database: {db_total_entities} entities, {db_total_aliases} aliases")
    
    # ─────────────────────────────────────────────────────────────────────────────
    # CHECK 2: Canonicalization Function Works
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n[2] CANONICALIZATION FUNCTION")
    print("-" * 40)
    
    function_errors = []
    with conn.cursor() as cur:
        # Check if function exists
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_proc 
                WHERE proname = 'get_canonical_name'
            )
        """)
        function_exists = cur.fetchone()[0]
        
        if not function_exists:
            print("✗ get_canonical_name() function does not exist")
            print("  Run: python scripts/disambiguate_entities.py --create-function")
            all_passed = False
        else:
            # Test a sample of aliases
            test_count = 0
            for canonical, aliases in KNOWN_ALIASES.items():
                # Test the canonical name returns itself
                cur.execute("SELECT get_canonical_name(%s)", (canonical,))
                result = cur.fetchone()[0]
                if result != canonical:
                    function_errors.append((canonical, canonical, result))
                test_count += 1
                
                # Test each alias returns the canonical name
                for alias in aliases[:3]:  # Test first 3 aliases per entity
                    cur.execute("SELECT get_canonical_name(%s)", (alias,))
                    result = cur.fetchone()[0]
                    if result != canonical:
                        function_errors.append((canonical, alias, result))
                    test_count += 1
            
            if function_errors:
                print(f"✗ {len(function_errors)} canonicalization errors:")
                for expected, input_name, got in function_errors[:5]:
                    print(f"    '{input_name}' → expected '{expected}', got '{got}'")
                if len(function_errors) > 5:
                    print(f"    ... and {len(function_errors) - 5} more")
                all_passed = False
            else:
                print(f"✓ get_canonical_name() works correctly ({test_count} tests)")
    
    # ─────────────────────────────────────────────────────────────────────────────
    # CHECK 3: Entity Exclusions Integrity
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n[3] ENTITY EXCLUSIONS INTEGRITY")
    print("-" * 40)
    
    # Compare code exclusions with database
    code_exclusion_count = len(EXCLUDED_ENTITIES)
    
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM entity_exclusions")
        db_exclusion_count = cur.fetchone()[0]
        
        if code_exclusion_count != db_exclusion_count:
            print(f"✗ Exclusion count mismatch: code={code_exclusion_count}, database={db_exclusion_count}")
            all_passed = False
        else:
            print(f"✓ Exclusion counts match: {code_exclusion_count} entities excluded")
        
        # List exclusions by reason
        cur.execute("""
            SELECT exclusion_reason, COUNT(*) 
            FROM entity_exclusions 
            GROUP BY exclusion_reason 
            ORDER BY COUNT(*) DESC
        """)
        reason_counts = cur.fetchall()
        if reason_counts:
            print("\n  Exclusions by reason:")
            for reason, count in reason_counts:
                print(f"    - {reason}: {count}")
    
    # ─────────────────────────────────────────────────────────────────────────────
    # CHECK 4: Documentation Reference Values
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n[4] DOCUMENTATION REFERENCE VALUES")
    print("-" * 40)
    print("  Use these values to verify documentation is current:")
    print(f"    - Total Known Aliases: {code_total_aliases}")
    print(f"    - Unique Canonical Entities: {code_total_entities}")
    print(f"    - Excluded Entities: {code_exclusion_count}")
    print(f"    - Average Aliases per Entity: {code_total_aliases / code_total_entities:.1f}")
    
    # Top entities by variant count
    top_entities = sorted(KNOWN_ALIASES.items(), key=lambda x: len(x[1]) + 1, reverse=True)[:5]
    print("\n  Top entities by variant count:")
    for canonical, aliases in top_entities:
        print(f"    - {canonical}: {len(aliases) + 1}")
    
    # ─────────────────────────────────────────────────────────────────────────────
    # CHECK 5: Key Entity Statistics (from database)
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n[5] KEY ENTITY STATISTICS")
    print("-" * 40)
    
    key_entities = ['Jeffrey Epstein', 'Ghislaine Maxwell', 'Geoffrey S. Berman']
    
    with conn.cursor() as cur:
        for entity in key_entities:
            # Get mention counts using canonical name
            cur.execute("""
                SELECT 
                    COUNT(*) as total_mentions,
                    COUNT(DISTINCT file_path) as doc_count
                FROM extracted_names en
                JOIN entity_aliases ea ON en.name_string = ea.alias_name
                WHERE ea.canonical_name = %s
            """, (entity,))
            result = cur.fetchone()
            if result and result[0] > 0:
                print(f"  {entity}: {result[0]:,} mentions in {result[1]:,} documents")
            else:
                # Fallback: try direct match
                cur.execute("""
                    SELECT COUNT(*), COUNT(DISTINCT file_path)
                    FROM extracted_names
                    WHERE name_string = %s
                """, (entity,))
                result = cur.fetchone()
                print(f"  {entity}: {result[0]:,} mentions in {result[1]:,} documents (direct match)")
    
    # ─────────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    if all_passed:
        print("✓ ALL INTEGRITY CHECKS PASSED")
    else:
        print("✗ INTEGRITY ISSUES DETECTED - Review errors above")
        print("\n  To fix:")
        print("    1. Update KNOWN_ALIASES dictionary if needed")
        print("    2. Run: python scripts/disambiguate_entities.py --create-function --update-views -v")
        print("    3. Update documentation with correct counts")
    print("=" * 80)
    
    return all_passed


def main():
    parser = argparse.ArgumentParser(description='Entity Disambiguation & Resolution')
    parser.add_argument('--analyze', action='store_true', 
                       help='Analyze names and find potential aliases')
    parser.add_argument('--review', action='store_true',
                       help='Show disambiguation review queue')
    parser.add_argument('--stats', action='store_true',
                       help='Show disambiguation statistics')
    parser.add_argument('--merge', action='store_true',
                       help='Auto-merge high-confidence matches')
    parser.add_argument('--create-function', action='store_true',
                       help='Create PostgreSQL canonicalization function')
    parser.add_argument('--update-views', action='store_true',
                       help='Update views to use canonical names')
    parser.add_argument('--verify', action='store_true',
                       help='Verify integrity between code, database, and documentation')
    parser.add_argument('--clear', action='store_true',
                       help='Clear disambiguation queue and auto-generated aliases (requires --confirm)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode - show what would be done without making changes')
    parser.add_argument('--confirm', action='store_true',
                       help='Required for destructive operations (--clear)')
    parser.add_argument('--limit', type=int, default=20,
                       help='Limit for review queue display')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    
    args = parser.parse_args()
    
    # If no arguments, show help
    if not any([args.analyze, args.review, args.stats, args.merge, args.clear, 
                args.create_function, args.update_views, args.verify]):
        parser.print_help()
        return
    
    # Check for --confirm on destructive operations
    if args.clear and not args.confirm and not args.dry_run:
        print("ERROR: --clear requires --confirm flag for safety.")
        print("Use --dry-run to preview what would be cleared.")
        print("\nExample: python3 scripts/disambiguate_entities.py --clear --confirm")
        sys.exit(1)
    
    # Connect to database
    if args.verbose:
        print("Connecting to database...")
    
    with get_db_connection(DB_CONNECTION) as conn:
        # Create tables if needed
        create_tables(conn, args.verbose)
        
        # Load known aliases and exclusions
        load_known_aliases(conn, args.verbose)
        load_excluded_entities(conn, args.verbose)
        
        # Execute requested operations
        if args.clear:
            if args.dry_run:
                print("\n[DRY RUN] Would clear disambiguation data:")
                print("  - TRUNCATE name_disambiguation_queue")
                print("  - DELETE FROM entity_aliases WHERE disambiguation_method != 'manual'")
            else:
                if args.verbose:
                    print("\nClearing disambiguation data...")
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE TABLE name_disambiguation_queue")
                    cur.execute("DELETE FROM entity_aliases WHERE disambiguation_method != 'manual'")
                conn.commit()
                print("✓ Cleared disambiguation queue and auto-generated aliases")
        
        if args.analyze:
            name_contexts = get_name_contexts(conn, args.verbose)
            find_similar_names(conn, name_contexts, args.verbose)
        
        if args.review:
            show_review_queue(conn, args.limit, args.verbose)
        
        if args.merge:
            auto_merge_high_confidence(conn, dry_run=args.dry_run, verbose=args.verbose)
        
        if args.create_function:
            create_canonicalization_function(conn, args.verbose)
        
        if args.update_views:
            update_views_for_canonicalization(conn, args.verbose)
        
        if args.stats:
            show_statistics(conn, args.verbose)
        
        if args.verify:
            success = verify_integrity(conn, args.verbose)
            if not success:
                sys.exit(1)
        
        if args.verbose and not args.verify:
            print("\n" + "=" * 80)
            print("✓ Entity disambiguation complete")
            print("=" * 80)


if __name__ == '__main__':
    main()
