#!/usr/bin/env python3
"""Build a document similarity network and compute persistent homology.

This script:
1. Loads term-document matrix from PostgreSQL (noun or verb TDM)
2. Computes TF-IDF weighted document vectors
3. Calculates pairwise cosine similarity between documents
4. Builds a filtration by sweeping through similarity thresholds
5. Computes persistent homology to find topological features that persist
6. Stores results in PostgreSQL tables

Persistent Homology Background:
    - H0 (dimension 0): Connected components - tracks when documents cluster together
    - H1 (dimension 1): Cycles/holes - tracks when loops form in the similarity network
    - Birth: Similarity threshold at which a feature appears
    - Death: Similarity threshold at which a feature disappears (merges or fills in)
    - Persistence: Death - Birth (longer = more significant feature)

Database Schema:
    document_similarity_pairs: Pairwise similarity scores (edge list)
    document_similarity_persistence: Persistence diagram (birth/death of features)
    document_similarity_metadata: Processing statistics and parameters

Usage:
    python3 scripts/build_document_similarity_network.py --dsn postgresql://user@localhost/postgres --verbose
    
    # Use verb TDM instead of noun TDM
    python3 scripts/build_document_similarity_network.py --tdm-type verb --verbose
    
    # Limit to top N documents by term count for faster computation
    python3 scripts/build_document_similarity_network.py --max-docs 1000 --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np
from scipy import sparse
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.metrics.pairwise import cosine_similarity

try:
    import psycopg
    from psycopg import Connection
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

# Optional: ripser for fast persistent homology computation
try:
    import ripser
    RIPSER_AVAILABLE = True
except ImportError:
    RIPSER_AVAILABLE = False

# Optional: gudhi as alternative TDA library
try:
    import gudhi
    GUDHI_AVAILABLE = True
except ImportError:
    GUDHI_AVAILABLE = False

# Optional: matplotlib for barcode visualization
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# Optional: networkx for network visualization
try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False

from config import DEFAULT_DSN
from db_utils import get_db_connection, table_exists


# ============================================================================
# DATABASE SCHEMA
# ============================================================================

CREATE_SIMILARITY_PAIRS_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_pairs (
    pair_id SERIAL PRIMARY KEY,
    doc_id_1 INTEGER NOT NULL,
    doc_id_2 INTEGER NOT NULL,
    file_path_1 TEXT NOT NULL,
    file_path_2 TEXT NOT NULL,
    cosine_similarity FLOAT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(doc_id_1, doc_id_2)
);

CREATE INDEX IF NOT EXISTS idx_sim_doc1 ON document_similarity_pairs(doc_id_1);
CREATE INDEX IF NOT EXISTS idx_sim_doc2 ON document_similarity_pairs(doc_id_2);
CREATE INDEX IF NOT EXISTS idx_sim_score ON document_similarity_pairs(cosine_similarity DESC);
"""

