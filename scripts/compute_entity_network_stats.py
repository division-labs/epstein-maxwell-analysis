#!/usr/bin/env python3
"""Compute entity network statistics and centrality measures.

This module analyzes the entity network stored in PostgreSQL using graph theory
algorithms to compute various centrality measures and detect community structure.
The entity network is a mixed-mode network containing both person and company
nodes, with different types of relationships between them.

Computed Metrics:
    Standard Centrality Measures:
        - Degree centrality: Number of direct connections
        - Betweenness centrality: How often a node lies on shortest paths
        - Eigenvector centrality: Connection to other important nodes
        - Closeness centrality: Average distance to all other nodes
        - PageRank: Influence based on link structure
        - Clustering coefficient: How connected a node's neighbors are

    Type-Specific Metrics (for mixed-mode networks):
        - Same-type degree: Connections to nodes of the same type
        - Cross-type degree: Connections to nodes of different types
        - Person subgraph metrics: Centrality computed on person-only network
        - Projection degree: Person connections through shared companies

    Community Detection:
        - Louvain algorithm for community assignment
        - Connected component identification

Output Tables:
    - entity_network_centrality: All centrality measures per entity
    - entity_network_communities: Community assignments per entity

Example:
    Run with verbose output::

        $ python3 scripts/compute_entity_network_stats.py --verbose

    Use custom database connection::

        $ python3 scripts/compute_entity_network_stats.py --dsn "postgresql://user:pass@host/db"

Note:
    Requires the entity_network_entities and entity_network_relationships
    tables to be populated first via load_sourced_entity_network.py.
"""

import argparse
import sys
from typing import Any, Dict

try:
    import psycopg
    from psycopg import Connection
except ImportError:
    print("Error: psycopg is required. Install with: pip install psycopg[binary]")
    sys.exit(1)

try:
    import networkx as nx
except ImportError:
    print("Error: networkx is required. Install with: pip install networkx")
    sys.exit(1)

from db_utils import get_db_connection


# ============================================================================
# DATABASE SCHEMA
# ============================================================================

CREATE_CENTRALITY_TABLE = """
DROP TABLE IF EXISTS entity_network_centrality CASCADE;
CREATE TABLE entity_network_centrality (
    centrality_id SERIAL PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entity_network_entities(entity_id) ON DELETE CASCADE,
    
    -- Full network metrics (all nodes, all edges)
    degree INTEGER NOT NULL,              -- Number of connections
    degree_centrality FLOAT NOT NULL,     -- Normalized degree (full network)
    betweenness_centrality FLOAT NOT NULL, -- Bridge score between clusters
    eigenvector_centrality FLOAT,         -- Importance based on neighbor importance
    closeness_centrality FLOAT,           -- Average distance to all other nodes
    clustering_coefficient FLOAT,         -- How connected neighbors are to each other
    pagerank FLOAT,                       -- Google-style importance ranking
    
    -- Type-specific metrics (for mixed-mode network analysis)
    degree_same_type INTEGER DEFAULT 0,   -- Connections to same type (person-person or company-company)
    degree_cross_type INTEGER DEFAULT 0,  -- Connections to other type (person-company)
    degree_centrality_normalized FLOAT,   -- Degree normalized by max possible for this type
    
    -- Person subgraph metrics (only computed for persons)
    person_subgraph_degree INTEGER,       -- Degree in person-only subgraph
    person_subgraph_betweenness FLOAT,    -- Betweenness in person-only subgraph
    person_subgraph_eigenvector FLOAT,    -- Eigenvector in person-only subgraph
    
    -- Bipartite projection metric (persons connected through shared companies)
    projection_degree INTEGER,            -- Degree in projected person-person network
    
    component_id INTEGER,                 -- Which connected component
    component_size INTEGER,               -- Size of the component
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_ent_cent_entity ON entity_network_centrality(entity_id);
CREATE INDEX IF NOT EXISTS idx_ent_cent_degree ON entity_network_centrality(degree_centrality DESC);
CREATE INDEX IF NOT EXISTS idx_ent_cent_between ON entity_network_centrality(betweenness_centrality DESC);
CREATE INDEX IF NOT EXISTS idx_ent_cent_eigen ON entity_network_centrality(eigenvector_centrality DESC);
CREATE INDEX IF NOT EXISTS idx_ent_cent_pagerank ON entity_network_centrality(pagerank DESC);
CREATE INDEX IF NOT EXISTS idx_ent_cent_person_subgraph ON entity_network_centrality(person_subgraph_betweenness DESC);
"""

