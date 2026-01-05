#!/usr/bin/env python3
"""Export visualization data to static JSON files for GitHub Pages hosting.

This script queries the PostgreSQL database and generates pre-computed JSON
files that replace dynamic API endpoints, enabling fully static hosting of
the document similarity network visualization.

The script exports:
    - Threshold metadata with persistence analysis (H0/H1 optimal thresholds)
    - Network data for each similarity threshold (nodes, edges, communities)
    - Entity network with relationships and centrality metrics
    - Temporal period definitions and document assignments
    - Document details and entity overlay data (chunked for efficiency)

Output Structure:
    static-viz/
    ├── index.html
    └── data/
        ├── thresholds.json          # Available thresholds with optimal
        ├── entity-network.json       # Entity relationship network
        ├── temporal-periods.json     # Time period definitions
        ├── entity-mentions-index.json # Document-to-entity lookup
        ├── networks/
        │   └── network_X.XX.json     # Network at each threshold
        ├── periods/
        │   └── period_ID_X.XX.json   # Documents per period/threshold
        ├── documents/
        │   └── docs_XXXX.json        # Document details (chunked)
        └── overlays/
            └── overlays_XXXX.json    # Entity overlays (chunked)

Example:
    Run from the scripts directory::

        $ cd scripts
        $ python export_static_data.py

    Or with conda environment::

        $ conda run -n network_env python export_static_data.py

Requires:
    - PostgreSQL database with document similarity tables populated
    - psycopg library for database connectivity
    - config.py with DATABASE_URL configured
"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict

import psycopg

# Import config to load .env file and get database URL
from config import DEFAULT_DSN
DB_URL = DEFAULT_DSN

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "static-viz"
DATA_DIR = OUTPUT_DIR / "data"

# Chunk size for document/overlay files
CHUNK_SIZE = 100


def ensure_dirs():
    """Create output directory structure for static JSON files.

    Creates the following directory hierarchy under static-viz/data/:
        - networks/: Network JSON files for each threshold
        - periods/: Period-filtered document lists
        - documents/: Chunked document detail files
        - overlays/: Chunked entity overlay files
    """
    dirs = [
        DATA_DIR,
        DATA_DIR / "networks",
        DATA_DIR / "periods",
        DATA_DIR / "documents",
        DATA_DIR / "overlays",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    print(f"Created output directories in {OUTPUT_DIR}")


def export_thresholds(conn):
    """Export threshold metadata with persistence-based optimal selection.

    Queries the database for available similarity thresholds and computes
    the optimal threshold using topological data analysis (persistent
    homology). The H0 threshold represents when major document clusters
    merge, while H1 represents when significant cycles form in the network.

    Args:
        conn: Active psycopg database connection.

    Returns:
        list: Available similarity threshold values (floats).

    Output File:
        data/thresholds.json containing:
            - thresholds: List of threshold objects with stats
            - optimal: Recommended threshold value
            - reason: JSON string with H0/H1 analysis details
    """
    print("Exporting thresholds...")
    cur = conn.cursor()
    
    # Get all threshold stats from communities table
    cur.execute("""
        SELECT similarity_threshold, 
               COUNT(DISTINCT doc_id) as node_count,
               COUNT(DISTINCT community) as community_count,
               AVG(modularity) as modularity
        FROM document_similarity_communities
        GROUP BY similarity_threshold
        ORDER BY similarity_threshold
    """)
    thresholds = []
    available_thresholds = []
    for row in cur.fetchall():
        threshold = float(row[0])
        available_thresholds.append(threshold)
        # Get edge count from pairs
        cur2 = conn.cursor()
        cur2.execute("""
            SELECT COUNT(*) FROM document_similarity_pairs
            WHERE cosine_similarity >= %s
        """, (threshold,))
        edge_count = cur2.fetchone()[0]
        
        thresholds.append({
            "similarity_threshold": threshold,
            "node_count": row[1],
            "edge_count": edge_count,
            "community_count": row[2],
            "modularity": float(row[3]) if row[3] else None
        })
    
    # Compute H0/H1 thresholds from persistence data
    h0_threshold = None
    h0_gap = 0
    h1_threshold = None
    h1_gap = 0
    
    # Get H0 death times (when components merge)
    cur.execute("""
        SELECT death FROM document_similarity_persistence
        WHERE dimension = 0 AND death < 1.0
        ORDER BY death DESC
    """)
    h0_deaths = [float(row[0]) for row in cur.fetchall()]
    
    # Find largest gap in H0 death times
    if len(h0_deaths) > 1:
        for i in range(len(h0_deaths) - 1):
            gap = h0_deaths[i] - h0_deaths[i + 1]
            if gap > h0_gap:
                h0_gap = gap
                h0_threshold = h0_deaths[i]
    
    # Get H1 birth times (when cycles form)
    cur.execute("""
        SELECT birth FROM document_similarity_persistence
        WHERE dimension = 1 AND birth > 0
        ORDER BY birth DESC
    """)
    h1_births = [float(row[0]) for row in cur.fetchall()]
    
    # Find largest gap in H1 birth times
    if len(h1_births) > 1:
        for i in range(len(h1_births) - 1):
            gap = h1_births[i] - h1_births[i + 1]
            if gap > h1_gap:
                h1_gap = gap
                h1_threshold = h1_births[i]
    
    # Snap to nearest available threshold
    def snap_to_nearest(value, options):
        if value is None or not options:
            return None
        nearest = min(options, key=lambda x: abs(x - value))
        return nearest
    
    h0_snapped = snap_to_nearest(h0_threshold, available_thresholds)
    h1_snapped = snap_to_nearest(h1_threshold, available_thresholds)
    
    # Determine optimal threshold based on larger normalized gap
    h0_range = max(h0_deaths) - min(h0_deaths) if len(h0_deaths) > 1 else 1
    h1_range = max(h1_births) - min(h1_births) if len(h1_births) > 1 else 1
    h0_score = h0_gap / h0_range if h0_range > 0 else 0
    h1_score = h1_gap / h1_range if h1_range > 0 else 0
    
    if h1_score > h0_score and h1_snapped is not None:
        optimal = h1_snapped
        selected = "H1"
    elif h0_snapped is not None:
        optimal = h0_snapped
        selected = "H0"
    else:
        # Fallback to highest modularity
        best = max(thresholds, key=lambda t: t["modularity"] or 0)
        optimal = best["similarity_threshold"]
        selected = "modularity"
    
    # Build reason JSON with H0/H1 data (same format as server.js)
    reason = json.dumps({
        "h0": {"threshold": h0_snapped, "gap": h0_gap, "raw": h0_threshold},
        "h1": {"threshold": h1_snapped, "gap": h1_gap, "raw": h1_threshold},
        "selected": selected
    })
    
    data = {
        "thresholds": thresholds,
        "optimal": optimal,
        "reason": reason
    }
    
    with open(DATA_DIR / "thresholds.json", "w") as f:
        json.dump(data, f, separators=(",", ":"))
    
    print(f"  Exported {len(thresholds)} thresholds (H0={h0_snapped}, H1={h1_snapped}, optimal={optimal})")
    return [t["similarity_threshold"] for t in thresholds]


def export_network(conn, threshold):
    """Export network data for a specific similarity threshold.

    Generates a complete network representation including nodes (documents),
    edges (similarity relationships), community assignments, and community
    labels derived from top noun terms.

    Args:
        conn: Active psycopg database connection.
        threshold: Similarity threshold value (float between 0 and 1).

    Returns:
        int: Number of nodes exported.

    Output File:
        data/networks/network_{threshold:.2f}.json containing:
            - nodes: Document nodes with centrality metrics
            - edges: Similarity edges above threshold
            - communityLabels: Top nouns per community
            - bridges: Bridge documents between communities
            - stats: Network statistics
    """
    cur = conn.cursor()
    
    # Get nodes from communities and centrality tables
    cur.execute("""
        SELECT c.doc_id, c.file_path, c.community, 
               COALESCE(cent.degree_centrality, 0) as degree,
               COALESCE(cent.betweenness_centrality, 0) as betweenness,
               COALESCE(cent.eigenvector_centrality, 0) as eigenvector,
               COALESCE(cent.closeness_centrality, 0) as pagerank,
               c.community_size
        FROM document_similarity_communities c
        LEFT JOIN document_similarity_centrality cent 
            ON c.doc_id = cent.doc_id AND c.similarity_threshold = cent.similarity_threshold
        WHERE c.similarity_threshold = %s
    """, (threshold,))
    
    nodes = []
    node_id_map = {}
    for i, row in enumerate(cur.fetchall()):
        node_id_map[row[0]] = i
        nodes.append({
            "id": i,
            "doc_id": row[0],
            "file_path": row[1],
            "community": row[2],
            "degree": float(row[3]) if row[3] else 0,
            "betweenness": float(row[4]) if row[4] else 0,
            "eigenvector": float(row[5]) if row[5] else 0,
            "pagerank": float(row[6]) if row[6] else 0,
            "community_size": row[7] or 0
        })
    
    # Get edges from similarity pairs
    cur.execute("""
        SELECT doc_id_1, doc_id_2, cosine_similarity
        FROM document_similarity_pairs
        WHERE cosine_similarity >= %s
    """, (threshold,))
    
    edges = []
    for row in cur.fetchall():
        if row[0] in node_id_map and row[1] in node_id_map:
            edges.append({
                "source": node_id_map[row[0]],
                "target": node_id_map[row[1]],
                "weight": float(row[2]) if row[2] else 0
            })
    
    # Get community labels
    cur.execute("""
        SELECT community, label, top_nouns
        FROM document_similarity_community_labels
        WHERE similarity_threshold = %s
    """, (threshold,))
    
    community_labels = {}
    for row in cur.fetchall():
        community_labels[str(row[0])] = {
            "label": row[1],
            "top_terms": row[2]
        }
    
    data = {
        "nodes": nodes,
        "edges": edges,
        "communityLabels": community_labels,
        "stats": {
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "communityCount": len(set(n["community"] for n in nodes))
        }
    }
    
    filename = DATA_DIR / "networks" / f"network_{threshold:.2f}.json"
    with open(filename, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    
    return len(nodes), len(edges)


def export_all_networks(conn, thresholds):
    """Export network data for all available thresholds.

    Iterates through all threshold values and generates corresponding
    network JSON files.

    Args:
        conn: Active psycopg database connection.
        thresholds: List of similarity threshold values to export.
    """
    print("Exporting networks...")
    for t in thresholds:
        nodes, edges = export_network(conn, t)
        print(f"  {t:.2f}: {nodes} nodes, {edges} edges")


def export_temporal_periods(conn):
    """Export temporal period definitions with document counts.

    Generates predefined historical periods relevant to the Epstein case
    and counts how many documents fall within each period based on
    extracted dates.

    Args:
        conn: Active psycopg database connection.

    Returns:
        list: Period IDs for subsequent exports.

    Output File:
        data/temporal-periods.json containing period definitions.
    """
    print("Exporting temporal periods...")
    cur = conn.cursor()
    
    # Generate periods from the date range in the data
    # Use predefined historical periods relevant to the case
    periods = [
        {"id": "all", "name": "All Periods", "startYear": 1990, "endYear": 2025, 
         "description": "All documents regardless of date"},
        {"id": "early", "name": "Early Period", "startYear": 1990, "endYear": 1999,
         "description": "1990s - Early financial activities"},
        {"id": "peak", "name": "Peak Activity", "startYear": 2000, "endYear": 2008,
         "description": "2000-2008 - Height of operations"},
        {"id": "investigation", "name": "First Investigation", "startYear": 2005, "endYear": 2011,
         "description": "2005-2011 - Initial investigations and plea deal"},
        {"id": "civil", "name": "Civil Litigation", "startYear": 2008, "endYear": 2017,
         "description": "2008-2017 - Civil lawsuits and settlements"},
        {"id": "arrest", "name": "Arrest & Aftermath", "startYear": 2019, "endYear": 2025,
         "description": "2019-present - Arrest, death, Maxwell trial"}
    ]
    
    # Count documents per period
    for period in periods:
        if period["id"] == "all":
            cur.execute("SELECT COUNT(DISTINCT doc_id) FROM document_similarity_communities")
        else:
            cur.execute("""
                SELECT COUNT(DISTINCT c.doc_id) 
                FROM document_similarity_communities c
                JOIN extracted_dates ed ON c.file_path = ed.file_path
                WHERE EXTRACT(YEAR FROM ed.date_datetime) >= %s 
                  AND EXTRACT(YEAR FROM ed.date_datetime) <= %s
            """, (period["startYear"], period["endYear"]))
        period["documentCount"] = cur.fetchone()[0]
    
    with open(DATA_DIR / "temporal-periods.json", "w") as f:
        json.dump({"periods": periods}, f, separators=(",", ":"))
    
    print(f"  Exported {len(periods)} periods")
    return [p["id"] for p in periods]


def export_period_documents(conn, period_id, threshold):
    """Export document list for a specific period and threshold.

    Queries documents that fall within the specified temporal period
    and are part of the network at the given similarity threshold.

    Args:
        conn: Active psycopg database connection.
        period_id: Period identifier ('all', 'early', 'peak', etc.).
        threshold: Similarity threshold value.

    Returns:
        int: Number of documents exported.

    Output File:
        data/periods/period_{period_id}_{threshold:.2f}.json
    """
    cur = conn.cursor()
    
    if period_id == "all":
        cur.execute("""
            SELECT DISTINCT file_path
            FROM document_similarity_communities
            WHERE similarity_threshold = %s
        """, (threshold,))
    else:
        # Define period year ranges
        period_ranges = {
            "early": (1990, 1999),
            "peak": (2000, 2008),
            "investigation": (2005, 2011),
            "civil": (2008, 2017),
            "arrest": (2019, 2025)
        }
        start_year, end_year = period_ranges.get(period_id, (1990, 2025))
        
        cur.execute("""
            SELECT DISTINCT c.file_path
            FROM document_similarity_communities c
            JOIN extracted_dates ed ON c.file_path = ed.file_path
            WHERE c.similarity_threshold = %s
              AND EXTRACT(YEAR FROM ed.date_datetime) >= %s
              AND EXTRACT(YEAR FROM ed.date_datetime) <= %s
        """, (threshold, start_year, end_year))
    
    file_paths = [row[0] for row in cur.fetchall()]
    
    filename = DATA_DIR / "periods" / f"period_{period_id}_{threshold:.2f}.json"
    with open(filename, "w") as f:
        json.dump({"filePaths": file_paths}, f, separators=(",", ":"))
    
    return len(file_paths)


def export_all_periods(conn, period_ids, thresholds):
    """Export period documents for all period/threshold combinations.

    Args:
        conn: Active psycopg database connection.
        period_ids: List of period identifiers.
        thresholds: List of similarity threshold values.
    """
    print("Exporting period documents...")
    count = 0
    for pid in period_ids:
        for t in thresholds:
            export_period_documents(conn, pid, t)
            count += 1
    print(f"  Exported {count} period files")


def export_entity_network(conn):
    """Export the entity relationship network.

    Generates a network of persons, companies, and organizations with
    their relationships and centrality metrics from the entity tables.

    Args:
        conn: Active psycopg database connection.

    Output File:
        data/entity-network.json containing:
            - nodes: Entities with types and metrics
            - edges: Relationships between entities
            - stats: Network summary statistics
    """
    print("Exporting entity network...")
    cur = conn.cursor()
    
    # Get entities with stats
    cur.execute("""
        SELECT e.entity_id, e.entity_name, e.entity_type, e.description,
               c.degree, c.betweenness_centrality, c.eigenvector_centrality, c.pagerank,
               c.person_subgraph_degree, c.person_subgraph_betweenness, 
               c.person_subgraph_eigenvector, c.projection_degree
        FROM entity_network_entities e
        LEFT JOIN entity_network_centrality c ON e.entity_id = c.entity_id
    """)
    
    nodes = []
    entity_map = {}
    for row in cur.fetchall():
        entity_map[row[0]] = len(nodes)
        nodes.append({
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "description": row[3],
            "degree": float(row[4]) if row[4] else 0,
            "betweenness": float(row[5]) if row[5] else 0,
            "eigenvector": float(row[6]) if row[6] else 0,
            "pagerank": float(row[7]) if row[7] else 0,
            "person_degree": float(row[8]) if row[8] else 0,
            "person_betweenness": float(row[9]) if row[9] else 0,
            "person_eigenvector": float(row[10]) if row[10] else 0,
            "company_degree": float(row[11]) if row[11] else 0
        })
    
    # Get relationships with sources
    cur.execute("""
        SELECT r.source_entity_id, r.target_entity_id, r.relationship_type,
               r.confidence_score, r.source_reference
        FROM entity_network_relationships r
    """)
    
    edges = []
    for row in cur.fetchall():
        if row[0] in entity_map and row[1] in entity_map:
            edges.append({
                "source": row[0],
                "target": row[1],
                "relationship_type": row[2],
                "confidence": float(row[3]) if row[3] else 1.0,
                "source_reference": row[4]
            })
    
    # Get sources for edges
    cur.execute("""
        SELECT rs.relationship_id, s.citation_chicago, s.url
        FROM entity_network_relationship_sources rs
        JOIN entity_network_sources s ON rs.source_id = s.source_id
    """)
    
    rel_sources = defaultdict(list)
    for row in cur.fetchall():
        rel_sources[row[0]].append({"citation": row[1], "url": row[2]})
    
    # Add sources to edges (need relationship_id)
    cur.execute("""
        SELECT relationship_id, source_entity_id, target_entity_id, relationship_type
        FROM entity_network_relationships
    """)
    rel_id_map = {}
    for row in cur.fetchall():
        key = (row[1], row[2], row[3])
        rel_id_map[key] = row[0]
    
    for edge in edges:
        key = (edge["source"], edge["target"], edge["relationship_type"])
        rel_id = rel_id_map.get(key)
        if rel_id and rel_id in rel_sources:
            edge["sources"] = rel_sources[rel_id]
    
    # Get source count
    cur.execute("SELECT COUNT(DISTINCT source_id) FROM entity_network_sources")
    source_count = cur.fetchone()[0]
    
    data = {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "entityCount": len(nodes),
            "relationshipCount": len(edges),
            "sourceCount": source_count
        }
    }
    
    with open(DATA_DIR / "entity-network.json", "w") as f:
        json.dump(data, f, separators=(",", ":"))
    
    print(f"  Exported {len(nodes)} entities, {len(edges)} relationships")


def export_entity_mentions_index(conn):
    """Export an index mapping entities to their document mentions.

    Creates a lookup table that maps each entity_id to the list of EFTA
    document IDs where that entity is mentioned, enabling efficient
    client-side filtering.

    Args:
        conn: Active psycopg database connection.

    Output File:
        data/entity-mentions-index.json mapping entity IDs to document lists.
    """
    print("Exporting entity mentions index...")
    cur = conn.cursor()
    
    # Get all entity mentions
    cur.execute("""
        SELECT entity_id, file_path
        FROM entity_network_mentions
        ORDER BY entity_id
    """)
    
    from collections import defaultdict
    entity_docs = defaultdict(list)
    for row in cur.fetchall():
        # Extract just the EFTA ID from the file path for compactness
        import re
        match = re.search(r'(EFTA\d+)', row[1])
        if match:
            entity_docs[row[0]].append(match.group(1))
    
    # Convert to regular dict for JSON
    data = {str(k): v for k, v in entity_docs.items()}
    
    with open(DATA_DIR / "entity-mentions-index.json", "w") as f:
        json.dump(data, f, separators=(",", ":"))
    
    print(f"  Exported index for {len(data)} entities")


def get_all_efta_ids(conn):
    """Get all EFTA document IDs from the similarity network.

    Extracts unique document identifiers from all documents that appear
    in the document similarity network.

    Args:
        conn: Active psycopg database connection.

    Returns:
        list: Sorted list of unique EFTA IDs (e.g., 'EFTA00005578').
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT file_path
        FROM document_similarity_communities
    """)
    
    efta_ids = []
    for row in cur.fetchall():
        # Extract EFTA ID from path
        import re
        match = re.search(r'(EFTA\d+)', row[0])
        if match:
            efta_ids.append(match.group(1))
    
    return sorted(set(efta_ids))


def extract_substantive_opener(text, max_length=200):
    """Extract the first substantive paragraph from document text.

    Intelligently skips email headers, page numbers, OCR artifacts, and
    other metadata to find actual document content. Logic is synchronized
    with server.js for consistency between static and dynamic modes.

    Args:
        text: Raw document text content.
        max_length: Maximum length of returned opener (default: 200).

    Returns:
        str: First substantive sentences from the document, truncated
            with '...' if exceeding max_length.
    """
    import re
    
    # Pre-clean the text (matches server.js cleanedText logic)
    cleaned_text = text
    cleaned_text = re.sub(r'^\s*\d+\s*$', '', cleaned_text, flags=re.MULTILINE)  # Remove standalone line numbers
    cleaned_text = re.sub(r'EFTA\d+', '', cleaned_text)  # Remove EFTA references
    cleaned_text = re.sub(r'\n{2,}', '\n', cleaned_text)  # Collapse multiple newlines
    cleaned_text = re.sub(r'^\s*[-_=*]+\s*$', '', cleaned_text, flags=re.MULTILINE)  # Remove separator lines
    cleaned_text = re.sub(r'^\s*Page\s+\d+.*$', '', cleaned_text, flags=re.MULTILINE | re.IGNORECASE)  # Remove page markers
    cleaned_text = re.sub(r'^\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\s*$', '', cleaned_text, flags=re.MULTILINE)  # Remove standalone dates
    cleaned_text = cleaned_text.strip()
    
    # Split into lines for filtering
    lines = [l.strip() for l in cleaned_text.split('\n') if l.strip()]
    
    # Patterns that indicate email headers/metadata (skip entire line if matched)
    # Synced with server.js skipPatterns
    skip_patterns = [
        r'^(from|to|cc|bcc|subject|date|sent|received):\s*',  # Email headers at start
        r'\b(from|to|cc|bcc|subject|date|sent):\s*',  # These keywords anywhere
        r'^(re|fw|fwd):\s*',  # Reply/forward markers
        r'\bsubject:\s*(re|fw|fwd)?:?\s*',  # Subject with optional re/fw
        r'@[a-zA-Z0-9.-]+\.(com|org|net|edu|gov|co\.\w+)',  # Email domains
        r'[®@][a-zA-Z]+\.(com|org|net)',  # OCR-mangled emails
        r'\([^)]*[@®][^)]*\)',  # Anything with @ in parentheses
        r'<[^>]*@[^>]*>',  # <email@domain> format
        r'<[^>]*>',  # Any <bracketed> content (often emails)
        r'^(monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s*\d',  # Day + date
        r'^\d{1,2}:\d{2}\s*(am|pm)?',  # Time at start
        r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d',  # Month + date
        r'^\s*\d+\s*$',  # Just a number
        r'^[-_=*\s]+$',  # Separator lines
        r'^(confidential|privileged|attorney.client)',  # Legal markers
        r'^(sent from|get outlook|inline-images)',  # Email client artifacts
        r'^\s*\[.*\]\s*$',  # Bracketed content only
        r'^(attachment|enclosed|please see attached)',  # Attachment references
        r'^dear\s+',  # Salutations
        r'^(sincerely|regards|best|thanks),?\s*$',  # Sign-offs
        r'^\s*-{2,}\s*(original|forwarded)',  # Forwarded message markers
        r'^[A-Z]{2,}\s+[A-Z]\s+[A-Z]{2,}\s*$',  # ALL CAPS names (JOHN A SMITH)
        r'^[A-Z][A-Z\s]{5,}$',  # ALL CAPS text (headers)
        r"'[A-Z][A-Z\s]+'|\"[A-Z][A-Z\s]+\"",  # 'QUOTED CAPS' names
        r'us\s+v\.\s*$',  # Legal case fragments
        r'^wrote:?\s*$',  # Email quote markers
        r'^on\s+\d+/\d+',  # "On 1/1/2020" email headers
        r'\+\d{1,3}\s*\d{3}',  # Phone numbers
        r'\bP\.?C\.?\s*$',  # Law firm suffixes
        r'\bL\.?L\.?P\.?\s*$',  # Law firm suffixes
        r'\bEsq\.?\s*$',  # Attorney title
        r'Partner\s*$',  # Partner title
        r'^\d+\s+(E\.|W\.|N\.|S\.)?\s*\d*(st|nd|rd|th)?\s*(Street|Avenue|Ave|St)',  # Addresses
    ]
    
    # Compile patterns for efficiency
    skip_re = [re.compile(p, re.IGNORECASE) for p in skip_patterns]
    
    # Find lines that are actual content (skip headers and short lines)
    content_lines = []
    in_header = True
    
    for line in lines:
        # Check if this line matches skip patterns
        should_skip = any(pattern.search(line) for pattern in skip_re)
        
        # If we're still in header area and see a skip pattern, continue skipping
        if in_header and should_skip:
            continue
        
        # If line is too short or looks like metadata, skip
        if len(line) < 20:
            continue
        
        # Check if line has enough actual words (not just numbers/symbols)
        words = [w for w in line.split() if re.search(r'[a-zA-Z]{2,}', w)]
        if len(words) < 4:
            continue
        
        # This looks like real content - we've exited the header
        in_header = False
        content_lines.append(line)
        
        # Collect enough lines for a good summary
        if len(content_lines) >= 5:
            break
    
    # Join content and extract sentences
    content_text = ' '.join(content_lines)
    sentences = [s.replace('\s+', ' ').strip() for s in re.split(r'[.!?]+', content_text)]
    sentences = [s for s in sentences if len(s) > 30 and re.search(r'[a-zA-Z]{3,}', s)]
    
    summary_opener = '. '.join(sentences[:2]).strip()
    
    if summary_opener:
        # Truncate if needed
        if len(summary_opener) > max_length:
            truncated = summary_opener[:max_length]
            last_space = truncated.rfind(' ')
            if last_space > max_length * 0.7:
                truncated = truncated[:last_space]
            return truncated + "..."
        return summary_opener + '.' if not summary_opener.endswith('.') else summary_opener
    
    # Fallback: if no substantive paragraph found, return first 200 chars
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


def export_document_details(conn, efta_id):
    """Export details for a single document.

    Retrieves document metadata, text summary, mentioned entities,
    known relationships, and top noun terms for a specific document.

    Args:
        conn: Active psycopg database connection.
        efta_id: Document identifier (e.g., 'EFTA00005578').

    Returns:
        dict: Document details including file_path, summary_opener,
            word_count, entities, known_relationships, and top_nouns.
            Returns None if document not found.
    """
    cur = conn.cursor()
    
    # Get file path for this EFTA ID
    cur.execute("""
        SELECT file_path FROM extracted_text_content
        WHERE file_path LIKE %s
        LIMIT 1
    """, (f"%{efta_id}%",))
    path_row = cur.fetchone()
    if not path_row:
        return None
    
    file_path = path_row[0]
    
    # Get word count
    cur.execute("""
        SELECT word_count FROM extracted_text_content
        WHERE file_path = %s
        LIMIT 1
    """, (file_path,))
    wc_row = cur.fetchone()
    word_count = wc_row[0] if wc_row else None
    
    # Get summary opener from the view if available - find first substantive paragraph
    summary_opener = None
    try:
        cur.execute("""
            SELECT raw_text FROM extracted_text_content
            WHERE file_path = %s
            LIMIT 1
        """, (file_path,))
        text_row = cur.fetchone()
        if text_row and text_row[0]:
            text = text_row[0].strip()
            summary_opener = extract_substantive_opener(text)
    except:
        pass
    
    # Get entities mentioned
    cur.execute("""
        SELECT e.entity_name, m.mention_count
        FROM entity_network_mentions m
        JOIN entity_network_entities e ON m.entity_id = e.entity_id
        WHERE m.file_path LIKE %s
        ORDER BY m.mention_count DESC
    """, (f"%{efta_id}%",))
    entities = [{"entity_name": row[0], "mention_count": row[1]} for row in cur.fetchall()]
    
    # Get known relationships between mentioned entities
    known_relationships = []
    if entities:
        entity_names = [e["entity_name"] for e in entities]
        placeholders = ",".join(["%s"] * len(entity_names))
        cur.execute(f"""
            SELECT e1.entity_name, r.relationship_type, e2.entity_name
            FROM entity_network_relationships r
            JOIN entity_network_entities e1 ON r.source_entity_id = e1.entity_id
            JOIN entity_network_entities e2 ON r.target_entity_id = e2.entity_id
            WHERE e1.entity_name IN ({placeholders}) AND e2.entity_name IN ({placeholders})
        """, entity_names + entity_names)
        known_relationships = [
            {"source_name": row[0], "relationship_type": row[1], "target_name": row[2]}
            for row in cur.fetchall()
        ]
    
    # Get top nouns via TDM vocabulary
    cur.execute("""
        SELECT v.term, c.count
        FROM noun_tdm_counts c
        JOIN noun_tdm_vocabulary v ON c.term_id = v.term_id
        JOIN noun_tdm_documents d ON c.doc_id = d.doc_id
        WHERE d.file_path LIKE %s
        ORDER BY c.count DESC
        LIMIT 8
    """, (f"%{efta_id}%",))
    top_nouns = [{"term": row[0]} for row in cur.fetchall()]
    
    return {
        "file_path": file_path,
        "summary_opener": summary_opener,
        "word_count": word_count,
        "entities": entities,
        "known_relationships": known_relationships,
        "top_nouns": top_nouns
    }


def export_entity_overlay(conn, efta_id):
    """Export entity overlay data for a document.

    Retrieves entities mentioned in the document along with their
    business associations. Shared document computation is deferred
    to client-side for efficiency.

    Args:
        conn: Active psycopg database connection.
        efta_id: Document identifier (e.g., 'EFTA00005578').

    Returns:
        dict: Entity overlay with entities and their associations.
            Returns None if no entities found.
    """
    cur = conn.cursor()
    
    # Get entities mentioned in this document
    cur.execute("""
        SELECT e.entity_id, e.entity_name, e.entity_type, m.mention_count
        FROM entity_network_mentions m
        JOIN entity_network_entities e ON m.entity_id = e.entity_id
        WHERE m.file_path LIKE %s
        ORDER BY m.mention_count DESC
    """, (f"%{efta_id}%",))
    
    entities = []
    for row in cur.fetchall():
        entities.append({
            "entity_id": row[0],
            "entity_name": row[1],
            "entity_type": row[2],
            "mention_count": row[3]
        })
    
    if not entities:
        return None
    
    # Get businesses/associations for each entity
    for entity in entities:
        cur.execute("""
            SELECT e2.entity_name, r.relationship_type
            FROM entity_network_relationships r
            JOIN entity_network_entities e2 ON r.target_entity_id = e2.entity_id
            WHERE r.source_entity_id = %s AND e2.entity_type = 'company'
        """, (entity["entity_id"],))
        entity["businesses"] = [
            {"name": row[0], "role": row[1]} for row in cur.fetchall()
        ]
    
    # shared_documents computed client-side using entity-mentions-index.json
    return {
        "entities": entities
    }


def export_documents_chunked(conn, efta_ids):
    """Export document details in chunked JSON files.

    Groups documents by their numeric ID into chunks of CHUNK_SIZE (100)
    to optimize loading performance in the browser.

    Args:
        conn: Active psycopg database connection.
        efta_ids: List of EFTA document identifiers to export.

    Output Files:
        data/documents/docs_XXXX.json where XXXX is the chunk number.
    """
    print("Exporting document details...")
    
    chunks = {}
    for efta_id in efta_ids:
        # Calculate chunk number
        num = int(efta_id.replace("EFTA", ""))
        chunk_num = (num - 1) // CHUNK_SIZE + 1
        chunk_key = f"{chunk_num:04d}"
        
        if chunk_key not in chunks:
            chunks[chunk_key] = {}
        
        details = export_document_details(conn, efta_id)
        if details:
            chunks[chunk_key][efta_id] = details
    
    # Write chunks
    for chunk_key, data in chunks.items():
        filename = DATA_DIR / "documents" / f"docs_{chunk_key}.json"
        with open(filename, "w") as f:
            json.dump(data, f, separators=(",", ":"))
    
    print(f"  Exported {len(efta_ids)} documents in {len(chunks)} chunks")


def export_overlays_chunked(conn, efta_ids):
    """Export entity overlay data in chunked JSON files.

    Groups overlays by document numeric ID into chunks of CHUNK_SIZE (100)
    to optimize loading performance in the browser.

    Args:
        conn: Active psycopg database connection.
        efta_ids: List of EFTA document identifiers to export.

    Output Files:
        data/overlays/overlays_XXXX.json where XXXX is the chunk number.
    """
    print("Exporting entity overlays...")
    
    chunks = {}
    exported = 0
    for efta_id in efta_ids:
        num = int(efta_id.replace("EFTA", ""))
        chunk_num = (num - 1) // CHUNK_SIZE + 1
        chunk_key = f"{chunk_num:04d}"
        
        if chunk_key not in chunks:
            chunks[chunk_key] = {}
        
        overlay = export_entity_overlay(conn, efta_id)
        if overlay and overlay["entities"]:
            chunks[chunk_key][efta_id] = overlay
            exported += 1
    
    # Write chunks
    for chunk_key, data in chunks.items():
        if data:  # Only write non-empty chunks
            filename = DATA_DIR / "overlays" / f"overlays_{chunk_key}.json"
            with open(filename, "w") as f:
                json.dump(data, f, separators=(",", ":"))
    
    non_empty_chunks = sum(1 for d in chunks.values() if d)
    print(f"  Exported {exported} overlays in {non_empty_chunks} chunks")


def calculate_size():
    """Calculate total size of exported data files.

    Walks the data directory tree and sums file sizes.

    Returns:
        int: Total size in bytes.
    """
    total = 0
    for root, dirs, files in os.walk(DATA_DIR):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def main():
    """Main entry point for static data export.

    Orchestrates the complete export process:
        1. Creates output directory structure
        2. Exports threshold metadata with persistence analysis
        3. Exports network data for all thresholds
        4. Exports temporal period definitions
        5. Exports entity network with relationships
        6. Exports document details and entity overlays (chunked)
        7. Reports total export size

    Raises:
        SystemExit: If database connection fails.
    """
    print("=" * 60)
    print("Static Data Export for GitHub Pages")
    print("=" * 60)
    
    ensure_dirs()
    
    with psycopg.connect(DB_URL) as conn:
        # Export thresholds and get list
        thresholds = export_thresholds(conn)
        
        # Export all networks
        export_all_networks(conn, thresholds)
        
        # Export temporal periods
        period_ids = export_temporal_periods(conn)
        
        # Export period documents
        export_all_periods(conn, period_ids, thresholds)
        
        # Export entity network
        export_entity_network(conn)
        
        # Export entity mentions index (for computing shared docs client-side)
        export_entity_mentions_index(conn)
        
        # Get all EFTA IDs
        efta_ids = get_all_efta_ids(conn)
        print(f"Found {len(efta_ids)} unique documents")
        
        # Export document details (chunked)
        export_documents_chunked(conn, efta_ids)
        
        # Export entity overlays (chunked)
        export_overlays_chunked(conn, efta_ids)
    
    # Calculate total size
    total_size = calculate_size()
    print("=" * 60)
    print(f"Export complete!")
    print(f"Total size: {total_size / 1024 / 1024:.2f} MB")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