CREATE_PERSISTENCE_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_persistence (
    feature_id SERIAL PRIMARY KEY,
    dimension INTEGER NOT NULL,  -- 0 = connected component, 1 = cycle/hole
    birth FLOAT NOT NULL,        -- Similarity threshold at which feature appears
    death FLOAT,                 -- Similarity threshold at which feature disappears (NULL = infinite)
    persistence FLOAT,           -- death - birth (NULL if infinite)
    birth_edge_doc1 INTEGER,     -- Document ID of edge that created feature
    birth_edge_doc2 INTEGER,     -- Document ID of edge that created feature
    representative_cycle TEXT,   -- JSON array of document IDs forming the cycle (for H1)
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pers_dim ON document_similarity_persistence(dimension);
CREATE INDEX IF NOT EXISTS idx_pers_persistence ON document_similarity_persistence(persistence DESC NULLS FIRST);
CREATE INDEX IF NOT EXISTS idx_pers_birth ON document_similarity_persistence(birth);
"""

CREATE_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);
"""

CREATE_BETTI_NUMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_betti_numbers (
    threshold_id SERIAL PRIMARY KEY,
    similarity_threshold FLOAT NOT NULL,
    betti_0 INTEGER NOT NULL,  -- Number of connected components
    betti_1 INTEGER NOT NULL,  -- Number of cycles/holes
    num_edges INTEGER NOT NULL,  -- Edges at this threshold
    num_vertices INTEGER NOT NULL,  -- Vertices (documents) in network
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_betti_threshold ON document_similarity_betti_numbers(similarity_threshold);
"""

CREATE_CENTRALITY_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_centrality (
    centrality_id SERIAL PRIMARY KEY,
    doc_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    similarity_threshold FLOAT NOT NULL,  -- Threshold used for network construction
    degree INTEGER NOT NULL,              -- Number of connections
    degree_centrality FLOAT NOT NULL,     -- Normalized degree
    betweenness_centrality FLOAT NOT NULL, -- Bridge score between clusters
    eigenvector_centrality FLOAT,         -- Importance based on neighbor importance
    closeness_centrality FLOAT,           -- Average distance to all other nodes
    clustering_coefficient FLOAT,         -- How connected neighbors are to each other
    component_id INTEGER,                 -- Which connected component
    component_size INTEGER,               -- Size of the component
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(doc_id, similarity_threshold)
);

CREATE INDEX IF NOT EXISTS idx_cent_doc ON document_similarity_centrality(doc_id);
CREATE INDEX IF NOT EXISTS idx_cent_threshold ON document_similarity_centrality(similarity_threshold);
CREATE INDEX IF NOT EXISTS idx_cent_degree ON document_similarity_centrality(degree_centrality DESC);
CREATE INDEX IF NOT EXISTS idx_cent_between ON document_similarity_centrality(betweenness_centrality DESC);
CREATE INDEX IF NOT EXISTS idx_cent_eigen ON document_similarity_centrality(eigenvector_centrality DESC);
"""

CREATE_COMMUNITIES_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_communities (
    community_id SERIAL PRIMARY KEY,
    doc_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    similarity_threshold FLOAT NOT NULL,
    community INTEGER NOT NULL,           -- Community/cluster assignment
    community_size INTEGER NOT NULL,      -- Number of documents in this community
    algorithm TEXT NOT NULL,              -- Algorithm used (louvain, leiden, etc.)
    modularity FLOAT,                     -- Overall modularity score
    internal_edges INTEGER,               -- Edges within community
    external_edges INTEGER,               -- Edges to other communities
    internal_density FLOAT,               -- Density within community
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(doc_id, similarity_threshold, algorithm)
);

CREATE INDEX IF NOT EXISTS idx_comm_doc ON document_similarity_communities(doc_id);
CREATE INDEX IF NOT EXISTS idx_comm_threshold ON document_similarity_communities(similarity_threshold);
CREATE INDEX IF NOT EXISTS idx_comm_community ON document_similarity_communities(community);
CREATE INDEX IF NOT EXISTS idx_comm_size ON document_similarity_communities(community_size DESC);
"""

CREATE_COMMUNITY_LABELS_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_community_labels (
    label_id SERIAL PRIMARY KEY,
    similarity_threshold FLOAT NOT NULL,
    algorithm TEXT NOT NULL,
    community INTEGER NOT NULL,
    label TEXT,                           -- Human-readable label (auto or manual)
    top_entities JSONB,                   -- Top entities in this community
    top_nouns JSONB,                      -- Top noun terms in this community
    top_verbs JSONB,                      -- Top verb terms in this community
    date_range_start DATE,                -- Earliest document date
    date_range_end DATE,                  -- Latest document date
    document_count INTEGER,               -- Number of documents
    avg_quality_score FLOAT,              -- Average document quality
    auto_generated BOOLEAN DEFAULT TRUE,
    human_reviewed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(similarity_threshold, algorithm, community)
);

CREATE INDEX IF NOT EXISTS idx_label_threshold ON document_similarity_community_labels(similarity_threshold);
CREATE INDEX IF NOT EXISTS idx_label_community ON document_similarity_community_labels(community);
"""

CREATE_BRIDGE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS document_similarity_bridge_documents (
    bridge_id SERIAL PRIMARY KEY,
    doc_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    similarity_threshold FLOAT NOT NULL,
    betweenness_centrality FLOAT NOT NULL,
    communities_bridged JSONB,            -- List of community IDs this doc bridges
    bridge_strength JSONB,                -- Strength of connection to each community
    entity_overlap JSONB,                 -- Entities shared with each bridged community
    bridge_type TEXT,                     -- 'inter-cluster', 'hub', 'peripheral'
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(doc_id, similarity_threshold)
);

CREATE INDEX IF NOT EXISTS idx_bridge_doc ON document_similarity_bridge_documents(doc_id);
CREATE INDEX IF NOT EXISTS idx_bridge_betweenness ON document_similarity_bridge_documents(betweenness_centrality DESC);
"""


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def initialize_database(conn: Connection, verbose: bool = False) -> None:
    """Create database tables if they don't exist."""
    if verbose:
        print("Initializing database schema for document similarity network...")
    
    with conn.cursor() as cur:
        cur.execute(CREATE_SIMILARITY_PAIRS_TABLE)
        cur.execute(CREATE_PERSISTENCE_TABLE)
        cur.execute(CREATE_METADATA_TABLE)
        cur.execute(CREATE_BETTI_NUMBERS_TABLE)
        cur.execute(CREATE_CENTRALITY_TABLE)
        cur.execute(CREATE_COMMUNITIES_TABLE)
        cur.execute(CREATE_COMMUNITY_LABELS_TABLE)
        cur.execute(CREATE_BRIDGE_DOCUMENTS_TABLE)
    conn.commit()
    
    if verbose:
        print("Database schema ready.")


def clear_existing_data(conn: Connection, verbose: bool = False) -> None:
    """Clear existing document similarity data."""
    if verbose:
        print("Clearing existing document similarity data...")
    
    with conn.cursor() as cur:
        cur.execute("DELETE FROM document_similarity_bridge_documents")
        cur.execute("DELETE FROM document_similarity_community_labels")
        cur.execute("DELETE FROM document_similarity_communities")
        cur.execute("DELETE FROM document_similarity_centrality")
        cur.execute("DELETE FROM document_similarity_betti_numbers")
        cur.execute("DELETE FROM document_similarity_persistence")
        cur.execute("DELETE FROM document_similarity_pairs")
        cur.execute("DELETE FROM document_similarity_metadata WHERE key LIKE 'doc_sim_%'")
    conn.commit()
    
    if verbose:
        print("Existing data cleared.")


def load_tdm_from_database(
    conn: Connection, 
    tdm_type: str = 'noun',
    max_docs: Optional[int] = None,
    min_terms: int = 5,
    verbose: bool = False
) -> Tuple[csr_matrix, List[int], List[str], List[str]]:
    """Load term-document matrix from database.
    
    Args:
        conn: Database connection
        tdm_type: 'noun' or 'verb'
        max_docs: Maximum number of documents to load (None = all)
        min_terms: Minimum terms per document to include
        verbose: Print progress
        
    Returns:
        (tdm_matrix, doc_ids, file_paths, terms)
    """
    prefix = 'noun' if tdm_type == 'noun' else 'verb'
    term_col = 'unique_nouns' if tdm_type == 'noun' else 'unique_verbs'
    
    if verbose:
        print(f"Loading {tdm_type} TDM from database...")
    
    # Load documents (optionally limited)
    doc_query = f"""
        SELECT doc_id, file_path, file_name, {term_col} as term_count
        FROM {prefix}_tdm_documents
        WHERE {term_col} >= %s
        ORDER BY {term_col} DESC
    """
    if max_docs:
        doc_query += f" LIMIT {max_docs}"
    
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(doc_query, (min_terms,))
        docs = cur.fetchall()
    
    if not docs:
        raise ValueError(f"No documents found with at least {min_terms} terms")
    
    doc_ids = [d['doc_id'] for d in docs]
    file_paths = [d['file_path'] for d in docs]
    doc_id_to_idx = {doc_id: idx for idx, doc_id in enumerate(doc_ids)}
    
    if verbose:
        print(f"  Loaded {len(docs)} documents")
    
    # Load vocabulary
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT term_id, term FROM {prefix}_tdm_vocabulary ORDER BY term_id")
        vocab = cur.fetchall()
    
    term_ids = [v['term_id'] for v in vocab]
    terms = [v['term'] for v in vocab]
    term_id_to_idx = {term_id: idx for idx, term_id in enumerate(term_ids)}
    
    if verbose:
        print(f"  Loaded {len(vocab)} terms")
    
    # Load counts (sparse)
    if verbose:
        print("  Loading term counts...")
    
    # Build sparse matrix
    rows, cols, data = [], [], []
    
    # Query in batches for memory efficiency
    batch_size = 100
    for i in range(0, len(doc_ids), batch_size):
        batch_doc_ids = doc_ids[i:i + batch_size]
        placeholders = ','.join(['%s'] * len(batch_doc_ids))
        
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, term_id, count FROM {prefix}_tdm_counts WHERE doc_id IN ({placeholders})",
                batch_doc_ids
            )
            for doc_id, term_id, count in cur.fetchall():
                if doc_id in doc_id_to_idx and term_id in term_id_to_idx:
                    rows.append(doc_id_to_idx[doc_id])
                    cols.append(term_id_to_idx[term_id])
                    data.append(count)
        
        if verbose and (i + batch_size) % 1000 == 0:
            print(f"    Processed {min(i + batch_size, len(doc_ids))}/{len(doc_ids)} documents")
    
    # Create sparse matrix (documents × terms)
    tdm = csr_matrix((data, (rows, cols)), shape=(len(doc_ids), len(term_ids)), dtype=np.float32)
    
    if verbose:
        print(f"  TDM shape: {tdm.shape}, non-zero entries: {tdm.nnz}")
    
    return tdm, doc_ids, file_paths, terms


def load_combined_tdm_from_database(
    conn: Connection,
    max_docs: Optional[int] = None,
    min_terms: int = 5,
    noun_weight: float = 1.0,
    verb_weight: float = 1.0,
    verbose: bool = False
) -> Tuple[csr_matrix, List[int], List[str], List[str]]:
    """Load and combine both noun and verb TDMs from database.
    
    Combines noun and verb features into a single feature space by:
    1. Loading documents that appear in both TDMs
    2. Concatenating noun and verb term columns (with prefixes to avoid collision)
    3. Optionally weighting noun vs verb features
    
    Args:
        conn: Database connection
        max_docs: Maximum number of documents to load (None = all)
        min_terms: Minimum total terms per document to include
        noun_weight: Weight multiplier for noun features (default: 1.0)
        verb_weight: Weight multiplier for verb features (default: 1.0)
        verbose: Print progress
        
    Returns:
        (combined_tdm_matrix, doc_ids, file_paths, combined_terms)
    """
    if verbose:
        print("Loading combined noun+verb TDM from database...")
    
    # First, find documents that have both noun and verb data
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT n.doc_id, n.file_path, n.file_name,
                   n.unique_nouns, v.unique_verbs,
                   (n.unique_nouns + v.unique_verbs) as total_terms
            FROM noun_tdm_documents n
            JOIN verb_tdm_documents v ON n.doc_id = v.doc_id
            WHERE (n.unique_nouns + v.unique_verbs) >= %s
            ORDER BY (n.unique_nouns + v.unique_verbs) DESC
        """, (min_terms,))
        
        if max_docs:
            docs = cur.fetchmany(max_docs)
        else:
            docs = cur.fetchall()
    
    if not docs:
        raise ValueError(f"No documents found with at least {min_terms} combined terms")
    
    doc_ids = [d['doc_id'] for d in docs]
    file_paths = [d['file_path'] for d in docs]
    doc_id_to_idx = {doc_id: idx for idx, doc_id in enumerate(doc_ids)}
    
    if verbose:
        avg_nouns = sum(d['unique_nouns'] for d in docs) / len(docs)
        avg_verbs = sum(d['unique_verbs'] for d in docs) / len(docs)
        print(f"  Loaded {len(docs)} documents (avg {avg_nouns:.1f} nouns, {avg_verbs:.1f} verbs)")
    
    # Load noun vocabulary
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT term_id, term FROM noun_tdm_vocabulary ORDER BY term_id")
        noun_vocab = cur.fetchall()
    
    noun_term_ids = [v['term_id'] for v in noun_vocab]
    noun_terms = [f"n:{v['term']}" for v in noun_vocab]  # Prefix to distinguish
    noun_term_id_to_idx = {term_id: idx for idx, term_id in enumerate(noun_term_ids)}
    
    # Load verb vocabulary
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT term_id, term FROM verb_tdm_vocabulary ORDER BY term_id")
        verb_vocab = cur.fetchall()
    
    verb_term_ids = [v['term_id'] for v in verb_vocab]
    # Verb column indices start after noun columns
    verb_offset = len(noun_term_ids)
    verb_terms = [f"v:{v['term']}" for v in verb_vocab]  # Prefix to distinguish
    verb_term_id_to_idx = {term_id: idx + verb_offset for idx, term_id in enumerate(verb_term_ids)}
    
    # Combined terms list
    combined_terms = noun_terms + verb_terms
    n_total_terms = len(combined_terms)
    
    if verbose:
        print(f"  Loaded {len(noun_vocab)} noun terms + {len(verb_vocab)} verb terms = {n_total_terms} total")
    
    # Load noun counts
    if verbose:
        print("  Loading noun term counts...")
    
    rows, cols, data = [], [], []
    batch_size = 100
    
    for i in range(0, len(doc_ids), batch_size):
        batch_doc_ids = doc_ids[i:i + batch_size]
        placeholders = ','.join(['%s'] * len(batch_doc_ids))
        
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, term_id, count FROM noun_tdm_counts WHERE doc_id IN ({placeholders})",
                batch_doc_ids
            )
            for doc_id, term_id, count in cur.fetchall():
                if doc_id in doc_id_to_idx and term_id in noun_term_id_to_idx:
                    rows.append(doc_id_to_idx[doc_id])
                    cols.append(noun_term_id_to_idx[term_id])
                    data.append(count * noun_weight)
    
    noun_entries = len(data)
    
    # Load verb counts
    if verbose:
        print("  Loading verb term counts...")
    
    for i in range(0, len(doc_ids), batch_size):
        batch_doc_ids = doc_ids[i:i + batch_size]
        placeholders = ','.join(['%s'] * len(batch_doc_ids))
        
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, term_id, count FROM verb_tdm_counts WHERE doc_id IN ({placeholders})",
                batch_doc_ids
            )
            for doc_id, term_id, count in cur.fetchall():
                if doc_id in doc_id_to_idx and term_id in verb_term_id_to_idx:
                    rows.append(doc_id_to_idx[doc_id])
                    cols.append(verb_term_id_to_idx[term_id])
                    data.append(count * verb_weight)
    
    verb_entries = len(data) - noun_entries
    
    # Create combined sparse matrix (documents × combined_terms)
    combined_tdm = csr_matrix(
        (data, (rows, cols)), 
        shape=(len(doc_ids), n_total_terms), 
        dtype=np.float32
    )
    
    if verbose:
        print(f"  Combined TDM shape: {combined_tdm.shape}")
        print(f"  Non-zero entries: {combined_tdm.nnz} ({noun_entries} noun, {verb_entries} verb)")
    
    return combined_tdm, doc_ids, file_paths, combined_terms


def compute_tfidf(tdm: csr_matrix, verbose: bool = False) -> csr_matrix:
    """Apply TF-IDF weighting to term-document matrix."""
    if verbose:
        print("Applying TF-IDF weighting...")
    
    transformer = TfidfTransformer(norm='l2', use_idf=True, smooth_idf=True)
    tfidf_matrix = transformer.fit_transform(tdm)
    
    if verbose:
        print(f"  TF-IDF matrix shape: {tfidf_matrix.shape}")
    
    return tfidf_matrix


def compute_similarity_matrix(
    tfidf_matrix: csr_matrix,
    min_similarity: float = 0.0,
    verbose: bool = False
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute pairwise cosine similarity.
    
    Args:
        tfidf_matrix: TF-IDF weighted document vectors
        min_similarity: Minimum similarity to store (filters noise)
        verbose: Print progress
        
    Returns:
        (row_indices, col_indices, similarity_values) - upper triangle only
    """
    n_docs = tfidf_matrix.shape[0]
    
    if verbose:
        print(f"Computing pairwise cosine similarity for {n_docs} documents...")
        print(f"  This will compute {n_docs * (n_docs - 1) // 2:,} pairs")
    
    # For smaller matrices, compute all at once
    if n_docs <= 5000:
        sim_matrix = cosine_similarity(tfidf_matrix)
        
        # Extract upper triangle (excluding diagonal)
        rows, cols = np.triu_indices(n_docs, k=1)
        similarities = sim_matrix[rows, cols]
        
        # Filter by minimum similarity
        mask = similarities >= min_similarity
        rows = rows[mask]
        cols = cols[mask]
        similarities = similarities[mask]
        
        if verbose:
            print(f"  Computed {len(similarities):,} pairs with similarity >= {min_similarity}")
        
        return rows, cols, similarities
    
    # For larger matrices, compute in batches
    if verbose:
        print("  Using batch computation for large matrix...")
    
    all_rows, all_cols, all_sims = [], [], []
    batch_size = 500
    
    for i in range(0, n_docs, batch_size):
        batch_end = min(i + batch_size, n_docs)
        batch = tfidf_matrix[i:batch_end]
        
        # Compare batch against all documents from i onwards
        remaining = tfidf_matrix[i:]
        batch_sim = cosine_similarity(batch, remaining)
        
        # Extract valid pairs (upper triangle relative to full matrix)
        for bi, doc_i in enumerate(range(i, batch_end)):
            # Start from bi+1 to avoid diagonal and lower triangle
            start_j = bi + 1
            for bj in range(start_j, batch_sim.shape[1]):
                doc_j = i + bj
                if batch_sim[bi, bj] >= min_similarity:
                    all_rows.append(doc_i)
                    all_cols.append(doc_j)
                    all_sims.append(batch_sim[bi, bj])
        
        if verbose and (i + batch_size) % 1000 == 0:
            print(f"    Processed {min(i + batch_size, n_docs)}/{n_docs} documents")
    
    if verbose:
        print(f"  Computed {len(all_sims):,} pairs with similarity >= {min_similarity}")
    
    return np.array(all_rows), np.array(all_cols), np.array(all_sims)


def save_similarity_pairs(
    conn: Connection,
    rows: np.ndarray,
    cols: np.ndarray,
    similarities: np.ndarray,
    doc_ids: List[int],
    file_paths: List[str],
    verbose: bool = False
) -> int:
    """Save similarity pairs to database."""
    if verbose:
        print(f"Saving {len(similarities):,} similarity pairs to database...")
    
    batch_size = 10000
    total_saved = 0
    
    for i in range(0, len(similarities), batch_size):
        batch_end = min(i + batch_size, len(similarities))
        batch_data = []
        
        for j in range(i, batch_end):
            idx1, idx2 = rows[j], cols[j]
            batch_data.append((
                doc_ids[idx1],
                doc_ids[idx2],
                file_paths[idx1],
                file_paths[idx2],
                float(similarities[j])
            ))
        
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO document_similarity_pairs 
                   (doc_id_1, doc_id_2, file_path_1, file_path_2, cosine_similarity)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (doc_id_1, doc_id_2) DO UPDATE 
                   SET cosine_similarity = EXCLUDED.cosine_similarity""",
                batch_data
            )
        conn.commit()
        
        total_saved += len(batch_data)
        if verbose and total_saved % 50000 == 0:
            print(f"  Saved {total_saved:,}/{len(similarities):,} pairs")
    
    if verbose:
        print(f"  Saved {total_saved:,} similarity pairs")
    
    return total_saved


# ============================================================================
# PERSISTENT HOMOLOGY COMPUTATION
# ============================================================================

def compute_persistent_homology_ripser(
    similarities: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    n_docs: int,
    max_dim: int = 1,
    verbose: bool = False
) -> List[Tuple[int, float, float]]:
    """Compute persistent homology using ripser.
    
    Ripser expects a distance matrix, so we convert similarity to distance.
    We use distance = 1 - similarity so that similar documents are close.
    
    Returns:
        List of (dimension, birth, death) tuples
    """
    if verbose:
        print("Computing persistent homology using ripser...")
    
    # Build full distance matrix
    # Use 1 - similarity as distance (similar docs = close)
    dist_matrix = np.ones((n_docs, n_docs), dtype=np.float32)
    np.fill_diagonal(dist_matrix, 0)
    
    for i, (r, c, s) in enumerate(zip(rows, cols, similarities)):
        dist = 1.0 - s
        dist_matrix[r, c] = dist
        dist_matrix[c, r] = dist
    
    if verbose:
        print(f"  Distance matrix shape: {dist_matrix.shape}")
        print(f"  Computing Vietoris-Rips complex up to dimension {max_dim}...")
    
    # Run ripser
    result = ripser.ripser(dist_matrix, maxdim=max_dim, distance_matrix=True)
    
    # Extract persistence diagrams
    features = []
    for dim in range(max_dim + 1):
        dgm = result['dgms'][dim]
        for birth, death in dgm:
            # Convert back to similarity scale: sim = 1 - dist
            sim_birth = 1.0 - birth
            sim_death = 1.0 - death if not np.isinf(death) else None
            features.append((dim, sim_birth, sim_death))
    
    if verbose:
        h0_count = sum(1 for f in features if f[0] == 0)
        h1_count = sum(1 for f in features if f[0] == 1)
        print(f"  Found {h0_count} H0 features (connected components)")
        print(f"  Found {h1_count} H1 features (cycles/holes)")
    
    return features


def compute_persistent_homology_gudhi(
    similarities: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    n_docs: int,
    max_dim: int = 1,
    verbose: bool = False
) -> List[Tuple[int, float, float]]:
    """Compute persistent homology using GUDHI.
    
    Returns:
        List of (dimension, birth, death) tuples
    """
    if verbose:
        print("Computing persistent homology using GUDHI...")
    
    # Build distance matrix
    dist_matrix = np.ones((n_docs, n_docs), dtype=np.float64)
    np.fill_diagonal(dist_matrix, 0)
    
    for r, c, s in zip(rows, cols, similarities):
        dist = 1.0 - s
        dist_matrix[r, c] = dist
        dist_matrix[c, r] = dist
    
    if verbose:
        print(f"  Building Rips complex...")
    
    # Create Rips complex
    rips = gudhi.RipsComplex(distance_matrix=dist_matrix, max_edge_length=2.0)
    simplex_tree = rips.create_simplex_tree(max_dimension=max_dim + 1)
    
    if verbose:
        print(f"  Computing persistence...")
    
    # Compute persistence
    simplex_tree.compute_persistence()
    persistence = simplex_tree.persistence()
    
    # Extract features
    features = []
    for dim, (birth, death) in persistence:
        if dim <= max_dim:
            sim_birth = 1.0 - birth
            sim_death = 1.0 - death if not np.isinf(death) else None
            features.append((dim, sim_birth, sim_death))
    
    if verbose:
        h0_count = sum(1 for f in features if f[0] == 0)
        h1_count = sum(1 for f in features if f[0] == 1)
        print(f"  Found {h0_count} H0 features (connected components)")
        print(f"  Found {h1_count} H1 features (cycles/holes)")
    
    return features


def compute_persistent_homology_native(
    similarities: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    n_docs: int,
    verbose: bool = False
) -> List[Tuple[int, float, float]]:
    """Compute H0 (connected components) persistent homology without external TDA libraries.
    
    Uses Union-Find to track connected components as we add edges in decreasing
    similarity order. This is the standard algorithm for H0 persistence.
    
    Note: This only computes H0 (connected components), not H1 (cycles).
    For H1, install ripser or gudhi.
    
    Returns:
        List of (dimension, birth, death) tuples
    """
    if verbose:
        print("Computing H0 persistent homology using native Union-Find...")
        print("  Note: Install 'ripser' or 'gudhi' for H1 (cycles) computation")
    
    # Union-Find data structure
    parent = list(range(n_docs))
    rank = [0] * n_docs
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])  # Path compression
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px == py:
            return False  # Already in same component
        # Union by rank
        if rank[px] < rank[py]:
            px, py = py, px
        parent[py] = px
        if rank[px] == rank[py]:
            rank[px] += 1
        return True
    
    # Sort edges by similarity (descending) - we add high-similarity edges first
    # In filtration terms, high similarity = low distance = appears early
    edge_order = np.argsort(-similarities)
    
    features = []
    
    # Each document starts as its own component (born at similarity = 1.0)
    # Components die when they merge with another component
    component_birth = {i: 1.0 for i in range(n_docs)}
    
    for idx in edge_order:
        r, c = rows[idx], cols[idx]
        sim = similarities[idx]
        
        root_r, root_c = find(r), find(c)
        
        if root_r != root_c:
            # Merging two components - one dies
            # The "younger" component (arbitrary: smaller root) dies
            dying_root = min(root_r, root_c)
            surviving_root = max(root_r, root_c)
            
            # Record the death
            birth = component_birth[dying_root]
            death = sim  # Dies at this similarity threshold
            features.append((0, birth, death))
            
            # Perform union
            union(r, c)
            
            # Transfer birth time to surviving component
            new_root = find(r)
            component_birth[new_root] = max(component_birth[root_r], component_birth[root_c])
    
    # One component survives forever (infinite persistence)
    roots = set(find(i) for i in range(n_docs))
    for root in roots:
        features.append((0, component_birth[root], None))  # None = infinite
    
    if verbose:
        finite_h0 = sum(1 for f in features if f[0] == 0 and f[2] is not None)
        infinite_h0 = sum(1 for f in features if f[0] == 0 and f[2] is None)
        print(f"  Found {finite_h0} finite H0 features (merged components)")
        print(f"  Found {infinite_h0} infinite H0 features (final components)")
    
    return features


def compute_betti_numbers(
    similarities: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    n_docs: int,
    n_thresholds: int = 100,
    verbose: bool = False
) -> List[Tuple[float, int, int, int]]:
    """Compute Betti numbers at various threshold values.
    
    Returns:
        List of (threshold, betti_0, betti_1, num_edges) tuples
    """
    if verbose:
        print(f"Computing Betti numbers at {n_thresholds} threshold values...")
    
    # Generate threshold values from min to max similarity
    min_sim = similarities.min()
    max_sim = similarities.max()
    thresholds = np.linspace(max_sim, min_sim, n_thresholds)
    
    results = []
    
    for thresh in thresholds:
        # Filter edges by threshold
        mask = similarities >= thresh
        n_edges = np.sum(mask)
        
        if n_edges == 0:
            # No edges - all vertices are separate components
            results.append((thresh, n_docs, 0, 0))
            continue
        
        # Compute connected components using Union-Find
        parent = list(range(n_docs))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[py] = px
        
        # Add edges above threshold
        filtered_rows = rows[mask]
        filtered_cols = cols[mask]
        
        for r, c in zip(filtered_rows, filtered_cols):
            union(r, c)
        
        # Count connected components (Betti 0)
        n_components = len(set(find(i) for i in range(n_docs)))
        
        # Euler characteristic: V - E + F = χ
        # For a graph embedded in a surface: χ = components - cycles
        # So cycles (Betti 1) = components - χ = components - (V - E + F)
        # For a simple graph (no faces): Betti_1 = E - V + components
        betti_1 = max(0, n_edges - n_docs + n_components)
        
        results.append((thresh, n_components, betti_1, int(n_edges)))
    
    if verbose:
        print(f"  Computed Betti numbers at {len(results)} thresholds")
        print(f"  Similarity range: [{min_sim:.4f}, {max_sim:.4f}]")
    
    return results


def compute_centrality_measures(
    conn: Connection,
    similarity_threshold: float,
    verbose: bool = False
) -> Dict:
    """Compute centrality measures for documents in the similarity network.
    
    Queries similarity pairs from the database at the given threshold,
    builds a network, computes various centrality measures PER CONNECTED
    COMPONENT (not globally), and stores the results back in the database.
    
    Computing per-component ensures that centrality values are meaningful
    within each cluster. Global computation would dilute scores because
    nodes can only lie on shortest paths within their own component.
    
    Args:
        conn: Database connection
        similarity_threshold: Minimum similarity for edges
        verbose: Print progress
        
    Returns:
        Dictionary with centrality statistics
    """
    if not NETWORKX_AVAILABLE:
        if verbose:
            print("Warning: networkx not available, skipping centrality computation")
        return {}
    
    if verbose:
        print(f"\nComputing centrality measures at threshold {similarity_threshold:.4f}...")
    
    # Query similarity pairs from database
    with conn.cursor() as cur:
        cur.execute("""
            SELECT doc_id_1, doc_id_2, file_path_1, file_path_2, cosine_similarity
            FROM document_similarity_pairs
            WHERE cosine_similarity >= %s
        """, (similarity_threshold,))
        pairs = cur.fetchall()
    
    if not pairs:
        if verbose:
            print("  No pairs found above threshold")
        return {}
    
    if verbose:
        print(f"  Loaded {len(pairs)} pairs from database")
    
    # Build network
    G = nx.Graph()
    file_paths = {}
    
    for doc1, doc2, fp1, fp2, sim in pairs:
        G.add_edge(doc1, doc2, weight=sim)
        file_paths[doc1] = fp1
        file_paths[doc2] = fp2
    
    if verbose:
        print(f"  Network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    
    # Find connected components
    components = list(nx.connected_components(G))
    node_to_component = {}
    component_sizes = {}
    for i, comp in enumerate(components):
        component_sizes[i] = len(comp)
        for node in comp:
            node_to_component[node] = i
    
    if verbose:
        print(f"  Found {len(components)} connected components")
        print(f"  Computing centrality measures per-component for accurate values...")
    
    # Initialize centrality dictionaries
    degree_cent = {}
    betweenness_cent = {}
    eigenvector_cent = {}
    closeness_cent = {}
    clustering = {}
    
    # Compute centrality measures PER COMPONENT
    # This ensures normalization is done within each component, not globally
    for comp_idx, comp_nodes in enumerate(components):
        if len(comp_nodes) < 2:
            # Single-node components: all centralities are 0 or 1
            node = list(comp_nodes)[0]
            degree_cent[node] = 0.0
            betweenness_cent[node] = 0.0
            eigenvector_cent[node] = 1.0  # Only node in component
            closeness_cent[node] = 0.0
            clustering[node] = 0.0
            continue
        
        # Extract subgraph for this component
        subG = G.subgraph(comp_nodes)
        
        # Degree centrality (normalized by component size - 1)
        comp_degree = nx.degree_centrality(subG)
        degree_cent.update(comp_degree)
        
        # Betweenness centrality (normalized by component's node pairs)
        comp_betweenness = nx.betweenness_centrality(subG, weight='weight')
        betweenness_cent.update(comp_betweenness)
        
        # Eigenvector centrality (computed within component)
        try:
            comp_eigenvector = nx.eigenvector_centrality(subG, weight='weight', max_iter=1000)
            eigenvector_cent.update(comp_eigenvector)
        except nx.PowerIterationFailedConvergence:
            # If convergence fails, set to None for this component
            for node in comp_nodes:
                eigenvector_cent[node] = None
        
        # Closeness centrality (normalized by component size - 1)
        comp_closeness = nx.closeness_centrality(subG)
        closeness_cent.update(comp_closeness)
        
        # Clustering coefficient
        comp_clustering = nx.clustering(subG, weight='weight')
        clustering.update(comp_clustering)
    
    if verbose:
        print(f"  Computed per-component centrality for {len(components)} components")
    
    # Clear existing centrality data for this threshold
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM document_similarity_centrality WHERE similarity_threshold = %s",
            (similarity_threshold,)
        )
    
    # Prepare batch data
    batch_data = []
    for node in G.nodes():
        comp_id = node_to_component[node]
        batch_data.append((
            int(node),
            file_paths.get(node, f"doc_{node}"),
            float(similarity_threshold),
            int(G.degree(node)),
            float(degree_cent[node]),
            float(betweenness_cent[node]),
            float(eigenvector_cent[node]) if eigenvector_cent[node] is not None else None,
            float(closeness_cent[node]),
            float(clustering[node]),
            int(comp_id),
            int(component_sizes[comp_id])
        ))
    
    # Save to database
    if verbose:
        print(f"  Saving centrality measures for {len(batch_data)} documents...")
    
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO document_similarity_centrality 
               (doc_id, file_path, similarity_threshold, degree, degree_centrality,
                betweenness_centrality, eigenvector_centrality, closeness_centrality,
                clustering_coefficient, component_id, component_size)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (doc_id, similarity_threshold) DO UPDATE SET
                   degree = EXCLUDED.degree,
                   degree_centrality = EXCLUDED.degree_centrality,
                   betweenness_centrality = EXCLUDED.betweenness_centrality,
                   eigenvector_centrality = EXCLUDED.eigenvector_centrality,
                   closeness_centrality = EXCLUDED.closeness_centrality,
                   clustering_coefficient = EXCLUDED.clustering_coefficient,
                   component_id = EXCLUDED.component_id,
                   component_size = EXCLUDED.component_size""",
            batch_data
        )
    conn.commit()
    
    # Compute summary statistics
    results = {
        'threshold': similarity_threshold,
        'num_nodes': G.number_of_nodes(),
        'num_edges': G.number_of_edges(),
        'num_components': len(components),
        'largest_component': max(component_sizes.values()) if component_sizes else 0,
    }
    
    # Find top central documents
    top_degree = sorted(degree_cent.items(), key=lambda x: -x[1])[:10]
    top_betweenness = sorted(betweenness_cent.items(), key=lambda x: -x[1])[:10]
    top_eigenvector = sorted(
        [(k, v) for k, v in eigenvector_cent.items() if v is not None],
        key=lambda x: -x[1]
    )[:10]
    
    results['top_by_degree'] = [(int(d), file_paths.get(d, ''), float(s)) for d, s in top_degree]
    results['top_by_betweenness'] = [(int(d), file_paths.get(d, ''), float(s)) for d, s in top_betweenness]
    results['top_by_eigenvector'] = [(int(d), file_paths.get(d, ''), float(s)) for d, s in top_eigenvector]
    
    if verbose:
        print(f"  Saved centrality measures to database")
        print(f"\n  Top 10 by Degree Centrality (per-component):")
        for doc_id, fp, score in results['top_by_degree']:
            label = os.path.basename(fp).replace('_extracted.txt', '')[:40]
            print(f"    {label:<42} {score:.4f}")
        
        print(f"\n  Top 10 by Betweenness Centrality (per-component):")
        for doc_id, fp, score in results['top_by_betweenness']:
            label = os.path.basename(fp).replace('_extracted.txt', '')[:40]
            print(f"    {label:<42} {score:.4f}")
        
        print(f"\n  Top 10 by Eigenvector Centrality (per-component):")
        for doc_id, fp, score in results['top_by_eigenvector']:
            label = os.path.basename(fp).replace('_extracted.txt', '')[:40]
            print(f"    {label:<42} {score:.4f}")
    
    return results