CREATE_COMMUNITIES_TABLE = """
CREATE TABLE IF NOT EXISTS entity_network_communities (
    community_id SERIAL PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entity_network_entities(entity_id) ON DELETE CASCADE,
    community INTEGER NOT NULL,           -- Community assignment
    algorithm TEXT NOT NULL DEFAULT 'louvain',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(entity_id, algorithm)
);

CREATE INDEX IF NOT EXISTS idx_ent_comm_entity ON entity_network_communities(entity_id);
CREATE INDEX IF NOT EXISTS idx_ent_comm_community ON entity_network_communities(community);
"""


def create_tables(conn: Connection, verbose: bool = False) -> None:
    """Create database tables for storing centrality and community data.

    Drops existing tables and recreates them with the full schema. This
    includes all centrality measures and community detection results.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, print progress messages to stdout.

    Note:
        This operation is destructive - all existing centrality and
        community data will be lost.
    """
    with conn.cursor() as cur:
        if verbose:
            print("Creating entity_network_centrality table...")
        cur.execute(CREATE_CENTRALITY_TABLE)
        
        if verbose:
            print("Creating entity_network_communities table...")
        cur.execute(CREATE_COMMUNITIES_TABLE)
    
    conn.commit()


def build_entity_graph(
    conn: Connection, verbose: bool = False
) -> tuple[nx.Graph, Dict[int, str]]:
    """Build a NetworkX graph from entity relationships in the database.

    Constructs an undirected graph where nodes are entities (persons or
    companies) and edges represent relationships between them. Duplicate
    edges between the same pair of entities are merged, combining their
    relationship types.

    Args:
        conn: Active psycopg database connection.
        verbose: If True, print progress messages to stdout.

    Returns:
        A tuple containing:
            - nx.Graph: NetworkX graph with entity_id as node identifiers.
              Node attributes include 'name' and 'type' (person/company).
              Edge attributes include 'weight', 'relationship_types' (set),
              and 'confidence' (float).
            - Dict[int, str]: Mapping from entity_id to entity name.
    """
    if verbose:
        print("Building entity network graph...")
    
    G = nx.Graph()  # Undirected graph
    entity_names = {}
    
    # Get all entities
    with conn.cursor() as cur:
        cur.execute("""
            SELECT entity_id, entity_name, entity_type
            FROM entity_network_entities
        """)
        for row in cur.fetchall():
            entity_id, entity_name, entity_type = row
            G.add_node(entity_id, name=entity_name, type=entity_type)
            entity_names[entity_id] = entity_name
    
    if verbose:
        print(f"  Added {G.number_of_nodes()} entity nodes")
    
    # Get all relationships (collapse bidirectional by creating undirected edges)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source_entity_id, target_entity_id, relationship_type, confidence_score
            FROM entity_network_relationships
            WHERE source_reference IN ('known_relationships', 'sourced_data')
        """)
        edge_count = 0
        for row in cur.fetchall():
            source_id, target_id, rel_type, confidence = row
            # For undirected graph, adding same edge twice just updates it
            if G.has_edge(source_id, target_id):
                # Increment weight for multiple relationship types
                G[source_id][target_id]['weight'] += 1
                G[source_id][target_id]['relationship_types'].add(rel_type)
            else:
                G.add_edge(source_id, target_id, 
                          weight=1,
                          relationship_types={rel_type},
                          confidence=confidence or 1.0)
                edge_count += 1
    
    if verbose:
        print(f"  Added {edge_count} unique edges")
    
    return G, entity_names


def compute_type_specific_metrics(
    G: nx.Graph, verbose: bool = False
) -> Dict[str, Dict[int, Any]]:
    """Compute type-specific metrics for a mixed-mode network.

    Analyzes the network considering the heterogeneous nature of nodes
    (persons vs companies). This provides more nuanced metrics than
    standard centrality measures for networks with different node types.

    Computed Metrics:
        - Same-type vs cross-type degree: Counts connections to nodes
          of the same or different type.
        - Person subgraph metrics: Centrality measures computed only
          on the person-to-person network (excluding companies).
        - Bipartite projection: Connects persons who share common
          company affiliations.

    Args:
        G: NetworkX graph with 'type' attribute on nodes ('person' or 'company').
        verbose: If True, print progress messages to stdout.

    Returns:
        Dictionary with the following keys, each mapping entity_id to value:
            - 'degree_same_type': Connections to same-type nodes
            - 'degree_cross_type': Connections to different-type nodes
            - 'degree_centrality_normalized': Degree normalized by max possible
            - 'person_subgraph_degree': Degree in person-only network (None for companies)
            - 'person_subgraph_betweenness': Betweenness in person-only network
            - 'person_subgraph_eigenvector': Eigenvector in person-only network
            - 'projection_degree': Connections through shared companies
    """
    results = {
        'degree_same_type': {},
        'degree_cross_type': {},
        'degree_centrality_normalized': {},
        'person_subgraph_degree': {},
        'person_subgraph_betweenness': {},
        'person_subgraph_eigenvector': {},
        'projection_degree': {}
    }
    
    if verbose:
        print("Computing type-specific metrics...")
    
    # Count nodes by type
    person_nodes = [n for n in G.nodes() if G.nodes[n].get('type') == 'person']
    company_nodes = [n for n in G.nodes() if G.nodes[n].get('type') == 'company']
    
    if verbose:
        print(f"  Person nodes: {len(person_nodes)}, Company nodes: {len(company_nodes)}")
    
    # Same-type vs cross-type degree
    for node in G.nodes():
        node_type = G.nodes[node].get('type')
        same = 0
        cross = 0
        for neighbor in G.neighbors(node):
            if G.nodes[neighbor].get('type') == node_type:
                same += 1
            else:
                cross += 1
        results['degree_same_type'][node] = same
        results['degree_cross_type'][node] = cross
        
        # Normalized degree centrality by type
        # Person max connections = all other persons + all companies
        # Company max connections = all persons (no company-company edges exist)
        if node_type == 'person':
            max_possible = len(person_nodes) - 1 + len(company_nodes)
        else:
            max_possible = len(person_nodes)
        
        total_degree = same + cross
        results['degree_centrality_normalized'][node] = total_degree / max_possible if max_possible > 0 else 0
    
    # Person subgraph (only person-person edges)
    if verbose:
        print("  Building person-only subgraph...")
    person_subgraph = G.subgraph(person_nodes).copy()
    
    # Remove any edges to companies that might have leaked through
    edges_to_remove = [(u, v) for u, v in person_subgraph.edges() 
                       if G.nodes[u].get('type') != 'person' or G.nodes[v].get('type') != 'person']
    person_subgraph.remove_edges_from(edges_to_remove)
    
    if verbose:
        print(f"  Person subgraph: {person_subgraph.number_of_nodes()} nodes, {person_subgraph.number_of_edges()} edges")
    
    # Compute metrics on person subgraph
    for node in G.nodes():
        if node in person_nodes and person_subgraph.has_node(node):
            results['person_subgraph_degree'][node] = person_subgraph.degree(node)
        else:
            results['person_subgraph_degree'][node] = None
    
    if person_subgraph.number_of_edges() > 0:
        # Betweenness on person subgraph
        person_betweenness = nx.betweenness_centrality(person_subgraph)
        for node in G.nodes():
            results['person_subgraph_betweenness'][node] = person_betweenness.get(node)
        
        # Eigenvector on person subgraph (only connected components)
        try:
            connected_persons = [n for n in person_subgraph.nodes() if person_subgraph.degree(n) > 0]
            if connected_persons:
                H = person_subgraph.subgraph(connected_persons).copy()
                person_eigen = nx.eigenvector_centrality(H, max_iter=1000)
                for node in G.nodes():
                    results['person_subgraph_eigenvector'][node] = person_eigen.get(node)
            else:
                for node in G.nodes():
                    results['person_subgraph_eigenvector'][node] = None
        except nx.PowerIterationFailedConvergence:
            if verbose:
                print("    Warning: person subgraph eigenvector did not converge")
            for node in G.nodes():
                results['person_subgraph_eigenvector'][node] = None
    else:
        for node in G.nodes():
            results['person_subgraph_betweenness'][node] = None
            results['person_subgraph_eigenvector'][node] = None
    
    # Bipartite projection: persons connected through shared companies
    if verbose:
        print("  Computing bipartite projection (persons connected through shared companies)...")
    
    # Build projection: two persons are connected if they share a company
    projection = nx.Graph()
    projection.add_nodes_from(person_nodes)
    
    for company in company_nodes:
        # Get all persons connected to this company
        connected_persons = [n for n in G.neighbors(company) if n in person_nodes]
        # Create edges between all pairs
        for i, p1 in enumerate(connected_persons):
            for p2 in connected_persons[i+1:]:
                if projection.has_edge(p1, p2):
                    projection[p1][p2]['weight'] += 1
                else:
                    projection.add_edge(p1, p2, weight=1)
    
    if verbose:
        print(f"  Projection: {projection.number_of_nodes()} nodes, {projection.number_of_edges()} edges")
    
    for node in G.nodes():
        if node in person_nodes:
            results['projection_degree'][node] = projection.degree(node)
        else:
            results['projection_degree'][node] = None
    
    return results


def compute_centrality_measures(
    G: nx.Graph, verbose: bool = False
) -> Dict[str, Dict[int, float]]:
    """Compute standard centrality measures for all nodes in the graph.

    Calculates multiple centrality metrics that characterize node importance
    from different perspectives. Also identifies connected components.

    Args:
        G: NetworkX graph to analyze.
        verbose: If True, print progress messages to stdout.

    Returns:
        Dictionary with the following keys, each mapping entity_id to value:
            - 'degree': Raw number of connections
            - 'degree_centrality': Normalized degree (0-1 scale)
            - 'betweenness_centrality': Fraction of shortest paths through node
            - 'eigenvector_centrality': Importance based on neighbor importance
            - 'closeness_centrality': Inverse of average distance to all nodes
            - 'clustering_coefficient': Transitivity of node's neighborhood
            - 'pagerank': PageRank score
            - 'component_id': Connected component identifier
            - 'component_size': Size of node's connected component

    Note:
        Eigenvector centrality may return None values if the power iteration
        fails to converge (common in disconnected graphs).
    """
    results = {}
    
    if verbose:
        print("Computing centrality measures...")
    
    # Only compute on nodes with at least one connection
    connected_nodes = [n for n in G.nodes() if G.degree(n) > 0]
    H = G.subgraph(connected_nodes).copy()
    
    if verbose:
        print(f"  Working with {H.number_of_nodes()} connected nodes, {H.number_of_edges()} edges")
    
    # Degree centrality
    if verbose:
        print("  Computing degree centrality...")
    results['degree'] = {n: G.degree(n) for n in G.nodes()}
    results['degree_centrality'] = nx.degree_centrality(G)
    
    # Betweenness centrality
    if verbose:
        print("  Computing betweenness centrality...")
    results['betweenness_centrality'] = nx.betweenness_centrality(G)
    
    # Eigenvector centrality (only on connected subgraph)
    if verbose:
        print("  Computing eigenvector centrality...")
    try:
        if H.number_of_nodes() > 0:
            eigenvector = nx.eigenvector_centrality(H, max_iter=1000)
            # Fill in zeros for disconnected nodes
            results['eigenvector_centrality'] = {n: eigenvector.get(n, 0.0) for n in G.nodes()}
        else:
            results['eigenvector_centrality'] = {n: 0.0 for n in G.nodes()}
    except nx.PowerIterationFailedConvergence:
        if verbose:
            print("    Warning: eigenvector centrality did not converge, using None")
        results['eigenvector_centrality'] = {n: None for n in G.nodes()}
    
    # Closeness centrality
    if verbose:
        print("  Computing closeness centrality...")
    results['closeness_centrality'] = nx.closeness_centrality(G)
    
    # Clustering coefficient
    if verbose:
        print("  Computing clustering coefficients...")
    results['clustering_coefficient'] = nx.clustering(G)
    
    # PageRank
    if verbose:
        print("  Computing PageRank...")
    results['pagerank'] = nx.pagerank(G)
    
    # Connected components
    if verbose:
        print("  Finding connected components...")
    components = list(nx.connected_components(G))
    node_to_component = {}
    component_sizes = {}
    for i, comp in enumerate(components):
        component_sizes[i] = len(comp)
        for node in comp:
            node_to_component[node] = i
    
    results['component_id'] = node_to_component
    results['component_size'] = {n: component_sizes.get(node_to_component.get(n, 0), 0) 
                                  for n in G.nodes()}
    
    if verbose:
        print(f"  Found {len(components)} connected components")
    
    return results


def detect_communities(G: nx.Graph, verbose: bool = False) -> Dict[int, int]:
    """Detect community structure using the Louvain algorithm.

    The Louvain algorithm optimizes modularity to find densely connected
    groups of nodes. If Louvain is not available, falls back to using
    connected components as a simpler community definition.

    Args:
        G: NetworkX graph to analyze.
        verbose: If True, print progress messages to stdout.

    Returns:
        Dictionary mapping entity_id to community number (0-indexed).

    Note:
        Uses a fixed random seed (42) for reproducible results.
    """
    if verbose:
        print("Detecting communities with Louvain algorithm...")
    
    try:
        from networkx.algorithms.community import louvain_communities
        communities = louvain_communities(G, resolution=1.0, seed=42)
        
        node_to_community = {}
        for i, comm in enumerate(communities):
            for node in comm:
                node_to_community[node] = i
        
        if verbose:
            print(f"  Found {len(communities)} communities")
        
        return node_to_community
    except ImportError:
        if verbose:
            print("  Warning: Louvain not available, using connected components as communities")
        # Fall back to connected components
        components = list(nx.connected_components(G))
        node_to_community = {}
        for i, comp in enumerate(components):
            for node in comp:
                node_to_community[node] = i
        return node_to_community


def save_centrality(
    conn: Connection,
    centrality: Dict[str, Dict[int, float]],
    type_metrics: Dict[str, Dict[int, Any]] = None,
    verbose: bool = False
) -> None:
    """Save computed centrality measures to the database.

    Truncates the existing centrality table and inserts all computed
    metrics. Uses batch insertion for efficiency.

    Args:
        conn: Active psycopg database connection.
        centrality: Dictionary of centrality measure dictionaries from
            compute_centrality_measures().
        type_metrics: Optional dictionary of type-specific metrics from
            compute_type_specific_metrics().
        verbose: If True, print progress messages to stdout.
    """
    if verbose:
        print("Saving centrality measures to database...")
    
    # Clear existing data
    with conn.cursor() as cur:
        cur.execute("TRUNCATE entity_network_centrality")
    
    # Prepare batch data
    batch_data = []
    all_nodes = set(centrality['degree'].keys())
    
    for node in all_nodes:
        # Type-specific metrics (may be None if not computed)
        degree_same = type_metrics['degree_same_type'].get(node, 0) if type_metrics else 0
        degree_cross = type_metrics['degree_cross_type'].get(node, 0) if type_metrics else 0
        degree_norm = type_metrics['degree_centrality_normalized'].get(node, 0) if type_metrics else None
        person_degree = type_metrics['person_subgraph_degree'].get(node) if type_metrics else None
        person_between = type_metrics['person_subgraph_betweenness'].get(node) if type_metrics else None
        person_eigen = type_metrics['person_subgraph_eigenvector'].get(node) if type_metrics else None
        proj_degree = type_metrics['projection_degree'].get(node) if type_metrics else None
        
        batch_data.append((
            int(node),
            int(centrality['degree'].get(node, 0)),
            float(centrality['degree_centrality'].get(node, 0)),
            float(centrality['betweenness_centrality'].get(node, 0)),
            float(centrality['eigenvector_centrality'].get(node, 0)) 
                if centrality['eigenvector_centrality'].get(node) is not None else None,
            float(centrality['closeness_centrality'].get(node, 0)),
            float(centrality['clustering_coefficient'].get(node, 0)),
            float(centrality['pagerank'].get(node, 0)),
            int(degree_same),
            int(degree_cross),
            float(degree_norm) if degree_norm is not None else None,
            int(person_degree) if person_degree is not None else None,
            float(person_between) if person_between is not None else None,
            float(person_eigen) if person_eigen is not None else None,
            int(proj_degree) if proj_degree is not None else None,
            int(centrality['component_id'].get(node, 0)),
            int(centrality['component_size'].get(node, 0))
        ))
    
    # Insert in batches
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO entity_network_centrality 
               (entity_id, degree, degree_centrality, betweenness_centrality,
                eigenvector_centrality, closeness_centrality, clustering_coefficient,
                pagerank, degree_same_type, degree_cross_type, degree_centrality_normalized,
                person_subgraph_degree, person_subgraph_betweenness, person_subgraph_eigenvector,
                projection_degree, component_id, component_size)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (entity_id) DO UPDATE SET
                   degree = EXCLUDED.degree,
                   degree_centrality = EXCLUDED.degree_centrality,
                   betweenness_centrality = EXCLUDED.betweenness_centrality,
                   eigenvector_centrality = EXCLUDED.eigenvector_centrality,
                   closeness_centrality = EXCLUDED.closeness_centrality,
                   clustering_coefficient = EXCLUDED.clustering_coefficient,
                   pagerank = EXCLUDED.pagerank,
                   degree_same_type = EXCLUDED.degree_same_type,
                   degree_cross_type = EXCLUDED.degree_cross_type,
                   degree_centrality_normalized = EXCLUDED.degree_centrality_normalized,
                   person_subgraph_degree = EXCLUDED.person_subgraph_degree,
                   person_subgraph_betweenness = EXCLUDED.person_subgraph_betweenness,
                   person_subgraph_eigenvector = EXCLUDED.person_subgraph_eigenvector,
                   projection_degree = EXCLUDED.projection_degree,
                   component_id = EXCLUDED.component_id,
                   component_size = EXCLUDED.component_size""",
            batch_data
        )
    
    conn.commit()
    
    if verbose:
        print(f"  Saved centrality for {len(batch_data)} entities")


