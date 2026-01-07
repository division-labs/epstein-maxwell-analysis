# Epstein-Maxwell Files Analysis Suite

A comprehensive document analysis platform for investigating the Epstein-Maxwell legal case files. The project processes ~14,680 OCR-extracted documents from 8 volumes of legal discovery materials, providing entity extraction, relationship mapping, document similarity analysis, and interactive network visualizations.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Scripts Reference](#scripts-reference)
- [Network Visualization Server](#network-visualization-server)
- [API Reference](#api-reference)
- [Database Setup](#database-setup)
- [Documentation](#documentation)

---

## Quick Start

### 1. Install Dependencies

```bash
python3 -m pip install -r requirements.txt

# Download spaCy language model
python3 -m spacy download en_core_web_md
```

### 2. Configure Database Connection

```bash
# Copy the example environment file
cp scripts/.env.example scripts/.env

# Edit scripts/.env with your PostgreSQL credentials
# DATABASE_URL=postgresql://user:password@localhost/postgres
```

### 3. Extract Text from PDFs

```bash
python3 scripts/extract_pdfs.py "." \
    --ext _extracted.txt --verbose
```

### 4. Catalog Files and Extract Entities

```bash
python3 scripts/catalog_to_postgres.py "." \
    --extract --ext _extracted.txt --verbose
```

### 5. Start the Visualization Server

```bash
cd scripts/network-viz
npm install
npm start
# Open http://localhost:3000
```

---

## Project Structure

```
Epstein-Maxwell Files/
├── scripts/                    # Python analysis scripts
│   ├── config.py              # Shared configuration
│   ├── db_utils.py            # Database utilities
│   ├── extract_pdfs.py        # PDF text extraction
│   ├── catalog_to_postgres.py # File cataloging + NER
│   ├── load_extracted_text.py # Load text content to DB
│   ├── pdf_metadata_to_postgres.py # PDF metadata extraction
│   ├── disambiguate_entities.py    # Entity canonicalization
│   ├── build_entity_network.py     # Relationship graph builder
│   ├── load_sourced_entity_network.py  # Load sourced entity data
│   ├── entity_network_sources.py   # Source citation management
│   ├── compute_entity_network_stats.py # Network centrality metrics
│   ├── build_document_similarity_network.py # TF-IDF document similarity
│   ├── analyze_spelling.py         # OCR/spelling analysis
│   ├── build_noun_tdm_postgres.py  # Noun term-document matrix
│   ├── build_verb_tdm_postgres.py  # Verb term-document matrix
│   ├── create_views.py             # Analytical database views
│   ├── reset_tables.py             # Table management utility
│   └── network-viz/           # Interactive visualization server
│       ├── server.js          # Express.js API server
│       ├── package.json       # Node.js dependencies
│       └── public/
│           └── index.html     # D3.js visualization frontend
├── VOL00001-VOL00008/         # Source document volumes
│   ├── DATA/                  # Index files (.OPT, .DAT)
│   └── IMAGES/                # PDFs and extracted text
├── DATABASE_DOCUMENTATION.md  # Database schema and usage
├── API_README.md              # This file
├── ADVANCEMENT_PLAN.md        # Future enhancements
├── CODE_IMPROVEMENTS.md       # Development notes
├── DATA_QUALITY_CORRECTIONS.md # Entity correction rules
└── requirements.txt           # Python dependencies
```

---

## Scripts Reference

### Core Pipeline

#### extract_pdfs.py

Extract text from PDF files using pypdf.

```bash
python3 scripts/extract_pdfs.py <root> [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `root` | positional | `.` | Root folder to crawl for PDFs |
| `--ext` | string | `_extracted.txt` | Output filename suffix |
| `--force` | flag | - | Overwrite existing output files |
| `--dry-run` | flag | - | Show what would be done without writing |
| `-v, --verbose` | flag | - | Verbose output |

---

#### catalog_to_postgres.py

Catalog files into PostgreSQL and optionally extract entities (names, dates, locations) using spaCy NER.

```bash
python3 scripts/catalog_to_postgres.py <root> [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `root` | positional | `.` | Root folder to crawl |
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--create-db` | flag | - | Create the database if it doesn't exist |
| `--extract` | flag | - | Extract entities (names, dates, locations) from text |
| `--ext` | string | `_extracted.txt` | Suffix for extracted text files |
| `-v, --verbose` | flag | - | Verbose output |

---

#### load_extracted_text.py

Load full extracted text content into the database for full-text search.

```bash
python3 scripts/load_extracted_text.py <root> [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `root` | positional | required | Root directory containing extracted text files |
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--ext` | string | `_extracted.txt` | File extension for extracted text files |
| `--batch-size` | int | `100` | Number of files to process before committing |
| `-v, --verbose` | flag | - | Verbose output |

---

#### pdf_metadata_to_postgres.py

Extract PDF document metadata (author, title, creation date, etc.) into PostgreSQL.

```bash
python3 scripts/pdf_metadata_to_postgres.py <root> [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `root` | positional | required | Root directory to scan for PDFs |
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `-v, --verbose` | flag | - | Verbose output |

---

### Analysis Tools

#### disambiguate_entities.py

Entity disambiguation and resolution system. Identifies and merges name variants and aliases to canonical entities.

```bash
python3 scripts/disambiguate_entities.py [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--analyze` | flag | - | Analyze names and find potential aliases |
| `--review` | flag | - | Show disambiguation review queue |
| `--stats` | flag | - | Show disambiguation statistics |
| `--merge` | flag | - | Auto-merge high-confidence matches |
| `--create-function` | flag | - | Create PostgreSQL `get_canonical_name()` function |
| `--update-views` | flag | - | Update views to use canonical names |
| `--verify` | flag | - | Verify integrity between code, database, and documentation |
| `--clear` | flag | - | Clear disambiguation queue and auto-generated aliases (requires `--confirm`) |
| `--dry-run` | flag | - | Show what would be done without making changes |
| `--confirm` | flag | - | Required for destructive operations (`--clear`) |
| `--limit` | int | - | Limit for review queue display |
| `-v, --verbose` | flag | - | Verbose output |

**Typical workflow:**
```bash
python3 scripts/disambiguate_entities.py --analyze --merge --create-function --update-views
```

---

#### build_entity_network.py

Build entity relationship network from extracted names and known business relationships.

```bash
python3 scripts/build_entity_network.py [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--seed` | string | - | Comma-separated list of seed names (e.g., `'Kushner,Leon Black'`) |
| `--from-database` | flag | - | Use extracted names from database as seeds |
| `--min-mentions` | int | `10` | Minimum mentions required for database seeds |
| `--link-mentions` | flag | - | Link entities to document mentions |
| `--clear` | flag | - | Clear existing entity network data (requires `--confirm`) |
| `--dry-run` | flag | - | Show what would be done without making changes |
| `--confirm` | flag | - | Required for `--clear` operation |
| `-v, --verbose` | flag | - | Verbose output |

---

#### load_sourced_entity_network.py

Load curated entity relationships with Chicago-style citations from `entity_network_sources.py`.

```bash
python3 scripts/load_sourced_entity_network.py [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--clear` | flag | - | Clear sourced data before loading (preserves entities) |
| `--report` | flag | - | Print citation report after loading |
| `-v, --verbose` | flag | - | Verbose output |

---

#### compute_entity_network_stats.py

Compute network centrality metrics (degree, betweenness, eigenvector, PageRank) and community detection.

```bash
python3 scripts/compute_entity_network_stats.py [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `-v, --verbose` | flag | - | Verbose output |

---

#### build_document_similarity_network.py

Build TF-IDF document similarity network and compute persistent homology for threshold optimization.

```bash
python3 scripts/build_document_similarity_network.py [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--tdm-type` | choice | `noun` | TDM to use: `noun`, `verb`, or `both` |
| `--max-docs` | int | all | Maximum number of documents to process |
| `--min-terms` | int | `5` | Minimum terms per document to include |
| `--min-similarity` | float | `0.1` | Minimum similarity to store (filters noise) |
| `--max-dim` | int | `1` | Maximum homology dimension to compute |
| `--n-thresholds` | int | `100` | Number of threshold values for Betti computation |
| `--skip-pairs` | flag | - | Skip saving individual similarity pairs (saves space) |
| `--native-only` | flag | - | Process only native documents |
| `--auto-threshold` | flag | - | Automatically select optimal threshold |
| `--threshold-method` | choice | - | Method: `auto`, `modularity`, `persistence`, `knee`, `silhouette` |
| `--no-plots` | flag | - | Skip generating visualization plots |
| `--clear` | flag | - | Clear existing data (requires `--confirm`) |
| `--dry-run` | flag | - | Show what would be done |
| `--confirm` | flag | - | Required for `--clear` operation |
| `-v, --verbose` | flag | - | Verbose output |
| `--skip-labels` | flag | - | Skip community label generation |
| `--skip-bridges` | flag | - | Skip bridge document identification |
| `--bridge-top-n` | int | - | Number of top bridge documents to identify |
| `--multi-threshold` | flag | - | Compute metrics at multiple thresholds |
| `--threshold-start` | float | - | Start of threshold range |
| `--threshold-end` | float | - | End of threshold range |
| `--threshold-step` | float | - | Step size for threshold range |
| `--export-format` | choice | - | Export format: `gexf`, `graphml`, `edgelist` |
| `--export-file` | string | - | Output file for network export |

---

#### analyze_spelling.py

Analyze extracted text for spelling issues, OCR errors, and foreign language content (29 languages supported).

```bash
python3 scripts/analyze_spelling.py <root> [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `root` | positional | required | Root directory to scan for text files |
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--ext` | string | `_extracted.txt` | File extension to match |
| `--log` | string | `spelling_analysis.log` | Output log file path |
| `-v, --verbose` | flag | - | Verbose output |

---

#### build_noun_tdm_postgres.py

Build noun term-document matrix using spaCy/NLTK POS tagging.

```bash
python3 scripts/build_noun_tdm_postgres.py <root> [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `root` | positional | required | Root directory to scan for text files |
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--ext` | string | `_extracted.txt` | File extension to match |
| `--method` | choice | `auto` | Extraction method: `auto`, `spacy`, `nltk`, `simple` |
| `--min-df` | int | `2` | Minimum document frequency for terms |
| `--max-df` | float | `0.8` | Maximum document frequency ratio |
| `--clear` | flag | - | Clear existing TDM data (requires `--confirm`) |
| `--dry-run` | flag | - | Show what would be done |
| `--confirm` | flag | - | Required for `--clear` operation |
| `-v, --verbose` | flag | - | Verbose output |

---

#### build_verb_tdm_postgres.py

Build verb term-document matrix using spaCy/NLTK POS tagging.

```bash
python3 scripts/build_verb_tdm_postgres.py <root> [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `root` | positional | required | Root directory to scan for text files |
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--ext` | string | `_extracted.txt` | File extension to match |
| `--method` | choice | `auto` | Extraction method: `auto`, `spacy`, `nltk`, `simple` |
| `--min-df` | int | `2` | Minimum document frequency for terms |
| `--max-df` | float | `0.8` | Maximum document frequency ratio |
| `--clear` | flag | - | Clear existing TDM data (requires `--confirm`) |
| `--dry-run` | flag | - | Show what would be done |
| `--confirm` | flag | - | Required for `--clear` operation |
| `-v, --verbose` | flag | - | Verbose output |

---

### Utilities

#### create_views.py

Create analytical database views for document analysis.

```bash
python3 scripts/create_views.py [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--list` | flag | - | List available view definitions and exit |
| `-v, --verbose` | flag | - | Verbose output |

---

#### reset_tables.py

Unified table reset utility. Supports truncating or dropping tables by feature group.

```bash
python3 scripts/reset_tables.py [options]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--dsn` | string | from `.env` | PostgreSQL connection string |
| `--tables` | list | - | Specific table names to reset |
| `--feature` | choice | - | Feature group: `spelling`, `entity_disambiguation`, `entity_network`, `catalog`, `text_content`, `tdm_nouns`, `tdm_verbs`, `pdf_metadata`, `all` |
| `--drop` | flag | - | Drop tables completely (requires `--confirm`) |
| `--no-preserve-manual` | flag | - | Do not preserve manual entries (e.g., manual entity aliases) |
| `--confirm` | flag | - | Required for destructive operations |
| `--dry-run` | flag | - | Show what would be reset without making changes |
| `--list-features` | flag | - | List available features and their tables |

**Examples:**
```bash
# List available features
python3 scripts/reset_tables.py --list-features

# Dry run to preview changes
python3 scripts/reset_tables.py --feature spelling --dry-run

# Truncate specific tables
python3 scripts/reset_tables.py --tables spelling_issues entity_aliases

# Drop and recreate tables
python3 scripts/reset_tables.py --feature entity_disambiguation --drop --confirm
```

---

#### export_static_data.py

Export visualization data to static JSON files for GitHub Pages deployment.

```bash
python3 scripts/export_static_data.py
```

This script exports:
- Threshold data with Betti numbers
- Network data at multiple similarity thresholds
- Temporal period definitions
- Document details and entity overlays
- Entity network with relationships

Output is written to `static-viz/data/`.

---

#### verify_database.py

Verify database structure and row counts against expected schema.

```bash
python3 scripts/verify_database.py
```

This script checks:
- Database connection
- Presence of all expected tables
- Row counts for each table
- Presence of all expected views

---

### Library Modules

These modules are imported by other scripts and are not run directly.

#### config.py

Shared configuration module providing environment-based settings.

**Key exports:**
- `get_dsn()` - Returns PostgreSQL DSN from `DATABASE_URL` environment variable or `.env` file
- `WORKSPACE_ROOT` - Absolute path to the workspace root directory

---

#### db_utils.py

Database connection and table management utilities.

**Key exports:**
- `get_connection(dsn)` - Get a PostgreSQL connection
- `ensure_tables(conn)` - Create all required tables if they don't exist
- `table_exists(conn, table_name)` - Check if a table exists

---

#### entity_network_sources.py

Curated entity network data module with Chicago-style citations. Contains sourced entities and relationships loaded by `load_sourced_entity_network.py`.

**Key exports:**
- `SOURCED_ENTITIES` - List of `SourcedEntity` instances (persons and companies)
- `SOURCED_RELATIONSHIPS` - List of `SourcedRelationship` instances with citations
- `get_all_sources()` - Returns all unique documentary sources
- `validate_data()` - Validates data integrity

**Source types:**
- `court_document` - Court filings, depositions, exhibits
- `newspaper` - News articles from major publications
- `book` - Published books
- `government_record` - Official government documents, SEC filings
- `documentary` - Documentaries with named sources
- `efta_document` - Documents from the EFTA corpus
- `deposition` - Sworn testimony from legal proceedings
- `flight_log` - Aircraft flight records

---

## Network Visualization Server (Excluded)

The project includes an interactive web-based visualization server built with Express.js and D3.js. 

(Note: At this time, this portion of the codebase is excluded from the public repository. However, the visualization code exists in a static form. See: https://github.com/division-labs/epstein-maxwell-netviz.)

### Setup

```bash
cd scripts/network-viz
npm install
npm start
```

Server runs at `http://localhost:3000`

### Features

#### Document Similarity Network

- **Force-directed graph** of documents connected by TF-IDF cosine similarity
- **Persistent homology analysis** to find optimal similarity threshold
- **Community detection** using Louvain algorithm with labeled clusters
- **Interactive controls:**
  - Similarity threshold slider with Betti curve visualization
  - Node sizing by degree, betweenness, eigenvector centrality, or community size
  - Temporal filtering by date periods
  - Click-to-focus → entity overlay → reset interaction flow

#### Entity Network View

- **Bipartite force-directed layout** separating persons (green) from companies (amber)
- **Soft bipartite separation** with force-directed positioning within each group
- **Relationship edge labels** showing connection types (victim_of, attorney_for, founder, etc.)
- **Relationship priority system** displaying most specific relationship when multiple exist
- **Click-to-pin tooltips** with detailed entity information:
  - Entity type and description
  - Connection count
  - Expandable source citations with Chicago-style formatting
  - Scrollable tooltip with modern scrollbar styling
- **Simulation control** - pauses on node click, resumes on background click

### Visualization Design

- **Typography:** DM Sans for UI, JetBrains Mono for network labels
- **Color scheme:** Dark theme (#0a0a0f background)
  - Persons: Green (#22c55e)
  - Companies: Amber (#f59e0b)
  - UI accents: Purple (#a855f7)
- **Responsive layout:** 300px sidebar with main visualization area

---

## API Reference

The visualization server exposes RESTful API endpoints for data access.

### Document Similarity Endpoints

#### `GET /api/network`

Returns the document similarity network at a given threshold.

**Query Parameters:**

| Parameter     | Type   | Default   | Description                         |
| ------------- | ------ | --------- | ----------------------------------- |
| `threshold` | float  | 0.35      | Minimum cosine similarity for edges |
| `algorithm` | string | "louvain" | Community detection algorithm       |

**Response:**

```json
{
  "nodes": [
    {
      "id": 0,
      "file_path": "/path/to/document.txt",
      "doc_id": "EFTA00000001",
      "community": 1,
      "community_size": 42,
      "degree": 0.15,
      "betweenness": 0.003,
      "eigenvector": 0.12,
      "clustering": 0.45
    }
  ],
  "edges": [
    { "source": 0, "target": 1, "similarity": 0.78 }
  ],
  "communityLabels": [
    {
      "community": 1,
      "label": "Legal Correspondence",
      "top_entities": ["Jeffrey Epstein", "Ghislaine Maxwell"],
      "top_nouns": ["deposition", "testimony", "court"],
      "document_count": 42,
      "date_range_start": "1995-01-15",
      "date_range_end": "2019-08-10"
    }
  ],
  "bridges": [
    {
      "doc_id": "EFTA00030021",
      "betweenness_centrality": 0.15,
      "communities_bridged": [1, 3, 7],
      "bridge_type": "multi_community"
    }
  ]
}
```

#### `GET /api/thresholds`

Returns precomputed statistics for all threshold values including persistent homology.

**Response:**

```json
{
  "thresholds": [
    {
      "similarity_threshold": 0.30,
      "node_count": 2847,
      "edge_count": 15234,
      "component_count": 12,
      "betti_0": 12,
      "betti_1": 5,
      "modularity": 0.72
    }
  ],
  "optimal": 0.35,
  "reason": "Maximum modularity with stable H₀/H₁ features"
}
```

#### `GET /api/document/:docId`

Returns detailed information about a specific document.

**Response:**

```json
{
  "doc_id": "EFTA00000001",
  "file_path": "/path/to/document.txt",
  "text_preview": "First 500 characters...",
  "entities": {
    "names": ["Jeffrey Epstein", "Ghislaine Maxwell"],
    "locations": ["New York", "Palm Beach"],
    "dates": ["2005-03-15", "2008-06-24"]
  },
  "neighbors": [
    { "doc_id": "EFTA00000002", "similarity": 0.85 }
  ]
}
```

#### `GET /api/temporal-periods`

Returns available temporal periods for filtering.

**Response:**

```json
{
  "periods": [
    {
      "period_id": 1,
      "label": "1990-1995",
      "start_date": "1990-01-01",
      "end_date": "1995-12-31",
      "document_count": 234
    }
  ]
}
```

### Entity Network Endpoints

#### `GET /api/entity-network`

Returns the complete entity relationship network with sourced citations.

**Response:**

```json
{
  "nodes": [
    {
      "id": 0,
      "entity_id": 1,
      "name": "Jeffrey Epstein",
      "type": "person",
      "description": "American financier and convicted sex offender",
      "description_sources": [
        { "citation": "Smith, J. (2019). Title. Publisher.", "url": "https://..." }
      ],
      "degree": 45,
      "degree_centrality": 0.32,
      "betweenness": 0.15,
      "eigenvector": 0.89,
      "pagerank": 0.12,
      "community": 1,
      "person_degree": 28,
      "person_betweenness": 0.22,
      "person_eigenvector": 0.95
    },
    {
      "id": 1,
      "entity_id": 2,
      "name": "J. Epstein & Company",
      "type": "company",
      "description": "Financial management firm",
      "company_degree": 15
    }
  ],
  "edges": [
    {
      "source": 0,
      "target": 1,
      "relationship_type": "founder",
      "all_relationships": ["founder", "ceo", "associated_with"],
      "confidence": 0.95,
      "sources": [
        {
          "citation": "Jones, A. (2020). Article Title. Publication.",
          "url": "https://...",
          "page_reference": "p. 45",
          "quote": "Epstein founded the firm in 1982..."
        }
      ],
      "bidirectional": false
    }
  ],
  "stats": {
    "entityCount": 142,
    "relationshipCount": 185,
    "sourceCount": 89,
    "communityCount": 8
  }
}
```

**Relationship Priority System:**

When multiple relationships exist between the same entity pair, the most specific relationship is displayed. Priority order (lower = higher priority):

| Priority | Relationship Type                                             |
| -------- | ------------------------------------------------------------- |
| 1        | victim_of                                                     |
| 2        | accuser_of                                                    |
| 3        | attorney_for                                                  |
| 4-8      | founder, co_founder, ceo, chairman, board_chairman            |
| 9-12     | executive, executive_vp, power_of_attorney, financial_advisor |
| 13-16    | spouse, former_spouse, parent_of, child_of                    |
| 90       | associate                                                     |
| 100      | associated_with                                               |

#### `GET /api/entity-overlay/:docId`

Returns entity data for overlaying on a focused document node.

**Response:**

```json
{
  "doc_id": "EFTA00000001",
  "entities": [
    {
      "entity_id": 1,
      "name": "Jeffrey Epstein",
      "type": "person",
      "mention_count": 15,
      "relationships": [
        { "target": "Ghislaine Maxwell", "type": "associate" }
      ]
    }
  ]
}
```

---

## Database Setup

### Prerequisites

- PostgreSQL 14+
- Python 3.9+

### Connection

Create a `.env` file in the `scripts/` directory with your database credentials:

```bash
# Copy the example file
cp scripts/.env.example scripts/.env

# Edit with your credentials
# DATABASE_URL=postgresql://user:password@localhost/postgres
```

The connection string is automatically loaded by all scripts via `config.py`.

### Initial Setup

```bash
# 1. Extract text from PDFs
python3 scripts/extract_pdfs.py . --ext _extracted.txt

# 2. Catalog files and extract entities
python3 scripts/catalog_to_postgres.py . --extract --ext _extracted.txt

# 3. Create analytical views
python3 scripts/create_views.py

# 4. Disambiguate entity names
python3 scripts/disambiguate_entities.py --analyze --merge --create-function --update-views
```

### Key Tables

| Table                                 | Description                                               |
| ------------------------------------- | --------------------------------------------------------- |
| `file_catalog`                      | File metadata (path, type, size, page count)              |
| `extracted_text_content`            | Full extracted text for search and analysis               |
| `extracted_names`                   | Person entities per document                              |
| `extracted_locations`               | Location entities per document                            |
| `extracted_dates`                   | Date entities per document                                |
| `entity_aliases`                    | Name variant → canonical mappings                        |
| `entity_exclusions`                 | Entities to exclude from analysis                         |
| `spelling_issues`                   | OCR/spelling error analysis                               |
| `entity_network_entities`           | Curated entity nodes (persons, companies)                 |
| `entity_network_relationships`      | Sourced relationship edges with citations                 |
| `entity_network_sources`            | Bibliography of source citations                          |
| `entity_network_centrality`         | Precomputed centrality metrics                            |
| `entity_network_communities`        | Community detection results                               |
| `document_similarity_pairs`         | TF-IDF cosine similarity scores                           |
| `document_similarity_communities`   | Document clustering results                               |
| `document_similarity_centrality`    | Document network centrality metrics                       |
| `document_similarity_persistence`   | Persistent homology features                              |
| `document_similarity_betti_numbers` | Topological invariants by threshold                       |
| `noun_tdm_*`                        | Noun term-document matrix (vocabulary, documents, counts) |
| `verb_tdm_*`                        | Verb term-document matrix (vocabulary, documents, counts) |

See [DATABASE_DOCUMENTATION.md](DATABASE_DOCUMENTATION.md) for complete schema reference.

---

## Documentation

- **[DATABASE_DOCUMENTATION.md](DATABASE_DOCUMENTATION.md)** - Complete database schema, utilities, and maintenance
- **[DATA_QUALITY_CORRECTIONS.md](DATA_QUALITY_CORRECTIONS.md)** - Entity correction rules and filters

---

## Key Statistics

- **~29,921 total files** across 8 volumes
- **~14,680 extracted text documents**
- **98,302 name mentions** → **19,797 unique entities**
- **142 curated entities** (80 persons, 62 companies)
- **185 sourced relationships** with citation provenance
- **89 bibliographic sources** in Chicago citation format
- **282 name variants** unified into **53 canonical entities**

---

*Last Updated: January 2026*