def detect_communities(
    conn: Connection,
    similarity_threshold: float,
    algorithm: str = 'louvain',
    verbose: bool = False
) -> Dict:
    """Detect communities in the document similarity network.
    
    Queries similarity pairs from the database at the given threshold,
    builds a network, runs community detection, and stores the results.
    
    Args:
        conn: Database connection
        similarity_threshold: Minimum similarity for edges
        algorithm: Community detection algorithm ('louvain', 'greedy', 'label_propagation')
        verbose: Print progress
        
    Returns:
        Dictionary with community detection results
    """
    if not NETWORKX_AVAILABLE:
        if verbose:
            print("Warning: networkx not available, skipping community detection")
        return {}
    
    if verbose:
        print(f"\nDetecting communities at threshold {similarity_threshold:.4f} using {algorithm}...")
    
    # Query similarity pairs from database
    with conn.cursor() as cur:
        cur.execute("""
            SELECT doc_id_1, doc_id_2, file_path_1, file_path_2, cosine_similarity
            FROM document_similarity_pairs
            WHERE cosine_similarity >= %s
        """, (similarity_threshold,))
        pairs = cur.fetchall()
    
    if not pairs:
        if verbose:
            print("  No pairs found above threshold")
        return {}
    
    if verbose:
        print(f"  Loaded {len(pairs)} pairs from database")
    
    # Build network
    G = nx.Graph()
    file_paths = {}
    
    for doc1, doc2, fp1, fp2, sim in pairs:
        G.add_edge(doc1, doc2, weight=sim)
        file_paths[doc1] = fp1
        file_paths[doc2] = fp2
    
    if verbose:
        print(f"  Network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    
    # Run community detection based on algorithm choice
    if verbose:
        print(f"  Running {algorithm} community detection...")
    
    if algorithm == 'louvain':
        # Louvain method - optimizes modularity
        communities = nx.community.louvain_communities(G, weight='weight', seed=42)
    elif algorithm == 'greedy':
        # Greedy modularity maximization
        communities = list(nx.community.greedy_modularity_communities(G, weight='weight'))
    elif algorithm == 'label_propagation':
        # Label propagation (fast but less stable)
        communities = list(nx.community.label_propagation_communities(G))
    else:
        if verbose:
            print(f"  Warning: unknown algorithm '{algorithm}', using louvain")
        communities = nx.community.louvain_communities(G, weight='weight', seed=42)
        algorithm = 'louvain'
    
    # Convert to list and sort by size (largest first)
    communities = sorted([list(c) for c in communities], key=len, reverse=True)
    
    if verbose:
        print(f"  Found {len(communities)} communities")
    
    # Compute modularity
    community_sets = [set(c) for c in communities]
    modularity = nx.community.modularity(G, community_sets, weight='weight')
    
    if verbose:
        print(f"  Modularity score: {modularity:.4f}")
    
    # Build node to community mapping
    node_to_community = {}
    community_sizes = {}
    for comm_idx, comm_members in enumerate(communities):
        community_sizes[comm_idx] = len(comm_members)
        for node in comm_members:
            node_to_community[node] = comm_idx
    
    # Compute internal/external edges per community
    community_internal_edges = {i: 0 for i in range(len(communities))}
    community_external_edges = {i: 0 for i in range(len(communities))}
    
    for u, v in G.edges():
        comm_u = node_to_community[u]
        comm_v = node_to_community[v]
        if comm_u == comm_v:
            community_internal_edges[comm_u] += 1
        else:
            community_external_edges[comm_u] += 1
            community_external_edges[comm_v] += 1
    
    # Compute internal density per community
    community_density = {}
    for comm_idx, members in enumerate(communities):
        n = len(members)
        if n > 1:
            max_edges = n * (n - 1) / 2
            community_density[comm_idx] = community_internal_edges[comm_idx] / max_edges
        else:
            community_density[comm_idx] = 0.0
    
    # Clear existing community data for this threshold/algorithm
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM document_similarity_communities WHERE similarity_threshold = %s AND algorithm = %s",
            (similarity_threshold, algorithm)
        )
    
    # Prepare batch data
    batch_data = []
    for node in G.nodes():
        comm_id = node_to_community[node]
        batch_data.append((
            int(node),
            file_paths.get(node, f"doc_{node}"),
            float(similarity_threshold),
            int(comm_id),
            int(community_sizes[comm_id]),
            algorithm,
            float(modularity),
            int(community_internal_edges[comm_id]),
            int(community_external_edges[comm_id]),
            float(community_density[comm_id])
        ))
    
    # Save to database
    if verbose:
        print(f"  Saving community assignments for {len(batch_data)} documents...")
    
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO document_similarity_communities 
               (doc_id, file_path, similarity_threshold, community, community_size,
                algorithm, modularity, internal_edges, external_edges, internal_density)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (doc_id, similarity_threshold, algorithm) DO UPDATE SET
                   community = EXCLUDED.community,
                   community_size = EXCLUDED.community_size,
                   modularity = EXCLUDED.modularity,
                   internal_edges = EXCLUDED.internal_edges,
                   external_edges = EXCLUDED.external_edges,
                   internal_density = EXCLUDED.internal_density""",
            batch_data
        )
    conn.commit()
    
    # Build results dictionary
    results = {
        'threshold': similarity_threshold,
        'algorithm': algorithm,
        'num_communities': len(communities),
        'modularity': modularity,
        'communities': []
    }
    
    # Get top documents per community
    for comm_idx, members in enumerate(communities):
        comm_info = {
            'id': comm_idx,
            'size': len(members),
            'internal_edges': community_internal_edges[comm_idx],
            'external_edges': community_external_edges[comm_idx],
            'density': community_density[comm_idx],
            'sample_docs': []
        }
        
        # Sample up to 5 documents from this community
        for doc_id in members[:5]:
            fp = file_paths.get(doc_id, '')
            comm_info['sample_docs'].append({
                'doc_id': int(doc_id),
                'file_path': fp,
                'label': os.path.basename(fp).replace('_extracted.txt', '') if fp else f'doc_{doc_id}'
            })
        
        results['communities'].append(comm_info)
    
    if verbose:
        print(f"\n  Community Summary:")
        print(f"  {'Comm':<6} {'Size':<8} {'Internal':<10} {'External':<10} {'Density':<10} Sample Documents")
        print(f"  {'-'*6} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*40}")
        
        for comm in results['communities'][:15]:  # Show top 15 communities
            sample = ', '.join([d['label'][:20] for d in comm['sample_docs'][:3]])
            print(f"  {comm['id']:<6} {comm['size']:<8} {comm['internal_edges']:<10} "
                  f"{comm['external_edges']:<10} {comm['density']:<10.4f} {sample[:50]}...")
        
        if len(results['communities']) > 15:
            print(f"  ... and {len(results['communities']) - 15} more communities")
        
        print(f"\n  Saved community assignments to database")
    
    return results


def label_communities(
    conn: Connection,
    similarity_threshold: float,
    algorithm: str = 'louvain',
    verbose: bool = False
) -> Dict:
    """Auto-label communities with top entities, terms, and date ranges.
    
    Queries entity_network_mentions and v_document_timeline to enrich
    community data with semantic labels.
    
    Args:
        conn: Database connection
        similarity_threshold: Threshold used for community detection
        algorithm: Algorithm used for community detection
        verbose: Print progress
        
    Returns:
        Dictionary with labeling results
    """
    if verbose:
        print(f"\nLabeling communities at threshold {similarity_threshold:.4f}...")
    
    results = {
        'threshold': similarity_threshold,
        'algorithm': algorithm,
        'communities_labeled': 0,
        'labels': []
    }
    
    try:
        # Get all communities
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT community, community_size
                FROM document_similarity_communities
                WHERE similarity_threshold = %s AND algorithm = %s
                ORDER BY community
            """, (similarity_threshold, algorithm))
            communities = cur.fetchall()
        
        if not communities:
            if verbose:
                print("  No communities found")
            return results
        
        # Check if entity_network_mentions table exists
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'entity_network_mentions'
                )
            """)
            has_entity_mentions = cur.fetchone()[0]
            
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'v_document_timeline'
                )
            """)
            has_timeline = cur.fetchone()[0]
            
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'v_document_quality'
                )
            """)
            has_quality = cur.fetchone()[0]
        
        # Clear existing labels for this threshold/algorithm
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM document_similarity_community_labels
                WHERE similarity_threshold = %s AND algorithm = %s
            """, (similarity_threshold, algorithm))
        conn.commit()
        
        batch_data = []
        
        for comm_id, comm_size in communities:
            label_info = {
                'community': comm_id,
                'size': comm_size,
                'top_entities': [],
                'top_nouns': [],
                'date_range': None,
                'avg_quality': None,
                'label': None
            }
            
            # Get file paths in this community
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT file_path FROM document_similarity_communities
                    WHERE similarity_threshold = %s AND algorithm = %s AND community = %s
                """, (similarity_threshold, algorithm, comm_id))
                file_paths = [r[0] for r in cur.fetchall()]
            
            if not file_paths:
                continue
            
            # Extract file names for matching (handles path format differences)
            file_names = [os.path.basename(fp) for fp in file_paths]
            
            # Get top entities for this community (match by file name)
            if has_entity_mentions and file_names:
                try:
                    # Use LIKE patterns to match by file name
                    like_patterns = ['%' + fn for fn in file_names]
                    placeholders = ' OR '.join(['m.file_path LIKE %s'] * len(like_patterns))
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            SELECT e.entity_name, SUM(m.mention_count) as total_mentions
                            FROM entity_network_mentions m
                            JOIN entity_network_entities e ON m.entity_id = e.entity_id
                            WHERE {placeholders}
                            GROUP BY e.entity_name
                            ORDER BY total_mentions DESC
                            LIMIT 10
                        """, like_patterns)
                        label_info['top_entities'] = [
                            {'name': r[0], 'mentions': int(r[1])} for r in cur.fetchall()
                        ]
                except Exception as e:
                    if verbose:
                        print(f"    Warning: Could not get entities for community {comm_id}: {e}")
                    conn.rollback()
            
            # Get top nouns for this community
            try:
                placeholders = ','.join(['%s'] * len(file_paths))
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT v.term, SUM(c.count) as total_count
                        FROM noun_tdm_counts c
                        JOIN noun_tdm_vocabulary v ON c.term_id = v.term_id
                        JOIN noun_tdm_documents d ON c.doc_id = d.doc_id
                        WHERE d.file_path IN ({placeholders})
                        GROUP BY v.term
                        ORDER BY total_count DESC
                        LIMIT 10
                    """, file_paths)
                    label_info['top_nouns'] = [
                        {'term': r[0], 'count': int(r[1])} for r in cur.fetchall()
                    ]
            except Exception as e:
                if verbose:
                    print(f"    Warning: Could not get nouns for community {comm_id}: {e}")
                conn.rollback()
            
            # Get date range for this community
            if has_timeline:
                try:
                    like_patterns = ['%' + fn for fn in file_names]
                    placeholders = ' OR '.join(['path LIKE %s'] * len(like_patterns))
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            SELECT MIN(document_date), MAX(document_date)
                            FROM v_document_timeline
                            WHERE ({placeholders})
                            AND document_date IS NOT NULL
                        """, like_patterns)
                        date_row = cur.fetchone()
                        if date_row and date_row[0]:
                            label_info['date_range'] = {
                                'start': date_row[0],
                                'end': date_row[1]
                            }
                except Exception as e:
                    if verbose:
                        print(f"    Warning: Could not get date range for community {comm_id}: {e}")
                    conn.rollback()
            
            # Get average quality for this community
            if has_quality:
                try:
                    placeholders = ','.join(['%s'] * len(file_paths))
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            SELECT AVG(word_count) as avg_words
                            FROM v_document_quality
                            WHERE file_path IN ({placeholders})
                        """, file_paths)
                        qual_row = cur.fetchone()
                        if qual_row and qual_row[0]:
                            label_info['avg_quality'] = float(qual_row[0])
                except Exception:
                    conn.rollback()
            
            # Generate auto-label based on top entities and nouns
            label_parts = []
            if label_info['top_entities']:
                top_entity = label_info['top_entities'][0]['name']
                if top_entity not in ['Jeffrey Epstein', 'Ghislaine Maxwell']:
                    label_parts.append(top_entity)
                elif len(label_info['top_entities']) > 1:
                    label_parts.append(label_info['top_entities'][1]['name'])
            
            if label_info['top_nouns']:
                # Skip very common terms
                skip_terms = {'epstein', 'maxwell', 'case', 'court', 'document', 'page', 'mr', 'ms'}
                
                # Check for term canonicalization (e.g., 'white' + 'pls' -> 'White Plains, NY')
                from config import TERM_CANONICALIZATION
                noun_terms = {n['term'].lower() for n in label_info['top_nouns'][:10]}
                canonicalized = set()
                for canonical_name, term_combos in TERM_CANONICALIZATION.items():
                    for combo in term_combos:
                        if all(t in noun_terms for t in combo):
                            if canonical_name not in canonicalized and len(label_parts) < 3:
                                label_parts.append(canonical_name)
                                canonicalized.add(canonical_name)
                                # Mark these terms as used
                                for t in combo:
                                    skip_terms.add(t)
                            break
                
                # Add remaining top nouns that weren't canonicalized
                for noun in label_info['top_nouns'][:5]:
                    if noun['term'].lower() not in skip_terms and len(label_parts) < 3:
                        label_parts.append(noun['term'].title())
            
            if label_info['date_range']:
                start = label_info['date_range']['start']
                if hasattr(start, 'year'):
                    label_parts.append(str(start.year))
            
            label_info['label'] = ' / '.join(label_parts[:3]) if label_parts else f'Community {comm_id}'
            
            # Prepare for batch insert
            batch_data.append((
                float(similarity_threshold),
                algorithm,
                int(comm_id),
                label_info['label'],
                json.dumps(label_info['top_entities']),
                json.dumps(label_info['top_nouns']),
                None,  # top_verbs - could add later
                label_info['date_range']['start'] if label_info['date_range'] else None,
                label_info['date_range']['end'] if label_info['date_range'] else None,
                int(comm_size),
                label_info['avg_quality'],
                True,  # auto_generated
                False  # human_reviewed
            ))
            
            results['labels'].append(label_info)
        
        # Save to database
        if batch_data:
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO document_similarity_community_labels
                    (similarity_threshold, algorithm, community, label, top_entities, 
                     top_nouns, top_verbs, date_range_start, date_range_end,
                     document_count, avg_quality_score, auto_generated, human_reviewed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (similarity_threshold, algorithm, community) DO UPDATE SET
                        label = EXCLUDED.label,
                        top_entities = EXCLUDED.top_entities,
                        top_nouns = EXCLUDED.top_nouns,
                        date_range_start = EXCLUDED.date_range_start,
                        date_range_end = EXCLUDED.date_range_end,
                        document_count = EXCLUDED.document_count,
                        avg_quality_score = EXCLUDED.avg_quality_score
                """, batch_data)
            conn.commit()
            results['communities_labeled'] = len(batch_data)
        
        if verbose:
            print(f"  Labeled {results['communities_labeled']} communities")
            print(f"\n  Community Labels:")
            print(f"  {'Comm':<6} {'Size':<6} {'Label':<40} Top Entity")
            print(f"  {'-'*6} {'-'*6} {'-'*40} {'-'*30}")
            for info in results['labels'][:20]:
                top_ent = info['top_entities'][0]['name'] if info['top_entities'] else '-'
                print(f"  {info['community']:<6} {info['size']:<6} {info['label'][:40]:<40} {top_ent[:30]}")
            if len(results['labels']) > 20:
                print(f"  ... and {len(results['labels']) - 20} more")
    
    except Exception as e:
        if verbose:
            print(f"  Warning: Error during community labeling: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    
    return results


def analyze_bridge_documents(
    conn: Connection,
    similarity_threshold: float,
    algorithm: str = 'louvain',
    top_n: int = 20,
    verbose: bool = False
) -> Dict:
    """Analyze documents that bridge multiple communities.
    
    Identifies high-betweenness documents and determines which communities
    they connect, providing insight into cross-cluster relationships.
    
    Args:
        conn: Database connection
        similarity_threshold: Threshold used for network construction
        algorithm: Algorithm used for community detection
        top_n: Number of top bridge documents to analyze
        verbose: Print progress
        
    Returns:
        Dictionary with bridge document analysis
    """
    if verbose:
        print(f"\nAnalyzing bridge documents at threshold {similarity_threshold:.4f}...")
    
    # Get top documents by betweenness centrality
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.doc_id, c.file_path, c.betweenness_centrality, 
                   cm.community as own_community
            FROM document_similarity_centrality c
            JOIN document_similarity_communities cm 
                ON c.doc_id = cm.doc_id 
                AND c.similarity_threshold = cm.similarity_threshold
            WHERE c.similarity_threshold = %s 
                AND cm.algorithm = %s
                AND c.betweenness_centrality > 0
            ORDER BY c.betweenness_centrality DESC
            LIMIT %s
        """, (similarity_threshold, algorithm, top_n))
        top_bridges = cur.fetchall()
    
    if not top_bridges:
        if verbose:
            print("  No bridge documents found")
        return {}
    
    results = {
        'threshold': similarity_threshold,
        'bridges': []
    }
    
    # Clear existing bridge data
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM document_similarity_bridge_documents
            WHERE similarity_threshold = %s
        """, (similarity_threshold,))
    
    batch_data = []
    
    for doc_id, file_path, betweenness, own_community in top_bridges:
        bridge_info = {
            'doc_id': doc_id,
            'file_path': file_path,
            'betweenness': betweenness,
            'own_community': own_community,
            'communities_bridged': {},
            'bridge_type': 'unknown'
        }
        
        # Find which communities this document connects to
        with conn.cursor() as cur:
            cur.execute("""
                SELECT cm.community, COUNT(*) as connections
                FROM document_similarity_pairs p
                JOIN document_similarity_communities cm 
                    ON (p.doc_id_2 = cm.doc_id OR p.doc_id_1 = cm.doc_id)
                    AND cm.similarity_threshold = %s
                    AND cm.algorithm = %s
                WHERE (p.doc_id_1 = %s OR p.doc_id_2 = %s)
                    AND p.cosine_similarity >= %s
                    AND cm.doc_id != %s
                GROUP BY cm.community
                ORDER BY connections DESC
            """, (similarity_threshold, algorithm, doc_id, doc_id, similarity_threshold, doc_id))
            
            community_connections = {}
            for comm, count in cur.fetchall():
                community_connections[int(comm)] = int(count)
            
            bridge_info['communities_bridged'] = community_connections
        
        # Determine bridge type
        n_communities = len(community_connections)
        if n_communities == 0:
            bridge_info['bridge_type'] = 'isolated'
        elif n_communities == 1:
            bridge_info['bridge_type'] = 'peripheral'
        elif n_communities == 2:
            bridge_info['bridge_type'] = 'inter-cluster'
        else:
            bridge_info['bridge_type'] = 'hub'
        
        # Prepare for batch insert
        batch_data.append((
            int(doc_id),
            file_path,
            float(similarity_threshold),
            float(betweenness),
            json.dumps(community_connections),
            json.dumps({}),  # bridge_strength
            json.dumps({}),  # entity_overlap
            bridge_info['bridge_type']
        ))
        
        results['bridges'].append(bridge_info)
    
    # Save to database
    if batch_data:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO document_similarity_bridge_documents
                (doc_id, file_path, similarity_threshold, betweenness_centrality,
                 communities_bridged, bridge_strength, entity_overlap, bridge_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (doc_id, similarity_threshold) DO UPDATE SET
                    betweenness_centrality = EXCLUDED.betweenness_centrality,
                    communities_bridged = EXCLUDED.communities_bridged,
                    bridge_type = EXCLUDED.bridge_type
            """, batch_data)
        conn.commit()
    
    if verbose:
        print(f"  Analyzed {len(results['bridges'])} bridge documents")
        print(f"\n  Top Bridge Documents:")
        print(f"  {'Doc ID':<15} {'Betweenness':<12} {'Type':<15} {'Communities Bridged'}")
        print(f"  {'-'*15} {'-'*12} {'-'*15} {'-'*30}")
        for b in results['bridges'][:15]:
            fname = os.path.basename(b['file_path']).replace('_extracted.txt', '')
            comms = list(b['communities_bridged'].keys())[:5]
            print(f"  {fname:<15} {b['betweenness']:<12.4f} {b['bridge_type']:<15} {comms}")
    
    return results


def export_graph(
    conn: Connection,
    similarity_threshold: float,
    output_path: str,
    format: str = 'gexf',
    include_communities: bool = True,
    include_centrality: bool = True,
    verbose: bool = False
) -> bool:
    """Export the similarity network to graph file formats.
    
    Supports GEXF (Gephi), GraphML (yEd/Cytoscape), and edge list formats.
    
    Args:
        conn: Database connection
        similarity_threshold: Minimum similarity for edges
        output_path: Path to output file
        format: 'gexf', 'graphml', or 'edgelist'
        include_communities: Add community as node attribute
        include_centrality: Add centrality measures as node attributes
        verbose: Print progress
        
    Returns:
        True if export successful
    """
    if not NETWORKX_AVAILABLE:
        if verbose:
            print("Warning: networkx not available, cannot export graph")
        return False
    
    if verbose:
        print(f"\nExporting graph to {format.upper()} format...")
    
    # Build graph from database
    with conn.cursor() as cur:
        cur.execute("""
            SELECT doc_id_1, doc_id_2, file_path_1, file_path_2, cosine_similarity
            FROM document_similarity_pairs
            WHERE cosine_similarity >= %s
        """, (similarity_threshold,))
        pairs = cur.fetchall()
    
    if not pairs:
        if verbose:
            print("  No pairs found above threshold")
        return False
    
    G = nx.Graph()
    file_paths = {}
    
    for doc1, doc2, fp1, fp2, sim in pairs:
        G.add_edge(doc1, doc2, weight=sim, similarity=sim)
        file_paths[doc1] = fp1
        file_paths[doc2] = fp2
    
    # Add file_path as node attribute
    for node in G.nodes():
        fp = file_paths.get(node, '')
        G.nodes[node]['file_path'] = fp
        G.nodes[node]['label'] = os.path.basename(fp).replace('_extracted.txt', '') if fp else str(node)
    
    # Add community data
    if include_communities:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT doc_id, community, community_size
                FROM document_similarity_communities
                WHERE similarity_threshold = %s
            """, (similarity_threshold,))
            for doc_id, comm, size in cur.fetchall():
                if doc_id in G.nodes():
                    G.nodes[doc_id]['community'] = comm
                    G.nodes[doc_id]['community_size'] = size
        
        # Add community labels if available
        with conn.cursor() as cur:
            cur.execute("""
                SELECT community, label
                FROM document_similarity_community_labels
                WHERE similarity_threshold = %s
            """, (similarity_threshold,))
            comm_labels = {r[0]: r[1] for r in cur.fetchall()}
            
            for node in G.nodes():
                comm = G.nodes[node].get('community')
                if comm is not None and comm in comm_labels:
                    G.nodes[node]['community_label'] = comm_labels[comm]
    
    # Add centrality data
    if include_centrality:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT doc_id, degree_centrality, betweenness_centrality, 
                       eigenvector_centrality, closeness_centrality
                FROM document_similarity_centrality
                WHERE similarity_threshold = %s
            """, (similarity_threshold,))
            for row in cur.fetchall():
                doc_id = row[0]
                if doc_id in G.nodes():
                    G.nodes[doc_id]['degree_centrality'] = row[1]
                    G.nodes[doc_id]['betweenness_centrality'] = row[2]
                    G.nodes[doc_id]['eigenvector_centrality'] = row[3] if row[3] else 0
                    G.nodes[doc_id]['closeness_centrality'] = row[4]
    
    # Export based on format
    try:
        if format.lower() == 'gexf':
            nx.write_gexf(G, output_path)
        elif format.lower() == 'graphml':
            nx.write_graphml(G, output_path)
        elif format.lower() == 'edgelist':
            nx.write_weighted_edgelist(G, output_path)
        else:
            if verbose:
                print(f"  Unknown format: {format}")
            return False
        
        if verbose:
            print(f"  Exported {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
            print(f"  Saved to: {output_path}")
        return True
        
    except Exception as e:
        if verbose:
            print(f"  Export error: {e}")
        return False


def compute_entity_weighted_similarity(
    conn: Connection,
    doc_ids: List[int],
    file_paths: List[str],
    tfidf_similarities: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    entity_weight: float = 0.3,
    verbose: bool = False
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Combine TF-IDF similarity with entity co-occurrence.
    
    Boosts similarity between documents that share named entities,
    particularly people mentioned together.
    
    Args:
        conn: Database connection
        doc_ids: List of document IDs
        file_paths: List of file paths corresponding to doc_ids
        tfidf_similarities: Original TF-IDF cosine similarities
        rows: Row indices of similarity pairs
        cols: Column indices of similarity pairs
        entity_weight: Weight for entity similarity (0-1), TF-IDF gets (1-entity_weight)
        verbose: Print progress
        
    Returns:
        (row_indices, col_indices, combined_similarity_values)
    """
    if verbose:
        print(f"\nComputing entity-weighted similarity (entity_weight={entity_weight})...")
    
    try:
        # Check if extracted_names table exists
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'extracted_names'
                )
            """)
            has_names = cur.fetchone()[0]
        
        if not has_names:
            if verbose:
                print("  extracted_names table not found, using TF-IDF only")
            return rows, cols, tfidf_similarities
        
        # Get entity co-occurrence counts
        if verbose:
            print("  Loading entity co-occurrences...")
        
        # Query names per document - use file_name matching since paths differ
        # Extract file names from our file paths for matching
        file_name_to_idx = {}
        for idx, fp in enumerate(file_paths):
            fn = os.path.basename(fp).replace('_extracted.txt', '')
            file_name_to_idx[fn] = idx
        
        doc_entities = {}
        
        with conn.cursor() as cur:
            # Get all names with their file paths, extract by file name
            cur.execute("""
                SELECT file_path, name_string, occurrence_count
                FROM extracted_names
            """)
            
            for fp, name, count in cur.fetchall():
                # Extract file name for matching
                fn = os.path.basename(fp).replace('.pdf', '').replace('_extracted.txt', '')
                if fn in file_name_to_idx:
                    idx = file_name_to_idx[fn]
                    actual_fp = file_paths[idx]
                    if actual_fp not in doc_entities:
                        doc_entities[actual_fp] = set()
                    doc_entities[actual_fp].add(name)
        
        if verbose:
            docs_with_entities = len(doc_entities)
            print(f"  Found entities in {docs_with_entities}/{len(file_paths)} documents")
        
        # Compute entity Jaccard similarity for each pair
        entity_sims = np.zeros(len(tfidf_similarities))
        
        for i, (r, c) in enumerate(zip(rows, cols)):
            fp1 = file_paths[r]
            fp2 = file_paths[c]
            
            ents1 = doc_entities.get(fp1, set())
            ents2 = doc_entities.get(fp2, set())
            
            if ents1 and ents2:
                intersection = len(ents1 & ents2)
                union = len(ents1 | ents2)
                entity_sims[i] = intersection / union if union > 0 else 0
        
        # Combine similarities
        tfidf_weight = 1 - entity_weight
        combined_sims = tfidf_weight * tfidf_similarities + entity_weight * entity_sims
        
        if verbose:
            boosted = np.sum(entity_sims > 0)
            avg_boost = np.mean(entity_sims[entity_sims > 0]) if boosted > 0 else 0
            print(f"  Entity overlap found in {boosted}/{len(tfidf_similarities)} pairs")
            print(f"  Average entity Jaccard: {avg_boost:.4f}")
        
        return rows, cols, combined_sims
        
    except Exception as e:
        if verbose:
            print(f"  Warning: Entity weighting failed ({e}), using TF-IDF only")
        conn.rollback()
        return rows, cols, tfidf_similarities


def find_optimal_threshold(
    similarities: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    n_docs: int,
    betti_data: Optional[List[Tuple[float, int, int, int]]] = None,
    features: Optional[List[Tuple[int, float, float]]] = None,
    n_thresholds: int = 50,
    method: str = 'auto',
    verbose: bool = False
) -> Dict:
    """Find the optimal similarity threshold for network visualization.
    
    Uses multiple methods to identify a meaningful threshold:
    
    1. 'modularity': Maximizes network modularity (community structure quality)
    2. 'persistence': Uses largest gap in H0 persistence diagram
    3. 'knee': Finds elbow/knee in components vs threshold curve
    4. 'silhouette': Maximizes average silhouette score of components
    5. 'auto': Combines multiple methods with voting/averaging
    
    Args:
        similarities: Array of similarity values
        rows: Row indices of similarity pairs
        cols: Column indices of similarity pairs
        n_docs: Number of documents
        betti_data: Pre-computed Betti numbers (optional, for efficiency)
        features: Pre-computed persistence features (optional)
        n_thresholds: Number of thresholds to evaluate
        method: Which method to use ('auto', 'modularity', 'persistence', 'knee', 'silhouette')
        verbose: Print progress
        
    Returns:
        Dictionary with optimal threshold and analysis details
    """
    if verbose:
        print(f"\nFinding optimal threshold using method: {method}...")
    
    min_sim = float(similarities.min())
    max_sim = float(similarities.max())
    
    # Generate candidate thresholds
    thresholds = np.linspace(max_sim * 0.95, min_sim + 0.05, n_thresholds)
    
    results = {
        'optimal_threshold': None,
        'method': method,
        'candidates': {},
        'analysis': {},
        'recommendation': None
    }
    
    # Method 1: Modularity-based (requires networkx)
    if method in ['auto', 'modularity'] and NETWORKX_AVAILABLE:
        if verbose:
            print("  Analyzing modularity across thresholds...")
        
        modularity_scores = []
        n_communities_list = []
        
        for thresh in thresholds:
            mask = similarities >= thresh
            if np.sum(mask) < 2:
                modularity_scores.append(0)
                n_communities_list.append(n_docs)
                continue
            
            # Build graph
            G = nx.Graph()
            G.add_nodes_from(range(n_docs))
            edges = [(int(rows[i]), int(cols[i]), {'weight': float(similarities[i])}) 
                     for i in range(len(similarities)) if mask[i]]
            G.add_edges_from(edges)
            
            # Remove isolated nodes for community detection
            G_connected = G.subgraph([n for n in G.nodes() if G.degree(n) > 0]).copy()
            
            if G_connected.number_of_nodes() < 2:
                modularity_scores.append(0)
                n_communities_list.append(n_docs)
                continue
            
            try:
                # Use Louvain community detection
                communities = nx.community.louvain_communities(G_connected, weight='weight', seed=42)
                modularity = nx.community.modularity(G_connected, communities, weight='weight')
                modularity_scores.append(modularity)
                n_communities_list.append(len(communities))
            except Exception:
                modularity_scores.append(0)
                n_communities_list.append(n_docs)
        
        modularity_scores = np.array(modularity_scores)
        
        # Find threshold with maximum modularity (preferring higher thresholds for ties)
        if np.max(modularity_scores) > 0:
            # Weight towards higher thresholds slightly
            weighted_scores = modularity_scores * (1 + 0.1 * np.linspace(1, 0, len(thresholds)))
            best_idx = np.argmax(weighted_scores)
            modularity_threshold = float(thresholds[best_idx])
            results['candidates']['modularity'] = {
                'threshold': modularity_threshold,
                'score': float(modularity_scores[best_idx]),
                'n_communities': int(n_communities_list[best_idx])
            }
            results['analysis']['modularity_curve'] = list(zip(
                [float(t) for t in thresholds],
                [float(m) for m in modularity_scores]
            ))
            if verbose:
                print(f"    Modularity optimal: {modularity_threshold:.4f} "
                      f"(Q={modularity_scores[best_idx]:.4f}, "
                      f"{n_communities_list[best_idx]} communities)")
    
    # Method 2: Persistence-based (uses gaps in H0 death times and H1 birth times)
    if method in ['auto', 'persistence'] and features:
        if verbose:
            print("  Analyzing persistence gaps (H0 and H1)...")
        
        # Get H0 death times (excluding infinite) - when components merge
        h0_deaths = sorted([d for dim, b, d in features if dim == 0 and d is not None], reverse=True)
        
        # Get H1 birth times - when cycles form
        h1_births = sorted([b for dim, b, d in features if dim == 1 and b is not None], reverse=True)
        
        h0_optimal, h0_gap, h0_gap_idx = None, 0, 0
        h1_optimal, h1_gap, h1_gap_idx = None, 0, 0
        
        # Find largest gap in H0 death times
        if len(h0_deaths) > 1:
            gaps = np.diff(h0_deaths)  # Will be negative (descending order)
            gaps = -gaps  # Make positive
            h0_gap_idx = np.argmax(gaps)
            h0_gap = float(gaps[h0_gap_idx])
            h0_optimal = float(h0_deaths[h0_gap_idx])
        
        # Find largest gap in H1 birth times
        if len(h1_births) > 1:
            gaps = np.diff(h1_births)  # Will be negative (descending order)
            gaps = -gaps  # Make positive
            h1_gap_idx = np.argmax(gaps)
            h1_gap = float(gaps[h1_gap_idx])
            h1_optimal = float(h1_births[h1_gap_idx])
        
        # Normalize gaps by range to compare H0 vs H1
        h0_range = (max(h0_deaths) - min(h0_deaths)) if len(h0_deaths) > 1 else 1.0
        h1_range = (max(h1_births) - min(h1_births)) if len(h1_births) > 1 else 1.0
        
        h0_score = h0_gap / h0_range if h0_range > 0 else 0
        h1_score = h1_gap / h1_range if h1_range > 0 else 0
        
        # Choose based on which has more significant normalized gap
        if h1_score > h0_score and h1_optimal is not None:
            persistence_threshold = h1_optimal
            selected_dim = 'H1'
            selected_gap = h1_gap
        elif h0_optimal is not None:
            persistence_threshold = h0_optimal
            selected_dim = 'H0'
            selected_gap = h0_gap
        else:
            persistence_threshold = None
            selected_dim = None
            selected_gap = 0
        
        if persistence_threshold is not None:
            results['candidates']['persistence'] = {
                'threshold': persistence_threshold,
                'gap_size': selected_gap,
                'dimension': selected_dim,
                'h0_gap': h0_gap,
                'h0_threshold': h0_optimal,
                'h1_gap': h1_gap,
                'h1_threshold': h1_optimal
            }
            if verbose:
                print(f"    H0 gap: {h0_gap:.4f} at {h0_optimal:.4f}" if h0_optimal else "    H0: no gap found")
                print(f"    H1 gap: {h1_gap:.4f} at {h1_optimal:.4f}" if h1_optimal else "    H1: no gap found")
                print(f"    Persistence optimal ({selected_dim}): {persistence_threshold:.4f} "
                      f"(gap={selected_gap:.4f})")
    
    # Method 3: Knee/elbow detection in components curve
    if method in ['auto', 'knee']:
        if verbose:
            print("  Finding knee in components curve...")
        
        # Compute components at each threshold if not provided
        if betti_data:
            # Use existing betti data
            betti_thresholds = np.array([t for t, b0, b1, e in betti_data])
            components = np.array([b0 for t, b0, b1, e in betti_data])
        else:
            # Compute fresh
            components = []
            for thresh in thresholds:
                parent = list(range(n_docs))
                def find(x):
                    if parent[x] != x:
                        parent[x] = find(parent[x])
                    return parent[x]
                def union(x, y):
                    px, py = find(x), find(y)
                    if px != py:
                        parent[py] = px
                
                mask = similarities >= thresh
                for r, c in zip(rows[mask], cols[mask]):
                    union(r, c)
                n_comp = len(set(find(i) for i in range(n_docs)))
                components.append(n_comp)
            
            betti_thresholds = thresholds
            components = np.array(components)
        
        # Find knee using the Kneedle algorithm (simplified)
        # Normalize data
        x_norm = (betti_thresholds - betti_thresholds.min()) / (betti_thresholds.max() - betti_thresholds.min() + 1e-10)
        y_norm = (components - components.min()) / (components.max() - components.min() + 1e-10)
        
        # Find point furthest from line connecting endpoints
        # Line from (x_norm[0], y_norm[0]) to (x_norm[-1], y_norm[-1])
        line_vec = np.array([x_norm[-1] - x_norm[0], y_norm[-1] - y_norm[0]])
        line_len = np.sqrt(np.sum(line_vec**2))
        
        if line_len > 0:
            line_unit = line_vec / line_len
            
            # Distance from each point to the line
            distances = []
            for i in range(len(x_norm)):
                point_vec = np.array([x_norm[i] - x_norm[0], y_norm[i] - y_norm[0]])
                proj_len = np.dot(point_vec, line_unit)
                proj = proj_len * line_unit
                perp = point_vec - proj
                dist = np.sqrt(np.sum(perp**2))
                # Only consider points above the line (convex side)
                cross = line_vec[0] * (y_norm[i] - y_norm[0]) - line_vec[1] * (x_norm[i] - x_norm[0])
                distances.append(dist if cross > 0 else -dist)
            
            distances = np.array(distances)
            knee_idx = np.argmax(distances)
            knee_threshold = float(betti_thresholds[knee_idx])
            
            results['candidates']['knee'] = {
                'threshold': knee_threshold,
                'n_components': int(components[knee_idx]),
                'curvature': float(distances[knee_idx])
            }
            if verbose:
                print(f"    Knee optimal: {knee_threshold:.4f} "
                      f"({int(components[knee_idx])} components)")
    
    # Method 4: Silhouette-based (component quality)
    if method in ['auto', 'silhouette'] and NETWORKX_AVAILABLE:
        if verbose:
            print("  Analyzing silhouette scores...")
        
        # Sample fewer thresholds for expensive computation
        sample_thresholds = thresholds[::max(1, len(thresholds)//20)]
        silhouette_scores = []
        
        for thresh in sample_thresholds:
            mask = similarities >= thresh
            if np.sum(mask) < 2:
                silhouette_scores.append(-1)
                continue
            
            # Build adjacency and find components
            parent = list(range(n_docs))
            def find(x):
                if parent[x] != x:
                    parent[x] = find(parent[x])
                return parent[x]
            def union(x, y):
                px, py = find(x), find(y)
                if px != py:
                    parent[py] = px
            
            for r, c in zip(rows[mask], cols[mask]):
                union(r, c)
            
            labels = np.array([find(i) for i in range(n_docs)])
            unique_labels = np.unique(labels)
            
            if len(unique_labels) < 2 or len(unique_labels) > n_docs - 2:
                silhouette_scores.append(-1)
                continue
            
            # Simplified silhouette: average intra-cluster similarity - inter-cluster similarity
            intra_sims = []
            inter_sims = []
            
            for i in range(len(similarities)):
                r, c = rows[i], cols[i]
                if labels[r] == labels[c]:
                    intra_sims.append(similarities[i])
                else:
                    inter_sims.append(similarities[i])
            
            if intra_sims and inter_sims:
                score = np.mean(intra_sims) - np.mean(inter_sims)
                silhouette_scores.append(score)
            else:
                silhouette_scores.append(-1)
        
        silhouette_scores = np.array(silhouette_scores)
        valid_mask = silhouette_scores > -1
        
        if np.any(valid_mask):
            best_idx = np.argmax(silhouette_scores)
            silhouette_threshold = float(sample_thresholds[best_idx])
            
            results['candidates']['silhouette'] = {
                'threshold': silhouette_threshold,
                'score': float(silhouette_scores[best_idx])
            }
            if verbose:
                print(f"    Silhouette optimal: {silhouette_threshold:.4f} "
                      f"(score={silhouette_scores[best_idx]:.4f})")
    
    # Combine results for 'auto' method
    if method == 'auto' and results['candidates']:
        candidate_thresholds = [v['threshold'] for v in results['candidates'].values()]
        
        # Use weighted average, giving more weight to modularity and persistence
        weights = {
            'modularity': 2.0,
            'persistence': 1.5,
            'knee': 1.0,
            'silhouette': 1.0
        }
        
        weighted_sum = 0
        weight_total = 0
        for method_name, candidate in results['candidates'].items():
            w = weights.get(method_name, 1.0)
            weighted_sum += candidate['threshold'] * w
            weight_total += w
        
        optimal = weighted_sum / weight_total if weight_total > 0 else np.median(candidate_thresholds)
        
        # Round to nearest evaluated threshold
        closest_idx = np.argmin(np.abs(thresholds - optimal))
        results['optimal_threshold'] = float(thresholds[closest_idx])
        
        # Generate recommendation text
        results['recommendation'] = (
            f"Recommended threshold: {results['optimal_threshold']:.4f} "
            f"(combined from {len(results['candidates'])} methods)"
        )
    elif results['candidates']:
        # Single method - use its result
        results['optimal_threshold'] = list(results['candidates'].values())[0]['threshold']
        results['recommendation'] = (
            f"Recommended threshold: {results['optimal_threshold']:.4f} "
            f"(using {method} method)"
        )
    else:
        # Fallback to median similarity
        results['optimal_threshold'] = float(np.median(similarities))
        results['recommendation'] = (
            f"Fallback threshold: {results['optimal_threshold']:.4f} "
            f"(median similarity - no optimization method succeeded)"
        )
    
    if verbose:
        print(f"\n  {results['recommendation']}")
        if len(results['candidates']) > 1:
            print(f"  Individual method recommendations:")
            for method_name, candidate in results['candidates'].items():
                print(f"    {method_name}: {candidate['threshold']:.4f}")
    
    return results


def save_persistence_diagram(
    conn: Connection,
    features: List[Tuple[int, float, float]],
    verbose: bool = False
) -> int:
    """Save persistence diagram to database."""
    if verbose:
        print(f"Saving {len(features)} persistence features to database...")
    
    batch_data = []
    for dim, birth, death in features:
        persistence = (death - birth) if death is not None else None
        batch_data.append((dim, birth, death, persistence))
    
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO document_similarity_persistence 
               (dimension, birth, death, persistence)
               VALUES (%s, %s, %s, %s)""",
            batch_data
        )
    conn.commit()
    
    if verbose:
        print(f"  Saved {len(features)} features")
    
    return len(features)