def save_communities(
    conn: Connection,
    communities: Dict[int, int],
    algorithm: str = 'louvain',
    verbose: bool = False
) -> None:
    """Save community assignments to the database.

    Clears existing community assignments for the specified algorithm
    and inserts the new assignments.

    Args:
        conn: Active psycopg database connection.
        communities: Dictionary mapping entity_id to community number.
        algorithm: Name of the community detection algorithm used.
            Defaults to 'louvain'.
        verbose: If True, print progress messages to stdout.
    """
    if verbose:
        print(f"Saving community assignments ({algorithm})...")
    
    # Clear existing data for this algorithm
    with conn.cursor() as cur:
        cur.execute("DELETE FROM entity_network_communities WHERE algorithm = %s", (algorithm,))
    
    # Insert
    batch_data = [(int(entity_id), int(community), algorithm) 
                  for entity_id, community in communities.items()]
    
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO entity_network_communities (entity_id, community, algorithm)
               VALUES (%s, %s, %s)
               ON CONFLICT (entity_id, algorithm) DO UPDATE SET
                   community = EXCLUDED.community""",
            batch_data
        )
    
    conn.commit()
    
    if verbose:
        print(f"  Saved {len(batch_data)} community assignments")


def print_top_entities(
    centrality: Dict[str, Dict[int, float]],
    entity_names: Dict[int, str],
    verbose: bool = False
) -> None:
    """Print top-ranked entities for each centrality measure.

    Displays leaderboards showing which entities rank highest by
    different centrality metrics.

    Args:
        centrality: Dictionary of centrality measure dictionaries.
        entity_names: Mapping from entity_id to entity name for display.
        verbose: If False, function returns immediately without output.
    """
    if not verbose:
        return
    
    print("\n" + "=" * 60)
    print("TOP ENTITIES BY CENTRALITY MEASURE")
    print("=" * 60)
    
    # Top by degree
    print("\nTop 10 by Degree (number of connections):")
    top_degree = sorted(centrality['degree'].items(), key=lambda x: -x[1])[:10]
    for entity_id, score in top_degree:
        print(f"  {entity_names.get(entity_id, entity_id)}: {score}")
    
    # Top by betweenness
    print("\nTop 10 by Betweenness Centrality (bridge between groups):")
    top_between = sorted(centrality['betweenness_centrality'].items(), key=lambda x: -x[1])[:10]
    for entity_id, score in top_between:
        print(f"  {entity_names.get(entity_id, entity_id)}: {score:.4f}")
    
    # Top by PageRank
    print("\nTop 10 by PageRank (influence based on connections):")
    top_pagerank = sorted(centrality['pagerank'].items(), key=lambda x: -x[1])[:10]
    for entity_id, score in top_pagerank:
        print(f"  {entity_names.get(entity_id, entity_id)}: {score:.4f}")
    
    # Top by eigenvector (if computed)
    eigen = centrality.get('eigenvector_centrality', {})
    valid_eigen = [(k, v) for k, v in eigen.items() if v is not None and v > 0]
    if valid_eigen:
        print("\nTop 10 by Eigenvector Centrality (connected to important nodes):")
        top_eigen = sorted(valid_eigen, key=lambda x: -x[1])[:10]
        for entity_id, score in top_eigen:
            print(f"  {entity_names.get(entity_id, entity_id)}: {score:.4f}")


def print_type_specific_summary(
    type_metrics: Dict[str, Dict[int, Any]],
    entity_names: Dict[int, str],
    G: nx.Graph,
    verbose: bool = False
) -> None:
    """Print summary of type-specific network metrics.

    Displays leaderboards for metrics computed on type-specific subgraphs,
    including person-only networks and bipartite projections.

    Args:
        type_metrics: Dictionary of type-specific metric dictionaries.
        entity_names: Mapping from entity_id to entity name for display.
        G: Original NetworkX graph (used to identify node types).
        verbose: If False, function returns immediately without output.
    """
    if not verbose:
        return
    
    print("\n" + "="*60)
    print("TYPE-SPECIFIC METRICS")
    print("="*60)
    
    # Person subgraph top entities
    person_between = type_metrics['person_subgraph_betweenness']
    valid = [(k, v) for k, v in person_between.items() if v is not None and v > 0]
    if valid:
        print("\nTop 10 Persons by Betweenness (Person-Person Network Only):")
        top = sorted(valid, key=lambda x: -x[1])[:10]
        for entity_id, score in top:
            print(f"  {entity_names.get(entity_id, entity_id)}: {score:.4f}")
    
    # Projection degree (persons connected through shared companies)
    proj_degree = type_metrics['projection_degree']
    valid = [(k, v) for k, v in proj_degree.items() if v is not None and v > 0]
    if valid:
        print("\nTop 10 Persons by Connections Through Shared Companies:")
        top = sorted(valid, key=lambda x: -x[1])[:10]
        for entity_id, score in top:
            print(f"  {entity_names.get(entity_id, entity_id)}: {score}")
    
    # Most connected companies (by cross-type degree)
    company_nodes = [n for n in G.nodes() if G.nodes[n].get('type') == 'company']
    cross_type = type_metrics['degree_cross_type']
    company_degrees = [(n, cross_type.get(n, 0)) for n in company_nodes]
    company_degrees = sorted(company_degrees, key=lambda x: -x[1])[:10]
    
    print("\nTop 10 Companies by Person Connections:")
    for entity_id, degree in company_degrees:
        print(f"  {entity_names.get(entity_id, entity_id)}: {degree}")


def main() -> None:
    """Main entry point for the entity network statistics computation.

    Parses command-line arguments, connects to the database, builds the
    entity network graph, computes all centrality measures and community
    assignments, and saves results to the database.

    Command-Line Arguments:
        --dsn: PostgreSQL connection string. Defaults to local connection.
        --verbose, -v: Enable verbose output with progress messages.

    Exit Codes:
        0: Success
        1: No entities found in database
    """
    parser = argparse.ArgumentParser(description='Compute entity network statistics')
    parser.add_argument('--dsn', help='Database connection string (default: DATABASE_URL env var)', 
                        default=None)
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()
    
    # Get database connection
    with get_db_connection(args.dsn) as conn:
        # Create tables for storing computed metrics
        create_tables(conn, verbose=args.verbose)
        
        # Build NetworkX graph from database relationships
        G, entity_names = build_entity_graph(conn, verbose=args.verbose)
        
        if G.number_of_nodes() == 0:
            print("No entities found in database")
            sys.exit(1)
        
        # Compute standard centrality measures (full network)
        centrality = compute_centrality_measures(G, verbose=args.verbose)
        
        # Compute type-specific metrics (mixed-mode network analysis)
        type_metrics = compute_type_specific_metrics(G, verbose=args.verbose)
        
        # Detect community structure using Louvain algorithm
        communities = detect_communities(G, verbose=args.verbose)
        
        # Save all computed metrics to database
        save_centrality(conn, centrality, type_metrics=type_metrics, verbose=args.verbose)
        save_communities(conn, communities, verbose=args.verbose)
        
        # Print summary leaderboards
        print_top_entities(centrality, entity_names, verbose=args.verbose)
        print_type_specific_summary(type_metrics, entity_names, G, verbose=args.verbose)
        
        if args.verbose:
            print("\n✓ Entity network statistics computed successfully")


if __name__ == '__main__':
    main()
