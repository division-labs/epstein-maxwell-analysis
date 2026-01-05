# Epstein-Maxwell Files - Database Documentation

This document provides comprehensive documentation for the PostgreSQL database infrastructure supporting the Epstein-Maxwell Files analysis project. It serves as both a technical reference for developers and a conceptual guide for understanding how the various database components work together to enable document analysis.

---

## Table of Contents

1. [Database Overview](#1-database-overview)
2. [Schema Reference](#2-schema-reference)
3. [Database Utilities](#3-database-utilities)
4. [Table Management](#4-table-management)
5. [Entity Canonicalization](#5-entity-canonicalization)
6. [Term-Document Matrices](#6-term-document-matrices)
7. [Performance Optimization](#7-performance-optimization)
8. [Maintenance & Troubleshooting](#8-maintenance--troubleshooting)

---

## 1. Database Overview

### 1.1 Purpose and Scope

This project analyzes a large corpus of legal documents released in connection with the Epstein-Maxwell case. The documents consist primarily of scanned PDFs that have been processed through OCR (Optical Character Recognition) to extract text. The database serves as the central repository for:

- **Document cataloging:** Tracking all files across eight volumes of legal discovery data
- **Text storage:** Preserving extracted text for full-text search and analysis
- **Named entity recognition (NER):** Storing people, places, and dates extracted from documents
- **Entity resolution:** Mapping name variants to canonical forms for accurate relationship analysis
- **Text quality analysis:** Identifying OCR errors, foreign language content, and spelling issues
- **Linguistic analysis:** Building term-document matrices for noun and verb frequency analysis

### 1.2 Why PostgreSQL?

PostgreSQL was chosen over alternatives like SQLite or flat files for several important reasons:

1. **Full-text search:** PostgreSQL's GIN indexes enable fast searching across millions of words
2. **Concurrent access:** Multiple scripts can read and write simultaneously without corruption
3. **Complex queries:** SQL window functions, CTEs, and aggregations simplify analysis
4. **Scalability:** Handles 30K+ documents and millions of entity mentions efficiently
5. **Data integrity:** Foreign key constraints and transactions ensure consistency

### 1.3 Connection Details

**Connection String:** Stored in `scripts/.env` file as `DATABASE_URL`

```bash
# Example .env file (create from .env.example)
DATABASE_URL=postgresql://user:password@localhost/postgres
```

The connection string is loaded automatically by `scripts/config.py` and made available to all scripts via `DEFAULT_DSN`. The `.env` file is excluded from version control via `.gitignore` to protect credentials.

### 1.4 Corpus Statistics

| Metric | Count |
|--------|-------|
| Total files | 30,560 |
| Extracted text documents | 14,680 |
| Person name mentions | 98,302 |
| Location mentions | 92,029 |
| Date mentions | 134,078 |
| Unique names | 19,797 |
| Unique locations | 4,423 |
| Unique dates | 39,524 |
| Entity aliases | 128 |
| Volumes | 8 (VOL00001-VOL00008) |

---

## 2. Schema Reference

This section documents all database tables, their relationships, and their purposes within the analysis pipeline. Tables are organized by functional area.

### 2.1 Core Data Tables

These tables form the foundation of the document repository. Every document in the corpus is tracked here, along with its extracted text content and PDF-specific metadata.

#### file_catalog (Primary file registry)

The **file_catalog** table is the master registry of all files in the corpus. It serves as the central reference point for all other tables via foreign key relationships. Every file—whether it's a PDF, image, native document, or extracted text file—gets an entry here.

- **Purpose:** Central catalog linking all documents; parent table for extracted content
- **Primary Key:** `path` (full filesystem path ensures uniqueness)
- **Columns:**
  - `path` — Absolute filesystem path (e.g., `/Users/.../VOL00001/IMAGES/0001/EFTA00000001.pdf`)
  - `file_name` — Just the filename without path (e.g., `EFTA00000001.pdf`)
  - `file_type` — File extension (e.g., `pdf`, `tif`, `txt`)
  - `size_bytes` — File size for storage analysis
  - `page_count` — Number of pages (PDFs only)
  - `mtime`, `ctime` — File modification and creation timestamps
  - `extracted_text_path` — Path to the corresponding `_extracted.txt` file (if any)
- **Row Count:** ~29,921 files (14,680 have extracted text)
- **Key Relationships:** Referenced by `extracted_text_content`, `extracted_names`, `extracted_locations`, `extracted_dates`

#### extracted_text_content (Full text storage)

The **extracted_text_content** table stores the actual text extracted from documents via OCR or direct text extraction. This is where full-text search queries operate. Text is stored as-is from the extraction process, including any OCR errors.

- **Purpose:** Stores raw text for full-text search and linguistic analysis
- **Primary Key:** `file_path`
- **Foreign Key:** `file_path` → `file_catalog(path)` ON DELETE CASCADE
- **Columns:**
  - `file_path` — Links to file_catalog
  - `raw_text` — The full extracted text content
  - `text_length` — Character count (useful for filtering by document size)
  - `word_count` — Tokenized word count
  - `last_updated` — Timestamp of last extraction
- **Indexes:** 
  - GIN index on `raw_text` for full-text search (`tsvector`)
  - B-tree on `file_path` for joins
  - B-tree on `text_length` for filtering

#### pdf_metadata (PDF-specific metadata)

The **pdf_metadata** table stores metadata extracted from PDF document properties. Many scanned documents have limited metadata, but some contain valuable information like creation dates, author names, and production tools used.

- **Purpose:** Stores PDF document properties for provenance tracking
- **Primary Key:** `path`
- **Columns:**
  - `path`, `file_name`, `size_bytes`, `page_count` — Basic file info
  - `title`, `author`, `subject`, `keywords` — Document metadata fields
  - `creator`, `producer` — Software used to create/convert the PDF
  - `creation_date`, `modification_date` — PDF internal timestamps
  - `metadata_json` — Raw metadata as JSON for any non-standard fields
  - `mtime`, `ctime` — Filesystem timestamps

### 2.2 Entity Extraction Tables

Named Entity Recognition (NER) identifies people, places, and dates mentioned in documents. These tables store the results of NER processing using spaCy's `en_core_web_sm` model. Entity co-occurrence patterns reveal relationships between people, connections to locations, and temporal patterns.

#### extracted_names (Person names)

Stores every person name mention detected by NER. Names are stored exactly as extracted (including OCR errors and case variations), with canonicalization applied at query time via the `get_canonical_name()` function.

- **Primary Key:** `(file_path, name_string)` — Ensures one record per name per document
- **Foreign Key:** `file_path` → `file_catalog(path)` ON DELETE CASCADE
- **Columns:**
  - `file_path` — Document containing the mention
  - `name_string` — The name exactly as extracted (e.g., "Jeffrey Epstein", "JEFFREY EPSTEIN")
  - `occurrence_count` — How many times this name appears in this document
- **Use Cases:** Person identification, co-occurrence analysis, document relevance scoring

#### extracted_locations (Location mentions)

Stores geographic entities (cities, states, countries, addresses) detected by NER. Location data helps establish where events occurred and geographic patterns in the documents.

- **Primary Key:** `(file_path, location_string)`
- **Foreign Key:** `file_path` → `file_catalog(path)` ON DELETE CASCADE
- **Columns:**
  - `file_path` — Document containing the mention
  - `location_string` — The location exactly as extracted
  - `occurrence_count` — Mention frequency in this document
- **Use Cases:** Geographic analysis, venue identification, travel pattern reconstruction

#### extracted_dates (Date mentions)

Stores temporal references extracted from documents. Where possible, dates are parsed into standardized datetime format for timeline analysis. Unparseable dates are stored as strings only.

- **Primary Key:** `(file_path, date_string)`
- **Foreign Key:** `file_path` → `file_catalog(path)` ON DELETE CASCADE
- **Columns:**
  - `file_path` — Document containing the mention
  - `date_string` — The date as it appears in text (e.g., "January 15, 2005")
  - `date_datetime` — Parsed datetime value (NULL if unparseable)
  - `occurrence_count` — Mention frequency in this document
- **Use Cases:** Timeline reconstruction, event dating, temporal filtering

### 2.3 Entity Disambiguation Tables

OCR documents often contain the same person's name in multiple forms due to case variations, OCR errors, and nickname usage. The disambiguation system groups these variants under canonical names to enable accurate relationship analysis.

#### entity_aliases

The **entity_aliases** table is the core mapping between name variants and their canonical forms. Each row represents one alias pointing to its canonical name. The `get_canonical_name()` PostgreSQL function reads from this table.

- **Purpose:** Maps variant spellings/case to canonical names for unification
- **Primary Key:** `alias_id` (SERIAL auto-increment)
- **Unique Constraint:** `(canonical_name, alias_name)` — Prevents duplicate mappings
- **Columns:**
  - `alias_id` — Auto-generated unique identifier
  - `canonical_name` — The standardized form (e.g., "Jeffrey Epstein")
  - `alias_name` — The variant form (e.g., "JEFFREY EPSTEIN", "Jeff Epstein")
  - `confidence_score` — How confident the match is (0.0-1.0)
  - `disambiguation_method` — How the alias was identified (`automatic`, `manual`, `fuzzy_match`)
  - `created_at` — When the alias was added
  - `reviewed` — Boolean flag for human review status
- **Indexes:** B-tree on `canonical_name`, `alias_name` for fast lookups
- **Protection:** Manual entries (`disambiguation_method = 'manual'`) are preserved during table resets

#### name_disambiguation_queue

A work queue for potential name matches that need human review. The disambiguation script identifies possible matches using fuzzy string matching and shared document contexts, then queues them for approval or rejection.

- **Purpose:** Staging area for potential aliases before confirmation
- **Primary Key:** `queue_id` (SERIAL)
- **Unique Constraint:** `(name_variant_1, name_variant_2)` — Prevents duplicate queue entries
- **Columns:**
  - `queue_id` — Auto-generated identifier
  - `name_variant_1`, `name_variant_2` — The two names being compared
  - `similarity_score` — String similarity metric (0.0-1.0)
  - `confidence_level` — Categorical rating (`HIGH`, `MEDIUM`, `LOW`)
  - `shared_contexts` — Number of documents containing both names
  - `status` — Workflow state (`pending`, `merged`, `rejected`)
  - `created_at`, `reviewed_at` — Timestamps for tracking
- **Indexes:** B-tree on `status` for filtering pending items

#### entity_exclusions

The **entity_exclusions** table stores entities that should be excluded from analysis. These include email artifacts (names inflated by email header repetition), organizations mistakenly extracted as persons, fragmented names (first/last name only), and other non-person entities.

- **Purpose:** Filter out non-persons and artifacts from entity analysis
- **Primary Key:** `exclusion_id` (SERIAL auto-increment)
- **Unique Constraint:** `entity_name` — One exclusion record per entity
- **Columns:**
  - `exclusion_id` — Auto-generated unique identifier
  - `entity_name` — The entity to exclude (e.g., "Boies Schiller")
  - `exclusion_reason` — Why excluded, must be one of:
    - `email_artifact` — Email header repetition inflates counts
    - `organization` — Law firms, addresses, case names
    - `ocr_artifact` — OCR errors and truncated text
    - `fragmented_name` — First/last name only (e.g., "George", "Marc")
    - `legal_pseudonym` — Represents multiple people (e.g., "Jane Doe")
    - `duplicate` — Use another canonical form instead
    - `unrelated_case` — Not related to Epstein-Maxwell matter
    - `pending_review` — Needs further investigation
- **Check Constraint:** `exclusion_reason` must be one of the allowed values
- **Source of Truth:** `EXCLUDED_ENTITIES` dict in `disambiguate_entities.py`

#### joint_name_mappings

The **joint_name_mappings** table handles compound names that contain multiple people (e.g., "Epstein and Maxwell"). These joint names are split into their component individual names for proper entity resolution.

- **Purpose:** Maps compound/joint names to individual component names
- **Primary Key:** `mapping_id` (SERIAL auto-increment)
- **Columns:**
  - `mapping_id` — Auto-generated unique identifier
  - `joint_name` — The compound name (e.g., "Epstein and Maxwell")
  - `component_name` — Individual name component (e.g., "Jeffrey Epstein")
  - `created_at` — When the mapping was added
- **Note:** A single joint name may have multiple rows, one for each component

### 2.4 Entity Network Tables

The entity network represents people and organizations as nodes in a graph, with relationships (edges) connecting them based on known associations and document co-occurrence. This enables network analysis like centrality scoring, community detection, and shortest-path queries.

**Current Statistics:**
- **68 entities** (37 people, 31 companies/organizations)
- **87 relationships** (associates, founders, executives, etc.)
- **7,248 document mentions** linked to entities
- **89 bibliographic sources** with Chicago-style citations
- **8 detected communities** via Louvain algorithm

#### entity_network_entities

The **entity_network_entities** table stores the nodes in the relationship graph. Each entity (person, company, organization) gets one row with a unique identifier used for relationship lookups.

- **Purpose:** Core nodes in the entity relationship graph
- **Primary Key:** `entity_id` (SERIAL auto-increment)
- **Unique Constraint:** `entity_name` — Each entity appears exactly once
- **Columns:**
  - `entity_id` — Graph node identifier
  - `entity_name` — Canonical name of the entity
  - `entity_type` — Classification (`person`, `company`, `organization`, `unknown`)
  - `description` — Optional notes about the entity
  - `created_at`, `updated_at` — Audit timestamps
- **Indexes:** B-tree on `entity_name` (lookups), `entity_type` (filtering)

#### entity_network_relationships

The **entity_network_relationships** table stores edges connecting entities. Relationships are inferred from document co-occurrence—if two people appear in the same document, they have a connection. The relationship strength reflects how many documents they share.

- **Purpose:** Edges connecting entities in the graph
- **Primary Key:** `relationship_id` (SERIAL)
- **Foreign Keys:** Both endpoints reference `entity_network_entities(entity_id)` with CASCADE delete
- **Unique Constraint:** `(source_entity_id, target_entity_id, relationship_type)` — One edge per type per pair
- **Columns:**
  - `relationship_id` — Edge identifier
  - `source_entity_id`, `target_entity_id` — The two connected entities
  - `relationship_type` — Nature of connection (`co_occurrence`, `employment`, `family`, etc.)
  - `confidence_score` — Strength/reliability of the connection (0.0-1.0)
  - `degree` — Number of documents supporting this relationship
  - `source_reference` — Citation for manually-added relationships
  - `created_at` — When the edge was created
- **Indexes:** Separate indexes on `source_entity_id`, `target_entity_id`, `relationship_type`, and `degree`

#### entity_network_mentions

The **entity_network_mentions** table links entities back to their source documents. This enables provenance tracking—you can always find which documents support any entity or relationship claim.

- **Purpose:** Document provenance for entity references
- **Primary Key:** `mention_id` (SERIAL)
- **Foreign Key:** `entity_id` → `entity_network_entities(entity_id)` ON DELETE CASCADE
- **Unique Constraint:** `(entity_id, file_path)` — One mention record per entity per document
- **Columns:**
  - `mention_id` — Record identifier
  - `entity_id` — Which entity was mentioned
  - `file_path` — Which document contains the mention
  - `mention_count` — How many times the entity appears in this document
  - `created_at` — When the mention was recorded
- **Indexes:** B-tree on `entity_id`, `file_path`

#### entity_network_sources

The **entity_network_sources** table stores bibliographic citations for relationship provenance. Each source represents a scholarly article, news report, court document, or other reference that documents entity relationships.

- **Purpose:** Central bibliography of sources for entity relationships and descriptions
- **Primary Key:** `source_id` (SERIAL)
- **Unique Constraint:** `citation_chicago` — Each source appears exactly once
- **Columns:**
  - `source_id` — Unique source identifier
  - `citation_chicago` — Full Chicago-style citation
  - `url` — Online reference URL (optional)
  - `source_type` — Classification (news_article, court_document, academic, book, etc.)
  - `access_date` — When the source was accessed
  - `created_at` — When added to database
- **Row Count:** ~89 sources

#### entity_network_relationship_sources

The **entity_network_relationship_sources** table links relationships to their supporting sources, including page references and quotes.

- **Purpose:** Many-to-many link between relationships and sources with evidence
- **Primary Key:** `relationship_source_id` (SERIAL)
- **Foreign Keys:**
  - `relationship_id` → `entity_network_relationships(relationship_id)` ON DELETE CASCADE
  - `source_id` → `entity_network_sources(source_id)` ON DELETE CASCADE
- **Columns:**
  - `relationship_source_id` — Record identifier
  - `relationship_id` — Which relationship is documented
  - `source_id` — Which source documents it
  - `page_reference` — Specific page or section (optional)
  - `quote` — Supporting quote from source (optional)
  - `created_at` — When the link was created
- **Indexes:** B-tree on `relationship_id`, `source_id`

#### entity_network_entity_sources

The **entity_network_entity_sources** table links entity descriptions to their sources.

- **Purpose:** Sources for entity descriptions and biographical information
- **Primary Key:** `entity_source_id` (SERIAL)
- **Foreign Keys:**
  - `entity_id` → `entity_network_entities(entity_id)` ON DELETE CASCADE
  - `source_id` → `entity_network_sources(source_id)` ON DELETE CASCADE
- **Columns:**
  - `entity_source_id` — Record identifier
  - `entity_id` — Which entity description is documented
  - `source_id` — Which source provides the information
  - `created_at` — When the link was created

#### entity_network_centrality

The **entity_network_centrality** table stores precomputed network centrality metrics for entities, including both full-network and type-specific measures.

- **Purpose:** Cached centrality calculations for visualization performance
- **Primary Key:** `entity_id`
- **Foreign Key:** `entity_id` → `entity_network_entities(entity_id)` ON DELETE CASCADE
- **Columns:**
  - `entity_id` — Entity identifier
  - `degree` — Number of connections
  - `degree_centrality` — Normalized degree (0-1)
  - `betweenness_centrality` — Bridge importance (0-1)
  - `eigenvector_centrality` — Influence measure (0-1)
  - `pagerank` — PageRank score
  - `clustering_coefficient` — Local clustering (0-1)
  - `degree_same_type` — Connections to same entity type
  - `degree_cross_type` — Connections to different entity type
  - `person_subgraph_degree` — Degree within person-only subgraph (persons only)
  - `person_subgraph_betweenness` — Betweenness in person subgraph
  - `person_subgraph_eigenvector` — Eigenvector in person subgraph
  - `projection_degree` — Two-mode projection degree
  - `computed_at` — Timestamp of computation

#### entity_network_communities

The **entity_network_communities** table stores community detection results from various algorithms.

- **Purpose:** Entity clustering and community assignments
- **Primary Key:** `community_id` (SERIAL)
- **Foreign Key:** `entity_id` → `entity_network_entities(entity_id)` ON DELETE CASCADE
- **Unique Constraint:** `(entity_id, algorithm)` — One community per entity per algorithm
- **Columns:**
  - `community_id` — Record identifier
  - `entity_id` — Which entity
  - `community` — Community number assignment
  - `algorithm` — Detection algorithm (louvain, label_propagation, etc.)
  - `computed_at` — When computed
- **Indexes:** B-tree on `entity_id`, `algorithm`, `community`

### 2.5 Term-Document Matrix Tables

Term-Document Matrices (TDMs) enable linguistic analysis by tracking word frequencies across documents. The project maintains separate TDMs for nouns and verbs, using spaCy for part-of-speech tagging. TDMs power analyses like:

- **Document similarity:** Finding documents with similar vocabulary
- **Topic modeling:** Identifying themes across the corpus
- **Keyword extraction:** Finding important terms per document
- **Co-occurrence analysis:** Which words appear together frequently

The sparse, normalized PostgreSQL schema uses ~90% less storage than a dense CSV matrix while enabling fast indexed lookups.

#### Noun TDM

| Table | Purpose | Columns |
|-------|---------|---------|
| `noun_tdm_vocabulary` | Dictionary of all nouns found | `term_id` (PK), `term` (UNIQUE), `document_frequency`, `created_at` |
| `noun_tdm_documents` | Registry of processed documents | `doc_id` (PK), `file_path` (UNIQUE), `file_name`, `noun_count`, `unique_nouns`, `processed_at` |
| `noun_tdm_counts` | Sparse matrix of term frequencies | `doc_id` (FK), `term_id` (FK), `count` — PK: `(doc_id, term_id)` |
| `noun_tdm_metadata` | Processing statistics | `key` (PK), `value`, `updated_at` |

- **`noun_tdm_vocabulary`:** Each unique noun gets one row with its document frequency (how many documents contain it). High document frequency indicates common words; low frequency indicates rare/specific terms.
- **`noun_tdm_documents`:** Tracks which documents have been processed, their total noun count, and unique noun count. Useful for filtering by document complexity.
- **`noun_tdm_counts`:** The actual TDM data in sparse format—only stores non-zero counts. A document with 50 unique nouns creates 50 rows (vs. 50,000+ columns in a dense matrix).
- **`noun_tdm_metadata`:** Stores processing metadata like total documents processed, total terms, build timestamp, etc.

#### Verb TDM

| Table | Purpose | Columns |
|-------|---------|---------|
| `verb_tdm_vocabulary` | Dictionary of all verbs found | `term_id` (PK), `term` (UNIQUE), `document_frequency`, `created_at` |
| `verb_tdm_documents` | Registry of processed documents | `doc_id` (PK), `file_path` (UNIQUE), `file_name`, `verb_count`, `unique_verbs`, `processed_at` |
| `verb_tdm_counts` | Sparse matrix of term frequencies | `doc_id` (FK), `term_id` (FK), `count` — PK: `(doc_id, term_id)` |
| `verb_tdm_metadata` | Processing statistics | `key` (PK), `value`, `updated_at` |

The verb TDM has an identical structure to the noun TDM. Verb analysis can reveal action patterns, tense usage, and document types (legal filings tend to use specific verbs like "alleged", "testified", "stipulated").

### 2.6 Quality Analysis Tables

OCR-processed documents often contain errors—character substitutions, word boundary issues, and artifacts. The spelling analysis system identifies these issues and provides correction suggestions. Additionally, the corpus contains some documents in foreign languages (Spanish, French, etc.) which are detected and flagged.

#### spelling_issues

The **spelling_issues** table is the most detailed table in the schema, capturing comprehensive information about each potential spelling or OCR error. This enables sophisticated filtering and correction prioritization.

- **Purpose:** Tracks every potential spelling/OCR error with context and correction suggestions
- **Primary Key:** `(word, file_path, occurrence_number)` — Tracks multiple occurrences of the same word
- **Column Groups (31 columns total):**

**Identity columns:** Uniquely identify each word occurrence
- `word` — The potentially misspelled word
- `file_path` — Source document
- `occurrence_number` — Which occurrence in the document (1st, 2nd, etc.)
- `subfolder` — Volume/folder path for filtering (e.g., `VOL00001/IMAGES/0001`)

**Position columns:** Where in the document the word appears
- `position_start`, `position_end` — Character offsets in raw text
- `document_length` — Total document length
- `position_percent` — Relative position (0.0-1.0), useful for finding header/footer artifacts

**Context columns:** Surrounding text for human review
- `context_before` — ~50 characters before the word
- `context_after` — ~50 characters after the word

**Correction columns:** Suggested fixes and confidence scores
- `suggested_correction` — Best guess for correct spelling
- `correction_confidence` — How confident the suggestion is (0.0-1.0)
- `hamming_distance` — Edit distance (same length)
- `levenshtein_distance` — Edit distance (any length)
- `damerau_levenshtein_distance` — Edit distance including transpositions

**OCR pattern columns:** Classification of error types
- `ocr_error_pattern` — Detected pattern (e.g., `rn→m`, `l→1`, `O→0`)
- `boundary_error_pattern` — Word boundary issues (merged/split words)

**Abbreviation columns:** Filtering out intentional non-words
- `is_abbreviation` — General abbreviation flag
- `is_state_code` — US state abbreviation (CA, NY, etc.)
- `is_country_code` — Country code (US, UK, etc.)
- `is_page_number` — Page reference (pg, p., page)
- `is_other_abbreviation` — Other known abbreviations
- `is_date_number` — Date components (2005, 15th, etc.)
- `is_ocr_fragment` — Random character sequences from OCR noise

**Language columns:** Foreign language detection (29 languages supported)
- `detected_language` — ISO language code (es, fr, de, etc.)
- `is_foreign_word` — Boolean flag
- `foreign_language_suggestion` — Correct spelling in detected language
- `foreign_language_confidence` — Detection confidence
- `foreign_word_translation` — English translation via Google Translate API

**Timestamp columns:** Tracking when issues were found
- `first_seen`, `last_seen` — Audit trail

- **Indexes:** Multiple indexes for common query patterns:
  - `word` — Find all occurrences of a specific word
  - `file_path` — Get all issues in a document
  - `subfolder` — Filter by volume
  - `position_percent` — Find header/footer artifacts
  - `is_abbreviation`, `is_page_number` — Filter out non-errors
  - `correction_confidence` — Prioritize high-confidence corrections
  - `detected_language`, `is_foreign_word` — Language analysis

### 2.7 Document Similarity Tables

The document similarity analysis uses TF-IDF (Term Frequency-Inverse Document Frequency) to compute cosine similarity between documents, enabling clustering and network visualization. Persistent homology analysis identifies optimal similarity thresholds by tracking topological features.

**Current Statistics:**
- **~14,680 documents** analyzed for similarity
- **~50,000+ document pairs** with similarity scores above threshold
- **8 detected communities** via Louvain algorithm
- **Persistent homology** computed across similarity range 0.0–1.0

#### document_similarity_pairs

The **document_similarity_pairs** table stores pairwise cosine similarity scores between documents. Only pairs above a minimum threshold are stored to manage table size.

- **Purpose:** Edge list for document similarity network
- **Primary Key:** `pair_id` (SERIAL)
- **Columns:**
  - `pair_id` — Auto-generated unique identifier
  - `doc_id_1`, `doc_id_2` — Document IDs from noun_tdm_documents
  - `file_path_1`, `file_path_2` — Full paths for display/lookup
  - `cosine_similarity` — TF-IDF cosine similarity score (0.0–1.0)
  - `created_at` — When the pair was computed
- **Indexes:** B-tree on document IDs for fast neighbor lookups

#### document_similarity_persistence

The **document_similarity_persistence** table stores persistent homology results—topological features (connected components, cycles) that persist across similarity thresholds.

- **Purpose:** Persistent homology diagram for threshold selection
- **Primary Key:** `feature_id` (SERIAL)
- **Columns:**
  - `feature_id` — Auto-generated unique identifier
  - `dimension` — Homology dimension (0 = components, 1 = cycles/holes)
  - `birth` — Similarity threshold where feature appears
  - `death` — Similarity threshold where feature disappears (NULL = persists to end)
  - `persistence` — Death minus birth (longer = more significant)
  - `birth_edge_doc1`, `birth_edge_doc2` — Documents forming the birth edge
  - `representative_cycle` — For H₁ features, the cycle members
  - `created_at` — When computed
- **Use Cases:** Finding optimal threshold where significant features stabilize

#### document_similarity_betti_numbers

The **document_similarity_betti_numbers** table stores Betti numbers (topological invariants) at each similarity threshold, enabling the Betti curve visualization.

- **Purpose:** Threshold-by-threshold topological summary
- **Primary Key:** `threshold_id` (SERIAL)
- **Columns:**
  - `threshold_id` — Auto-generated unique identifier
  - `similarity_threshold` — The threshold value (e.g., 0.30, 0.35, 0.40)
  - `betti_0` — Number of connected components (H₀)
  - `betti_1` — Number of cycles/holes (H₁)
  - `num_edges` — Edge count at this threshold
  - `num_vertices` — Vertex count (documents with at least one edge)
  - `created_at` — When computed
- **Use Cases:** Betti curve visualization, threshold optimization

#### document_similarity_metadata

The **document_similarity_metadata** table stores key-value pairs for processing parameters and statistics.

- **Purpose:** Processing configuration and statistics
- **Primary Key:** `key` (TEXT)
- **Columns:**
  - `key` — Parameter name (e.g., `tdm_type`, `min_threshold`, `total_pairs`)
  - `value` — Parameter value as text
  - `updated_at` — Last update timestamp
- **Common Keys:** `tdm_type`, `min_threshold`, `max_docs`, `computed_at`, `total_pairs`

#### document_similarity_centrality

The **document_similarity_centrality** table stores precomputed centrality metrics for documents at a specific similarity threshold.

- **Purpose:** Cached centrality calculations for visualization performance
- **Primary Key:** `centrality_id` (SERIAL)
- **Columns:**
  - `centrality_id` — Auto-generated unique identifier
  - `doc_id` — Document ID from noun_tdm_documents
  - `file_path` — Full path for display
  - `similarity_threshold` — Threshold used for this computation
  - `degree` — Number of connections
  - `degree_centrality` — Normalized degree (0.0–1.0)
  - `betweenness_centrality` — Bridge score between clusters
  - `eigenvector_centrality` — Importance based on neighbor importance
  - `closeness_centrality` — Average distance to all other nodes
  - `clustering_coefficient` — How connected neighbors are to each other
  - `component_id` — Which connected component
  - `component_size` — Size of the component
  - `created_at` — When computed
- **Indexes:** B-tree on `doc_id`, `similarity_threshold`

#### document_similarity_communities

The **document_similarity_communities** table stores community detection results for documents.

- **Purpose:** Document clustering and community assignments
- **Primary Key:** `community_id` (SERIAL)
- **Columns:**
  - `community_id` — Auto-generated unique identifier
  - `doc_id` — Document ID
  - `file_path` — Full path for display
  - `similarity_threshold` — Threshold used for clustering
  - `community` — Assigned community number
  - `community_size` — Number of documents in this community
  - `algorithm` — Detection algorithm (e.g., `louvain`)
  - `modularity` — Quality score for the partition
  - `internal_edges` — Edges within the community
  - `external_edges` — Edges to other communities
  - `internal_density` — Density of internal connections
  - `created_at` — When computed
- **Indexes:** B-tree on `doc_id`, `similarity_threshold`, `algorithm`

#### document_similarity_community_labels

The **document_similarity_community_labels** table stores human-readable labels and metadata for each detected community.

- **Purpose:** Community interpretation and labeling
- **Primary Key:** `label_id` (SERIAL)
- **Columns:**
  - `label_id` — Auto-generated unique identifier
  - `similarity_threshold` — Threshold for this clustering
  - `algorithm` — Detection algorithm used
  - `community` — Community number
  - `label` — Human-readable label (e.g., "Legal Correspondence")
  - `top_entities` — JSONB array of most frequent entities in community
  - `top_nouns` — JSONB array of most frequent nouns
  - `top_verbs` — JSONB array of most frequent verbs
  - `date_range_start`, `date_range_end` — Temporal span of documents
  - `document_count` — Number of documents in community
  - `avg_quality_score` — Average document quality metric
  - `auto_generated` — Whether label was auto-generated
  - `human_reviewed` — Whether a human has verified the label
  - `created_at` — When created
- **Use Cases:** Community tooltips in visualization, filtering by topic

#### document_similarity_bridge_documents

The **document_similarity_bridge_documents** table identifies documents that bridge multiple communities—key documents connecting different topic clusters.

- **Purpose:** Identify structurally important documents
- **Primary Key:** `bridge_id` (SERIAL)
- **Columns:**
  - `bridge_id` — Auto-generated unique identifier
  - `doc_id` — Document ID
  - `file_path` — Full path for display
  - `similarity_threshold` — Threshold for this analysis
  - `betweenness_centrality` — How often document lies on shortest paths
  - `communities_bridged` — JSONB array of connected community IDs
  - `bridge_strength` — JSONB object with per-community connection counts
  - `entity_overlap` — JSONB object showing shared entities across communities
  - `bridge_type` — Classification (e.g., `multi_community`, `single_bridge`)
  - `created_at` — When identified
- **Use Cases:** Finding key documents, understanding inter-topic connections

### 2.8 Analytical Views (14 total)

Views provide pre-built queries for common analysis tasks. They don't store data—they're saved SQL queries that execute against the underlying tables. Some views are computationally expensive and may benefit from materialization (see Section 7.3).

| View | Purpose | Performance |
|------|---------|-------------|
| `entity_mentions_consolidated` | Unified entity counts with canonical names and alias resolution | Fast—aggregates with get_canonical_name() |
| `v_corpus_summary` | Overall corpus statistics (total docs, total entities, avg per doc) | Fast—single aggregation |
| `v_document_quality` | Document quality metrics (word count, entity density, text length) | Medium—joins file_catalog with extracted_text_content |
| `v_document_entities` | Entity counts per document (names, locations, dates) | **Optimized**—was 5+ min, now <1 sec |
| `v_document_timeline` | Documents by parsed date for temporal analysis | Medium—requires date parsing |
| `v_entity_mentions` | Canonicalized entity counts with exclusion filtering | Fast—uses get_canonical_name(), filters excluded entities |
| `v_person_cooccurrence` | Who appears with whom and how often | **Heavy**—N² comparison, consider materializing |
| `v_location_summary` | Location mention frequencies and document counts | Fast—simple aggregation |
| `v_ocr_pattern_summary` | Summary of OCR error patterns across corpus | Fast—aggregates spelling_issues |
| `v_spelling_variants` | Groups similar misspellings (e.g., "recieved"/"received") | Medium—string similarity |
| `v_foreign_language_words` | Non-English words with translations | Fast—filtered query |
| `v_complex_documents` | Documents with high entity density (many names/dates/locations) | Medium—calculated metrics |
| `v_high_priority_corrections` | Priority queue of corrections (high confidence, high frequency) | Fast—filtered and sorted |
| `v_corrected_text` | Text with spelling corrections applied via `apply_text_corrections()` | **Heavy**—applies JSONB corrections |

### 2.9 Database Functions

PostgreSQL functions encapsulate complex logic for reuse across queries and views.

#### get_canonical_name(TEXT)

The **get_canonical_name** function is central to entity resolution. It takes any name string and returns the canonical form, enabling accurate aggregation across name variants.

- **Purpose:** Maps name variants to canonical forms for entity unification
- **Input:** Any name string (e.g., `'JEFFREY EPSTEIN'`, `'Jeff Epstein'`)
- **Returns:** Canonical name (e.g., `'Jeffrey Epstein'`) or original if no mapping exists
- **Created by:** `disambiguate_entities.py --create-function`
- **Preprocessing:** Before alias lookup, the function:
  1. Strips email suffixes: `Sent`, `Cc`, `To`, `From`, `Subject`, `Re`, `Fwd`
  2. Strips signature suffixes: `Partner`, `Counsel`, `Associate`
  3. Strips possessive forms: `'s`, `s'`, `'s`, `s'`
- **Implementation:** Looks up preprocessed name in `entity_aliases` table. Unmapped names pass through unchanged.
- **Performance:** O(1) lookup—indexed table scan

**Usage examples:**
```sql
-- Direct call
SELECT get_canonical_name('JEFFREY EPSTEIN');  -- Returns: 'Jeffrey Epstein'

-- With suffix stripping
SELECT get_canonical_name('Sigrid McCawley Partner');  -- Returns: 'Sigrid McCawley'
SELECT get_canonical_name('Joe Nascimento Sent');  -- Returns: 'Joseph Nascimento'

-- In aggregation
SELECT get_canonical_name(name_string) AS person, COUNT(*) AS mentions
FROM extracted_names
GROUP BY get_canonical_name(name_string)
ORDER BY mentions DESC;
```

#### apply_text_corrections(TEXT, JSONB)

The **apply_text_corrections** function applies a set of spelling corrections to text. It's used by the `v_corrected_text` view to show documents with OCR errors fixed.

- **Purpose:** Applies spelling corrections to raw text
- **Input Parameters:**
  - `original_text` (TEXT) — The text to correct
  - `corrections` (JSONB) — Array of correction rules: `[{"old": "teh", "new": "the"}, ...]`
- **Returns:** Corrected text with all substitutions applied
- **Created by:** `create_views.py`
- **Implementation:** Iterates through corrections array, applying each substitution in order

**Usage example:**
```sql
SELECT apply_text_corrections(
    'Teh quick brown fox jumpd over teh lazy dog.',
    '[{"old": "Teh", "new": "The"}, {"old": "teh", "new": "the"}, {"old": "jumpd", "new": "jumped"}]'::jsonb
);
-- Returns: 'The quick brown fox jumped over the lazy dog.'
```

---

## 3. Database Utilities

All project scripts use shared database utilities in [db_utils.py](scripts/db_utils.py). This promotes code reuse, ensures consistent error handling, and centralizes connection management. Scripts import from `db_utils` rather than duplicating database code.

### 3.1 Connection Management

Database connections are managed via context managers to ensure proper cleanup even when errors occur. This prevents connection leaks that could exhaust PostgreSQL's connection pool.

```python
from db_utils import get_db_connection

# Standard usage with automatic commit/rollback
with get_db_connection(dsn) as conn:
    # Execute queries...
    # Connection automatically closed on exit
    # Transaction committed if no exception, rolled back otherwise
    pass

# Autocommit mode for DDL statements (CREATE TABLE, DROP, etc.)
# DDL cannot run inside a transaction in PostgreSQL
with get_db_connection(dsn, autocommit=True) as conn:
    conn.execute("CREATE TABLE ...")  # Immediate execution
```

### 3.2 Table Operations

Helper functions abstract common table management operations, providing consistent behavior and dry-run support for safe testing.

```python
from db_utils import table_exists, create_table_if_not_exists, drop_table, truncate_table

# Check existence before operations
if table_exists(conn, 'my_table'):
    print("Table exists")

# Idempotent table creation—safe to call multiple times
created = create_table_if_not_exists(conn, 'my_table', CREATE_TABLE_SQL)
# Returns True if created, False if already existed

# Drop table (requires cascade=True for tables with foreign key references)
dropped = drop_table(conn, 'my_table', cascade=True)

# Truncate clears data but keeps table structure
# restart_identity resets SERIAL columns to 1
truncated = truncate_table(conn, 'my_table', cascade=True, restart_identity=True)

# Dry run mode previews what would happen without making changes
drop_table(conn, 'my_table', dry_run=True)
# Output: "[DRY RUN] Would drop table 'my_table'"
```

### 3.3 Data Operations

Efficient data operations for querying and bulk loading. The `bulk_insert` function handles batching automatically to avoid memory issues with large datasets.

```python
from db_utils import execute_query, bulk_insert, get_table_row_count

# Execute parameterized queries (prevents SQL injection)
results = execute_query(conn, "SELECT * FROM my_table WHERE id = %s", (123,))

# Bulk insert with automatic batching
# Processes 1000 rows at a time to balance memory and transaction overhead
rows = [(1, 'foo'), (2, 'bar'), (3, 'baz')]
count = bulk_insert(conn, 'my_table', ['id', 'name'], rows, batch_size=1000)
# Returns: 3 (number of rows inserted)

# Quick row count without loading all data
count = get_table_row_count(conn, 'my_table')
```

### 3.4 Schema Inspection

Functions for exploring database structure, useful for debugging and reporting.

```python
from db_utils import list_tables, get_table_stats

# List all tables in a schema
tables = list_tables(conn, schema='public')
# Returns: ['file_catalog', 'extracted_text_content', ...]

# Get row counts for all tables at once
stats = get_table_stats(conn)
for table, count in stats.items():
    print(f"{table}: {count:,} rows")
# Output:
# file_catalog: 29,921 rows
# extracted_text_content: 14,680 rows
# extracted_names: 198,456 rows
# ...
```

---

## 4. Table Management

Managing table data in a document analysis project requires careful consideration. You need the ability to reprocess data as code improves, while preserving manually-curated information like human-verified entity aliases.

### 4.1 Philosophy

The project uses a **hybrid approach** to data management:

1. **Automatic duplicate prevention:** All INSERT statements use `ON CONFLICT` clauses (UPSERT pattern). Re-running a script updates existing records rather than creating duplicates. This makes scripts idempotent—safe to run multiple times.

2. **Manual reset capability:** The [reset_tables.py](scripts/reset_tables.py) utility provides controlled data clearing when you need to start fresh—perhaps to reprocess with improved extraction code.

3. **Protection for curated data:** Manually-created entity aliases (where `disambiguation_method = 'manual'`) are preserved during resets by default. These represent human knowledge that shouldn't be lost.

### 4.2 Reset Utility Usage

The reset utility operates at the "feature" level—logical groups of related tables—rather than requiring you to remember individual table names.

```bash
# See available features and their tables
python3 scripts/reset_tables.py --list-features

# Reset all tables for a feature (truncates data, keeps structure)
python3 scripts/reset_tables.py --feature entity_disambiguation

# Reset specific tables by name
python3 scripts/reset_tables.py --tables spelling_issues word_frequencies

# Drop tables entirely (removes structure too)
# Requires explicit --confirm flag as a safety measure
python3 scripts/reset_tables.py --feature spelling --drop --confirm

# Preview what would happen without making changes
python3 scripts/reset_tables.py --feature all --dry-run
```

### 4.3 Features and Their Tables

Features group related tables for batch operations. This reflects the logical structure of the analysis pipeline.

| Feature | Tables | Description |
|---------|--------|-------------|
| `spelling` | `spelling_issues` | Spelling/OCR analysis results |
| `entity_disambiguation` | `entity_aliases`, `name_disambiguation_queue`, `joint_name_mappings` | Name variant mappings and review queue |
| `entity_network` | `entity_network_entities`, `entity_network_relationships`, `entity_network_mentions`, `entity_network_sources`, `entity_network_relationship_sources`, `entity_network_entity_sources`, `entity_network_centrality`, `entity_network_communities` | Curated entity graph with sourced citations |
| `catalog` | `file_catalog`, `extracted_dates`, `extracted_names`, `extracted_locations`, `entity_exclusions` | Core file registry and NER results |
| `text_content` | `extracted_text_content` | Full extracted text storage |
| `tdm_nouns` | `noun_tdm_vocabulary`, `noun_tdm_documents`, `noun_tdm_counts`, `noun_tdm_metadata` | Noun frequency matrix |
| `tdm_verbs` | `verb_tdm_vocabulary`, `verb_tdm_documents`, `verb_tdm_counts`, `verb_tdm_metadata` | Verb frequency matrix |
| `pdf_metadata` | `pdf_metadata` | PDF document metadata |
| `document_similarity` | `document_similarity_pairs`, `document_similarity_persistence`, `document_similarity_metadata`, `document_similarity_betti_numbers`, `document_similarity_centrality`, `document_similarity_communities`, `document_similarity_community_labels`, `document_similarity_bridge_documents` | TF-IDF document similarity network |
| `all` | All project tables | Complete database reset (use with caution!) |

### 4.4 Reset Modes

#### TRUNCATE Mode (Default)

Truncation clears all data but preserves the table structure (columns, indexes, constraints). This is the fastest and safest option for routine reprocessing.

- **Speed:** Nearly instant, regardless of data volume
- **Sequences:** Resets SERIAL/auto-increment columns to 1
- **Indexes:** Remain intact (no rebuild needed)
- **Manual data:** Can be preserved with flags

#### DROP Mode

Dropping completely removes tables from the database. Use this when schema changes require table recreation (new columns, changed constraints, etc.).

- **Speed:** Fast but requires script re-run to recreate
- **Safety:** Requires `--confirm` flag to prevent accidents
- **When to use:** After schema changes, or for truly clean starts

### 4.5 Protected Manual Data

The `entity_aliases` table may contain manually-verified mappings (where `disambiguation_method = 'manual'`). These represent human research that would be costly to recreate.

**Default behavior:** Manual entries are preserved during TRUNCATE operations. The reset utility selectively deletes only non-manual rows.

```bash
# Standard reset (preserves manual entries)
python3 scripts/reset_tables.py --feature entity_disambiguation

# Override protection (deletes everything including manual)
python3 scripts/reset_tables.py --feature entity_disambiguation --no-preserve-manual
```

### 4.6 Duplicate Prevention in Scripts

All data-loading scripts use `ON CONFLICT` clauses to handle re-runs gracefully. This pattern either updates existing rows or skips duplicates, depending on the table's requirements.

```sql
-- catalog_to_postgres.py: Updates existing files with new metadata
INSERT INTO file_catalog (path, file_name, file_type, size_bytes, ...)
VALUES (%s, %s, %s, %s, ...)
ON CONFLICT (path) DO UPDATE SET
    file_name = EXCLUDED.file_name,
    size_bytes = EXCLUDED.size_bytes,
    mtime = EXCLUDED.mtime;

-- disambiguate_entities.py: Silently skips existing queue entries
INSERT INTO name_disambiguation_queue (name_variant_1, name_variant_2, ...)
VALUES (%s, %s, ...)
ON CONFLICT DO NOTHING;

-- analyze_spelling.py: Updates issues with latest analysis
INSERT INTO spelling_issues (word, file_path, occurrence_number, ...)
VALUES (%s, %s, %s, ...)
ON CONFLICT (word, file_path, occurrence_number) DO UPDATE SET
    suggested_correction = EXCLUDED.suggested_correction,
    correction_confidence = EXCLUDED.correction_confidence,
    last_seen = NOW();
```

### 4.7 CLI Conventions

All scripts with destructive database operations follow consistent CLI conventions:

| Flag | Purpose | Required With |
|------|---------|---------------|
| `--clear` | Clear/delete existing data before operation | `--confirm` |
| `--drop` | Drop tables completely (reset_tables.py only) | `--confirm` |
| `--dry-run` | Preview what would happen without making changes | — |
| `--confirm` | Confirm destructive operations | `--clear`, `--drop` |
| `--verbose` | Show detailed progress output | — |

**Examples:**

```bash
# Preview what --clear would do
python3 scripts/build_noun_tdm_postgres.py . --clear --dry-run

# Actually clear and rebuild (requires --confirm)
python3 scripts/build_noun_tdm_postgres.py . --clear --confirm --verbose

# Clear entity disambiguation data
python3 scripts/disambiguate_entities.py --clear --confirm

# Clear entity network before rebuilding
python3 scripts/build_entity_network.py --clear --confirm --from-database
```

**Scripts supporting these conventions:**
- `reset_tables.py` — Full support (`--clear` via `--feature`, `--drop`, `--dry-run`, `--confirm`)
- `disambiguate_entities.py` — `--clear`, `--dry-run`, `--confirm`
- `build_noun_tdm_postgres.py` — `--clear`, `--dry-run`, `--confirm`
- `build_verb_tdm_postgres.py` — `--clear`, `--dry-run`, `--confirm`
- `build_entity_network.py` — `--clear`, `--dry-run`, `--confirm`

---

## 5. Entity Canonicalization

Entity canonicalization is the process of mapping different representations of the same real-world entity to a single canonical form. This is essential for accurate analysis—without it, the same person appears as multiple separate entities in reports.

### 5.1 Overview

The entity disambiguation system addresses a fundamental challenge in document analysis: **name variation**. The same person may appear with different capitalizations, abbreviations, nicknames, or OCR-introduced errors. The system:

1. **Detects potential aliases** using fuzzy string matching and document co-occurrence
2. **Queues matches for review** with confidence scores
3. **Stores confirmed mappings** in the `entity_aliases` table
4. **Generates a PostgreSQL function** that applies mappings at query time
5. **Updates analytical views** to use canonical names automatically

### 5.2 The Problem

Without canonicalization, entity counting and relationship analysis produce fragmented, misleading results:

```
"Jeffrey Epstein" appears with "Ghislaine Maxwell" in 50 documents
"JEFFREY EPSTEIN" appears with "Ghislaine Maxwell" in 30 documents  
"Jeff Epstein" appears with "GHISLAINE MAXWELL" in 20 documents
```

**The true relationship strength is ~100 documents, but it's split across variants!**

This problem compounds with more entities. If you have 5 variants of Person A and 4 variants of Person B, you could see up to 20 separate relationship entries (5 × 4) for what should be one relationship.

### 5.3 Solution: PostgreSQL Function

The `get_canonical_name(TEXT)` function provides instant lookup of canonical forms. It's implemented as a CASE statement compiled directly into PostgreSQL, so there's no table lookup overhead at query time.

```sql
-- Examples of canonicalization in action
SELECT get_canonical_name('JEFFREY EPSTEIN');        -- Returns: Jeffrey Epstein
SELECT get_canonical_name('Jeff Epstein');           -- Returns: Jeffrey Epstein
SELECT get_canonical_name('Bobbi C. Sternheim');     -- Returns: Bobbi Sternheim
SELECT get_canonical_name('Unknown Person');         -- Returns: Unknown Person (unchanged)
```

The function is regenerated from the `entity_aliases` table whenever new mappings are added, ensuring it always reflects the current state of knowledge.

### 5.4 Workflow

The disambiguation workflow is designed for iterative refinement. You can run analysis multiple times as new documents are added or as you refine the matching criteria.

```bash
# Step 1: Check current state (how many names, aliases, queue items)
python3 scripts/disambiguate_entities.py --stats

# Step 2: Analyze names for potential matches using fuzzy matching
# This populates the name_disambiguation_queue table
python3 scripts/disambiguate_entities.py --analyze

# Step 3: Review high-confidence matches before merging
# Shows potential aliases with their similarity scores
python3 scripts/disambiguate_entities.py --review --limit 50

# Step 4: Preview what merging would do (dry run)
python3 scripts/disambiguate_entities.py --merge --dry-run

# Step 5: Execute the merge (creates entity_aliases entries)
python3 scripts/disambiguate_entities.py --merge

# Step 6: Regenerate the PostgreSQL function from current aliases
python3 scripts/disambiguate_entities.py --create-function

# Step 7: Update views to use the new canonical name function
python3 scripts/disambiguate_entities.py --update-views
```

**Important:** Steps 6 and 7 must be run after adding new aliases for changes to take effect in queries and views.

### 5.5 Before/After Results

The impact of canonicalization is dramatic. What appeared to be weak, fragmented relationships consolidate into strong, accurate connections.

**Before canonicalization:**
```
person_1              | person_2              | shared_documents
Jeffrey Epstein       | Ghislaine Maxwell     | 50
JEFFREY EPSTEIN       | Ghislaine Maxwell     | 30
Jeff Epstein          | GHISLAINE MAXWELL     | 20
jeffrey epstein       | G. Maxwell            | 15
J. Epstein            | Maxwell               | 10
```

**After canonicalization:**
```
person_1              | person_2              | shared_documents
Jeffrey Epstein       | Ghislaine Maxwell     | 125
```

The relationship strength increased from a maximum of 50 (the largest fragment) to 125 (the true total). This represents a **150% improvement** in relationship detection for this pair.

### 5.6 Using Canonical Names in Queries

Once the `get_canonical_name()` function is created, you can use it anywhere in your SQL queries. The function is transparent—it returns the canonical name if a mapping exists, or the original name if not.

```sql
-- Get all documents mentioning Jeffrey Epstein (any variant)
-- This catches "JEFFREY EPSTEIN", "Jeff Epstein", etc.
SELECT DISTINCT file_path, name_string
FROM extracted_names
WHERE get_canonical_name(name_string) = 'Jeffrey Epstein';

-- Count mentions by canonical entity (consolidates all variants)
SELECT 
    get_canonical_name(name_string) AS entity,
    COUNT(DISTINCT file_path) AS doc_count,
    COUNT(*) AS total_mentions
FROM extracted_names
GROUP BY get_canonical_name(name_string)
ORDER BY doc_count DESC;

-- Find all known aliases for a person
SELECT alias_name, confidence_score, disambiguation_method
FROM entity_aliases
WHERE canonical_name = 'Jeffrey Epstein';
```

### 5.7 Known Aliases (282 total)

The system currently tracks 282 alias mappings across 53 canonical entities. Aliases are added through both automatic fuzzy matching and manual curation.

**Key entities with loaded aliases:**
- **Jeffrey Epstein:** 21 variants (case variations, abbreviations, OCR errors)
- **Ghislaine Maxwell:** 7 variants
- **Mark S. Cohen:** 7 variants (attorney)
- **Jay Lefkowitz:** 6 variants (attorney)
- **Bobbi Sternheim:** 6 variants (defense attorney)
- **Michael C. Miller:** 6 variants
- **Laura Menninger:** 5 variants (defense attorney)
- **Reid Weingarten:** 5 variants (attorney)
- **Jane Doe:** 5 variants
- **35+ other key figures:** attorneys, officials, witnesses, associates

Aliases can be viewed and managed directly:

```sql
-- View all aliases grouped by canonical name
SELECT canonical_name, 
       COUNT(*) AS alias_count,
       STRING_AGG(alias_name, ', ') AS aliases
FROM entity_aliases
GROUP BY canonical_name
ORDER BY alias_count DESC;

-- Add a manual alias
INSERT INTO entity_aliases (canonical_name, alias_name, confidence_score, disambiguation_method)
VALUES ('Jeffrey Epstein', 'J. E. Epstein', 1.0, 'manual');

-- After adding aliases, regenerate the function:
-- python3 scripts/disambiguate_entities.py --create-function
```

---

## 6. Term-Document Matrices

Term-Document Matrices (TDMs) are a foundational technique in text analysis. They represent a corpus as a matrix where rows are documents, columns are terms (words), and cells contain frequency counts. This enables mathematical operations on text data.

### 6.1 Overview

The project maintains PostgreSQL-based TDMs for both nouns and verbs, extracted using spaCy's part-of-speech tagging. Unlike traditional dense matrix files (CSV, NumPy), these use a normalized relational schema that stores only non-zero values.

**Why separate noun and verb TDMs?**

- **Nouns** reveal topics, entities, and objects discussed in documents
- **Verbs** reveal actions, states, and the nature of events
- Together they provide complementary views of document content

**Example applications:**

- Find documents similar to a given document (cosine similarity)
- Identify important terms per document (TF-IDF weighting)
- Discover topic clusters across the corpus
- Track terminology changes over time

### 6.2 Prerequisites

The TDM scripts require spaCy for part-of-speech tagging and NLTK for tokenization support.

```bash
# Install required packages
pip install psycopg spacy nltk

# Download the English language model for spaCy
python -m spacy download en_core_web_sm
```

### 6.3 Building TDMs

Building a TDM processes all extracted text files, tokenizes them, filters by part of speech, and stores the results. This is a one-time operation (unless you want to rebuild from scratch).

#### Noun TDM

```bash
python3 scripts/build_noun_tdm_postgres.py <root_directory> \
    --ext _extracted.txt \
    --clear --confirm \     # Clears existing TDM data (requires --confirm)
    --verbose               # Shows progress during processing
```

#### Verb TDM

```bash
python3 scripts/build_verb_tdm_postgres.py <root_directory> \
    --ext _extracted.txt \
    --clear --confirm \
    --verbose
```

**Safety flags:** Use `--dry-run` to preview what would be done, and `--confirm` is required for `--clear` operations.

**Processing time:** Approximately 30-60 minutes for the full corpus (~14,680 documents), depending on system performance.

### 6.4 Querying TDMs

Once built, the TDMs enable powerful linguistic queries using standard SQL.

**View the vocabulary (most common terms):**
```sql
-- Top 20 most common nouns by document frequency
SELECT term, document_frequency 
FROM noun_tdm_vocabulary 
ORDER BY document_frequency DESC 
LIMIT 20;
```

**Find documents containing a specific term:**
```sql
-- Which documents mention "epstein" and how often?
SELECT d.file_name, c.count
FROM noun_tdm_counts c
JOIN noun_tdm_documents d ON c.doc_id = d.doc_id
JOIN noun_tdm_vocabulary v ON c.term_id = v.term_id
WHERE v.term = 'epstein'
ORDER BY c.count DESC;
```

**Find co-occurring terms (terms that appear together):**
```sql
-- Nouns that frequently appear in the same documents
SELECT v1.term as noun1, v2.term as noun2, COUNT(*) as co_occurrences
FROM noun_tdm_counts c1
JOIN noun_tdm_counts c2 ON c1.doc_id = c2.doc_id AND c1.term_id < c2.term_id
JOIN noun_tdm_vocabulary v1 ON c1.term_id = v1.term_id
JOIN noun_tdm_vocabulary v2 ON c2.term_id = v2.term_id
GROUP BY v1.term, v2.term
ORDER BY co_occurrences DESC
LIMIT 20;
```

**Calculate document similarity (basic):**
```sql
-- Documents sharing the most terms with document ID 1
SELECT d2.file_name, COUNT(*) AS shared_terms
FROM noun_tdm_counts c1
JOIN noun_tdm_counts c2 ON c1.term_id = c2.term_id AND c1.doc_id != c2.doc_id
JOIN noun_tdm_documents d2 ON c2.doc_id = d2.doc_id
WHERE c1.doc_id = 1
GROUP BY d2.doc_id, d2.file_name
ORDER BY shared_terms DESC
LIMIT 10;
```

### 6.5 CSV vs PostgreSQL Comparison

The PostgreSQL approach offers significant advantages over traditional CSV-based TDMs, especially for large corpora.

| Feature | CSV (Dense Matrix) | PostgreSQL (Sparse Normalized) |
|---------|-----|------------|
| **Storage format** | Dense matrix (all cells stored) | Sparse (only non-zero values) |
| **File size** | ~50 MB | ~5 MB (90% smaller) |
| **Query speed** | Must load entire file into memory | Indexed lookups (100x faster) |
| **Updates** | Rewrite entire file | Incremental updates |
| **Memory usage** | Load full matrix at once | Query only needed data |
| **Concurrent access** | File locking issues | Full ACID support |
| **Complex queries** | Requires Python code | Native SQL JOINs |

---

## 7. Performance Optimization

PostgreSQL query performance can vary dramatically based on how queries are structured. This section documents optimization techniques used in the project, focusing on a real case study that achieved a **932x speedup**.

### 7.1 Case Study: v_document_entities View

The `v_document_entities` view joins the file catalog with three entity tables (names, locations, dates) to show entity counts per document. The naive implementation was unusably slow.

**Problem:** Original query taking **5+ minutes** (313 seconds) for a simple SELECT

**Root Cause Analysis:**

The problem was a **Cartesian product explosion** from joining multiple one-to-many tables simultaneously. Each file can have multiple names, multiple locations, and multiple dates. When joined together before aggregation:

```
29,921 documents × 6.8 avg dates × 6.0 avg names × 4.5 avg locations 
= 68 MILLION intermediate rows!
```

PostgreSQL had to materialize and process 68 million rows just to count entities per document.

**Original (slow) query structure:**
```sql
-- BAD: Joins raw tables, then aggregates
SELECT fc.path, 
       COUNT(DISTINCT ed.date_string) AS date_count,
       COUNT(DISTINCT en.name_string) AS name_count,
       COUNT(DISTINCT el.location_string) AS location_count
FROM file_catalog fc
LEFT JOIN extracted_dates ed ON fc.path = ed.file_path
LEFT JOIN extracted_names en ON fc.path = en.file_path
LEFT JOIN extracted_locations el ON fc.path = el.file_path
GROUP BY fc.path;
-- Processing 68 MILLION intermediate rows!
```

**Solution: Aggregate in subqueries FIRST, then join**

By pre-aggregating each entity table in a subquery, we join already-summarized data (one row per document) rather than raw entity rows.

```sql
-- GOOD: Aggregate in subqueries, then join
SELECT fc.path,
       COALESCE(dates.count, 0) AS date_count,
       COALESCE(names.count, 0) AS name_count,
       COALESCE(locations.count, 0) AS location_count
FROM file_catalog fc
LEFT JOIN (
    SELECT file_path, COUNT(DISTINCT date_string) AS count 
    FROM extracted_dates GROUP BY file_path
) dates ON fc.path = dates.file_path
LEFT JOIN (
    SELECT file_path, COUNT(DISTINCT name_string) AS count 
    FROM extracted_names GROUP BY file_path
) names ON fc.path = names.file_path
LEFT JOIN (
    SELECT file_path, COUNT(DISTINCT location_string) AS count 
    FROM extracted_locations GROUP BY file_path
) locations ON fc.path = locations.file_path;
-- Processing only 30,000 rows!
```

**Results:**

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| SELECT ... LIMIT 10 | 313.92s | 0.34s | **932x faster** |
| SELECT COUNT(*) | 225.34s | 0.04s | **5,703x faster** |
| Intermediate rows | 68 million | 30 thousand | **2,278x reduction** |

**Key insight:** When joining multiple one-to-many tables, always aggregate in subqueries first. This is one of the most impactful SQL optimization patterns.

### 7.2 Indexing Recommendations

Proper indexing dramatically improves query performance on large tables. The following indexes are recommended for this project:

```sql
-- Entity table indexes for filtering and grouping
CREATE INDEX IF NOT EXISTS idx_extracted_names_name 
    ON extracted_names(name_string);
CREATE INDEX IF NOT EXISTS idx_extracted_locations_location 
    ON extracted_locations(location_string);
CREATE INDEX IF NOT EXISTS idx_extracted_dates_datetime 
    ON extracted_dates(date_datetime);

-- File catalog indexes
CREATE INDEX IF NOT EXISTS idx_file_catalog_type 
    ON file_catalog(file_type);

-- Spelling analysis indexes
CREATE INDEX IF NOT EXISTS idx_spelling_issues_word 
    ON spelling_issues(word);
CREATE INDEX IF NOT EXISTS idx_spelling_issues_confidence 
    ON spelling_issues(correction_confidence DESC);

-- TDM indexes for fast term lookups
CREATE INDEX IF NOT EXISTS idx_noun_vocabulary_df 
    ON noun_tdm_vocabulary(document_frequency DESC);
CREATE INDEX IF NOT EXISTS idx_noun_documents_path 
    ON noun_tdm_documents(file_path);
```

**When to add indexes:**
- Columns frequently used in WHERE clauses
- Columns used in JOIN conditions
- Columns used in ORDER BY (especially with LIMIT)
- Columns used in GROUP BY

**Trade-off:** Indexes speed up reads but slow down writes. For this project (read-heavy analysis), liberal indexing is appropriate.

### 7.3 View Materialization

For expensive views with relatively stable data, **materialized views** store computed results physically, dramatically speeding up repeated queries.

```sql
-- Create a materialized view (computes and stores results)
CREATE MATERIALIZED VIEW mv_person_cooccurrence AS
SELECT * FROM v_person_cooccurrence;

-- Query the materialized view (instant, like a table)
SELECT * FROM mv_person_cooccurrence 
WHERE person_1 = 'Jeffrey Epstein' 
ORDER BY shared_documents DESC;

-- Refresh when underlying data changes
REFRESH MATERIALIZED VIEW mv_person_cooccurrence;

-- Refresh concurrently (allows reads during refresh)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_person_cooccurrence;
```

**Good candidates for materialization:**
- `v_person_cooccurrence` — O(n²) comparison of all name pairs
- `v_corrected_text` — Applies corrections to every document
- Any view taking more than a few seconds to query

**Not recommended for materialization:**
- Views over frequently-changing data
- Simple views that are already fast

---

## 8. Maintenance & Troubleshooting

This section covers operational tasks for maintaining the database and resolving common issues.

### 8.1 Backup Commands

Regular backups protect against data loss and enable recovery from mistakes. Different data has different backup priorities:

**Back up TDM data (computationally expensive to recreate):**
```bash
# Creates a timestamped SQL dump of all TDM tables
pg_dump -d postgres \
    -t noun_tdm_vocabulary -t noun_tdm_documents -t noun_tdm_counts -t noun_tdm_metadata \
    -t verb_tdm_vocabulary -t verb_tdm_documents -t verb_tdm_counts -t verb_tdm_metadata \
    > tdm_backup_$(date +%Y%m%d).sql
```

**Back up manual entity aliases (human knowledge, irreplaceable):**
```bash
# Exports only manually-curated aliases to CSV
psql -d postgres -c "COPY (SELECT * FROM entity_aliases WHERE disambiguation_method = 'manual') TO STDOUT WITH CSV HEADER" > entity_aliases_manual_backup.csv
```

### 8.2 Clear TDM Data

Sometimes you need to rebuild the TDM from scratch (e.g., after changing tokenization rules):

```sql
-- Clear noun TDM (must delete in dependency order)
DELETE FROM noun_tdm_counts;      -- First: depends on vocab and docs
DELETE FROM noun_tdm_documents;   -- Second
DELETE FROM noun_tdm_vocabulary;  -- Third
DELETE FROM noun_tdm_metadata WHERE key LIKE 'noun_tdm_%';
```

### 8.3 Data Integrity Checks

Periodically verify data integrity, especially after script errors:

```sql
-- Check for NULL critical fields (should return 0)
SELECT COUNT(*) FROM file_catalog WHERE path IS NULL;
SELECT COUNT(*) FROM file_catalog WHERE file_name IS NULL;

-- Check for duplicate paths (should return no rows)
SELECT path, COUNT(*) FROM file_catalog GROUP BY path HAVING COUNT(*) > 1;

-- Find orphaned records (entities without parent files)
SELECT etc.file_path FROM extracted_text_content etc
LEFT JOIN file_catalog fc ON etc.file_path = fc.path
WHERE fc.path IS NULL;
```

### 8.4 Common Issues

**Issue: "Table does not exist"**

Tables are created on-demand by their respective scripts. Run the appropriate script:
```bash
python3 scripts/disambiguate_entities.py --stats  # Creates entity tables
python3 scripts/analyze_spelling.py --help        # Creates spelling_issues
python3 scripts/create_views.py                   # Creates all views
```

**Issue: Foreign key violations when deleting**

Use CASCADE when truncating tables with dependencies:
```sql
TRUNCATE TABLE entity_network_entities CASCADE;
```

**Issue: Names not being canonicalized**

Check aliases exist and recreate the function:
```sql
SELECT * FROM entity_aliases WHERE canonical_name = 'Jeffrey Epstein';
```
```bash
python3 scripts/disambiguate_entities.py --create-function
```

### 8.5 Scripts Using db_utils

All database scripts use the shared [db_utils.py](scripts/db_utils.py) module:

**Scripts with database operations:**
- [analyze_spelling.py](scripts/analyze_spelling.py) — Spelling/OCR analysis
- [build_entity_network.py](scripts/build_entity_network.py) — Entity relationship graph from co-occurrences
- [load_sourced_entity_network.py](scripts/load_sourced_entity_network.py) — Curated entity data with citations
- [entity_network_sources.py](scripts/entity_network_sources.py) — Source citation management
- [compute_entity_network_stats.py](scripts/compute_entity_network_stats.py) — Centrality and community detection
- [build_document_similarity_network.py](scripts/build_document_similarity_network.py) — TF-IDF similarity network
- [build_noun_tdm_postgres.py](scripts/build_noun_tdm_postgres.py) — Noun TDM builder
- [build_verb_tdm_postgres.py](scripts/build_verb_tdm_postgres.py) — Verb TDM builder
- [catalog_to_postgres.py](scripts/catalog_to_postgres.py) — File cataloging with NER
- [create_views.py](scripts/create_views.py) — Analytical views
- [disambiguate_entities.py](scripts/disambiguate_entities.py) — Entity canonicalization
- [generate_statistics_report.py](scripts/generate_statistics_report.py) — Statistics reports
- [load_extracted_text.py](scripts/load_extracted_text.py) — Text content loading
- [pdf_metadata_to_postgres.py](scripts/pdf_metadata_to_postgres.py) — PDF metadata extraction
- [reset_tables.py](scripts/reset_tables.py) — Table management utility
- [verify_database.py](scripts/verify_database.py) — Database verification utility

**Configuration modules (no database operations):**
- [config.py](scripts/config.py) — Shared configuration constants
- [db_utils.py](scripts/db_utils.py) — Database utility functions

### 8.6 Network Visualization Server

The interactive visualization server is located at `scripts/network-viz/`:

```bash
cd scripts/network-viz
npm install
npm start  # Runs on http://localhost:3000
```

**Server Components:**
- [server.js](scripts/network-viz/server.js) — Express.js API server with 7 REST endpoints
- [public/index.html](scripts/network-viz/public/index.html) — D3.js force-directed visualization

**API Endpoints:**
| Endpoint | Description |
|----------|-------------|
| `GET /api/network` | Document similarity network at threshold |
| `GET /api/thresholds` | Precomputed threshold statistics with persistent homology |
| `GET /api/document/:docId` | Document details with entities and neighbors |
| `GET /api/entity-overlay/:docId` | Entity overlay data for focused documents |
| `GET /api/entity-network` | Complete entity relationship graph with sources |
| `GET /api/temporal-periods` | Available date filtering periods |
| `GET /api/documents-by-period/:periodId` | Documents in a specific time period |

See [API_README.md](API_README.md) for complete endpoint documentation.

---

## Appendix: Quick Reference

This appendix provides a condensed reference for common database operations. For detailed explanations, see the corresponding sections above.

### Connection

**Python (psycopg):**
```python
import psycopg
from config import DEFAULT_DSN

# Basic connection using config
conn = psycopg.connect(DEFAULT_DSN)

# With context manager (recommended)
from db_utils import get_db_connection

with get_db_connection(DEFAULT_DSN) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM file_catalog LIMIT 10")
        rows = cur.fetchall()
```

**Command line (psql):**
```bash
psql -d postgres    # Connect to database
\dt                 # List tables
\dv                 # List views
\df                 # List functions
\d+ table_name      # Describe table with details
```

### Tables (35 total)

| Table | Primary Key | Purpose | Typical Rows |
|-------|-------------|---------|--------------|
| `file_catalog` | `path` | Central file registry | ~30K |
| `extracted_text_content` | `file_path` | Full text storage | ~15K |
| `pdf_metadata` | `path` | PDF document properties | ~15K |
| `extracted_names` | `(file_path, name_string)` | Person entity mentions | ~45K |
| `extracted_locations` | `(file_path, location_string)` | Location entity mentions | ~32K |
| `extracted_dates` | `(file_path, date_string)` | Date entity mentions | ~62K |
| `entity_aliases` | `alias_id` | Name variant mappings | ~282 |
| `entity_exclusions` | `exclusion_id` | Excluded entities (artifacts, orgs) | ~37 |
| `joint_name_mappings` | `mapping_id` | Compound name splits | ~10 |
| `name_disambiguation_queue` | `queue_id` | Pending alias reviews | ~66K |
| `entity_network_entities` | `entity_id` | Curated entity nodes | ~142 |
| `entity_network_relationships` | `relationship_id` | Sourced relationship edges | ~185 |
| `entity_network_mentions` | `mention_id` | Document provenance | ~7K |
| `entity_network_sources` | `source_id` | Bibliographic citations | ~89 |
| `entity_network_relationship_sources` | `(relationship_id, source_id)` | Relationship-source links | ~200 |
| `entity_network_entity_sources` | `(entity_id, source_id)` | Entity description sources | ~100 |
| `entity_network_centrality` | `entity_id` | Precomputed metrics | ~142 |
| `entity_network_communities` | `community_id` | Community assignments | ~142 |
| `document_similarity_pairs` | `pair_id` | TF-IDF similarity scores | ~50K |
| `document_similarity_persistence` | `feature_id` | Persistent homology features | ~1K |
| `document_similarity_metadata` | `key` | Processing parameters | ~10 |
| `document_similarity_betti_numbers` | `threshold_id` | Topological invariants | ~50 |
| `document_similarity_centrality` | `centrality_id` | Document centrality metrics | ~15K |
| `document_similarity_communities` | `community_id` | Document clustering | ~15K |
| `document_similarity_community_labels` | `label_id` | Community labels/metadata | ~20 |
| `document_similarity_bridge_documents` | `bridge_id` | Bridge document identification | ~100 |
| `noun_tdm_vocabulary` | `term_id` | Noun dictionary | ~24K |
| `noun_tdm_documents` | `doc_id` | Processed doc registry | ~15K |
| `noun_tdm_counts` | `(doc_id, term_id)` | Noun frequencies (sparse) | ~712K |
| `noun_tdm_metadata` | `key` | TDM build info | ~4 |
| `verb_tdm_vocabulary` | `term_id` | Verb dictionary | ~4K |
| `verb_tdm_documents` | `doc_id` | Processed doc registry | ~15K |
| `verb_tdm_counts` | `(doc_id, term_id)` | Verb frequencies (sparse) | ~253K |
| `verb_tdm_metadata` | `key` | TDM build info | ~4 |
| `spelling_issues` | `(word, file_path, occurrence_number)` | OCR/spelling errors | ~612 |

### Views (14 total)

| View | Purpose | Performance Notes |
|------|---------|-------------------|
| `entity_mentions_consolidated` | Unified entity counts with aliases | Fast |
| `v_corpus_summary` | Overall corpus statistics | Fast (single aggregation) |
| `v_document_quality` | Document quality metrics | Medium |
| `v_document_entities` | Entity counts per document | **Optimized** (was slow) |
| `v_document_timeline` | Documents organized by date | Medium |
| `v_entity_mentions` | Canonicalized entity counts | Fast (filters exclusions) |
| `v_person_cooccurrence` | Who appears with whom | **Heavy** (consider materializing) |
| `v_location_summary` | Location mention frequencies | Fast |
| `v_ocr_pattern_summary` | OCR error pattern summary | Fast |
| `v_spelling_variants` | Groups similar misspellings | Medium |
| `v_foreign_language_words` | Non-English word detection | Fast |
| `v_complex_documents` | High entity-density documents | Medium |
| `v_high_priority_corrections` | Priority spelling fixes | Fast |
| `v_corrected_text` | Text with corrections applied | **Heavy** |

### Functions (2 total)

| Function | Signature | Purpose |
|----------|-----------|---------|
| `get_canonical_name` | `(TEXT) → TEXT` | Maps name variants to canonical forms |
| `apply_text_corrections` | `(TEXT, JSONB) → TEXT` | Applies spelling corrections to text |

### Common Queries

**Find documents by person:**
```sql
SELECT DISTINCT file_path 
FROM extracted_names 
WHERE get_canonical_name(name_string) = 'Jeffrey Epstein';
```

**Full-text search:**
```sql
SELECT file_path, ts_rank(to_tsvector('english', raw_text), query) AS rank
FROM extracted_text_content, plainto_tsquery('english', 'search terms') AS query
WHERE to_tsvector('english', raw_text) @@ query
ORDER BY rank DESC LIMIT 10;
```

**Entity co-occurrence:**
```sql
SELECT * FROM v_person_cooccurrence 
WHERE person_1 = 'Jeffrey Epstein' 
ORDER BY shared_documents DESC LIMIT 20;
```

**Get sourced entity relationships:**
```sql
SELECT 
    e1.entity_name AS source_entity,
    r.relationship_type,
    e2.entity_name AS target_entity,
    s.citation_chicago AS source
FROM entity_network_relationships r
JOIN entity_network_entities e1 ON r.source_entity_id = e1.entity_id
JOIN entity_network_entities e2 ON r.target_entity_id = e2.entity_id
LEFT JOIN entity_network_relationship_sources rs ON r.relationship_id = rs.relationship_id
LEFT JOIN entity_network_sources s ON rs.source_id = s.source_id
WHERE e1.entity_name = 'Jeffrey Epstein'
ORDER BY r.relationship_type;
```

---

*Last Updated: January 2026*