# ============================================================================
# PERSISTENCE SIGNIFICANCE ANALYSIS
# ============================================================================

def analyze_persistence_significance(
    features: List[Tuple[int, float, float]],
    significance_percentile: float = 90.0,
    verbose: bool = False
) -> Dict:
    """Analyze persistence diagram to identify significant features.
    
    Uses multiple methods to identify which topological features are
    likely to be significant (not noise):
    
    1. Percentile threshold: Features above the Nth percentile persistence
    2. IQR outlier detection: Features > Q3 + 1.5*IQR
    3. Persistence entropy: Measures concentration of persistence values
    4. Gap statistic: Identifies natural breaks in persistence distribution
    
    Args:
        features: List of (dimension, birth, death) tuples
        significance_percentile: Percentile threshold for significance
        verbose: Print analysis details
        
    Returns:
        Dictionary with analysis results and significant feature indices
    """
    if verbose:
        print("\nAnalyzing persistence significance...")
    
    results = {
        'h0': {'features': [], 'significant_indices': [], 'stats': {}},
        'h1': {'features': [], 'significant_indices': [], 'stats': {}},
        'summary': {}
    }
    
    # Separate by dimension and compute persistence
    for dim_key, dim_val in [('h0', 0), ('h1', 1)]:
        dim_features = []
        for i, (dim, birth, death) in enumerate(features):
            if dim == dim_val:
                pers = (death - birth) if death is not None else None
                dim_features.append({
                    'index': i,
                    'birth': birth,
                    'death': death,
                    'persistence': pers,
                    'is_infinite': death is None
                })
        
        results[dim_key]['features'] = dim_features
        
        if not dim_features:
            continue
        
        # Get finite persistence values for statistical analysis
        finite_pers = [f['persistence'] for f in dim_features 
                       if f['persistence'] is not None]
        
        if not finite_pers:
            continue
        
        finite_pers = np.array(finite_pers)
        
        # Basic statistics
        stats = {
            'count': len(dim_features),
            'finite_count': len(finite_pers),
            'infinite_count': sum(1 for f in dim_features if f['is_infinite']),
            'mean_persistence': float(np.mean(finite_pers)),
            'median_persistence': float(np.median(finite_pers)),
            'std_persistence': float(np.std(finite_pers)),
            'min_persistence': float(np.min(finite_pers)),
            'max_persistence': float(np.max(finite_pers)),
        }
        
        # Percentile threshold
        percentile_threshold = np.percentile(finite_pers, significance_percentile)
        stats['percentile_threshold'] = float(percentile_threshold)
        stats['percentile_used'] = significance_percentile
        
        # IQR-based outlier threshold (robust to outliers)
        q1, q3 = np.percentile(finite_pers, [25, 75])
        iqr = q3 - q1
        iqr_threshold = q3 + 1.5 * iqr
        stats['q1'] = float(q1)
        stats['q3'] = float(q3)
        stats['iqr'] = float(iqr)
        stats['iqr_threshold'] = float(iqr_threshold)
        
        # Persistence entropy (normalized)
        # Lower entropy = more concentrated (few dominant features)
        # Higher entropy = more spread out (many similar features)
        pers_normalized = finite_pers / finite_pers.sum()
        pers_normalized = pers_normalized[pers_normalized > 0]  # Remove zeros
        entropy = -np.sum(pers_normalized * np.log(pers_normalized))
        max_entropy = np.log(len(pers_normalized)) if len(pers_normalized) > 1 else 1
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
        stats['persistence_entropy'] = float(entropy)
        stats['normalized_entropy'] = float(normalized_entropy)
        
        # Gap analysis - find largest gaps in sorted persistence values
        sorted_pers = np.sort(finite_pers)[::-1]  # Descending
        if len(sorted_pers) > 1:
            gaps = np.diff(sorted_pers)  # Will be negative since descending
            gaps = -gaps  # Make positive
            if len(gaps) > 0:
                max_gap_idx = np.argmax(gaps)
                max_gap_value = float(gaps[max_gap_idx])
                gap_threshold = sorted_pers[max_gap_idx]  # Value just above the gap
                stats['max_gap_value'] = max_gap_value
                stats['gap_threshold'] = float(gap_threshold)
                stats['features_above_gap'] = int(max_gap_idx + 1)
        
        results[dim_key]['stats'] = stats
        
        # Identify significant features using multiple criteria
        significant_indices = []
        for f in dim_features:
            is_significant = False
            reasons = []
            
            # Infinite features are always significant
            if f['is_infinite']:
                is_significant = True
                reasons.append('infinite')
            elif f['persistence'] is not None:
                # Check percentile threshold
                if f['persistence'] >= percentile_threshold:
                    is_significant = True
                    reasons.append(f'above_{significance_percentile}th_percentile')
                
                # Check IQR outlier
                if f['persistence'] >= iqr_threshold:
                    is_significant = True
                    reasons.append('iqr_outlier')
                
                # Check gap threshold (if computed)
                if 'gap_threshold' in stats and f['persistence'] >= stats['gap_threshold']:
                    is_significant = True
                    reasons.append('above_gap')
            
            if is_significant:
                significant_indices.append({
                    'feature_index': f['index'],
                    'birth': float(f['birth']) if f['birth'] is not None else None,
                    'death': float(f['death']) if f['death'] is not None else None,
                    'persistence': float(f['persistence']) if f['persistence'] is not None else None,
                    'reasons': reasons
                })
        
        results[dim_key]['significant_indices'] = significant_indices
        stats['significant_count'] = len(significant_indices)
    
    # Summary
    results['summary'] = {
        'total_features': len(features),
        'h0_significant': len(results['h0']['significant_indices']),
        'h1_significant': len(results['h1']['significant_indices']),
        'total_significant': (len(results['h0']['significant_indices']) + 
                             len(results['h1']['significant_indices'])),
    }
    
    if verbose:
        print(f"\n  Persistence Significance Analysis:")
        print(f"  {'='*50}")
        
        for dim_key, label in [('h0', 'H0 (Components)'), ('h1', 'H1 (Cycles)')]:
            stats = results[dim_key]['stats']
            if not stats:
                continue
            
            print(f"\n  {label}:")
            print(f"    Total features: {stats.get('count', 0)}")
            print(f"    Finite features: {stats.get('finite_count', 0)}")
            print(f"    Infinite features: {stats.get('infinite_count', 0)}")
            
            if stats.get('finite_count', 0) > 0:
                print(f"    Mean persistence: {stats['mean_persistence']:.4f}")
                print(f"    Median persistence: {stats['median_persistence']:.4f}")
                print(f"    Std persistence: {stats['std_persistence']:.4f}")
                print(f"    Range: [{stats['min_persistence']:.4f}, {stats['max_persistence']:.4f}]")
                print(f"    {significance_percentile}th percentile threshold: {stats['percentile_threshold']:.4f}")
                print(f"    IQR outlier threshold (Q3+1.5*IQR): {stats['iqr_threshold']:.4f}")
                print(f"    Normalized entropy: {stats['normalized_entropy']:.4f} (0=concentrated, 1=uniform)")
                
                if 'gap_threshold' in stats:
                    print(f"    Gap analysis: {stats['features_above_gap']} features above largest gap")
                    print(f"    Gap threshold: {stats['gap_threshold']:.4f}")
                
                print(f"    Significant features: {stats['significant_count']}")
        
        print(f"\n  Total significant features: {results['summary']['total_significant']}")
    
    return results


def get_top_persistent_features(
    features: List[Tuple[int, float, float]],
    top_n: int = 20,
    dimension: Optional[int] = None
) -> List[Dict]:
    """Get the top N most persistent features.
    
    Args:
        features: List of (dimension, birth, death) tuples
        top_n: Number of top features to return
        dimension: Filter by dimension (None = all)
        
    Returns:
        List of feature dictionaries sorted by persistence (descending)
    """
    feature_list = []
    
    for i, (dim, birth, death) in enumerate(features):
        if dimension is not None and dim != dimension:
            continue
        
        pers = (death - birth) if death is not None else float('inf')
        feature_list.append({
            'rank': 0,  # Will be set after sorting
            'index': i,
            'dimension': dim,
            'birth': birth,
            'death': death,
            'persistence': pers if death is not None else None,
            'is_infinite': death is None,
            'birth_similarity': birth,  # Alias for clarity
            'death_similarity': death,  # Alias for clarity
        })
    
    # Sort by persistence (infinite first, then by persistence value)
    feature_list.sort(key=lambda x: (not x['is_infinite'], 
                                      -x['persistence'] if x['persistence'] else 0))
    
    # Assign ranks
    for rank, f in enumerate(feature_list[:top_n], 1):
        f['rank'] = rank
    
    return feature_list[:top_n]


def save_significance_analysis(
    conn: Connection,
    analysis_results: Dict,
    verbose: bool = False
) -> None:
    """Save significance analysis results to metadata table."""
    if verbose:
        print("Saving significance analysis to database...")
    
    import json
    
    with conn.cursor() as cur:
        # Save summary stats
        for dim_key in ['h0', 'h1']:
            stats = analysis_results[dim_key].get('stats', {})
            if stats:
                cur.execute(
                    """INSERT INTO document_similarity_metadata (key, value, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE 
                       SET value = EXCLUDED.value, updated_at = NOW()""",
                    (f"doc_sim_{dim_key}_stats", json.dumps(stats))
                )
        
        # Save significant feature indices
        for dim_key in ['h0', 'h1']:
            sig_features = analysis_results[dim_key].get('significant_indices', [])
            if sig_features:
                cur.execute(
                    """INSERT INTO document_similarity_metadata (key, value, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE 
                       SET value = EXCLUDED.value, updated_at = NOW()""",
                    (f"doc_sim_{dim_key}_significant", json.dumps(sig_features))
                )
        
        # Save summary
        cur.execute(
            """INSERT INTO document_similarity_metadata (key, value, updated_at)
               VALUES (%s, %s, NOW())
               ON CONFLICT (key) DO UPDATE 
               SET value = EXCLUDED.value, updated_at = NOW()""",
            ("doc_sim_significance_summary", json.dumps(analysis_results['summary']))
        )
    
    conn.commit()
    
    if verbose:
        print(f"  Saved significance analysis")


def print_top_features_report(
    features: List[Tuple[int, float, float]],
    top_n: int = 10,
    verbose: bool = True
) -> None:
    """Print a report of the most persistent features."""
    if not verbose:
        return
    
    print(f"\n  Top {top_n} Most Persistent Features:")
    print(f"  {'='*60}")
    print(f"  {'Rank':<6}{'Dim':<6}{'Birth':>10}{'Death':>10}{'Persistence':>12}{'Type':<10}")
    print(f"  {'-'*60}")
    
    top_features = get_top_persistent_features(features, top_n=top_n)
    
    for f in top_features:
        dim_label = 'H0' if f['dimension'] == 0 else 'H1'
        birth_str = f"{f['birth']:.4f}"
        death_str = f"{f['death']:.4f}" if f['death'] is not None else "∞"
        pers_str = f"{f['persistence']:.4f}" if f['persistence'] is not None else "∞"
        type_str = "infinite" if f['is_infinite'] else "finite"
        
        print(f"  {f['rank']:<6}{dim_label:<6}{birth_str:>10}{death_str:>10}{pers_str:>12}{type_str:<10}")
    
    print(f"  {'='*60}")


def save_betti_numbers(
    conn: Connection,
    betti_data: List[Tuple[float, int, int, int]],
    n_docs: int,
    verbose: bool = False
) -> int:
    """Save Betti numbers at each threshold to database."""
    if verbose:
        print(f"Saving Betti numbers at {len(betti_data)} thresholds...")
    
    batch_data = [(thresh, b0, b1, n_edges, n_docs) 
                  for thresh, b0, b1, n_edges in betti_data]
    
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO document_similarity_betti_numbers 
               (similarity_threshold, betti_0, betti_1, num_edges, num_vertices)
               VALUES (%s, %s, %s, %s, %s)""",
            batch_data
        )
    conn.commit()
    
    if verbose:
        print(f"  Saved {len(betti_data)} threshold records")
    
    return len(betti_data)


def save_metadata(
    conn: Connection,
    metadata: Dict[str, str],
    verbose: bool = False
) -> None:
    """Save processing metadata."""
    with conn.cursor() as cur:
        for key, value in metadata.items():
            cur.execute(
                """INSERT INTO document_similarity_metadata (key, value, updated_at)
                   VALUES (%s, %s, NOW())
                   ON CONFLICT (key) DO UPDATE 
                   SET value = EXCLUDED.value, updated_at = NOW()""",
                (f"doc_sim_{key}", str(value))
            )
    conn.commit()
    
    if verbose:
        print(f"Saved {len(metadata)} metadata entries")


# ============================================================================
# VISUALIZATION
# ============================================================================

def generate_barcode_plot(
    features: List[Tuple[int, float, float]],
    output_path: str,
    title: str = "Persistence Barcode",
    max_features_per_dim: int = 100,
    verbose: bool = False
) -> bool:
    """Generate and save a barcode plot of persistence features.
    
    Args:
        features: List of (dimension, birth, death) tuples
        output_path: Path to save the plot (PNG, PDF, SVG supported)
        title: Plot title
        max_features_per_dim: Maximum features to show per dimension (for readability)
        verbose: Print progress
        
    Returns:
        True if successful, False otherwise
    """
    if not MATPLOTLIB_AVAILABLE:
        if verbose:
            print("Warning: matplotlib not available, skipping barcode plot")
        return False
    
    if verbose:
        print(f"Generating barcode plot...")
    
    # Separate features by dimension
    h0_features = [(b, d) for dim, b, d in features if dim == 0]
    h1_features = [(b, d) for dim, b, d in features if dim == 1]
    
    # Sort by persistence (longest bars first) and limit
    def sort_key(bd):
        b, d = bd
        if d is None:
            return float('inf')  # Infinite features first
        return d - b
    
    h0_features = sorted(h0_features, key=sort_key, reverse=True)[:max_features_per_dim]
    h1_features = sorted(h1_features, key=sort_key, reverse=True)[:max_features_per_dim]
    
    # Determine plot layout
    n_dims = sum([1 for f in [h0_features, h1_features] if f])
    if n_dims == 0:
        if verbose:
            print("  No features to plot")
        return False
    
    # Create figure
    fig, axes = plt.subplots(n_dims, 1, figsize=(12, 4 * n_dims), squeeze=False)
    
    # Color scheme
    colors = {0: '#1f77b4', 1: '#ff7f0e'}  # Blue for H0, Orange for H1
    labels = {0: 'H₀ (Connected Components)', 1: 'H₁ (Cycles/Holes)'}
    
    ax_idx = 0
    
    # Find global x-axis limits (similarity scale: 0 to 1)
    all_births = [b for b, d in h0_features + h1_features]
    all_deaths = [d for b, d in h0_features + h1_features if d is not None]
    
    if all_births and all_deaths:
        x_min = min(min(all_deaths), 0)
        x_max = max(max(all_births), 1)
    else:
        x_min, x_max = 0, 1
    
    # Plot H0 features
    if h0_features:
        ax = axes[ax_idx, 0]
        _plot_barcode_dimension(
            ax, h0_features, colors[0], labels[0], 
            x_min, x_max, max_features_per_dim
        )
        ax_idx += 1
    
    # Plot H1 features
    if h1_features:
        ax = axes[ax_idx, 0]
        _plot_barcode_dimension(
            ax, h1_features, colors[1], labels[1],
            x_min, x_max, max_features_per_dim
        )
    
    # Overall title
    fig.suptitle(title, fontsize=14, fontweight='bold', y=1.02)
    
    plt.tight_layout()
    
    # Save figure
    try:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        if verbose:
            print(f"  Saved barcode plot to: {output_path}")
        return True
    except Exception as e:
        if verbose:
            print(f"  Error saving plot: {e}")
        plt.close(fig)
        return False


def _plot_barcode_dimension(
    ax: 'plt.Axes',
    features: List[Tuple[float, float]],
    color: str,
    label: str,
    x_min: float,
    x_max: float,
    max_features: int
) -> None:
    """Plot barcode for a single homology dimension."""
    n_features = len(features)
    
    # Plot each bar
    for i, (birth, death) in enumerate(features):
        y = n_features - i - 1  # Plot from top to bottom
        
        if death is None:
            # Infinite bar - extend to x_min with arrow
            ax.hlines(y, x_min, birth, colors=color, linewidth=2)
            ax.plot(x_min, y, '<', color=color, markersize=6)  # Arrow pointing left
        else:
            # Finite bar
            ax.hlines(y, death, birth, colors=color, linewidth=2)
            ax.plot([death, birth], [y, y], 'o', color=color, markersize=4)
    
    # Styling
    ax.set_xlabel('Cosine Similarity (threshold)', fontsize=11)
    ax.set_ylabel('Feature Index', fontsize=11)
    ax.set_title(label, fontsize=12, fontweight='bold')
    ax.set_xlim(x_min - 0.05, x_max + 0.05)
    ax.set_ylim(-0.5, n_features - 0.5)
    ax.invert_xaxis()  # High similarity on left (born early), low on right (dies late)
    ax.grid(True, alpha=0.3, axis='x')
    ax.axvline(x=0, color='gray', linestyle='--', alpha=0.5, label='Sim = 0')
    ax.axvline(x=1, color='gray', linestyle='--', alpha=0.5, label='Sim = 1')
    
    # Add annotation
    finite_count = sum(1 for _, d in features if d is not None)
    infinite_count = len(features) - finite_count
    annotation = f"Showing {len(features)} features"
    if infinite_count > 0:
        annotation += f" ({infinite_count} infinite)"
    ax.annotate(annotation, xy=(0.02, 0.98), xycoords='axes fraction',
                fontsize=9, verticalalignment='top', 
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))


def generate_betti_curve_plot(
    betti_data: List[Tuple[float, int, int, int]],
    output_path: str,
    title: str = "Betti Numbers vs Similarity Threshold",
    verbose: bool = False
) -> bool:
    """Generate and save a Betti curve plot.
    
    Shows how the number of connected components (β₀) and cycles (β₁)
    change as the similarity threshold varies.
    
    Args:
        betti_data: List of (threshold, betti_0, betti_1, num_edges) tuples
        output_path: Path to save the plot
        title: Plot title
        verbose: Print progress
        
    Returns:
        True if successful, False otherwise
    """
    if not MATPLOTLIB_AVAILABLE:
        if verbose:
            print("Warning: matplotlib not available, skipping Betti curve plot")
        return False
    
    if verbose:
        print(f"Generating Betti curve plot...")
    
    if not betti_data:
        if verbose:
            print("  No Betti data to plot")
        return False
    
    # Extract data
    thresholds = [t for t, b0, b1, e in betti_data]
    betti_0 = [b0 for t, b0, b1, e in betti_data]
    betti_1 = [b1 for t, b0, b1, e in betti_data]
    num_edges = [e for t, b0, b1, e in betti_data]
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    
    # Plot Betti numbers
    ax1.plot(thresholds, betti_0, 'b-', linewidth=2, label='β₀ (Components)')
    ax1.plot(thresholds, betti_1, 'r-', linewidth=2, label='β₁ (Cycles)')
    ax1.set_ylabel('Betti Number', fontsize=11)
    ax1.set_title('Topological Features', fontsize=12, fontweight='bold')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(max(thresholds), min(thresholds))  # High to low similarity
    
    # Plot number of edges
    ax2.fill_between(thresholds, num_edges, alpha=0.3, color='green')
    ax2.plot(thresholds, num_edges, 'g-', linewidth=2, label='Edges')
    ax2.set_xlabel('Cosine Similarity Threshold', fontsize=11)
    ax2.set_ylabel('Number of Edges', fontsize=11)
    ax2.set_title('Network Connectivity', fontsize=12, fontweight='bold')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # Overall title
    fig.suptitle(title, fontsize=14, fontweight='bold', y=1.02)
    
    plt.tight_layout()
    
    # Save figure
    try:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        if verbose:
            print(f"  Saved Betti curve plot to: {output_path}")
        return True
    except Exception as e:
        if verbose:
            print(f"  Error saving plot: {e}")
        plt.close(fig)
        return False


def generate_persistence_diagram_plot(
    features: List[Tuple[int, float, float]],
    output_path: str,
    significance_results: Optional[Dict] = None,
    title: str = "Persistence Diagram",
    verbose: bool = False
) -> bool:
    """Generate a persistence diagram (birth vs death scatter plot).
    
    This is a complementary visualization to the barcode where each feature
    is plotted as a point with birth on x-axis and death on y-axis.
    Points far from the diagonal have high persistence.
    
    Args:
        features: List of (dimension, birth, death) tuples
        output_path: Path to save the plot
        significance_results: Optional analysis results to highlight significant features
        title: Plot title
        verbose: Print progress
        
    Returns:
        True if successful, False otherwise
    """
    if not MATPLOTLIB_AVAILABLE:
        if verbose:
            print("Warning: matplotlib not available, skipping persistence diagram")
        return False
    
    if verbose:
        print(f"Generating persistence diagram...")
    
    # Separate by dimension
    h0_features = [(b, d) for dim, b, d in features if dim == 0 and d is not None]
    h1_features = [(b, d) for dim, b, d in features if dim == 1 and d is not None]
    h0_infinite = [b for dim, b, d in features if dim == 0 and d is None]
    h1_infinite = [b for dim, b, d in features if dim == 1 and d is None]
    
    if not h0_features and not h1_features:
        if verbose:
            print("  No finite features to plot")
        return False
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # Find axis limits
    all_births = [b for b, d in h0_features + h1_features] + h0_infinite + h1_infinite
    all_deaths = [d for b, d in h0_features + h1_features]
    
    if all_births and all_deaths:
        min_val = min(min(all_deaths), min(all_births)) - 0.05
        max_val = max(max(all_births), max(all_deaths)) + 0.05
    else:
        min_val, max_val = -0.05, 1.05
    
    # Plot diagonal (birth = death line)
    ax.plot([min_val, max_val], [min_val, max_val], 'k--', alpha=0.5, label='Diagonal (zero persistence)')
    
    # Plot H0 features
    if h0_features:
        h0_births, h0_deaths = zip(*h0_features)
        ax.scatter(h0_births, h0_deaths, c='#1f77b4', s=50, alpha=0.6, 
                   label=f'H₀ Components ({len(h0_features)})', marker='o')
    
    # Plot H1 features
    if h1_features:
        h1_births, h1_deaths = zip(*h1_features)
        ax.scatter(h1_births, h1_deaths, c='#ff7f0e', s=50, alpha=0.6,
                   label=f'H₁ Cycles ({len(h1_features)})', marker='^')
    
    # Plot infinite features along bottom edge
    if h0_infinite:
        ax.scatter(h0_infinite, [min_val + 0.02] * len(h0_infinite), 
                   c='#1f77b4', s=100, alpha=0.8, marker='v',
                   label=f'H₀ Infinite ({len(h0_infinite)})')
    if h1_infinite:
        ax.scatter(h1_infinite, [min_val + 0.02] * len(h1_infinite),
                   c='#ff7f0e', s=100, alpha=0.8, marker='v',
                   label=f'H₁ Infinite ({len(h1_infinite)})')
    
    # Highlight significant features if provided
    if significance_results:
        for dim_key, color, marker in [('h0', '#1f77b4', 'o'), ('h1', '#ff7f0e', '^')]:
            sig_features = significance_results[dim_key].get('significant_indices', [])
            for sf in sig_features:
                if sf['death'] is not None:
                    ax.scatter([sf['birth']], [sf['death']], 
                               edgecolors='red', facecolors='none',
                               s=150, linewidths=2, marker=marker)
    
    # Add persistence threshold lines (optional visualization aid)
    if significance_results:
        for dim_key, color in [('h0', '#1f77b4'), ('h1', '#ff7f0e')]:
            stats = significance_results[dim_key].get('stats', {})
            if 'percentile_threshold' in stats:
                thresh = stats['percentile_threshold']
                # Line parallel to diagonal at distance = threshold
                ax.plot([min_val, max_val - thresh], 
                        [min_val + thresh, max_val],
                        color=color, linestyle=':', alpha=0.5,
                        label=f'{dim_key.upper()} threshold: {thresh:.3f}')
    
    # Styling
    ax.set_xlabel('Birth (Similarity Threshold)', fontsize=12)
    ax.set_ylabel('Death (Similarity Threshold)', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlim(min_val, max_val)
    ax.set_ylim(min_val, max_val)
    ax.set_aspect('equal')
    ax.legend(loc='lower right', fontsize=9)
    ax.grid(True, alpha=0.3)
    
    # Add annotation about reading the plot
    ax.annotate('← Higher persistence\n(further from diagonal)',
                xy=(0.95, 0.05), xycoords='axes fraction',
                fontsize=9, ha='right', va='bottom',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    # Save figure
    try:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        if verbose:
            print(f"  Saved persistence diagram to: {output_path}")
        return True
    except Exception as e:
        if verbose:
            print(f"  Error saving plot: {e}")
        plt.close(fig)
        return False


def generate_network_plot(
    rows: np.ndarray,
    cols: np.ndarray,
    similarities: np.ndarray,
    doc_ids: List[int],
    file_paths: List[str],
    output_path: str,
    similarity_threshold: float = 0.3,
    max_nodes: int = 500,
    max_edges: int = 5000,
    title: str = "Document Similarity Network",
    verbose: bool = False
) -> bool:
    """Generate a network graph visualization of document similarities.
    
    Nodes represent documents, edges represent similarity above threshold.
    Edge thickness and color indicate similarity strength.
    Node color indicates connected component membership.
    
    Args:
        rows: Row indices of similarity pairs
        cols: Column indices of similarity pairs  
        similarities: Similarity values
        doc_ids: Document IDs corresponding to indices
        file_paths: File paths for labeling
        output_path: Path to save the plot
        similarity_threshold: Minimum similarity for edges to display
        max_nodes: Maximum nodes to show (for readability)
        max_edges: Maximum edges to show (for performance)
        title: Plot title
        verbose: Print progress
        
    Returns:
        True if successful, False otherwise
    """
    if not MATPLOTLIB_AVAILABLE:
        if verbose:
            print("Warning: matplotlib not available, skipping network plot")
        return False
    
    if not NETWORKX_AVAILABLE:
        if verbose:
            print("Warning: networkx not available, skipping network plot")
            print("  Install with: pip install networkx")
        return False
    
    if verbose:
        print(f"Generating network graph plot...")
    
    # Filter edges by threshold
    mask = similarities >= similarity_threshold
    filtered_rows = rows[mask]
    filtered_cols = cols[mask]
    filtered_sims = similarities[mask]
    
    if len(filtered_sims) == 0:
        if verbose:
            print(f"  No edges above threshold {similarity_threshold}")
        return False
    
    # Find nodes that have edges
    active_nodes = set(filtered_rows) | set(filtered_cols)
    
    if verbose:
        print(f"  {len(active_nodes)} nodes with edges above threshold")
        print(f"  {len(filtered_sims)} edges above threshold")
    
    # Limit for visualization
    if len(active_nodes) > max_nodes:
        if verbose:
            print(f"  Limiting to top {max_nodes} most connected nodes")
        # Count edges per node
        node_edge_count = {}
        for r, c in zip(filtered_rows, filtered_cols):
            node_edge_count[r] = node_edge_count.get(r, 0) + 1
            node_edge_count[c] = node_edge_count.get(c, 0) + 1
        # Keep top nodes by edge count
        top_nodes = set(sorted(node_edge_count.keys(), 
                               key=lambda x: node_edge_count[x], 
                               reverse=True)[:max_nodes])
        # Re-filter edges
        edge_mask = np.array([r in top_nodes and c in top_nodes 
                              for r, c in zip(filtered_rows, filtered_cols)])
        filtered_rows = filtered_rows[edge_mask]
        filtered_cols = filtered_cols[edge_mask]
        filtered_sims = filtered_sims[edge_mask]
        active_nodes = top_nodes
    
    if len(filtered_sims) > max_edges:
        if verbose:
            print(f"  Limiting to top {max_edges} strongest edges")
        top_edge_idx = np.argsort(-filtered_sims)[:max_edges]
        filtered_rows = filtered_rows[top_edge_idx]
        filtered_cols = filtered_cols[top_edge_idx]
        filtered_sims = filtered_sims[top_edge_idx]
    
    # Build networkx graph
    G = nx.Graph()
    
    # Add nodes
    for node_idx in active_nodes:
        # Extract short label from file path
        fp = file_paths[node_idx] if node_idx < len(file_paths) else f"doc_{node_idx}"
        label = os.path.basename(fp).replace('_extracted.txt', '').replace('.txt', '')
        if len(label) > 15:
            label = label[:12] + '...'
        G.add_node(node_idx, label=label, doc_id=doc_ids[node_idx] if node_idx < len(doc_ids) else node_idx)
    
    # Add edges with similarity as weight
    for r, c, sim in zip(filtered_rows, filtered_cols, filtered_sims):
        G.add_edge(r, c, weight=float(sim))
    
    if verbose:
        print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    
    # Find connected components for coloring
    components = list(nx.connected_components(G))
    node_to_component = {}
    for i, comp in enumerate(components):
        for node in comp:
            node_to_component[node] = i
    
    if verbose:
        print(f"  Found {len(components)} connected components")
    
    # Create figure
    fig, ax = plt.subplots(figsize=(16, 16))
    
    # Choose layout algorithm based on graph size
    if G.number_of_nodes() < 100:
        if verbose:
            print(f"  Using spring layout...")
        pos = nx.spring_layout(G, k=2/np.sqrt(G.number_of_nodes()), iterations=50, seed=42)
    elif G.number_of_nodes() < 300:
        if verbose:
            print(f"  Using Kamada-Kawai layout...")
        pos = nx.kamada_kawai_layout(G)
    else:
        if verbose:
            print(f"  Using fast spring layout for large graph...")
        pos = nx.spring_layout(G, k=1.5/np.sqrt(G.number_of_nodes()), iterations=30, seed=42)
    
    # Color map for components
    n_components = len(components)
    if n_components <= 10:
        cmap = plt.cm.tab10
    elif n_components <= 20:
        cmap = plt.cm.tab20
    else:
        cmap = plt.cm.nipy_spectral
    
    node_colors = [cmap(node_to_component[node] % cmap.N / cmap.N) for node in G.nodes()]
    
    # Edge colors and widths based on similarity
    edge_weights = [G[u][v]['weight'] for u, v in G.edges()]
    edge_colors = [plt.cm.YlOrRd(w) for w in edge_weights]
    edge_widths = [0.5 + 2 * w for w in edge_weights]  # Scale width by similarity
    
    # Draw edges
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color=edge_colors,
        width=edge_widths,
        alpha=0.6
    )
    
    # Draw nodes
    node_sizes = [100 + 20 * G.degree(node) for node in G.nodes()]  # Size by degree
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors,
        node_size=node_sizes,
        alpha=0.8,
        edgecolors='black',
        linewidths=0.5
    )
    
    # Draw labels only for smaller graphs or high-degree nodes
    if G.number_of_nodes() <= 50:
        labels = nx.get_node_attributes(G, 'label')
        nx.draw_networkx_labels(G, pos, labels, font_size=7, ax=ax)
    elif G.number_of_nodes() <= 150:
        # Only label high-degree nodes
        high_degree_nodes = [n for n in G.nodes() if G.degree(n) >= 5]
        labels = {n: G.nodes[n]['label'] for n in high_degree_nodes}
        nx.draw_networkx_labels(G, pos, labels, font_size=6, ax=ax)
    
    # Title and styling
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.axis('off')
    
    # Add legend/info box
    info_text = (f"Nodes: {G.number_of_nodes()}\\n"
                 f"Edges: {G.number_of_edges()}\\n"
                 f"Components: {len(components)}\\n"
                 f"Threshold: {similarity_threshold:.2f}")
    ax.annotate(info_text, xy=(0.02, 0.98), xycoords='axes fraction',
                fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
                family='monospace')
    
    # Add colorbar for edge weights
    sm = plt.cm.ScalarMappable(cmap=plt.cm.YlOrRd, 
                                norm=plt.Normalize(vmin=similarity_threshold, vmax=1.0))
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.3, aspect=20, pad=0.02)
    cbar.set_label('Cosine Similarity', fontsize=10)
    
    plt.tight_layout()
    
    # Save figure
    try:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        if verbose:
            print(f"  Saved network plot to: {output_path}")
        return True
    except Exception as e:
        if verbose:
            print(f"  Error saving plot: {e}")
        plt.close(fig)
        return False


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build document similarity network and compute persistent homology"
    )
    parser.add_argument(
        "--dsn",
        default=DEFAULT_DSN,
        help="PostgreSQL connection string"
    )
    parser.add_argument(
        "--tdm-type",
        choices=['noun', 'verb', 'both'],
        default='noun',
        help="Which TDM to use for similarity computation (default: noun). Use 'both' to combine noun and verb features."
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        help="Maximum number of documents to process (default: all)"
    )
    parser.add_argument(
        "--min-terms",
        type=int,
        default=5,
        help="Minimum terms per document to include (default: 5)"
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.1,
        help="Minimum similarity to store (filters noise, default: 0.1)"
    )
    parser.add_argument(
        "--max-dim",
        type=int,
        default=1,
        help="Maximum homology dimension to compute (default: 1)"
    )
    parser.add_argument(
        "--n-thresholds",
        type=int,
        default=100,
        help="Number of threshold values for Betti number computation (default: 100)"
    )
    parser.add_argument(
        "--skip-pairs",
        action="store_true",
        help="Skip saving individual similarity pairs (saves space)"
    )
    parser.add_argument(
        "--native-only",
        action="store_true",
        help="Use native H0 implementation only (avoids GUDHI/ripser crashes on large matrices)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for output plots (default: current directory)"
    )
    parser.add_argument(
        "--barcode-plot",
        type=str,
        default="persistence_barcode.png",
        help="Filename for barcode plot (default: persistence_barcode.png)"
    )
    parser.add_argument(
        "--betti-plot",
        type=str,
        default="betti_curves.png",
        help="Filename for Betti curve plot (default: betti_curves.png)"
    )
    parser.add_argument(
        "--diagram-plot",
        type=str,
        default="persistence_diagram.png",
        help="Filename for persistence diagram plot (default: persistence_diagram.png)"
    )
    parser.add_argument(
        "--network-plot",
        type=str,
        default="similarity_network.png",
        help="Filename for network graph plot (default: similarity_network.png)"
    )
    parser.add_argument(
        "--network-threshold",
        type=float,
        default=None,
        help="Similarity threshold for network plot edges (default: uses --min-similarity)"
    )
    parser.add_argument(
        "--auto-threshold",
        action="store_true",
        help="Automatically find optimal threshold for network visualization"
    )
    parser.add_argument(
        "--threshold-method",
        choices=['auto', 'modularity', 'persistence', 'knee', 'silhouette'],
        default='auto',
        help="Method for automatic threshold selection (default: auto)"
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip generating visualization plots"
    )
    parser.add_argument(
        "--significance-percentile",
        type=float,
        default=90.0,
        help="Percentile threshold for significant features (default: 90)"
    )
    parser.add_argument(
        "--top-features",
        type=int,
        default=20,
        help="Number of top features to report (default: 20)"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing data before processing (requires --confirm)"
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
    
    # New enhancement arguments
    parser.add_argument(
        "--entity-weight",
        type=float,
        default=0.0,
        help="Weight for entity co-occurrence in similarity (0.0-1.0, default: 0.0 = TF-IDF only)"
    )
    parser.add_argument(
        "--export-format",
        choices=['gexf', 'graphml', 'edgelist'],
        default=None,
        help="Export graph to file format (default: no export)"
    )
    parser.add_argument(
        "--export-file",
        type=str,
        default=None,
        help="Output filename for graph export (default: similarity_network.<format>)"
    )
    parser.add_argument(
        "--skip-labels",
        action="store_true",
        help="Skip community labeling analysis"
    )
    parser.add_argument(
        "--skip-bridges",
        action="store_true",
        help="Skip bridge document analysis"
    )
    parser.add_argument(
        "--bridge-top-n",
        type=int,
        default=20,
        help="Number of top bridge documents to analyze (default: 20)"
    )
    parser.add_argument(
        "--multi-threshold",
        action="store_true",
        help="Compute communities at multiple thresholds for interactive visualization"
    )
    parser.add_argument(
        "--threshold-start",
        type=float,
        default=0.2,
        help="Starting threshold for multi-threshold analysis (default: 0.2)"
    )
    parser.add_argument(
        "--threshold-end",
        type=float,
        default=0.95,
        help="Ending threshold for multi-threshold analysis (default: 0.95)"
    )
    parser.add_argument(
        "--threshold-step",
        type=float,
        default=0.05,
        help="Step size for multi-threshold analysis (default: 0.05)"
    )
    args = parser.parse_args()
    
    if psycopg is None:
        print("psycopg is required. Install with: pip install psycopg", file=sys.stderr)
        return 2
    
    # Check for --confirm on destructive operations
    if args.clear and not args.confirm and not args.dry_run:
        print("ERROR: --clear requires --confirm flag for safety.", file=sys.stderr)
        return 1
    
    # Report available TDA libraries
    if args.verbose:
        print("TDA library availability:")
        print(f"  ripser: {'available' if RIPSER_AVAILABLE else 'not installed'}")
        print(f"  gudhi: {'available' if GUDHI_AVAILABLE else 'not installed'}")
        print(f"  matplotlib: {'available' if MATPLOTLIB_AVAILABLE else 'not installed'}")
        if not RIPSER_AVAILABLE and not GUDHI_AVAILABLE:
            print("  Using native H0 computation (install ripser or gudhi for H1)")
    
    # Handle dry-run mode
    if args.dry_run:
        print("[DRY RUN] Would perform the following operations:")
        if args.clear:
            print("  - Clear existing document similarity data")
        print(f"  - Load {args.tdm_type} TDM from database")
        if args.max_docs:
            print(f"  - Limit to top {args.max_docs} documents by term count")
        print(f"  - Filter documents with < {args.min_terms} terms")
        print(f"  - Compute TF-IDF weighted document vectors")
        print(f"  - Compute pairwise cosine similarity")
        print(f"  - Filter pairs with similarity < {args.min_similarity}")
        if not args.skip_pairs:
            print("  - Save similarity pairs to database")
        print(f"  - Compute persistent homology up to dimension {args.max_dim}")
        print(f"  - Analyze significance at {args.significance_percentile}th percentile")
        print(f"  - Report top {args.top_features} most persistent features")
        print(f"  - Compute Betti numbers at {args.n_thresholds} thresholds")
        print("  - Save results to database")
        if not args.no_plots and MATPLOTLIB_AVAILABLE:
            output_dir = args.output_dir or os.getcwd()
            print(f"  - Generate barcode plot: {os.path.join(output_dir, args.barcode_plot)}")
            print(f"  - Generate persistence diagram: {os.path.join(output_dir, args.diagram_plot)}")
            print(f"  - Generate Betti curve plot: {os.path.join(output_dir, args.betti_plot)}")
        return 0
    
    try:
        with get_db_connection(args.dsn) as conn:
            start_time = time.time()
            
            # Initialize database
            initialize_database(conn, verbose=args.verbose)
            
            # Clear existing data if requested
            if args.clear:
                clear_existing_data(conn, verbose=args.verbose)
            
            # Load TDM from database
            if args.tdm_type == 'both':
                tdm, doc_ids, file_paths, terms = load_combined_tdm_from_database(
                    conn,
                    max_docs=args.max_docs,
                    min_terms=args.min_terms,
                    noun_weight=1.0,
                    verb_weight=1.0,
                    verbose=args.verbose
                )
            else:
                tdm, doc_ids, file_paths, terms = load_tdm_from_database(
                    conn,
                    tdm_type=args.tdm_type,
                    max_docs=args.max_docs,
                    min_terms=args.min_terms,
                    verbose=args.verbose
                )
            
            n_docs = len(doc_ids)
            
            # Apply TF-IDF weighting
            tfidf_matrix = compute_tfidf(tdm, verbose=args.verbose)
            
            # Compute similarity matrix
            rows, cols, similarities = compute_similarity_matrix(
                tfidf_matrix,
                min_similarity=args.min_similarity,
                verbose=args.verbose
            )
            
            if len(similarities) == 0:
                print("No document pairs found above minimum similarity threshold.")
                return 1
            
            # Apply entity weighting if requested
            if args.entity_weight > 0:
                rows, cols, similarities = compute_entity_weighted_similarity(
                    conn,
                    doc_ids,
                    file_paths,
                    similarities,
                    rows,
                    cols,
                    entity_weight=args.entity_weight,
                    verbose=args.verbose
                )
            
            # Save similarity pairs (optional)
            if not args.skip_pairs:
                n_pairs = save_similarity_pairs(
                    conn, rows, cols, similarities, doc_ids, file_paths,
                    verbose=args.verbose
                )
            else:
                n_pairs = len(similarities)
                if args.verbose:
                    print(f"Skipping storage of {n_pairs:,} similarity pairs")
            
            # Compute persistent homology
            if args.native_only:
                # User requested native-only (avoids GUDHI/ripser crashes)
                features = compute_persistent_homology_native(
                    similarities, rows, cols, n_docs,
                    verbose=args.verbose
                )
            elif RIPSER_AVAILABLE:
                features = compute_persistent_homology_ripser(
                    similarities, rows, cols, n_docs,
                    max_dim=args.max_dim,
                    verbose=args.verbose
                )
            elif GUDHI_AVAILABLE:
                features = compute_persistent_homology_gudhi(
                    similarities, rows, cols, n_docs,
                    max_dim=args.max_dim,
                    verbose=args.verbose
                )
            else:
                # Native implementation (H0 only)
                features = compute_persistent_homology_native(
                    similarities, rows, cols, n_docs,
                    verbose=args.verbose
                )
            
            # Save persistence diagram
            n_features = save_persistence_diagram(conn, features, verbose=args.verbose)
            
            # Analyze persistence significance
            significance_results = analyze_persistence_significance(
                features,
                significance_percentile=args.significance_percentile,
                verbose=args.verbose
            )
            save_significance_analysis(conn, significance_results, verbose=args.verbose)
            
            # Print top features report
            print_top_features_report(features, top_n=args.top_features, verbose=args.verbose)
            
            # Compute and save Betti numbers at various thresholds
            betti_data = compute_betti_numbers(
                similarities, rows, cols, n_docs,
                n_thresholds=args.n_thresholds,
                verbose=args.verbose
            )
            save_betti_numbers(conn, betti_data, n_docs, verbose=args.verbose)
            
            # Save metadata
            elapsed = time.time() - start_time
            metadata = {
                'tdm_type': args.tdm_type,
                'num_documents': n_docs,
                'num_terms': len(terms),
                'num_pairs': n_pairs,
                'num_persistence_features': n_features,
                'min_similarity': args.min_similarity,
                'max_dimension': args.max_dim,
                'processing_time_seconds': f"{elapsed:.2f}",
                'processed_at': datetime.now().isoformat(),
                'tda_library': 'ripser' if RIPSER_AVAILABLE else ('gudhi' if GUDHI_AVAILABLE else 'native')
            }
            save_metadata(conn, metadata, verbose=args.verbose)
            
            # Generate visualization plots
            if not args.no_plots:
                output_dir = args.output_dir or os.getcwd()
                
                # Barcode plot
                barcode_path = os.path.join(output_dir, args.barcode_plot)
                generate_barcode_plot(
                    features,
                    barcode_path,
                    title=f"Document Similarity Persistence Barcode ({n_docs:,} documents)",
                    verbose=args.verbose
                )
                
                # Persistence diagram plot
                diagram_path = os.path.join(output_dir, args.diagram_plot)
                generate_persistence_diagram_plot(
                    features,
                    diagram_path,
                    significance_results=significance_results,
                    title=f"Document Similarity Persistence Diagram ({n_docs:,} documents)",
                    verbose=args.verbose
                )
                
                # Betti curve plot
                betti_path = os.path.join(output_dir, args.betti_plot)
                generate_betti_curve_plot(
                    betti_data,
                    betti_path,
                    title=f"Betti Numbers vs Similarity Threshold ({n_docs:,} documents)",
                    verbose=args.verbose
                )
                
                # Network graph plot
                network_path = os.path.join(output_dir, args.network_plot)
                
                # Determine network threshold
                if args.auto_threshold:
                    # Find optimal threshold automatically
                    threshold_results = find_optimal_threshold(
                        similarities, rows, cols, n_docs,
                        betti_data=betti_data,
                        features=features,
                        method=args.threshold_method,
                        verbose=args.verbose
                    )
                    network_threshold = threshold_results['optimal_threshold']
                    
                    # Save threshold analysis to metadata
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO document_similarity_metadata (key, value, updated_at)
                               VALUES (%s, %s, NOW())
                               ON CONFLICT (key) DO UPDATE 
                               SET value = EXCLUDED.value, updated_at = NOW()""",
                            ("doc_sim_optimal_threshold", json.dumps({
                                'optimal_threshold': network_threshold,
                                'method': args.threshold_method,
                                'candidates': threshold_results.get('candidates', {})
                            }))
                        )
                    conn.commit()
                elif args.network_threshold:
                    network_threshold = args.network_threshold
                else:
                    network_threshold = args.min_similarity
                
                generate_network_plot(
                    rows, cols, similarities,
                    doc_ids, file_paths,
                    network_path,
                    similarity_threshold=network_threshold,
                    title=f"Document Similarity Network (threshold ≥ {network_threshold:.3f})",
                    verbose=args.verbose
                )
                
                # Compute and save centrality measures
                centrality_results = compute_centrality_measures(
                    conn,
                    similarity_threshold=network_threshold,
                    verbose=args.verbose
                )
                
                # Multi-threshold community detection for interactive visualization
                if args.multi_threshold:
                    if args.verbose:
                        print(f"\nComputing communities at multiple thresholds ({args.threshold_start:.2f} to {args.threshold_end:.2f}, step {args.threshold_step:.2f})...")
                    
                    import numpy as np
                    thresholds = np.arange(args.threshold_start, args.threshold_end + args.threshold_step/2, args.threshold_step)
                    best_modularity = -1
                    best_threshold = network_threshold
                    
                    for thresh in thresholds:
                        if args.verbose:
                            print(f"  Processing threshold {thresh:.2f}...", end=" ")
                        
                        # Detect communities at this threshold
                        comm_result = detect_communities(
                            conn,
                            similarity_threshold=float(thresh),
                            algorithm='louvain',
                            verbose=False
                        )
                        
                        if comm_result:
                            mod = comm_result.get('modularity', 0)
                            n_comm = comm_result.get('num_communities', 0)
                            if args.verbose:
                                print(f"{n_comm} communities, modularity={mod:.4f}")
                            
                            # Track best modularity
                            if mod > best_modularity:
                                best_modularity = mod
                                best_threshold = float(thresh)
                            
                            # Compute centrality at this threshold
                            compute_centrality_measures(
                                conn,
                                similarity_threshold=float(thresh),
                                verbose=False
                            )
                            
                            # Label communities at this threshold
                            if not args.skip_labels:
                                label_communities(
                                    conn,
                                    similarity_threshold=float(thresh),
                                    algorithm='louvain',
                                    verbose=False
                                )
                            
                            # Analyze bridges at this threshold
                            if not args.skip_bridges:
                                analyze_bridge_documents(
                                    conn,
                                    similarity_threshold=float(thresh),
                                    algorithm='louvain',
                                    top_n=args.bridge_top_n,
                                    verbose=False
                                )
                    
                    if args.verbose:
                        print(f"\n  Optimal threshold: {best_threshold:.2f} (modularity={best_modularity:.4f})")
                        print(f"  Total thresholds computed: {len(thresholds)}")
                    
                    # Use optimal threshold for exports
                    network_threshold = best_threshold
                
                # Detect communities at final threshold (or single threshold mode)
                if not args.multi_threshold:
                    community_results = detect_communities(
                        conn,
                        similarity_threshold=network_threshold,
                        algorithm='louvain',
                        verbose=args.verbose
                    )
                else:
                    # Re-fetch the best threshold results for summary
                    community_results = detect_communities(
                        conn,
                        similarity_threshold=network_threshold,
                        algorithm='louvain',
                        verbose=False
                    )
                
                # Label communities with entities and temporal info
                if not args.skip_labels and community_results:
                    label_results = label_communities(
                        conn,
                        similarity_threshold=network_threshold,
                        algorithm='louvain',
                        verbose=args.verbose
                    )
                
                # Analyze bridge documents
                if not args.skip_bridges and centrality_results:
                    bridge_results = analyze_bridge_documents(
                        conn,
                        similarity_threshold=network_threshold,
                        algorithm='louvain',
                        top_n=args.bridge_top_n,
                        verbose=args.verbose
                    )
                
                # Export graph if requested
                if args.export_format:
                    export_filename = args.export_file or f"similarity_network.{args.export_format}"
                    export_path = os.path.join(output_dir, export_filename)
                    export_graph(
                        conn,
                        similarity_threshold=network_threshold,
                        output_path=export_path,
                        format=args.export_format,
                        include_communities=True,
                        include_centrality=True,
                        verbose=args.verbose
                    )
            
            # Summary
            if args.verbose:
                print("\n" + "=" * 60)
                print("DOCUMENT SIMILARITY NETWORK SUMMARY")
                print("=" * 60)
                print(f"Documents processed: {n_docs:,}")
                print(f"Similarity pairs (>= {args.min_similarity}): {n_pairs:,}")
                if args.entity_weight > 0:
                    print(f"  Entity weight: {args.entity_weight}")
                print(f"Persistence features: {n_features}")
                print(f"  H0 (components): {sum(1 for f in features if f[0] == 0)}")
                if args.max_dim >= 1:
                    print(f"  H1 (cycles): {sum(1 for f in features if f[0] == 1)}")
                print(f"Significant features: {significance_results['summary']['total_significant']}")
                print(f"Betti number thresholds: {len(betti_data)}")
                if community_results:
                    print(f"Communities detected: {community_results.get('num_communities', 0)}")
                    print(f"  Modularity: {community_results.get('modularity', 0):.4f}")
                    if not args.skip_labels and 'label_results' in dir() and label_results:
                        print(f"  Communities labeled: {label_results.get('communities_labeled', 0)}")
                if not args.skip_bridges and 'bridge_results' in dir() and bridge_results:
                    print(f"Bridge documents analyzed: {len(bridge_results.get('bridges', []))}")
                if not args.no_plots and MATPLOTLIB_AVAILABLE:
                    print(f"Plots saved:")
                    print(f"  - Barcode: {barcode_path}")
                    print(f"  - Persistence diagram: {diagram_path}")
                    print(f"  - Betti curves: {betti_path}")
                    print(f"  - Network graph: {network_path}")
                if args.export_format:
                    export_filename = args.export_file or f"similarity_network.{args.export_format}"
                    print(f"Graph exported: {os.path.join(output_dir, export_filename)}")
                print(f"Processing time: {elapsed:.2f} seconds")
                print("=" * 60)
            
            return 0
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
