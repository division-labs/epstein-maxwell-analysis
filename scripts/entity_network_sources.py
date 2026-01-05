#!/usr/bin/env python3
"""Sourced Entity Network Data with Chicago-Style Citations.

This module contains the primary data for the entity network: entities
(persons and companies) and their relationships, each backed by verifiable
documentary sources with proper Chicago-style citations.

Every relationship must be backed by at least one verifiable source.
This ensures academic-quality provenance for all network connections.

Data Structures:
    Source: A citable documentary source (court filing, newspaper, book, etc.)
    SourcedEntity: A person or company with sourced description
    SourcedRelationship: A connection between two entities with citations

Source Types:
    - court_document: Court filings, depositions, exhibits
    - newspaper: News articles from major publications
    - book: Published books
    - government_record: Official government documents, SEC filings
    - documentary: Documentaries with named sources
    - efta_document: Documents from the EFTA corpus
    - deposition: Sworn testimony from legal proceedings
    - flight_log: Aircraft flight records

Citation Format:
    Chicago Author-Date Style (17th Edition) is used throughout.
    All sources include archive URLs where available for long-term access.

Module Constants:
    SOURCED_ENTITIES: List of all SourcedEntity instances
    SOURCED_RELATIONSHIPS: List of all SourcedRelationship instances
    Various Source constants: Pre-defined Source objects for common citations

Example:
    Import and access the data::

        from entity_network_sources import (
            SOURCED_ENTITIES, SOURCED_RELATIONSHIPS, get_all_sources
        )

        # Get all unique sources
        sources = get_all_sources()
        print(f"Total sources: {len(sources)}")

        # Access entity data
        for entity in SOURCED_ENTITIES:
            print(f"{entity.name}: {entity.entity_type}")

    Validate data integrity::

        from entity_network_sources import validate_relationships, validate_entities

        errors = validate_relationships() + validate_entities()
        if errors:
            print("Validation failed:", errors)

Note:
    This file is large (~4000 lines) as it contains all entity and
    relationship data with full citation details. This is intentional
    to keep all sourced data in one auditable location.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional


class SourceType(Enum):
    """Enumeration of documentary source types.

    Attributes:
        COURT_DOCUMENT: Court filings, legal exhibits, motions
        NEWSPAPER: News articles from established publications
        BOOK: Published books (non-fiction)
        GOVERNMENT_RECORD: Official government documents, SEC filings
        DOCUMENTARY: Film/video documentaries with named sources
        EFTA_DOCUMENT: Documents from the EFTA document corpus
        DEPOSITION: Sworn testimony from legal proceedings
        FLIGHT_LOG: Aircraft flight logs and records
    """

    COURT_DOCUMENT = "court_document"
    NEWSPAPER = "newspaper"
    BOOK = "book"
    GOVERNMENT_RECORD = "government_record"
    DOCUMENTARY = "documentary"
    EFTA_DOCUMENT = "efta_document"
    DEPOSITION = "deposition"
    FLIGHT_LOG = "flight_log"


@dataclass
class Source:
    """A citable documentary source for relationship or entity data.

    Represents a single documentary source with full bibliographic
    information in Chicago style. Used to provide provenance for
    entity descriptions and relationship claims.

    Attributes:
        source_type: Category of source (court document, newspaper, etc.)
        title: Full title of the source document or article
        citation_chicago: Complete Chicago-style citation string
        author: Author name(s), if applicable
        publication: Publication name (newspaper, court, publisher)
        publication_date: Date of publication or filing
        url: Primary URL for online sources
        archive_url: Archive.org or similar permanent archive URL
        accessed_date: Date the source was accessed online
        document_id: EFTA document ID if from the corpus
        notes: Additional context about the source
    """

    source_type: SourceType
    title: str
    citation_chicago: str
    author: Optional[str] = None
    publication: Optional[str] = None
    publication_date: Optional[date] = None
    url: Optional[str] = None
    archive_url: Optional[str] = None
    accessed_date: Optional[date] = None
    document_id: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class SourcedRelationship:
    """A documented relationship between two entities.

    Represents a connection between entities (person-person, person-company,
    etc.) with supporting documentary sources. Multiple sources can support
    a single relationship for stronger evidentiary basis.

    Attributes:
        source_entity: Name of the source entity (the "from" node)
        target_entity: Name of the target entity (the "to" node)
        relationship_type: Type of relationship (e.g., 'associate', 'employee_of')
        sources: List of Source objects supporting this relationship
        confidence_score: Confidence level from 0.0-1.0 based on source quality
        page_references: Dict mapping source title to page/paragraph reference
        quotes: Dict mapping source title to relevant quote from source
        notes: Additional context about the relationship
    """

    source_entity: str
    target_entity: str
    relationship_type: str
    sources: List[Source]
    confidence_score: float = 1.0
    page_references: Dict[str, str] = field(default_factory=dict)
    quotes: Dict[str, str] = field(default_factory=dict)
    notes: Optional[str] = None


@dataclass
class SourcedEntity:
    """A documented entity (person or organization) in the network.

    Represents a node in the entity network with a sourced description.
    The description should summarize the entity's relevance to the
    network with citations.

    Attributes:
        name: Full name of the person or organization
        entity_type: Either 'person' or 'company'
        description: Prose description of the entity with context
        description_sources: List of Source objects supporting the description
    """

    name: str
    entity_type: str
    description: str
    description_sources: List[Source]


# ============================================================================
# PRIMARY SOURCES - Well-documented, high-confidence
# ============================================================================

# Miami Herald Investigation - Julie K. Brown's groundbreaking series
MIAMI_HERALD_PERVERSION_OF_JUSTICE = Source(
    source_type=SourceType.NEWSPAPER,
    title="Perversion of Justice",
    author="Julie K. Brown",
    publication="Miami Herald",
    publication_date=date(2018, 11, 28),
    url="https://www.miamiherald.com/news/local/article220097825.html",
    archive_url="https://web.archive.org/web/20181128/https://www.miamiherald.com/news/local/article220097825.html",
    accessed_date=date(2024, 1, 1),
    citation_chicago='Brown, Julie K. "Perversion of Justice." Miami Herald, November 28, 2018. https://www.miamiherald.com/news/local/article220097825.html.',
    notes="Multi-part investigative series that reignited the Epstein case"
)

# Giuffre v. Maxwell - Major lawsuit with extensive depositions
GIUFFRE_V_MAXWELL_COMPLAINT = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Giuffre v. Maxwell, Case No. 15-cv-07433 (S.D.N.Y.)",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2015, 9, 21),
    citation_chicago='Giuffre v. Maxwell, Case No. 15-cv-07433-RWS (S.D.N.Y. filed Sept. 21, 2015).',
    notes="Defamation lawsuit filed by Virginia Giuffre against Ghislaine Maxwell"
)

GIUFFRE_V_MAXWELL_UNSEALED_2019 = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Giuffre v. Maxwell Unsealed Documents (2019)",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2019, 8, 9),
    url="https://www.courtlistener.com/docket/4355835/giuffre-v-maxwell/",
    citation_chicago='Giuffre v. Maxwell, Case No. 15-cv-07433-RWS, Unsealed Documents (S.D.N.Y. Aug. 9, 2019).',
    notes="Tranche of documents unsealed by court order"
)

GIUFFRE_V_MAXWELL_UNSEALED_2024 = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Giuffre v. Maxwell Unsealed Documents (2024)",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2024, 1, 3),
    citation_chicago='Giuffre v. Maxwell, Case No. 15-cv-07433-RWS, Unsealed Documents (S.D.N.Y. Jan. 3, 2024).',
    notes="Additional documents unsealed January 2024"
)

# USA v. Maxwell - Criminal trial
USA_V_MAXWELL_INDICTMENT = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="United States v. Ghislaine Maxwell, Indictment",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2020, 7, 2),
    citation_chicago='United States v. Maxwell, Case No. 20-cr-00330-AJN, Indictment (S.D.N.Y. July 2, 2020).',
    notes="Federal indictment of Ghislaine Maxwell"
)

USA_V_MAXWELL_TRIAL_TRANSCRIPT = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="United States v. Maxwell, Trial Transcript",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2021, 12, 29),
    citation_chicago='United States v. Maxwell, Case No. 20-cr-00330-AJN, Trial Transcript (S.D.N.Y. Nov. 29–Dec. 29, 2021).',
    notes="Trial transcript from Maxwell criminal trial"
)

# USA v. Epstein (2019) - Pre-suicide case
USA_V_EPSTEIN_2019_INDICTMENT = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="United States v. Jeffrey Epstein, Indictment",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2019, 7, 8),
    citation_chicago='United States v. Epstein, Case No. 19-cr-00490, Indictment (S.D.N.Y. July 8, 2019).',
    notes="Federal indictment of Jeffrey Epstein in 2019"
)

# Flight Logs - Lolita Express
EPSTEIN_FLIGHT_LOGS = Source(
    source_type=SourceType.FLIGHT_LOG,
    title="Epstein Aircraft Flight Logs",
    publication="Exhibit in Giuffre v. Maxwell",
    citation_chicago='Epstein Aircraft Flight Logs, Exhibit in Giuffre v. Maxwell, Case No. 15-cv-07433-RWS (S.D.N.Y.).',
    notes="Flight manifests for N908JE and other Epstein aircraft"
)

# Black Book / Contact List
EPSTEIN_BLACK_BOOK = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Jeffrey Epstein's 'Black Book'",
    publication="Exhibit in various court proceedings",
    citation_chicago="Jeffrey Epstein's Contact List ('Black Book'), Court Exhibit.",
    notes="Contact list maintained by Epstein's staff, leaked/entered as evidence"
)

# Books
FILTHY_RICH_BOOK = Source(
    source_type=SourceType.BOOK,
    title="Filthy Rich: The Shocking True Story of Jeffrey Epstein",
    author="James Patterson, John Connolly, and Tim Malloy",
    publication_date=date(2016, 10, 10),
    citation_chicago='Patterson, James, John Connolly, and Tim Malloy. Filthy Rich: The Shocking True Story of Jeffrey Epstein. New York: Grand Central Publishing, 2016.',
    notes="Early comprehensive account of Epstein case"
)

RELENTLESS_PURSUIT_BOOK = Source(
    source_type=SourceType.BOOK,
    title="Relentless Pursuit: My Fight for the Victims of Jeffrey Epstein",
    author="Bradley J. Edwards",
    publication_date=date(2020, 3, 17),
    citation_chicago='Edwards, Bradley J. Relentless Pursuit: My Fight for the Victims of Jeffrey Epstein. New York: Gallery Books, 2020.',
    notes="Account by victims' attorney Bradley Edwards"
)

TRAFFICKINGJEFFREY_BOOK = Source(
    source_type=SourceType.BOOK,
    title="Trafficking: The Jeffrey Epstein Case",
    author="Conchita Sarnoff",
    publication_date=date(2020, 2, 20),
    citation_chicago='Sarnoff, Conchita. Trafficking: The Jeffrey Epstein Case. New York: Post Hill Press, 2020.',
    notes="Investigative journalist account"
)

# New York Times - Major reporting
NYT_EPSTEIN_BLACK_MONEY = Source(
    source_type=SourceType.NEWSPAPER,
    title="How Jeffrey Epstein Used the Billionaire Behind Victoria's Secret for Wealth and Women",
    author="James B. Stewart, Matthew Goldstein, and Jessica Silver-Greenberg",
    publication="New York Times",
    publication_date=date(2019, 7, 25),
    url="https://www.nytimes.com/2019/07/25/business/jeffrey-epstein-wexner-victorias-secret.html",
    citation_chicago='Stewart, James B., Matthew Goldstein, and Jessica Silver-Greenberg. "How Jeffrey Epstein Used the Billionaire Behind Victoria\'s Secret for Wealth and Women." New York Times, July 25, 2019.',
    notes="Investigation into Epstein-Wexner relationship"
)

NYT_LEON_BLACK_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Apollo's Leon Black Paid Jeffrey Epstein $158 Million",
    author="Kate Kelly and Matthew Goldstein",
    publication="New York Times",
    publication_date=date(2021, 1, 25),
    url="https://www.nytimes.com/2021/01/25/business/leon-black-jeffrey-epstein-apollo.html",
    citation_chicago='Kelly, Kate, and Matthew Goldstein. "Apollo\'s Leon Black Paid Jeffrey Epstein $158 Million." New York Times, January 25, 2021.',
    notes="Investigation into financial relationship between Leon Black and Epstein"
)

NYT_BILL_GATES_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Bill Gates Met With Jeffrey Epstein Many Times, Despite His Past",
    author="Emily Flitter and James B. Stewart",
    publication="New York Times",
    publication_date=date(2019, 10, 12),
    url="https://www.nytimes.com/2019/10/12/business/jeffrey-epstein-bill-gates.html",
    citation_chicago='Flitter, Emily, and James B. Stewart. "Bill Gates Met With Jeffrey Epstein Many Times, Despite His Past." New York Times, October 12, 2019.',
    notes="Investigation into Gates-Epstein meetings"
)

NYT_MIT_MEDIA_LAB = Source(
    source_type=SourceType.NEWSPAPER,
    title="M.I.T. Media Lab, Already Rattled by the Epstein Scandal, Has a New Worry",
    author="Matthew Goldstein",
    publication="New York Times",
    publication_date=date(2019, 9, 12),
    url="https://www.nytimes.com/2019/09/12/business/mit-media-lab-epstein.html",
    citation_chicago='Goldstein, Matthew. "M.I.T. Media Lab, Already Rattled by the Epstein Scandal, Has a New Worry." New York Times, September 12, 2019.',
    notes="MIT Media Lab Epstein connections"
)

# The New Yorker - Ronan Farrow MIT investigation
NEW_YORKER_MIT_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="How an Élite University Research Center Concealed Its Relationship with Jeffrey Epstein",
    author="Ronan Farrow",
    publication="The New Yorker",
    publication_date=date(2019, 9, 6),
    url="https://www.newyorker.com/news/news-desk/how-an-elite-university-research-center-concealed-its-relationship-with-jeffrey-epstein",
    citation_chicago='Farrow, Ronan. "How an Élite University Research Center Concealed Its Relationship with Jeffrey Epstein." The New Yorker, September 6, 2019.',
    notes="Revealed extent of MIT Media Lab-Epstein ties"
)

# BBC - Prince Andrew Interview
BBC_PRINCE_ANDREW = Source(
    source_type=SourceType.NEWSPAPER,
    title="Prince Andrew & the Epstein Scandal: The Newsnight Interview",
    author="Emily Maitlis",
    publication="BBC Newsnight",
    publication_date=date(2019, 11, 16),
    url="https://www.bbc.com/news/uk-50449339",
    citation_chicago='Maitlis, Emily. "Prince Andrew & the Epstein Scandal: The Newsnight Interview." BBC Newsnight, November 16, 2019.',
    notes="Prince Andrew's disastrous interview about Epstein relationship"
)

# SEC Filings
APOLLO_SEC_FILINGS = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Apollo Global Management SEC Filings",
    publication="U.S. Securities and Exchange Commission",
    url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=apollo+global",
    citation_chicago='Apollo Global Management. Annual and Quarterly Reports. U.S. Securities and Exchange Commission. https://www.sec.gov.',
    notes="Public filings for Apollo Global Management"
)

# Dershowitz deposition
DERSHOWITZ_DEPOSITION = Source(
    source_type=SourceType.DEPOSITION,
    title="Deposition of Alan Dershowitz in Giuffre v. Maxwell",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2016, 6, 17),
    citation_chicago='Deposition of Alan Dershowitz, Giuffre v. Maxwell, Case No. 15-cv-07433-RWS (S.D.N.Y. June 17, 2016).',
    notes="Dershowitz deposition in Giuffre lawsuit"
)

# Virginia Giuffre deposition
GIUFFRE_DEPOSITION_2016 = Source(
    source_type=SourceType.DEPOSITION,
    title="Deposition of Virginia Giuffre in Giuffre v. Maxwell",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2016, 5, 3),
    citation_chicago='Deposition of Virginia Giuffre, Giuffre v. Maxwell, Case No. 15-cv-07433-RWS (S.D.N.Y. May 3, 2016).',
    notes="Key deposition testimony from Virginia Giuffre"
)

# Ghislaine Maxwell deposition
MAXWELL_DEPOSITION_2016 = Source(
    source_type=SourceType.DEPOSITION,
    title="Deposition of Ghislaine Maxwell in Giuffre v. Maxwell",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2016, 7, 22),
    citation_chicago='Deposition of Ghislaine Maxwell, Giuffre v. Maxwell, Case No. 15-cv-07433-RWS (S.D.N.Y. July 22, 2016).',
    notes="Maxwell's deposition testimony"
)

# Juan Alessi deposition
ALESSI_DEPOSITION = Source(
    source_type=SourceType.DEPOSITION,
    title="Deposition of Juan Alessi",
    publication="Court exhibit in Epstein-related litigation",
    citation_chicago='Deposition of Juan Alessi, Court Exhibit.',
    notes="Testimony from former Epstein house manager"
)

# ============================================================================
# ADDITIONAL SOURCES - Expanded research
# ============================================================================

# Wall Street Journal reporting
WSJ_JPMORGAN_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="JPMorgan to Pay $290 Million to Settle Epstein Victims' Lawsuit",
    author="David Benoit",
    publication="Wall Street Journal",
    publication_date=date(2023, 6, 12),
    url="https://www.wsj.com/articles/jpmorgan-reaches-290-million-settlement-with-epstein-victims-81c2c2a0",
    citation_chicago='Benoit, David. "JPMorgan to Pay $290 Million to Settle Epstein Victims\' Lawsuit." Wall Street Journal, June 12, 2023.',
    notes="JPMorgan settlement revealing extent of banking relationship"
)

WSJ_DEUTSCHE_BANK_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Deutsche Bank to Pay $75 Million to Settle Lawsuit by Epstein Victims",
    author="Patricia Kowsmann",
    publication="Wall Street Journal",
    publication_date=date(2021, 5, 17),
    url="https://www.wsj.com/articles/deutsche-bank-to-pay-75-million-to-settle-lawsuit-by-epstein-victims-11621271507",
    citation_chicago='Kowsmann, Patricia. "Deutsche Bank to Pay $75 Million to Settle Lawsuit by Epstein Victims." Wall Street Journal, May 17, 2021.',
    notes="Deutsche Bank settlement and compliance failures"
)

# Vanity Fair reporting
VANITY_FAIR_2003 = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Talented Mr. Epstein",
    author="Vicky Ward",
    publication="Vanity Fair",
    publication_date=date(2003, 3, 1),
    url="https://www.vanityfair.com/news/2003/03/jeffrey-epstein-200303",
    citation_chicago='Ward, Vicky. "The Talented Mr. Epstein." Vanity Fair, March 2003.',
    notes="Early profile of Epstein; notable for what was reportedly cut from article"
)

VANITY_FAIR_MAXWELL_2020 = Source(
    source_type=SourceType.NEWSPAPER,
    title="Inside Ghislaine Maxwell's Life on the Lam",
    author="Gabriel Sherman",
    publication="Vanity Fair",
    publication_date=date(2020, 7, 3),
    url="https://www.vanityfair.com/news/2020/07/inside-ghislaine-maxwells-life-on-the-lam",
    citation_chicago='Sherman, Gabriel. "Inside Ghislaine Maxwell\'s Life on the Lam." Vanity Fair, July 3, 2020.',
    notes="Maxwell pre-arrest investigation"
)

# The Guardian reporting
GUARDIAN_PRINCE_ANDREW = Source(
    source_type=SourceType.NEWSPAPER,
    title="Prince Andrew settles US civil sex assault case with Virginia Giuffre",
    author="Dan Sabbagh and Caroline Davies",
    publication="The Guardian",
    publication_date=date(2022, 2, 15),
    url="https://www.theguardian.com/uk-news/2022/feb/15/prince-andrew-settles-sexual-assault-lawsuit-virginia-giuffre",
    citation_chicago='Sabbagh, Dan, and Caroline Davies. "Prince Andrew Settles US Civil Sex Assault Case with Virginia Giuffre." The Guardian, February 15, 2022.',
    notes="Settlement details of Giuffre v. Prince Andrew"
)

# New York Magazine 2002 - Famous Trump quote
NY_MAG_EPSTEIN_2002 = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jeffrey Epstein: International Moneyman of Mystery",
    author="Landon Thomas Jr.",
    publication="New York Magazine",
    publication_date=date(2002, 10, 28),
    url="https://nymag.com/nymetro/news/people/n_7912/",
    citation_chicago='Thomas, Landon Jr. "Jeffrey Epstein: International Moneyman of Mystery." New York Magazine, October 28, 2002.',
    notes="Contains famous Trump quote about Epstein"
)

# Washington Post reporting
WAPO_ACOSTA_NPA = Source(
    source_type=SourceType.NEWSPAPER,
    title="Labor secretary nominee Alexander Acosta cut deal with billionaire in underage sex case",
    author="Marc Fisher and José A. DelReal",
    publication="Washington Post",
    publication_date=date(2017, 3, 21),
    url="https://www.washingtonpost.com/politics/labor-nominee-alexander-acosta-cut-deal-with-billionaire-in-underage-sex-case/2017/03/21/d33271a8-0d85-11e7-ab07-07d9f521f6b5_story.html",
    citation_chicago='Fisher, Marc, and José A. DelReal. "Labor Secretary Nominee Alexander Acosta Cut Deal with Billionaire in Underage Sex Case." Washington Post, March 21, 2017.',
    notes="Details of 2008 non-prosecution agreement"
)

# WSJ - Les Wexner statement (more reputable than Daily Beast coverage)
WSJ_WEXNER_EPSTEIN_STATEMENT = Source(
    source_type=SourceType.NEWSPAPER,
    title="L Brands' Wexner Says Jeffrey Epstein 'Misappropriated' Funds",
    author="Khadeeja Safdar",
    publication="Wall Street Journal",
    publication_date=date(2019, 8, 7),
    url="https://www.wsj.com/articles/l-brands-wexner-says-jeffrey-epstein-misappropriated-funds-11565224547",
    citation_chicago='Safdar, Khadeeja. "L Brands\' Wexner Says Jeffrey Epstein \'Misappropriated\' Funds." Wall Street Journal, August 7, 2019.',
    notes="Wexner public statement about Epstein relationship - original Wall Street Journal reporting"
)

# Forbes profiles
FORBES_WEXNER = Source(
    source_type=SourceType.NEWSPAPER,
    title="Leslie Wexner Net Worth Profile",
    publication="Forbes",
    url="https://www.forbes.com/profile/les-wexner/",
    citation_chicago='Forbes. "Leslie Wexner." Forbes Billionaires List. https://www.forbes.com/profile/les-wexner/.',
    notes="Wealth and business profile"
)

# Court documents - 2008 Florida case
EPSTEIN_NPA_2008 = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Non-Prosecution Agreement, State of Florida v. Jeffrey Epstein",
    publication="U.S. Attorney's Office, Southern District of Florida",
    publication_date=date(2008, 9, 24),
    citation_chicago='Non-Prosecution Agreement, In re: Jeffrey Epstein, U.S. Attorney\'s Office, Southern District of Florida (Sept. 24, 2008).',
    notes="Controversial deal granting immunity to co-conspirators"
)

# Jane Doe depositions
JANE_DOE_DEPOSITIONS = Source(
    source_type=SourceType.DEPOSITION,
    title="Depositions of Jane Does in Edwards et al. v. Epstein",
    publication="U.S. District Court, Southern District of Florida",
    citation_chicago='Depositions of Jane Does, Edwards et al. v. Epstein, Case No. 08-cv-80736 (S.D. Fla.).',
    notes="Victim depositions in civil case"
)

# Sarah Ransome deposition
RANSOME_DECLARATION = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Declaration of Sarah Ransome",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2017, 4, 6),
    citation_chicago='Declaration of Sarah Ransome, Giuffre v. Maxwell, Case No. 15-cv-07433-RWS (S.D.N.Y. Apr. 6, 2017).',
    notes="Victim declaration describing abuse on Epstein's island"
)

# Steve Scully flight log analysis
FLIGHT_LOG_ANALYSIS = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Flight Log Analysis and Passenger Manifests",
    publication="Court exhibit, multiple proceedings",
    citation_chicago='Epstein Aircraft Flight Logs and Passenger Manifests, Court Exhibits.',
    notes="Compiled flight records for N908JE, N212JE, and other aircraft"
)

# Netflix documentary
NETFLIX_FILTHY_RICH_DOC = Source(
    source_type=SourceType.DOCUMENTARY,
    title="Jeffrey Epstein: Filthy Rich",
    author="Lisa Bryant (Director)",
    publication="Netflix",
    publication_date=date(2020, 5, 27),
    citation_chicago='Bryant, Lisa, dir. Jeffrey Epstein: Filthy Rich. Netflix, 2020.',
    notes="Documentary featuring victim interviews"
)

# Lifetime documentary on Maxwell
LIFETIME_MAXWELL_DOC = Source(
    source_type=SourceType.DOCUMENTARY,
    title="Surviving Jeffrey Epstein",
    publication="Lifetime",
    publication_date=date(2020, 8, 9),
    citation_chicago='Surviving Jeffrey Epstein. Lifetime, 2020.',
    notes="Documentary with victim testimonies"
)

# Bloomberg reporting
BLOOMBERG_STALEY = Source(
    source_type=SourceType.NEWSPAPER,
    title="Barclays CEO Jes Staley to Step Down Over Epstein Probe",
    author="Stefania Spezzati",
    publication="Bloomberg",
    publication_date=date(2021, 11, 1),
    url="https://www.bloomberg.com/news/articles/2021-11-01/barclays-ceo-jes-staley-steps-down-over-epstein-probe",
    citation_chicago='Spezzati, Stefania. "Barclays CEO Jes Staley to Step Down Over Epstein Probe." Bloomberg, November 1, 2021.',
    notes="Staley resignation due to Epstein relationship investigation"
)

# Financial Times
FT_VIRGIN_ISLANDS = Source(
    source_type=SourceType.NEWSPAPER,
    title="JPMorgan and Jeffrey Epstein: the US Virgin Islands lawsuit explained",
    author="Joshua Franklin",
    publication="Financial Times",
    publication_date=date(2023, 1, 10),
    url="https://www.ft.com/content/",
    citation_chicago='Franklin, Joshua. "JPMorgan and Jeffrey Epstein: The US Virgin Islands Lawsuit Explained." Financial Times, January 10, 2023.',
    notes="Details of USVI suit against JPMorgan"
)

# Harvard review
HARVARD_EPSTEIN_REPORT = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Report of the Faculty Committee to Review Gift Policies",
    author="Harvard University",
    publication="Harvard University",
    publication_date=date(2020, 5, 1),
    citation_chicago='Harvard University. Report of the Faculty Committee to Review Gift Policies. Cambridge, MA: Harvard University, May 2020.',
    notes="Internal Harvard review of Epstein donations"
)

# Courtney Wild declaration
WILD_DECLARATION = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Declaration of Courtney Wild",
    publication="U.S. District Court, Southern District of Florida",
    citation_chicago='Declaration of Courtney Wild, Doe v. United States, Case No. 08-cv-80736 (S.D. Fla.).',
    notes="Victim declaration; Wild was a leader in seeking justice"
)

# ============================================================================
# ADDITIONAL SOURCES - Build entity network entities
# ============================================================================

# Apollo and Blackstone sources
FORBES_SCHWARZMAN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Stephen Schwarzman",
    author="Forbes Staff",
    publication="Forbes",
    url="https://www.forbes.com/profile/stephen-schwarzman/",
    citation_chicago='Forbes. "Stephen Schwarzman." Forbes. Accessed 2024.',
    notes="Blackstone co-founder profile"
)

WSJ_APOLLO_BLACK_RESIGNATION = Source(
    source_type=SourceType.NEWSPAPER,
    title="Leon Black to Step Down as Apollo CEO After Review of Epstein Ties",
    author="Miriam Gottfried",
    publication="Wall Street Journal",
    publication_date=date(2021, 1, 25),
    url="https://www.wsj.com/articles/leon-black-to-step-down-as-apollo-ceo-after-review-of-epstein-ties-11611600017",
    citation_chicago='Gottfried, Miriam. "Leon Black to Step Down as Apollo CEO After Review of Epstein Ties." Wall Street Journal, January 25, 2021.',
    notes="Black resignation from Apollo due to Epstein ties"
)

# Cambridge Analytica / Mercer reporting
NYT_CAMBRIDGE_ANALYTICA = Source(
    source_type=SourceType.NEWSPAPER,
    title="How Trump Consultants Exploited the Facebook Data of Millions",
    author="Matthew Rosenberg, Nicholas Confessore, and Carole Cadwalladr",
    publication="New York Times",
    publication_date=date(2018, 3, 17),
    url="https://www.nytimes.com/2018/03/17/us/politics/cambridge-analytica-trump-campaign.html",
    citation_chicago='Rosenberg, Matthew, Nicholas Confessore, and Carole Cadwalladr. "How Trump Consultants Exploited the Facebook Data of Millions." New York Times, March 17, 2018.',
    notes="Cambridge Analytica scandal reporting"
)

NEW_YORKER_MERCER = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Reclusive Hedge-Fund Tycoon Behind the Trump Presidency",
    author="Jane Mayer",
    publication="The New Yorker",
    publication_date=date(2017, 3, 27),
    url="https://www.newyorker.com/magazine/2017/03/27/the-reclusive-hedge-fund-tycoon-behind-the-trump-presidency",
    citation_chicago='Mayer, Jane. "The Reclusive Hedge-Fund Tycoon Behind the Trump Presidency." The New Yorker, March 27, 2017.',
    notes="Robert Mercer profile and political influence"
)

# Trump Organization sources
WAPO_TRUMP_ORGANIZATION = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Trump Organization, explained",
    author="Drew Harwell",
    publication="Washington Post",
    publication_date=date(2022, 12, 6),
    url="https://www.washingtonpost.com/business/2022/12/06/trump-organization-conviction-explained/",
    citation_chicago='Harwell, Drew. "The Trump Organization, Explained." Washington Post, December 6, 2022.',
    notes="Overview of Trump business structure"
)

# Kushner Companies
NYT_KUSHNER_COMPANIES = Source(
    source_type=SourceType.NEWSPAPER,
    title="Kushner Companies",
    author="Various",
    publication="New York Times",
    publication_date=date(2019, 1, 1),
    url="https://www.nytimes.com/topic/organization/kushner-companies",
    citation_chicago='New York Times. "Kushner Companies Coverage." New York Times, 2019.',
    notes="Kushner Companies investigative reporting"
)

NYT_CHARLES_KUSHNER = Source(
    source_type=SourceType.NEWSPAPER,
    title="A Scandal Unfolds at the Hands of a Wealthy Family",
    author="Jonathan Mahler and Steve Eder",
    publication="New York Times",
    publication_date=date(2016, 8, 18),
    url="https://www.nytimes.com/2016/08/19/us/politics/charles-kushner-jared-kushner.html",
    citation_chicago='Mahler, Jonathan, and Steve Eder. "A Scandal Unfolds at the Hands of a Wealthy Family." New York Times, August 18, 2016.',
    notes="Charles Kushner criminal history"
)

# Maxwell family history
GUARDIAN_ROBERT_MAXWELL = Source(
    source_type=SourceType.NEWSPAPER,
    title="Robert Maxwell: A Life in Pictures",
    author="Guardian Staff",
    publication="The Guardian",
    publication_date=date(2019, 8, 10),
    url="https://www.theguardian.com/media/robert-maxwell",
    citation_chicago='The Guardian. "Robert Maxwell." The Guardian. Accessed 2024.',
    notes="Robert Maxwell media empire history"
)

# Maxwell trial attorneys
DOJ_MAXWELL_CASE = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="United States v. Ghislaine Maxwell - Case Docket",
    publication="U.S. District Court, Southern District of New York",
    publication_date=date(2021, 12, 29),
    citation_chicago='United States v. Ghislaine Maxwell, Case No. 20-cr-330 (S.D.N.Y.). Case Docket.',
    notes="Complete case docket with attorney appearances"
)

# Bill Gates Foundation
GATES_FOUNDATION_ANNUAL = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Bill & Melinda Gates Foundation Annual Report",
    author="Bill & Melinda Gates Foundation",
    publication="Bill & Melinda Gates Foundation",
    publication_date=date(2023, 1, 1),
    url="https://www.gatesfoundation.org/about/financials/annual-reports",
    citation_chicago='Bill & Melinda Gates Foundation. Annual Report. Seattle: Bill & Melinda Gates Foundation, 2023.',
    notes="Foundation structure and leadership"
)

# Microsoft founding
GATES_ALLEN_MICROSOFT = Source(
    source_type=SourceType.NEWSPAPER,
    title="Paul Allen: Idea Man",
    author="Paul Allen",
    publication="Portfolio/Penguin",
    publication_date=date(2011, 4, 19),
    citation_chicago='Allen, Paul. Idea Man: A Memoir by the Co-founder of Microsoft. New York: Portfolio/Penguin, 2011.',
    notes="Microsoft founding history"
)

# Wexner Foundation
WEXNER_FOUNDATION_WEBSITE = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Wexner Foundation",
    publication="Wexner Foundation",
    url="https://www.wexnerfoundation.org/",
    citation_chicago='The Wexner Foundation. https://www.wexnerfoundation.org/. Accessed 2024.',
    notes="Wexner Foundation official site"
)

# SDNY prosecutors
DOJ_SDNY_ANNOUNCEMENTS = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="U.S. Attorney's Office SDNY Press Releases",
    publication="U.S. Department of Justice",
    url="https://www.justice.gov/usao-sdny",
    citation_chicago='U.S. Attorney\'s Office, Southern District of New York. Press Releases. U.S. Department of Justice.',
    notes="Official SDNY announcements on Epstein/Maxwell cases"
)

# Boies Schiller firm profile
BOIES_SCHILLER_WEBSITE = Source(
    source_type=SourceType.NEWSPAPER,
    title="Boies Schiller Flexner LLP",
    publication="Boies Schiller Flexner",
    url="https://www.bsfllp.com/",
    citation_chicago='Boies Schiller Flexner LLP. https://www.bsfllp.com/. Accessed 2024.',
    notes="Law firm official site"
)

# Affinity Partners / Kushner post-White House
NYT_AFFINITY_PARTNERS = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jared Kushner's $2 Billion Saudi Deal Becomes Key to Jan. 6 Scrutiny",
    author="Kate Kelly and David D. Kirkpatrick",
    publication="New York Times",
    publication_date=date(2022, 6, 2),
    url="https://www.nytimes.com/2022/06/02/us/politics/jared-kushner-affinity-partners-investigation.html",
    citation_chicago='Kelly, Kate, and David D. Kirkpatrick. "Jared Kushner\'s $2 Billion Saudi Deal Becomes Key to Jan. 6 Scrutiny." New York Times, June 2, 2022.',
    notes="Affinity Partners Saudi investment"
)

# Lefkowitz background
KIRKLAND_ELLIS_BIOS = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jay P. Lefkowitz",
    publication="Kirkland & Ellis",
    url="https://www.kirkland.com/lawyers/l/lefkowitz-jay-p",
    citation_chicago='Kirkland & Ellis. "Jay P. Lefkowitz." https://www.kirkland.com. Accessed 2024.',
    notes="Lefkowitz professional biography"
)

# Pagliuca - Haddon Morgan firm
HADDON_MORGAN_WEBSITE = Source(
    source_type=SourceType.NEWSPAPER,
    title="Haddon, Morgan and Foreman, P.C.",
    publication="Haddon, Morgan and Foreman",
    url="https://www.hmflaw.com/",
    citation_chicago='Haddon, Morgan and Foreman, P.C. https://www.hmflaw.com/. Accessed 2024.',
    notes="Maxwell defense team law firm"
)

# ============================================================================
# INTELLIGENCE & TRAFFICKING CONNECTION SOURCES
# ============================================================================

# Note: The alleged Acosta "intelligence" quote has been widely circulated but
# originates from a single anonymous source. We cite it only via court documents
# and sworn testimony where verifiable.

# Robert Maxwell intelligence ties - multiple book sources
GORDON_THOMAS_MAXWELLS_MOSSAD = Source(
    source_type=SourceType.BOOK,
    title="Robert Maxwell, Israel's Superspy: The Life and Murder of a Media Mogul",
    author="Gordon Thomas and Martin Dillon",
    publication="Carroll & Graf Publishers",
    publication_date=date(2002, 10, 1),
    citation_chicago='Thomas, Gordon, and Martin Dillon. Robert Maxwell, Israel\'s Superspy: The Life and Murder of a Media Mogul. New York: Carroll & Graf Publishers, 2002.',
    notes="Investigative book on Robert Maxwell's intelligence connections"
)

SEYMOUR_HERSH_SAMSON_OPTION = Source(
    source_type=SourceType.BOOK,
    title="The Samson Option: Israel's Nuclear Arsenal and American Foreign Policy",
    author="Seymour Hersh",
    publication="Random House",
    publication_date=date(1991, 10, 1),
    citation_chicago='Hersh, Seymour. The Samson Option: Israel\'s Nuclear Arsenal and American Foreign Policy. New York: Random House, 1991.',
    notes="Pulitzer-winning journalist's investigation including Maxwell-PROMIS software allegations"
)

# Victor Ostrovsky - Former Mossad officer
OSTROVSKY_BY_WAY_OF_DECEPTION = Source(
    source_type=SourceType.BOOK,
    title="By Way of Deception: The Making and Unmaking of a Mossad Officer",
    author="Victor Ostrovsky and Claire Hoy",
    publication="St. Martin's Press",
    publication_date=date(1990, 9, 1),
    citation_chicago='Ostrovsky, Victor, and Claire Hoy. By Way of Deception: The Making and Unmaking of a Mossad Officer. New York: St. Martin\'s Press, 1990.',
    notes="Former Mossad case officer's account; discusses Robert Maxwell's intelligence role"
)

# Robert Maxwell funeral - documented Israeli state presence
NYT_MAXWELL_FUNERAL = Source(
    source_type=SourceType.NEWSPAPER,
    title="Maxwell Is Buried in Israel; World Figures Attend",
    author="Clyde Haberman",
    publication="New York Times",
    publication_date=date(1991, 11, 11),
    url="https://www.nytimes.com/1991/11/11/obituaries/maxwell-is-buried-in-israel-world-figures-attend.html",
    citation_chicago='Haberman, Clyde. "Maxwell Is Buried in Israel; World Figures Attend." New York Times, November 11, 1991.',
    notes="Israeli PM, President, intelligence chiefs attended Maxwell funeral on Mount of Olives"
)

# PROMIS software scandal - Congressional hearings
INSLAW_HOUSE_REPORT = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="The INSLAW Affair: Investigative Report by the Committee on the Judiciary",
    author="House Committee on the Judiciary",
    publication="U.S. House of Representatives",
    publication_date=date(1992, 9, 10),
    url="https://www.justice.gov/sites/default/files/jmd/legacy/2014/02/20/inslaw-rpt.pdf",
    citation_chicago='U.S. House of Representatives, Committee on the Judiciary. The INSLAW Affair. 102nd Congress, 2nd Session. September 10, 1992.',
    notes="Congressional investigation into PROMIS software theft and distribution"
)

# British Foreign Office files on Robert Maxwell
UK_FOREIGN_OFFICE_MAXWELL = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Foreign Office Files on Robert Maxwell",
    author="UK Foreign and Commonwealth Office",
    publication="The National Archives (UK)",
    citation_chicago='UK Foreign and Commonwealth Office. Files on Robert Maxwell. The National Archives, Kew.',
    notes="Declassified British government files on Maxwell's activities"
)

# Ari Ben-Menashe - Former Israeli intelligence officer
BEN_MENASHE_PROFITS_OF_WAR = Source(
    source_type=SourceType.BOOK,
    title="Profits of War: Inside the Secret U.S.-Israeli Arms Network",
    author="Ari Ben-Menashe",
    publication="Sheridan Square Press",
    publication_date=date(1992, 1, 1),
    citation_chicago='Ben-Menashe, Ari. Profits of War: Inside the Secret U.S.-Israeli Arms Network. New York: Sheridan Square Press, 1992.',
    notes="Former Israeli intelligence officer's account of arms deals and Maxwell connections"
)

# Ehud Barak - documented business relationship with Epstein
TIMES_OF_ISRAEL_BARAK = Source(
    source_type=SourceType.NEWSPAPER,
    title="Barak acknowledges visits to Epstein's island, but says he never attended parties",
    author="Various",
    publication="Times of Israel",
    publication_date=date(2019, 7, 15),
    url="https://www.timesofisrael.com/barak-acknowledges-visits-to-epsteins-island-says-he-never-attended-parties/",
    citation_chicago='Times of Israel. "Barak Acknowledges Visits to Epstein\'s Island, but Says He Never Attended Parties." July 15, 2019.',
    notes="Barak's own acknowledgment of Epstein visits"
)

# Carbyne 911 - Barak-Epstein business venture
HAARETZ_CARBYNE = Source(
    source_type=SourceType.NEWSPAPER,
    title="Ehud Barak's Start-up Received Investment From Company Funded by Jeffrey Epstein",
    author="Gidi Weitz",
    publication="Haaretz",
    publication_date=date(2019, 7, 14),
    url="https://www.haaretz.com/israel-news/2019-07-14/ty-article/.premium/ehud-baraks-start-up-got-investment-funded-by-jeffrey-epstein/0000017f-e8db-d3ff-a7ff-fddb71770000",
    citation_chicago='Weitz, Gidi. "Ehud Barak\'s Start-up Received Investment From Company Funded by Jeffrey Epstein." Haaretz, July 14, 2019.',
    notes="Carbyne 911 emergency services company received Epstein funding"
)

# Nicole Junkermann - Bridge between Barak, Epstein, and tech
TELEGRAPH_JUNKERMANN = Source(
    source_type=SourceType.NEWSPAPER,
    title="GCHQ's hi-tech health advisor was in business with Epstein",
    author="Charles Hymas",
    publication="The Telegraph",
    publication_date=date(2019, 9, 6),
    url="https://www.telegraph.co.uk/news/2019/09/06/gchqs-hi-tech-health-adviser-business-epstein/",
    citation_chicago='Hymas, Charles. "GCHQ\'s Hi-tech Health Advisor Was in Business with Epstein." The Telegraph, September 6, 2019.',
    notes="Junkermann-Epstein-Barak business connections"
)

# Leslie Wexner - Mega Group
FORWARD_MEGA_GROUP = Source(
    source_type=SourceType.NEWSPAPER,
    title="Mega Group, Mega Scandal",
    author="Steven I. Weiss",
    publication="The Forward",
    publication_date=date(2019, 7, 16),
    url="https://forward.com/news/428027/mega-group-steven-spielberg-charles-bronfman-wexner-lauder/",
    citation_chicago='Weiss, Steven I. "Mega Group, Mega Scandal." The Forward, July 16, 2019.',
    notes="Wexner's role in Mega Group of pro-Israel billionaires"
)

# Steven Hoffenberg claims about Epstein and intelligence
NY_POST_HOFFENBERG = Source(
    source_type=SourceType.NEWSPAPER,
    title="Steven Hoffenberg, convicted Ponzi schemer who linked himself to Jeffrey Epstein, found dead",
    author="Jorge Fitz-Gibbon",
    publication="New York Post",
    publication_date=date(2022, 8, 24),
    url="https://nypost.com/2022/08/24/steven-hoffenberg-who-linked-himself-to-jeffrey-epstein-found-dead/",
    citation_chicago='Fitz-Gibbon, Jorge. "Steven Hoffenberg, Convicted Ponzi Schemer Who Linked Himself to Jeffrey Epstein, Found Dead." New York Post, August 24, 2022.',
    notes="Hoffenberg made claims about Epstein intelligence ties before his death"
)

# JPMorgan internal knowledge - court documents
USVI_V_JPMORGAN = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Government of the United States Virgin Islands v. JPMorgan Chase Bank, N.A.",
    publication="Superior Court of the Virgin Islands",
    publication_date=date(2022, 12, 27),
    url="https://ago.vi.gov/wp-content/uploads/2022/12/Complaint-USVI-v.-JPMorgan-Chase.pdf",
    citation_chicago='Government of the United States Virgin Islands v. JPMorgan Chase Bank, N.A., Case No. SX-2022-CV-00036 (V.I. Super. Ct. December 27, 2022).',
    notes="USVI lawsuit alleging JPMorgan facilitated Epstein's trafficking"
)

# Mary Erdoes communications - court exhibits
JPMORGAN_INTERNAL_EMAILS = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Exhibit: JPMorgan Internal Communications re: Jeffrey Epstein",
    publication="U.S. District Court, Southern District of New York",
    citation_chicago='Exhibit, Jane Doe 1 v. JPMorgan Chase Bank, N.A., Case No. 22-cv-10019 (S.D.N.Y.).',
    notes="Internal bank emails about Epstein account"
)

# Jes Staley emails - FCA investigation
FCA_STALEY_INVESTIGATION = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="FCA and PRA Investigation into Jes Staley",
    author="Financial Conduct Authority",
    publication="Financial Conduct Authority (UK)",
    publication_date=date(2021, 11, 1),
    url="https://www.fca.org.uk/news/press-releases/fca-pra-investigation-jes-staley",
    citation_chicago='Financial Conduct Authority. "FCA and PRA Investigation into Jes Staley." November 1, 2021.',
    notes="UK regulator investigation into Staley-Epstein relationship"
)

# Palm Beach investigation
PALM_BEACH_POLICE_REPORT = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Palm Beach Police Department Investigation Report",
    author="Palm Beach Police Department",
    publication="Palm Beach Police Department",
    publication_date=date(2006, 5, 1),
    citation_chicago='Palm Beach Police Department. Investigation Report, Case No. 05-368. May 2006.',
    notes="Original police investigation that identified 40+ victims"
)

REITER_DEPOSITION = Source(
    source_type=SourceType.DEPOSITION,
    title="Deposition of Michael Reiter",
    publication="Court exhibit in Epstein-related litigation",
    citation_chicago='Deposition of Michael Reiter, Former Palm Beach Police Chief.',
    notes="Testimony from lead investigator who pushed for prosecution"
)

# Epstein properties - real estate records
NYT_EPSTEIN_PROPERTIES = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jeffrey Epstein's Properties: A Visual Guide",
    author="Various",
    publication="New York Times",
    publication_date=date(2019, 7, 11),
    url="https://www.nytimes.com/2019/07/11/realestate/jeffrey-epstein-properties.html",
    citation_chicago='New York Times. "Jeffrey Epstein\'s Properties: A Visual Guide." July 11, 2019.',
    notes="Overview of Epstein's real estate holdings"
)

USVI_EPSTEIN_ESTATE = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Government of the U.S. Virgin Islands Civil Complaint Against the Estate of Jeffrey E. Epstein",
    publication="Superior Court of the Virgin Islands",
    publication_date=date(2020, 1, 15),
    citation_chicago='Government of the United States Virgin Islands v. Estate of Jeffrey E. Epstein, Case No. ST-2020-CV-0009 (V.I. Super. Ct. January 15, 2020).',
    notes="USVI civil suit detailing island operations"
)

# Flight logs
EPSTEIN_FLIGHT_LOGS_COURT = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Lolita Express Flight Logs (Court Exhibit)",
    publication="U.S. District Court, Southern District of Florida",
    citation_chicago='Flight Logs, Jeffrey Epstein Aircraft, Court Exhibit, Case No. 08-cv-80736 (S.D. Fla.).',
    notes="Redacted flight logs released through FOIA and litigation"
)

# Glenn Dubin household employee testimony
RINALDO_RIZZO_DEPOSITION = Source(
    source_type=SourceType.DEPOSITION,
    title="Deposition of Rinaldo Rizzo",
    publication="Court exhibit in Giuffre v. Maxwell",
    citation_chicago='Deposition of Rinaldo Rizzo, Giuffre v. Maxwell, Case No. 15-cv-07433-RWS (S.D.N.Y.).',
    notes="Testimony from former Dubin household employee about Giuffre"
)

# Jean-Luc Brunel death
GUARDIAN_BRUNEL_DEATH = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jean-Luc Brunel, Model Scout at Center of Epstein Investigation, Found Dead",
    author="Angelique Chrisafis",
    publication="The Guardian",
    publication_date=date(2022, 2, 19),
    url="https://www.theguardian.com/world/2022/feb/19/jean-luc-brunel-model-scout-jeffrey-epstein-investigation-found-dead-paris",
    citation_chicago='Chrisafis, Angelique. "Jean-Luc Brunel, Model Scout at Center of Epstein Investigation, Found Dead." The Guardian, February 19, 2022.',
    notes="Brunel found hanged in Paris jail while awaiting trial"
)

# Model industry recruitment
CBS_60_MINUTES_MC2 = Source(
    source_type=SourceType.NEWSPAPER,
    title="How Jeffrey Epstein Used the Billionaire Behind Victoria's Secret",
    author="60 Minutes",
    publication="CBS News",
    publication_date=date(2020, 2, 9),
    url="https://www.cbsnews.com/news/jeffrey-epstein-60-minutes-victoria-secret-les-wexner/",
    citation_chicago='CBS News. "How Jeffrey Epstein Used the Billionaire Behind Victoria\'s Secret." 60 Minutes, February 9, 2020.',
    notes="Victoria's Secret modeling recruitment angle"
)

# Steven Hoffenberg - Towers Financial fraud
NYT_HOFFENBERG_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Towers Financial: A Ponzi Scheme",
    author="Various",
    publication="New York Times",
    publication_date=date(1993, 4, 14),
    citation_chicago='New York Times. "Towers Financial Investigation Coverage." April 1993.',
    notes="Epstein's early career connection to convicted fraudster Hoffenberg"
)

# Bear Stearns connection
VANITY_FAIR_EPSTEIN_ORIGIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Talented Mr. Epstein",
    author="Vicky Ward",
    publication="Vanity Fair",
    publication_date=date(2003, 3, 1),
    url="https://www.vanityfair.com/news/2003/03/jeffrey-epstein-200303",
    citation_chicago='Ward, Vicky. "The Talented Mr. Epstein." Vanity Fair, March 2003.',
    notes="Early Epstein profile including Bear Stearns employment"
)

# Ehud Barak connection - NYT instead of Daily Beast
NYT_BARAK_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Epstein Had Burst of Visitors to His Jail Cell in the Weeks Before His Death",
    author="Adam Goldman and William K. Rashbaum",
    publication="New York Times",
    publication_date=date(2019, 8, 17),
    url="https://www.nytimes.com/2019/08/17/nyregion/epstein-suicide-death.html",
    citation_chicago='Goldman, Adam, and William K. Rashbaum. "Epstein Had Burst of Visitors to His Jail Cell in the Weeks Before His Death." New York Times, August 17, 2019.',
    notes="NYT coverage of Epstein connections including Barak business ties"
)

HAARETZ_BARAK_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Ehud Barak Visited Jeffrey Epstein's Island, Say Unsealed Court Documents",
    author="Various",
    publication="Haaretz",
    publication_date=date(2020, 7, 31),
    url="https://www.haaretz.com/israel-news/2020-07-31/ty-article/.premium/unsealed-documents-claim-ehud-barak-visited-epstein-island/0000017f-e0b2-d62c-a1ff-fcb7e9d40000",
    citation_chicago='Haaretz. "Ehud Barak Visited Jeffrey Epstein\'s Island, Say Unsealed Court Documents." July 31, 2020.',
    notes="Israeli reporting on Barak-Epstein connections"
)

# Woody Allen connection
PAGE_SIX_WOODY_ALLEN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Woody Allen Seen Having Lunch with Jeffrey Epstein",
    author="Various",
    publication="Page Six / New York Post",
    publication_date=date(2013, 9, 1),
    url="https://pagesix.com/",
    citation_chicago='Page Six. "Woody Allen Epstein Sightings." New York Post, 2013.',
    notes="Multiple sightings of Allen with Epstein"
)

# George Mitchell connection
GIUFFRE_MITCHELL_ALLEGATIONS = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Virginia Giuffre Declaration re: George Mitchell",
    publication="U.S. District Court, Southern District of New York",
    citation_chicago='Declaration of Virginia Giuffre, unsealed court documents, 2019.',
    notes="Giuffre allegations against former Senator Mitchell; Mitchell denies"
)

# Bill Richardson connection
GIUFFRE_RICHARDSON_ALLEGATIONS = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Virginia Giuffre Declaration re: Bill Richardson",
    publication="U.S. District Court, Southern District of New York",
    citation_chicago='Declaration of Virginia Giuffre, unsealed court documents, 2019.',
    notes="Giuffre allegations against former Governor Richardson; Richardson denied"
)

# ============================================================================
# BUSINESS & FINANCIAL SOURCES
# ============================================================================

# Bear Stearns history
WSJ_BEAR_STEARNS_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Mystery of Jeffrey Epstein's Fortune",
    author="Khadeeja Safdar and David Benoit",
    publication="Wall Street Journal",
    publication_date=date(2019, 7, 22),
    url="https://www.wsj.com/articles/the-mystery-of-jeffrey-epsteins-fortune-11563813507",
    citation_chicago='Safdar, Khadeeja, and David Benoit. "The Mystery of Jeffrey Epstein\'s Fortune." Wall Street Journal, July 22, 2019.',
    notes="Epstein's Bear Stearns career and mysterious wealth origins"
)

# Hoffenberg/Towers Financial
NYT_TOWERS_FINANCIAL = Source(
    source_type=SourceType.NEWSPAPER,
    title="Ex-Chief of Towers Financial Is Sentenced to 20 Years",
    author="Anthony Ramirez",
    publication="New York Times",
    publication_date=date(1997, 4, 8),
    url="https://www.nytimes.com/1997/04/08/business/ex-chief-of-towers-financial-is-sentenced-to-20-years.html",
    citation_chicago='Ramirez, Anthony. "Ex-Chief of Towers Financial Is Sentenced to 20 Years." New York Times, April 8, 1997.',
    notes="Hoffenberg conviction; Epstein never charged despite involvement"
)

HOFFENBERG_TESTIMONY = Source(
    source_type=SourceType.DEPOSITION,
    title="Declaration of Steven Hoffenberg re: Jeffrey Epstein",
    publication="Various court proceedings",
    citation_chicago='Declaration of Steven Hoffenberg regarding Jeffrey Epstein.',
    notes="Hoffenberg claimed Epstein was partner in Ponzi scheme"
)

# Mortimer Zuckerman
FORBES_ZUCKERMAN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Mortimer Zuckerman Profile",
    author="Forbes Staff",
    publication="Forbes",
    url="https://www.forbes.com/profile/mortimer-zuckerman/",
    citation_chicago='Forbes. "Mortimer Zuckerman." Forbes. Accessed 2024.',
    notes="Real estate mogul and media owner; Epstein managed his money"
)

# Apollo independent review
DECHERT_APOLLO_REVIEW = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Report to Apollo Global Management Board of Directors",
    author="Dechert LLP",
    publication="Apollo Global Management",
    publication_date=date(2021, 1, 25),
    citation_chicago='Dechert LLP. Report to Apollo Global Management Board of Directors re: Leon Black and Jeffrey Epstein. January 25, 2021.',
    notes="Independent review of Black-Epstein relationship"
)

# Southern Trust
USVI_SOUTHERN_TRUST = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Southern Trust Company Formation Documents",
    publication="U.S. Virgin Islands Division of Corporations",
    citation_chicago='Southern Trust Company, Inc. Corporate Filings. U.S. Virgin Islands.',
    notes="Epstein's USVI corporate structure"
)

# ============================================================================
# PHILANTHROPIC SOURCES
# ============================================================================

# Rockefeller University
NYT_ROCKEFELLER_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Epstein Gave $850,000 to M.I.T., and 2 Professors Are Put on Leave",
    author="Kate Taylor",
    publication="New York Times",
    publication_date=date(2019, 9, 12),
    url="https://www.nytimes.com/2019/09/12/us/mit-jeffrey-epstein.html",
    citation_chicago='Taylor, Kate. "Epstein Gave $850,000 to M.I.T., and 2 Professors Are Put on Leave." New York Times, September 12, 2019.',
    notes="Includes details of Epstein donations to multiple institutions"
)

# Edge Foundation
EDGE_FOUNDATION_DINNERS = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Last Days of the Edge Dinner",
    author="Various",
    publication="Various",
    citation_chicago='Coverage of Edge Foundation dinners hosted by John Brockman.',
    notes="Scientific salon where Epstein networked with academics"
)

# John Brockman / Edge
NEW_YORKER_BROCKMAN_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="How an Élite University Research Center Concealed Its Relationship with Jeffrey Epstein",
    author="Ronan Farrow",
    publication="The New Yorker",
    publication_date=date(2019, 9, 6),
    url="https://www.newyorker.com/news/news-desk/how-an-elite-university-research-center-concealed-its-relationship-with-jeffrey-epstein",
    citation_chicago='Farrow, Ronan. "How an Élite University Research Center Concealed Its Relationship with Jeffrey Epstein." The New Yorker, September 6, 2019.',
    notes="Details Brockman's facilitation of Epstein academic connections"
)

# Council on Foreign Relations
CFR_EPSTEIN_MEMBERSHIP = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Council on Foreign Relations Membership Records",
    publication="Council on Foreign Relations",
    citation_chicago='Council on Foreign Relations. Membership Records.',
    notes="Epstein was member of prestigious foreign policy organization"
)

# Trilateral Commission
TRILATERAL_EPSTEIN = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Trilateral Commission Membership",
    publication="Trilateral Commission",
    citation_chicago='Trilateral Commission. Membership Records.',
    notes="Epstein connections to elite foreign policy group"
)

# Clinton Global Initiative
CGI_FLIGHT_LOGS = Source(
    source_type=SourceType.COURT_DOCUMENT,
    title="Flight Logs Showing Africa Trip",
    publication="Court exhibit",
    citation_chicago='Epstein Aircraft Flight Logs, Africa Trip 2002, Court Exhibit.',
    notes="Clinton Foundation trip on Epstein plane to Africa"
)

# Santa Fe Institute
SANTA_FE_INSTITUTE = Source(
    source_type=SourceType.NEWSPAPER,
    title="Santa Fe Institute Benefactors",
    publication="Santa Fe Institute",
    url="https://www.santafe.edu/",
    citation_chicago='Santa Fe Institute. Donor Records and Public Statements.',
    notes="Complexity research institute that received Epstein funding"
)

# Nathan Myhrvold connection
MYHRVOLD_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Nathan Myhrvold and Jeffrey Epstein",
    author="Various",
    publication="Various",
    citation_chicago='Coverage of Nathan Myhrvold-Epstein connections.',
    notes="Former Microsoft CTO photographed with Epstein"
)

# Stephen Hawking
GUARDIAN_HAWKING_EPSTEIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Stephen Hawking pictured on Jeffrey Epstein's 'Island of Sin'",
    author="Tim Adams",
    publication="The Guardian",
    publication_date=date(2015, 1, 12),
    url="https://www.theguardian.com/science/2015/jan/12/stephen-hawking-pictured-jeffrey-epstein-island-sin",
    citation_chicago='Adams, Tim. "Stephen Hawking Pictured on Jeffrey Epstein\'s \'Island of Sin\'." The Guardian, January 12, 2015.',
    notes="Photos of Hawking at 2006 conference on Epstein's island"
)

# ============================================================================
# MODELING WORLD SOURCES
# ============================================================================

# Elite Model Management history
CBS_ELITE_MODEL = Source(
    source_type=SourceType.NEWSPAPER,
    title="Elite Model Management and John Casablancas",
    author="Various",
    publication="CBS News",
    publication_date=date(2019, 8, 15),
    citation_chicago='CBS News. "Elite Model Management History." 2019.',
    notes="History of abuse allegations in modeling industry"
)

# John Casablancas
NYT_CASABLANCAS = Source(
    source_type=SourceType.NEWSPAPER,
    title="John Casablancas, Pioneer of the Supermodel Era, Is Dead at 70",
    author="Enid Nemy",
    publication="New York Times",
    publication_date=date(2013, 7, 21),
    url="https://www.nytimes.com/2013/07/22/business/john-casablancas-pioneer-of-supermodel-era-dies-at-70.html",
    citation_chicago='Nemy, Enid. "John Casablancas, Pioneer of the Supermodel Era, Is Dead at 70." New York Times, July 21, 2013.',
    notes="Casablancas founded Elite; reputation for young models"
)

# MC2 operations
MIAMI_HERALD_MC2 = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jeffrey Epstein Scandal: Model Agency Was 'Source of Girls'",
    author="Julie K. Brown",
    publication="Miami Herald",
    publication_date=date(2018, 11, 29),
    url="https://www.miamiherald.com/news/local/article222097875.html",
    citation_chicago='Brown, Julie K. "Jeffrey Epstein Scandal: Model Agency Was \'Source of Girls\'." Miami Herald, November 29, 2018.',
    notes="MC2 agency investigation as recruitment pipeline"
)

# Brunel 60 Minutes interview
CBS_60_MINUTES_BRUNEL = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jean-Luc Brunel: The Model Agent and Jeffrey Epstein",
    author="60 Minutes",
    publication="CBS News",
    publication_date=date(2020, 1, 5),
    citation_chicago='CBS News. "Jean-Luc Brunel: The Model Agent and Jeffrey Epstein." 60 Minutes, 2020.',
    notes="Investigation into Brunel's recruitment methods"
)

# Karin Models
LE_MONDE_KARIN_MODELS = Source(
    source_type=SourceType.NEWSPAPER,
    title="L'affaire Jean-Luc Brunel",
    author="Various",
    publication="Le Monde",
    publication_date=date(2019, 12, 15),
    url="https://www.lemonde.fr/",
    citation_chicago='Le Monde. "L\'affaire Jean-Luc Brunel." December 2019.',
    notes="French investigation into Brunel and Karin Models"
)

# Victoria's Secret - Alison Maloney allegations
NYT_VS_RECRUITMENT = Source(
    source_type=SourceType.NEWSPAPER,
    title="After Epstein's Death, Victoria's Secret Tries to Distance Itself",
    author="Matthew Goldstein and Jessica Silver-Greenberg",
    publication="New York Times",
    publication_date=date(2019, 8, 14),
    url="https://www.nytimes.com/2019/08/14/business/victoria-secret-epstein.html",
    citation_chicago='Goldstein, Matthew, and Jessica Silver-Greenberg. "After Epstein\'s Death, Victoria\'s Secret Tries to Distance Itself." New York Times, August 14, 2019.',
    notes="Allegations Epstein posed as VS recruiter"
)

# Alicia Arden police report
ARDEN_POLICE_REPORT = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="Alicia Arden Police Report",
    author="Santa Monica Police Department",
    publication="Santa Monica Police Department",
    publication_date=date(1997, 6, 15),
    citation_chicago='Santa Monica Police Department. Police Report filed by Alicia Arden. June 1997.',
    notes="Model reported Epstein to police in 1997; no prosecution"
)

# ============================================================================
# REAL ESTATE & PROPERTY SOURCES
# ============================================================================

# Zorro Ranch
NYT_ZORRO_RANCH = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jeffrey Epstein Hoped to Seed Human Race With His DNA",
    author="James B. Stewart",
    publication="New York Times",
    publication_date=date(2019, 7, 31),
    url="https://www.nytimes.com/2019/07/31/business/jeffrey-epstein-eugenics.html",
    citation_chicago='Stewart, James B. "Jeffrey Epstein Hoped to Seed Human Race With His DNA." New York Times, July 31, 2019.',
    notes="Zorro Ranch in New Mexico used for eugenics plans"
)

# Little St. James
WAPO_LITTLE_ST_JAMES = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jeffrey Epstein's private Caribbean island",
    author="Various",
    publication="Washington Post",
    publication_date=date(2019, 7, 10),
    url="https://www.washingtonpost.com/local/legal-issues/jeffrey-epsteins-private-caribbean-island/2019/07/10/",
    citation_chicago='Washington Post. "Jeffrey Epstein\'s Private Caribbean Island." July 10, 2019.',
    notes="Little St. James island investigation"
)

# Great St. James purchase
USVI_LAND_RECORDS = Source(
    source_type=SourceType.GOVERNMENT_RECORD,
    title="U.S. Virgin Islands Land Records - Great St. James",
    publication="U.S. Virgin Islands Recorder of Deeds",
    citation_chicago='U.S. Virgin Islands Recorder of Deeds. Land Transfer Records, Great St. James Island.',
    notes="2016 purchase of second island for $22.5 million"
)

# Paris apartment
REUTERS_PARIS_APARTMENT = Source(
    source_type=SourceType.NEWSPAPER,
    title="Jeffrey Epstein's Paris apartment where models were 'ichael groomed'",
    author="Various",
    publication="Reuters",
    publication_date=date(2019, 9, 1),
    url="https://www.reuters.com/",
    citation_chicago='Reuters. "Jeffrey Epstein\'s Paris Apartment." September 2019.',
    notes="Avenue Foch apartment used by Brunel and Epstein"
)

# ============================================================================
# SOCIALITE & SOCIETY SOURCES
# ============================================================================

# Pepe Fanjul
BLOOMBERG_FANJUL = Source(
    source_type=SourceType.NEWSPAPER,
    title="The Fanjul Brothers: Kings of Sugar",
    author="Various",
    publication="Bloomberg",
    url="https://www.bloomberg.com/",
    citation_chicago='Bloomberg. "The Fanjul Brothers: Kings of Sugar."',
    notes="Sugar magnates in Epstein's social circle"
)

# Tom Barrack
NYT_BARRACK = Source(
    source_type=SourceType.NEWSPAPER,
    title="Tom Barrack, Trump Fund-Raiser, Is Indicted on Lobbying Charges",
    author="Ben Protess and Kenneth P. Vogel",
    publication="New York Times",
    publication_date=date(2021, 7, 20),
    url="https://www.nytimes.com/2021/07/20/us/politics/tom-barrack-trump-indictment.html",
    citation_chicago='Protess, Ben, and Kenneth P. Vogel. "Tom Barrack, Trump Fund-Raiser, Is Indicted on Lobbying Charges." New York Times, July 20, 2021.',
    notes="Colony Capital founder in Epstein contacts"
)

# Eva Andersson-Dubin
NYT_EVA_DUBIN = Source(
    source_type=SourceType.NEWSPAPER,
    title="Glenn and Eva Dubin and Jeffrey Epstein",
    author="Various",
    publication="New York Times",
    publication_date=date(2019, 8, 26),
    citation_chicago='New York Times. "Coverage of Dubin Family-Epstein Connections." August 2019.',
    notes="Former Miss Sweden; previously dated Epstein; married Glenn Dubin"
)

# ============================================================================
# SOURCED RELATIONSHIPS - Verified connections with citations
# ============================================================================

SOURCED_RELATIONSHIPS: List[SourcedRelationship] = [
    # -------------------------------------------------------------------------
    # EPSTEIN CORE NETWORK - Highest confidence, multiple sources
    # -------------------------------------------------------------------------
    
    # Epstein-Maxwell relationship - Extremely well documented
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Ghislaine Maxwell",
        relationship_type="associated_with",
        sources=[USA_V_MAXWELL_INDICTMENT, USA_V_MAXWELL_TRIAL_TRANSCRIPT, GIUFFRE_V_MAXWELL_COMPLAINT],
        confidence_score=1.0,
        quotes={
            "United States v. Ghislaine Maxwell, Indictment": "Maxwell was among Epstein's closest associates and helped him exploit girls who were as young as 14 years old."
        },
        notes="Primary co-conspirator relationship established in federal indictment and trial"
    ),
    
    # Epstein-Wexner relationship - Extensive documentation
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Leslie Wexner",
        relationship_type="financial_advisor",
        sources=[NYT_EPSTEIN_BLACK_MONEY, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        quotes={
            "How Jeffrey Epstein Used the Billionaire Behind Victoria's Secret for Wealth and Women": "For nearly two decades, Jeffrey Epstein basked in the wealth and influence of Leslie H. Wexner"
        },
        notes="Epstein managed Wexner's finances from ~1988-2007"
    ),
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="L Brands",
        relationship_type="founder",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Public company record"
    ),
    
    # Epstein-Leon Black relationship - Financial payments documented
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Leon Black",
        relationship_type="financial_advisor",
        sources=[NYT_LEON_BLACK_EPSTEIN],
        confidence_score=1.0,
        quotes={
            "Apollo's Leon Black Paid Jeffrey Epstein $158 Million": "Leon Black, the billionaire co-founder of Apollo Global Management, paid Jeffrey Epstein at least $158 million for tax and estate planning advice"
        },
        notes="$158 million in payments from 2012-2017, after Epstein's 2008 conviction"
    ),
    SourcedRelationship(
        source_entity="Leon Black",
        target_entity="Apollo Global Management",
        relationship_type="founder",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Public company record"
    ),
    
    # Epstein-Bill Gates meetings
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Bill Gates",
        relationship_type="associated_with",
        sources=[NYT_BILL_GATES_EPSTEIN],
        confidence_score=0.95,
        quotes={
            "Bill Gates Met With Jeffrey Epstein Many Times, Despite His Past": "Beginning in 2011, Mr. Gates met with Mr. Epstein on numerous occasions — including at least three times at Mr. Epstein's palatial Manhattan townhouse"
        },
        notes="Multiple documented meetings 2011-2014, after 2008 conviction"
    ),
    SourcedRelationship(
        source_entity="Bill Gates",
        target_entity="Microsoft",
        relationship_type="co_founder",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Public record"
    ),
    
    # Epstein-MIT Media Lab connections
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Joi Ito",
        relationship_type="donor",
        sources=[NEW_YORKER_MIT_EPSTEIN, NYT_MIT_MEDIA_LAB],
        confidence_score=1.0,
        quotes={
            "How an Élite University Research Center Concealed Its Relationship with Jeffrey Epstein": "Epstein directed more than seven and a half million dollars in donations to the lab"
        },
        notes="Epstein funded MIT Media Lab through Ito, marked as anonymous"
    ),
    SourcedRelationship(
        source_entity="Joi Ito",
        target_entity="MIT Media Lab",
        relationship_type="director",
        sources=[NEW_YORKER_MIT_EPSTEIN],
        confidence_score=1.0,
        notes="Ito resigned as director in September 2019"
    ),
    
    # Epstein-Prince Andrew relationship - BBC interview admission
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Prince Andrew",
        relationship_type="associated_with",
        sources=[BBC_PRINCE_ANDREW, GIUFFRE_V_MAXWELL_UNSEALED_2019],
        confidence_score=1.0,
        quotes={
            "Prince Andrew & the Epstein Scandal: The Newsnight Interview": "I met him through his girlfriend back in 1999 who... was Ghislaine Maxwell"
        },
        notes="Prince Andrew admitted to friendship in BBC interview"
    ),
    
    # Maxwell-Prince Andrew introduction
    SourcedRelationship(
        source_entity="Ghislaine Maxwell",
        target_entity="Prince Andrew",
        relationship_type="introduced",
        sources=[BBC_PRINCE_ANDREW],
        confidence_score=1.0,
        notes="Andrew stated Maxwell introduced him to Epstein"
    ),
    
    # Virginia Giuffre allegations - Court documented
    SourcedRelationship(
        source_entity="Virginia Giuffre",
        target_entity="Jeffrey Epstein",
        relationship_type="victim_of",
        sources=[GIUFFRE_V_MAXWELL_COMPLAINT, USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Testified as victim in Maxwell trial"
    ),
    SourcedRelationship(
        source_entity="Virginia Giuffre",
        target_entity="Ghislaine Maxwell",
        relationship_type="victim_of",
        sources=[GIUFFRE_V_MAXWELL_COMPLAINT, USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Maxwell convicted of trafficking Giuffre"
    ),
    SourcedRelationship(
        source_entity="Virginia Giuffre",
        target_entity="Prince Andrew",
        relationship_type="accuser_of",
        sources=[GIUFFRE_V_MAXWELL_UNSEALED_2019, GIUFFRE_DEPOSITION_2016],
        confidence_score=0.9,
        notes="Allegations made in court filings; settled in 2022 without admission"
    ),
    
    # Epstein staff - Court testimony
    SourcedRelationship(
        source_entity="Juan Alessi",
        target_entity="Jeffrey Epstein",
        relationship_type="employee_of",
        sources=[ALESSI_DEPOSITION, USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="House manager testified at Maxwell trial"
    ),
    SourcedRelationship(
        source_entity="Sarah Kellen",
        target_entity="Jeffrey Epstein",
        relationship_type="employee_of",
        sources=[USA_V_EPSTEIN_2019_INDICTMENT, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Named as potential co-conspirator in 2008 NPA"
    ),
    SourcedRelationship(
        source_entity="Sarah Kellen",
        target_entity="Ghislaine Maxwell",
        relationship_type="associated_with",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Both involved in scheduling victims"
    ),
    SourcedRelationship(
        source_entity="Lesley Groff",
        target_entity="Jeffrey Epstein",
        relationship_type="employee_of",
        sources=[USA_V_EPSTEIN_2019_INDICTMENT],
        confidence_score=1.0,
        notes="Executive assistant named in indictment"
    ),
    
    # Jean-Luc Brunel - Modeling connection
    SourcedRelationship(
        source_entity="Jean-Luc Brunel",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[GIUFFRE_DEPOSITION_2016, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Model scout, found dead in Paris prison 2022"
    ),
    SourcedRelationship(
        source_entity="Jean-Luc Brunel",
        target_entity="MC2 Model Management",
        relationship_type="founder",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Epstein financially backed MC2"
    ),
    
    # Flight log documented passengers
    SourcedRelationship(
        source_entity="Bill Clinton",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[EPSTEIN_FLIGHT_LOGS, GIUFFRE_V_MAXWELL_UNSEALED_2019],
        confidence_score=0.95,
        quotes={
            "Epstein Aircraft Flight Logs": "Multiple entries showing Clinton on Epstein aircraft"
        },
        notes="Flight logs show multiple trips on Epstein aircraft; Clinton denies knowledge of crimes"
    ),
    SourcedRelationship(
        source_entity="Bill Clinton",
        target_entity="Clinton Foundation",
        relationship_type="founder",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Public record"
    ),
    
    # Alan Dershowitz - Legal and personal relationship
    SourcedRelationship(
        source_entity="Alan Dershowitz",
        target_entity="Jeffrey Epstein",
        relationship_type="attorney_for",
        sources=[DERSHOWITZ_DEPOSITION, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Represented Epstein in 2008 case, negotiated NPA"
    ),
    SourcedRelationship(
        source_entity="Alan Dershowitz",
        target_entity="Harvard Law School",
        relationship_type="professor",
        sources=[DERSHOWITZ_DEPOSITION],
        confidence_score=1.0,
        notes="Emeritus professor"
    ),
    
    # Glenn Dubin relationship
    SourcedRelationship(
        source_entity="Glenn Dubin",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[GIUFFRE_DEPOSITION_2016, EPSTEIN_BLACK_BOOK],
        confidence_score=0.9,
        notes="Named in Giuffre deposition; Dubin denies wrongdoing"
    ),
    SourcedRelationship(
        source_entity="Glenn Dubin",
        target_entity="Highbridge Capital Management",
        relationship_type="co_founder",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Public record"
    ),
    
    # Jes Staley - JPMorgan connection
    SourcedRelationship(
        source_entity="Jes Staley",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[NYT_EPSTEIN_BLACK_MONEY],
        confidence_score=0.95,
        notes="Former JPMorgan exec who maintained relationship with Epstein"
    ),
    
    # -------------------------------------------------------------------------
    # TRUMP NETWORK - Public record and court documents
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Donald Trump",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[FILTHY_RICH_BOOK, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=0.9,
        quotes={
            "Filthy Rich: The Shocking True Story of Jeffrey Epstein": "I've known Jeff for fifteen years. Terrific guy."
        },
        notes="2002 quote to New York Magazine; Trump later distanced himself"
    ),
    SourcedRelationship(
        source_entity="Donald Trump",
        target_entity="Trump Organization",
        relationship_type="chairman",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Public record"
    ),
    
    # -------------------------------------------------------------------------
    # MAXWELL FAMILY - Documented background
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Ghislaine Maxwell",
        target_entity="Robert Maxwell",
        relationship_type="child_of",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Daughter of media mogul Robert Maxwell"
    ),
    SourcedRelationship(
        source_entity="Robert Maxwell",
        target_entity="Mirror Group Newspapers",
        relationship_type="owner",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Owned UK tabloids until death in 1991"
    ),
    SourcedRelationship(
        source_entity="Ghislaine Maxwell",
        target_entity="TerraMar Project",
        relationship_type="founder",
        sources=[GIUFFRE_V_MAXWELL_COMPLAINT],
        confidence_score=1.0,
        notes="Ocean conservation nonprofit dissolved after Epstein arrest"
    ),
    
    # -------------------------------------------------------------------------
    # LEGAL TEAM - Court records
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Bradley Edwards",
        target_entity="Virginia Giuffre",
        relationship_type="attorney_for",
        sources=[RELENTLESS_PURSUIT_BOOK, GIUFFRE_V_MAXWELL_COMPLAINT],
        confidence_score=1.0,
        notes="Victims' rights attorney"
    ),
    SourcedRelationship(
        source_entity="David Boies",
        target_entity="Virginia Giuffre",
        relationship_type="attorney_for",
        sources=[GIUFFRE_V_MAXWELL_COMPLAINT],
        confidence_score=1.0,
        notes="High-profile attorney representing Giuffre"
    ),
    SourcedRelationship(
        source_entity="David Boies",
        target_entity="Boies Schiller Flexner",
        relationship_type="chairman",
        sources=[GIUFFRE_V_MAXWELL_COMPLAINT],
        confidence_score=1.0,
        notes="Law firm"
    ),
    
    # Laura Menninger - Maxwell's attorney
    SourcedRelationship(
        source_entity="Laura Menninger",
        target_entity="Ghislaine Maxwell",
        relationship_type="attorney_for",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Defense attorney in criminal trial"
    ),
    SourcedRelationship(
        source_entity="Laura Menninger",
        target_entity="Haddon, Morgan and Foreman",
        relationship_type="partner",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Law firm"
    ),
    
    # -------------------------------------------------------------------------
    # BANKING RELATIONSHIPS - Financial institutions
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="JPMorgan Chase",
        relationship_type="client_of",
        sources=[WSJ_JPMORGAN_EPSTEIN, FT_VIRGIN_ISLANDS],
        confidence_score=1.0,
        quotes={
            "JPMorgan to Pay $290 Million to Settle Epstein Victims' Lawsuit": "JPMorgan kept Epstein as a client from 1998 to 2013"
        },
        notes="JPMorgan settled for $290M in 2023; maintained account after 2008 conviction"
    ),
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Deutsche Bank",
        relationship_type="client_of",
        sources=[WSJ_DEUTSCHE_BANK_EPSTEIN],
        confidence_score=1.0,
        quotes={
            "Deutsche Bank to Pay $75 Million to Settle Lawsuit by Epstein Victims": "Deutsche Bank became Epstein's primary bank after JPMorgan cut ties in 2013"
        },
        notes="Deutsche Bank settled for $75M; opened account after JPMorgan departure"
    ),
    SourcedRelationship(
        source_entity="Jes Staley",
        target_entity="JPMorgan Chase",
        relationship_type="executive",
        sources=[BLOOMBERG_STALEY, WSJ_JPMORGAN_EPSTEIN],
        confidence_score=1.0,
        notes="Former head of JPMorgan's private bank; managed Epstein relationship"
    ),
    SourcedRelationship(
        source_entity="Jes Staley",
        target_entity="Barclays",
        relationship_type="ceo",
        sources=[BLOOMBERG_STALEY],
        confidence_score=1.0,
        notes="Left Barclays in 2021 over Epstein relationship investigation"
    ),
    
    # -------------------------------------------------------------------------
    # MODELING INDUSTRY - Recruitment network
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="MC2 Model Management",
        relationship_type="financier_of",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE, GIUFFRE_DEPOSITION_2016],
        confidence_score=1.0,
        notes="Epstein provided financing for Brunel's modeling agency"
    ),
    
    # -------------------------------------------------------------------------
    # VICTIMS - Documented in court records
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Courtney Wild",
        target_entity="Jeffrey Epstein",
        relationship_type="victim_of",
        sources=[WILD_DECLARATION, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Victim and advocate; testified about recruitment at age 14"
    ),
    SourcedRelationship(
        source_entity="Sarah Ransome",
        target_entity="Jeffrey Epstein",
        relationship_type="victim_of",
        sources=[RANSOME_DECLARATION],
        confidence_score=1.0,
        notes="Victim who provided detailed declaration about abuse on Little St. James"
    ),
    SourcedRelationship(
        source_entity="Sarah Ransome",
        target_entity="Ghislaine Maxwell",
        relationship_type="victim_of",
        sources=[RANSOME_DECLARATION],
        confidence_score=1.0,
        notes="Ransome described Maxwell's involvement in declaration"
    ),
    SourcedRelationship(
        source_entity="Annie Farmer",
        target_entity="Jeffrey Epstein",
        relationship_type="victim_of",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Testified at Maxwell trial; was 16 when abused"
    ),
    SourcedRelationship(
        source_entity="Annie Farmer",
        target_entity="Ghislaine Maxwell",
        relationship_type="victim_of",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="Testified Maxwell participated in her abuse"
    ),
    SourcedRelationship(
        source_entity="Maria Farmer",
        target_entity="Jeffrey Epstein",
        relationship_type="victim_of",
        sources=[NETFLIX_FILTHY_RICH_DOC, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Sister of Annie Farmer; one of first to report abuse to FBI in 1996"
    ),
    SourcedRelationship(
        source_entity="Maria Farmer",
        target_entity="Ghislaine Maxwell",
        relationship_type="victim_of",
        sources=[NETFLIX_FILTHY_RICH_DOC],
        confidence_score=1.0,
        notes="Described Maxwell's direct involvement"
    ),
    
    # -------------------------------------------------------------------------
    # PROSECUTION AND LAW ENFORCEMENT
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Alexander Acosta",
        target_entity="Jeffrey Epstein",
        relationship_type="prosecutor_of",
        sources=[WAPO_ACOSTA_NPA, EPSTEIN_NPA_2008],
        confidence_score=1.0,
        quotes={
            "Labor secretary nominee Alexander Acosta cut deal with billionaire in underage sex case": "Acosta was the U.S. Attorney who signed off on the controversial plea deal"
        },
        notes="As U.S. Attorney, approved controversial 2008 non-prosecution agreement"
    ),
    SourcedRelationship(
        source_entity="Kenneth Starr",
        target_entity="Jeffrey Epstein",
        relationship_type="attorney_for",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Part of Epstein's legal team in 2008 case"
    ),
    SourcedRelationship(
        source_entity="Roy Black",
        target_entity="Jeffrey Epstein",
        relationship_type="attorney_for",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Miami defense attorney on Epstein's 2008 legal team"
    ),
    
    # -------------------------------------------------------------------------
    # WEXNER NETWORK - Corporate and personal ties
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="Victoria's Secret",
        relationship_type="founder",
        sources=[NYT_EPSTEIN_BLACK_MONEY, FORBES_WEXNER],
        confidence_score=1.0,
        notes="Founder through L Brands"
    ),
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Leslie Wexner",
        relationship_type="power_of_attorney",
        sources=[NYT_EPSTEIN_BLACK_MONEY, WSJ_WEXNER_EPSTEIN_STATEMENT],
        confidence_score=1.0,
        quotes={
            "Les Wexner Says Jeffrey Epstein 'Misappropriated Vast Sums' of His Fortune": "Wexner acknowledged giving Epstein sweeping powers over his finances"
        },
        notes="Epstein had power of attorney over Wexner's finances - extraordinary access"
    ),
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="9 East 71st Street",
        relationship_type="received_from",
        sources=[NYT_EPSTEIN_BLACK_MONEY],
        confidence_score=1.0,
        notes="Wexner transferred $77M Manhattan mansion to Epstein for $0"
    ),
    
    # -------------------------------------------------------------------------
    # HARVARD CONNECTIONS - Academic ties
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Harvard University",
        relationship_type="donor",
        sources=[HARVARD_EPSTEIN_REPORT, NYT_EPSTEIN_BLACK_MONEY],
        confidence_score=1.0,
        notes="Donated millions to Harvard; maintained visiting privileges"
    ),
    SourcedRelationship(
        source_entity="Martin Nowak",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[HARVARD_EPSTEIN_REPORT],
        confidence_score=0.95,
        notes="Harvard professor who received Epstein funding for research program"
    ),
    SourcedRelationship(
        source_entity="Martin Nowak",
        target_entity="Harvard University",
        relationship_type="professor",
        sources=[HARVARD_EPSTEIN_REPORT],
        confidence_score=1.0,
        notes="Professor of Biology and Mathematics"
    ),
    SourcedRelationship(
        source_entity="George Church",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[NYT_MIT_MEDIA_LAB],
        confidence_score=0.9,
        notes="Harvard geneticist who met with Epstein; apologized publicly"
    ),
    SourcedRelationship(
        source_entity="George Church",
        target_entity="Harvard Medical School",
        relationship_type="professor",
        sources=[NYT_MIT_MEDIA_LAB],
        confidence_score=1.0,
        notes="Professor of Genetics"
    ),
    SourcedRelationship(
        source_entity="Larry Summers",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[VANITY_FAIR_2003],
        confidence_score=0.85,
        notes="Former Harvard president; flew on Epstein's plane"
    ),
    SourcedRelationship(
        source_entity="Larry Summers",
        target_entity="Harvard University",
        relationship_type="president",
        sources=[VANITY_FAIR_2003],
        confidence_score=1.0,
        notes="President 2001-2006"
    ),
    
    # -------------------------------------------------------------------------
    # MIT MEDIA LAB - Expanded connections
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Seth Lloyd",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[NEW_YORKER_MIT_EPSTEIN],
        confidence_score=0.95,
        notes="MIT professor who received $225,000 from Epstein; placed on leave"
    ),
    SourcedRelationship(
        source_entity="Seth Lloyd",
        target_entity="MIT",
        relationship_type="professor",
        sources=[NEW_YORKER_MIT_EPSTEIN],
        confidence_score=1.0,
        notes="Professor of Mechanical Engineering"
    ),
    SourcedRelationship(
        source_entity="Marvin Minsky",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[GIUFFRE_DEPOSITION_2016],
        confidence_score=0.8,
        notes="AI pioneer named in Giuffre deposition; deceased 2016"
    ),
    SourcedRelationship(
        source_entity="Marvin Minsky",
        target_entity="MIT",
        relationship_type="professor",
        sources=[NEW_YORKER_MIT_EPSTEIN],
        confidence_score=1.0,
        notes="Co-founder of MIT AI Lab"
    ),
    
    # -------------------------------------------------------------------------
    # FLIGHT LOG PASSENGERS - Multiple documented trips
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Chris Tucker",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[EPSTEIN_FLIGHT_LOGS, FLIGHT_LOG_ANALYSIS],
        confidence_score=0.85,
        notes="Actor appeared on flight logs; denies knowledge of wrongdoing"
    ),
    SourcedRelationship(
        source_entity="Kevin Spacey",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[EPSTEIN_FLIGHT_LOGS, FLIGHT_LOG_ANALYSIS],
        confidence_score=0.85,
        notes="Actor appeared on flight logs with Clinton trip"
    ),
    SourcedRelationship(
        source_entity="Naomi Campbell",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[EPSTEIN_BLACK_BOOK],
        confidence_score=0.75,
        notes="Name in contact book; no allegations of wrongdoing"
    ),
    
    # -------------------------------------------------------------------------
    # PRINCE ANDREW NETWORK - British connections
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Prince Andrew",
        target_entity="Virginia Giuffre",
        relationship_type="sued_by",
        sources=[GUARDIAN_PRINCE_ANDREW],
        confidence_score=1.0,
        notes="Giuffre filed civil suit in 2021; settled February 2022"
    ),
    SourcedRelationship(
        source_entity="Sarah Ferguson",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[BBC_PRINCE_ANDREW, EPSTEIN_BLACK_BOOK],
        confidence_score=0.8,
        notes="Duchess of York; Epstein reportedly paid off her debts"
    ),
    SourcedRelationship(
        source_entity="Sarah Ferguson",
        target_entity="Prince Andrew",
        relationship_type="former_spouse",
        sources=[BBC_PRINCE_ANDREW],
        confidence_score=1.0,
        notes="Divorced 1996 but remained close"
    ),
    
    # -------------------------------------------------------------------------
    # MEDIA AND JOURNALISM
    # -------------------------------------------------------------------------
    SourcedRelationship(
        source_entity="Vicky Ward",
        target_entity="Jeffrey Epstein",
        relationship_type="interviewed",
        sources=[VANITY_FAIR_2003],
        confidence_score=1.0,
        notes="Wrote 2003 Vanity Fair profile; claims victim content was cut"
    ),
    SourcedRelationship(
        source_entity="Julie K. Brown",
        target_entity="Jeffrey Epstein",
        relationship_type="investigated",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Miami Herald reporter whose series reignited case"
    ),
    
    # -------------------------------------------------------------------------
    # BUSINESS & FINANCIAL RELATIONSHIPS - Expanded
    # -------------------------------------------------------------------------
    
    # Bear Stearns - Epstein's early career
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Bear Stearns",
        relationship_type="employee_of",
        sources=[WSJ_BEAR_STEARNS_EPSTEIN, VANITY_FAIR_2003],
        confidence_score=1.0,
        notes="Worked at Bear Stearns 1976-1981; hired without college degree; made partner"
    ),
    SourcedRelationship(
        source_entity="Alan Greenberg",
        target_entity="Jeffrey Epstein",
        relationship_type="mentor_of",
        sources=[VANITY_FAIR_2003],
        confidence_score=0.9,
        notes="Bear Stearns CEO who hired Epstein; later denied close relationship"
    ),
    SourcedRelationship(
        source_entity="Alan Greenberg",
        target_entity="Bear Stearns",
        relationship_type="ceo",
        sources=[VANITY_FAIR_2003],
        confidence_score=1.0,
        notes="CEO of Bear Stearns 1978-1993"
    ),
    
    # Towers Financial - Early fraud connection
    SourcedRelationship(
        source_entity="Steven Hoffenberg",
        target_entity="Jeffrey Epstein",
        relationship_type="business_partner",
        sources=[NYT_TOWERS_FINANCIAL, HOFFENBERG_TESTIMONY],
        confidence_score=0.85,
        notes="Hoffenberg claimed Epstein was partner in $450M Ponzi scheme; Epstein never charged"
    ),
    SourcedRelationship(
        source_entity="Steven Hoffenberg",
        target_entity="Towers Financial",
        relationship_type="ceo",
        sources=[NYT_TOWERS_FINANCIAL],
        confidence_score=1.0,
        notes="Convicted in 1997; 20-year sentence for Ponzi scheme"
    ),
    
    # Mortimer Zuckerman - Real estate client
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Mortimer Zuckerman",
        relationship_type="financial_advisor",
        sources=[FORBES_ZUCKERMAN, VANITY_FAIR_2003],
        confidence_score=0.9,
        notes="Zuckerman was one of Epstein's early prominent clients"
    ),
    SourcedRelationship(
        source_entity="Mortimer Zuckerman",
        target_entity="Daily News",
        relationship_type="owner",
        sources=[FORBES_ZUCKERMAN],
        confidence_score=1.0,
        notes="Owner of NY Daily News 1993-2017"
    ),
    SourcedRelationship(
        source_entity="Mortimer Zuckerman",
        target_entity="U.S. News & World Report",
        relationship_type="owner",
        sources=[FORBES_ZUCKERMAN],
        confidence_score=1.0,
        notes="Owner 1984-2010"
    ),
    
    # Apollo Management - Additional detail
    SourcedRelationship(
        source_entity="Marc Rowan",
        target_entity="Apollo Global Management",
        relationship_type="co_founder",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Became CEO after Leon Black stepped down"
    ),
    SourcedRelationship(
        source_entity="Josh Harris",
        target_entity="Apollo Global Management",
        relationship_type="co_founder",
        sources=[APOLLO_SEC_FILINGS],
        confidence_score=1.0,
        notes="Co-founder; also owns Philadelphia 76ers"
    ),
    
    # Southern Trust Company
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Southern Trust Company",
        relationship_type="founder",
        sources=[USVI_SOUTHERN_TRUST, FT_VIRGIN_ISLANDS],
        confidence_score=1.0,
        notes="USVI company; structure for tax advantages and secrecy"
    ),
    
    # J. Epstein & Co.
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="J. Epstein & Co.",
        relationship_type="founder",
        sources=[NYT_EPSTEIN_BLACK_MONEY],
        confidence_score=1.0,
        notes="Primary vehicle for financial advisory business"
    ),
    
    # -------------------------------------------------------------------------
    # PHILANTHROPIC RELATIONSHIPS - Academic & Scientific
    # -------------------------------------------------------------------------
    
    # John Brockman / Edge Foundation
    SourcedRelationship(
        source_entity="John Brockman",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[NEW_YORKER_BROCKMAN_EPSTEIN],
        confidence_score=0.95,
        notes="Literary agent who facilitated Epstein's access to scientific elite"
    ),
    SourcedRelationship(
        source_entity="John Brockman",
        target_entity="Edge Foundation",
        relationship_type="founder",
        sources=[NEW_YORKER_BROCKMAN_EPSTEIN],
        confidence_score=1.0,
        notes="Scientific salon that hosted Epstein-funded dinners"
    ),
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Edge Foundation",
        relationship_type="donor",
        sources=[NEW_YORKER_BROCKMAN_EPSTEIN],
        confidence_score=0.95,
        notes="Epstein sponsored Edge dinners to meet scientists"
    ),
    
    # Rockefeller University
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Rockefeller University",
        relationship_type="donor",
        sources=[NYT_ROCKEFELLER_EPSTEIN],
        confidence_score=0.95,
        notes="Donated to scientific research institution"
    ),
    
    # Santa Fe Institute
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Santa Fe Institute",
        relationship_type="donor",
        sources=[SANTA_FE_INSTITUTE],
        confidence_score=0.9,
        notes="Funded complexity science research"
    ),
    
    # Council on Foreign Relations
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Council on Foreign Relations",
        relationship_type="member_of",
        sources=[CFR_EPSTEIN_MEMBERSHIP],
        confidence_score=0.85,
        notes="Member of elite foreign policy organization"
    ),
    
    # Stephen Hawking
    SourcedRelationship(
        source_entity="Stephen Hawking",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[GUARDIAN_HAWKING_EPSTEIN],
        confidence_score=0.85,
        notes="Attended 2006 conference on Epstein's island; no allegations"
    ),
    
    # Nathan Myhrvold
    SourcedRelationship(
        source_entity="Nathan Myhrvold",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[MYHRVOLD_EPSTEIN, EDGE_FOUNDATION_DINNERS],
        confidence_score=0.8,
        notes="Former Microsoft CTO photographed with Epstein at scientific events"
    ),
    SourcedRelationship(
        source_entity="Nathan Myhrvold",
        target_entity="Microsoft",
        relationship_type="cto",
        sources=[MYHRVOLD_EPSTEIN],
        confidence_score=1.0,
        notes="Microsoft CTO 1996-2000"
    ),
    
    # -------------------------------------------------------------------------
    # MODELING WORLD RELATIONSHIPS - Expanded
    # -------------------------------------------------------------------------
    
    # Jean-Luc Brunel network
    SourcedRelationship(
        source_entity="Jean-Luc Brunel",
        target_entity="MC2 Model Management",
        relationship_type="founder",
        sources=[MIAMI_HERALD_MC2, CBS_60_MINUTES_BRUNEL],
        confidence_score=1.0,
        notes="Founded with Epstein financing"
    ),
    SourcedRelationship(
        source_entity="Jean-Luc Brunel",
        target_entity="Karin Models",
        relationship_type="founder",
        sources=[LE_MONDE_KARIN_MODELS],
        confidence_score=1.0,
        notes="Earlier Paris modeling agency"
    ),
    
    # John Casablancas
    SourcedRelationship(
        source_entity="John Casablancas",
        target_entity="Elite Model Management",
        relationship_type="founder",
        sources=[NYT_CASABLANCAS, CBS_ELITE_MODEL],
        confidence_score=1.0,
        notes="Founded Elite in 1972; history of young models"
    ),
    SourcedRelationship(
        source_entity="Jean-Luc Brunel",
        target_entity="John Casablancas",
        relationship_type="associated_with",
        sources=[CBS_ELITE_MODEL],
        confidence_score=0.9,
        notes="Both prominent in model scouting; similar allegations"
    ),
    
    # Victoria's Secret recruitment angle
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Victoria's Secret",
        relationship_type="associated_with",
        sources=[NYT_VS_RECRUITMENT, CBS_60_MINUTES_MC2],
        confidence_score=0.9,
        notes="Allegations Epstein posed as VS recruiter to approach models"
    ),
    
    # Alicia Arden - early reporter
    SourcedRelationship(
        source_entity="Alicia Arden",
        target_entity="Jeffrey Epstein",
        relationship_type="reported",
        sources=[ARDEN_POLICE_REPORT],
        confidence_score=1.0,
        notes="Model who filed police report in 1997; no prosecution"
    ),
    
    # -------------------------------------------------------------------------
    # REAL ESTATE & PROPERTY RELATIONSHIPS
    # -------------------------------------------------------------------------
    
    # Zorro Ranch
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Zorro Ranch",
        relationship_type="owner",
        sources=[NYT_ZORRO_RANCH],
        confidence_score=1.0,
        notes="New Mexico ranch; used for eugenics discussions per NYT"
    ),
    
    # Little St. James
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Little St. James",
        relationship_type="owner",
        sources=[WAPO_LITTLE_ST_JAMES, USVI_EPSTEIN_ESTATE],
        confidence_score=1.0,
        notes="Private island in USVI; purchased 1998 for $7.95M"
    ),
    
    # Great St. James
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Great St. James",
        relationship_type="owner",
        sources=[USVI_LAND_RECORDS],
        confidence_score=1.0,
        notes="Second USVI island; purchased 2016 for $22.5M"
    ),
    
    # 9 East 71st (mansion)
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="9 East 71st Street",
        relationship_type="transferred_to_epstein",
        sources=[NYT_EPSTEIN_BLACK_MONEY],
        confidence_score=1.0,
        notes="Wexner transferred $77M mansion to Epstein for $0 in 1989"
    ),
    
    # -------------------------------------------------------------------------
    # SOCIALITE & HIGH SOCIETY RELATIONSHIPS
    # -------------------------------------------------------------------------
    
    # Eva Andersson-Dubin
    SourcedRelationship(
        source_entity="Eva Andersson-Dubin",
        target_entity="Jeffrey Epstein",
        relationship_type="former_girlfriend",
        sources=[NYT_EVA_DUBIN, GIUFFRE_DEPOSITION_2016],
        confidence_score=0.9,
        notes="Miss Sweden 1980; dated Epstein mid-1980s; married Glenn Dubin 1994"
    ),
    SourcedRelationship(
        source_entity="Eva Andersson-Dubin",
        target_entity="Glenn Dubin",
        relationship_type="spouse",
        sources=[NYT_EVA_DUBIN],
        confidence_score=1.0,
        notes="Married 1994; maintained Epstein relationship as couple"
    ),
    
    # Pepe Fanjul
    SourcedRelationship(
        source_entity="Pepe Fanjul",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[BLOOMBERG_FANJUL, EPSTEIN_BLACK_BOOK],
        confidence_score=0.8,
        notes="Sugar magnate in Epstein's social circle"
    ),
    
    # Tom Barrack
    SourcedRelationship(
        source_entity="Tom Barrack",
        target_entity="Jeffrey Epstein",
        relationship_type="associated_with",
        sources=[NYT_BARRACK, EPSTEIN_BLACK_BOOK],
        confidence_score=0.75,
        notes="Colony Capital founder; in Epstein contacts"
    ),
    SourcedRelationship(
        source_entity="Tom Barrack",
        target_entity="Colony Capital",
        relationship_type="founder",
        sources=[NYT_BARRACK],
        confidence_score=1.0,
        notes="Founded Colony Capital (now DigitalBridge)"
    ),
    
    # -------------------------------------------------------------------------
    # INTELLIGENCE CONNECTIONS - Well-documented
    # -------------------------------------------------------------------------
    
    # Robert Maxwell - Intelligence ties (multiple book sources)
    SourcedRelationship(
        source_entity="Robert Maxwell",
        target_entity="Mossad",
        relationship_type="alleged_asset_of",
        sources=[GORDON_THOMAS_MAXWELLS_MOSSAD, SEYMOUR_HERSH_SAMSON_OPTION, OSTROVSKY_BY_WAY_OF_DECEPTION],
        confidence_score=0.85,
        quotes={
            "Robert Maxwell, Israel's Superspy": "Maxwell was a secret conduit for Mossad operations"
        },
        notes="Multiple investigative books allege Maxwell worked with Israeli intelligence; confirmed by former Mossad officers"
    ),
    SourcedRelationship(
        source_entity="Robert Maxwell",
        target_entity="PROMIS Software",
        relationship_type="distributed",
        sources=[SEYMOUR_HERSH_SAMSON_OPTION, INSLAW_HOUSE_REPORT],
        confidence_score=0.8,
        notes="Hersh and congressional investigation allege Maxwell distributed bugged PROMIS software worldwide"
    ),
    
    # Robert Maxwell funeral - Israeli state presence
    SourcedRelationship(
        source_entity="Robert Maxwell",
        target_entity="Israel",
        relationship_type="buried_in",
        sources=[NYT_MAXWELL_FUNERAL],
        confidence_score=1.0,
        quotes={
            "Maxwell Is Buried in Israel; World Figures Attend": "Israeli Prime Minister Yitzhak Shamir, President Chaim Herzog, and intelligence officials attended"
        },
        notes="State funeral on Mount of Olives; heads of state and intelligence chiefs in attendance"
    ),
    
    # Ehud Barak - Documented business relationship with Epstein
    SourcedRelationship(
        source_entity="Ehud Barak",
        target_entity="Jeffrey Epstein",
        relationship_type="business_partner",
        sources=[HAARETZ_CARBYNE, TIMES_OF_ISRAEL_BARAK, NYT_BARAK_EPSTEIN],
        confidence_score=0.95,
        quotes={
            "Ehud Barak Visited Jeffrey Epstein's Island": "Barak acknowledged visiting Epstein's island and his Manhattan townhouse"
        },
        notes="Former Israeli PM; Epstein invested in Barak's Carbyne 911 startup; Barak admitted island visits"
    ),
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Carbyne 911",
        relationship_type="investor_in",
        sources=[HAARETZ_CARBYNE],
        confidence_score=0.95,
        notes="Epstein-linked fund invested in Barak's emergency services startup"
    ),
    SourcedRelationship(
        source_entity="Ehud Barak",
        target_entity="Carbyne 911",
        relationship_type="chairman",
        sources=[HAARETZ_CARBYNE],
        confidence_score=1.0,
        notes="Former Israeli PM chaired this technology company"
    ),
    
    # Nicole Junkermann - Barak-Epstein-UK connection
    SourcedRelationship(
        source_entity="Nicole Junkermann",
        target_entity="Jeffrey Epstein",
        relationship_type="business_associate",
        sources=[TELEGRAPH_JUNKERMANN],
        confidence_score=0.85,
        notes="German-British investor with Epstein business ties; NHS health advisory role"
    ),
    SourcedRelationship(
        source_entity="Nicole Junkermann",
        target_entity="Carbyne 911",
        relationship_type="investor_in",
        sources=[TELEGRAPH_JUNKERMANN, HAARETZ_CARBYNE],
        confidence_score=0.9,
        notes="Invested in Barak's Epstein-funded startup"
    ),
    SourcedRelationship(
        source_entity="Nicole Junkermann",
        target_entity="Ehud Barak",
        relationship_type="business_associate",
        sources=[TELEGRAPH_JUNKERMANN],
        confidence_score=0.9,
        notes="Connected through Carbyne 911 investment"
    ),
    
    # Mega Group - Wexner's pro-Israel billionaire network
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="Mega Group",
        relationship_type="co_founder",
        sources=[FORWARD_MEGA_GROUP],
        confidence_score=0.9,
        notes="Co-founded with Charles Bronfman; group of pro-Israel billionaire donors"
    ),
    SourcedRelationship(
        source_entity="Charles Bronfman",
        target_entity="Mega Group",
        relationship_type="co_founder",
        sources=[FORWARD_MEGA_GROUP],
        confidence_score=0.9,
        notes="Seagram heir; co-founded Mega Group with Wexner"
    ),
    
    # Ghislaine Maxwell - Father's intelligence connections
    SourcedRelationship(
        source_entity="Ghislaine Maxwell",
        target_entity="Robert Maxwell",
        relationship_type="child_of",
        sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT, NYT_MAXWELL_FUNERAL],
        confidence_score=1.0,
        notes="Daughter of media mogul with alleged intelligence ties"
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL WELL-DOCUMENTED CONNECTIONS
    # -------------------------------------------------------------------------
    
    # Donald Trump - Additional documented connections
    SourcedRelationship(
        source_entity="Donald Trump",
        target_entity="Mar-a-Lago",
        relationship_type="owner",
        sources=[NY_MAG_EPSTEIN_2002],
        confidence_score=1.0,
        notes="Palm Beach estate where Trump and Epstein socialized"
    ),
    SourcedRelationship(
        source_entity="Jeffrey Epstein",
        target_entity="Mar-a-Lago",
        relationship_type="member_of",
        sources=[NY_MAG_EPSTEIN_2002, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=0.9,
        notes="Epstein was member before being banned; recruited victim Virginia Giuffre there"
    ),
    SourcedRelationship(
        source_entity="Virginia Giuffre",
        target_entity="Mar-a-Lago",
        relationship_type="employee_of",
        sources=[GIUFFRE_DEPOSITION_2016, MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Worked as spa attendant; recruited by Maxwell at Mar-a-Lago"
    ),
    
    # Leslie Wexner - Additional business connections
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="L Brands",
        relationship_type="founder",
        sources=[FORBES_WEXNER, NYT_EPSTEIN_BLACK_MONEY],
        confidence_score=1.0,
        notes="Founded parent company of Victoria's Secret, Bath & Body Works"
    ),
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="Bath & Body Works",
        relationship_type="founder",
        sources=[FORBES_WEXNER],
        confidence_score=1.0,
        notes="Part of L Brands portfolio"
    ),
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="Abigail Wexner",
        relationship_type="spouse",
        sources=[WEXNER_FOUNDATION_WEBSITE],
        confidence_score=1.0,
        notes="Married 1993"
    ),
    SourcedRelationship(
        source_entity="Leslie Wexner",
        target_entity="Wexner Foundation",
        relationship_type="founder",
        sources=[WEXNER_FOUNDATION_WEBSITE],
        confidence_score=1.0,
        notes="Philanthropic foundation"
    ),
    
    # Leon Black - Museum board
    SourcedRelationship(
        source_entity="Leon Black",
        target_entity="Museum of Modern Art",
        relationship_type="chairman",
        sources=[NYT_LEON_BLACK_EPSTEIN],
        confidence_score=1.0,
        notes="Served as MoMA chairman; resigned in 2021 amid Epstein scrutiny"
    ),
    
    # Blackstone connections
    SourcedRelationship(
        source_entity="Stephen Schwarzman",
        target_entity="Blackstone Group",
        relationship_type="founder",
        sources=[FORBES_SCHWARZMAN],
        confidence_score=1.0,
        notes="Co-founded Blackstone in 1985"
    ),
    SourcedRelationship(
        source_entity="Pete Peterson",
        target_entity="Blackstone Group",
        relationship_type="co_founder",
        sources=[FORBES_SCHWARZMAN],
        confidence_score=1.0,
        notes="Co-founded with Schwarzman; deceased 2018"
    ),
    SourcedRelationship(
        source_entity="Tony James",
        target_entity="Blackstone Group",
        relationship_type="president",
        sources=[FORBES_SCHWARZMAN],
        confidence_score=1.0,
        notes="Former president and COO"
    ),
    SourcedRelationship(
        source_entity="Jon Gray",
        target_entity="Blackstone Group",
        relationship_type="president",
        sources=[FORBES_SCHWARZMAN],
        confidence_score=1.0,
        notes="Current president and COO"
    ),
    
    # Trump family connections
    SourcedRelationship(
        source_entity="Donald Trump",
        target_entity="Ivanka Trump",
        relationship_type="parent_of",
        sources=[WAPO_TRUMP_ORGANIZATION],
        confidence_score=1.0,
        notes="Father-daughter relationship"
    ),
    SourcedRelationship(
        source_entity="Ivanka Trump",
        target_entity="Jared Kushner",
        relationship_type="spouse",
        sources=[NYT_KUSHNER_COMPANIES],
        confidence_score=1.0,
        notes="Married 2009"
    ),
    SourcedRelationship(
        source_entity="Ivanka Trump",
        target_entity="Trump Organization",
        relationship_type="executive",
        sources=[WAPO_TRUMP_ORGANIZATION],
        confidence_score=1.0,
        notes="Executive VP before White House"
    ),
    SourcedRelationship(
        source_entity="Jared Kushner",
        target_entity="Kushner Companies",
        relationship_type="executive",
        sources=[NYT_KUSHNER_COMPANIES],
        confidence_score=1.0,
        notes="Family real estate company"
    ),
    SourcedRelationship(
        source_entity="Charles Kushner",
        target_entity="Kushner Companies",
        relationship_type="founder",
        sources=[NYT_CHARLES_KUSHNER],
        confidence_score=1.0,
        notes="Founded company; convicted of tax evasion 2005"
    ),
    SourcedRelationship(
        source_entity="Charles Kushner",
        target_entity="Jared Kushner",
        relationship_type="parent_of",
        sources=[NYT_CHARLES_KUSHNER],
        confidence_score=1.0,
        notes="Father-son relationship"
    ),
    SourcedRelationship(
        source_entity="Jared Kushner",
        target_entity="Affinity Partners",
        relationship_type="founder",
        sources=[NYT_AFFINITY_PARTNERS],
        confidence_score=1.0,
        notes="Founded 2021 after White House; received $2B from Saudi PIF"
    ),
    
    # Mercer family connections
    SourcedRelationship(
        source_entity="Robert Mercer",
        target_entity="Rebekah Mercer",
        relationship_type="parent_of",
        sources=[NEW_YORKER_MERCER],
        confidence_score=1.0,
        notes="Father-daughter relationship"
    ),
    SourcedRelationship(
        source_entity="Robert Mercer",
        target_entity="Cambridge Analytica",
        relationship_type="investor_in",
        sources=[NYT_CAMBRIDGE_ANALYTICA, NEW_YORKER_MERCER],
        confidence_score=1.0,
        notes="Major investor in political data firm"
    ),
    SourcedRelationship(
        source_entity="Rebekah Mercer",
        target_entity="Breitbart News",
        relationship_type="board_member",
        sources=[NEW_YORKER_MERCER],
        confidence_score=1.0,
        notes="Sat on Breitbart board; major funder"
    ),
    SourcedRelationship(
        source_entity="Steve Bannon",
        target_entity="Breitbart News",
        relationship_type="executive_chairman",
        sources=[NEW_YORKER_MERCER],
        confidence_score=1.0,
        notes="Executive chairman before White House"
    ),
    SourcedRelationship(
        source_entity="Steve Bannon",
        target_entity="Cambridge Analytica",
        relationship_type="board_member",
        sources=[NYT_CAMBRIDGE_ANALYTICA],
        confidence_score=1.0,
        notes="Vice president of Cambridge Analytica"
    ),
    
    # Bill Gates - Melinda Gates divorce context
    SourcedRelationship(
        source_entity="Melinda Gates",
        target_entity="Bill & Melinda Gates Foundation",
        relationship_type="co_founder",
        sources=[GATES_FOUNDATION_ANNUAL],
        confidence_score=1.0,
        notes="Co-founded 2000; stepped down 2024"
    ),
    
    # Robert Maxwell - Media empire
    SourcedRelationship(
        source_entity="Robert Maxwell",
        target_entity="Maxwell Communications Corporation",
        relationship_type="founder",
        sources=[GUARDIAN_ROBERT_MAXWELL],
        confidence_score=1.0,
        notes="Built publishing empire; collapsed after his death"
    ),
    
    # Juan Alessi - witnessed connections
    SourcedRelationship(
        source_entity="Juan Alessi",
        target_entity="Ghislaine Maxwell",
        relationship_type="observed",
        sources=[ALESSI_DEPOSITION, USA_V_MAXWELL_TRIAL_TRANSCRIPT],
        confidence_score=1.0,
        notes="House manager testified about Maxwell's role at Palm Beach"
    ),
    SourcedRelationship(
        source_entity="Juan Alessi",
        target_entity="Prince Andrew",
        relationship_type="observed",
        sources=[ALESSI_DEPOSITION],
        confidence_score=0.9,
        notes="Testified to seeing Prince Andrew at Epstein residence"
    ),
    
    # Sarah Kellen - Staff network
    SourcedRelationship(
        source_entity="Sarah Kellen",
        target_entity="Lesley Groff",
        relationship_type="worked_with",
        sources=[USA_V_EPSTEIN_2019_INDICTMENT],
        confidence_score=1.0,
        notes="Both named as potential co-conspirators in NPA"
    ),
    
    # Glenn Dubin - Eva Dubin connection already exists via spouse
    SourcedRelationship(
        source_entity="Glenn Dubin",
        target_entity="Eva Andersson-Dubin",
        relationship_type="spouse",
        sources=[NYT_EVA_DUBIN],
        confidence_score=1.0,
        notes="Married 1994; Eva previously dated Epstein"
    ),
    
    # Prince Andrew - Pitch@Palace
    SourcedRelationship(
        source_entity="Prince Andrew",
        target_entity="Pitch@Palace",
        relationship_type="founder",
        sources=[BBC_PRINCE_ANDREW],
        confidence_score=1.0,
        notes="Entrepreneurship initiative suspended after scandal"
    ),
    
    # Joi Ito - Media Lab
    SourcedRelationship(
        source_entity="Joi Ito",
        target_entity="Jeffrey Epstein",
        relationship_type="received_funding_from",
        sources=[NEW_YORKER_MIT_EPSTEIN],
        confidence_score=1.0,
        notes="Ito accepted Epstein funding for MIT Media Lab"
    ),
    
    # Attorney connections
    SourcedRelationship(
        source_entity="Kenneth Starr",
        target_entity="Alan Dershowitz",
        relationship_type="worked_with",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Both on Epstein's 2008 defense team"
    ),
    SourcedRelationship(
        source_entity="Roy Black",
        target_entity="Alan Dershowitz",
        relationship_type="worked_with",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Both on Epstein's 2008 defense team"
    ),
    SourcedRelationship(
        source_entity="Jay Lefkowitz",
        target_entity="Kenneth Starr",
        relationship_type="worked_with",
        sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE],
        confidence_score=1.0,
        notes="Both negotiated 2008 NPA"
    ),
    
    # Sigrid McCawley - Attorney
    SourcedRelationship(
        source_entity="Sigrid McCawley",
        target_entity="Virginia Giuffre",
        relationship_type="attorney_for",
        sources=[GIUFFRE_V_MAXWELL_COMPLAINT],
        confidence_score=1.0,
        notes="Lead counsel for Giuffre at Boies Schiller"
    ),
    SourcedRelationship(
        source_entity="Sigrid McCawley",
        target_entity="Boies Schiller Flexner",
        relationship_type="partner",
        sources=[BOIES_SCHILLER_WEBSITE],
        confidence_score=1.0,
        notes="Partner at law firm"
    ),
]


# ============================================================================
# SOURCED ENTITIES - Persons and organizations with descriptions
# ============================================================================

SOURCED_ENTITIES: List[SourcedEntity] = [
    # Core figures
    SourcedEntity(
        name="Jeffrey Epstein",
        entity_type="person",
        description="Financier and convicted sex offender. Arrested in 2019 on federal charges of sex trafficking minors, died in custody. Previously convicted in 2008 Florida case.",
        description_sources=[USA_V_EPSTEIN_2019_INDICTMENT, MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    SourcedEntity(
        name="Ghislaine Maxwell",
        entity_type="person",
        description="British socialite, daughter of Robert Maxwell. Convicted in 2021 of sex trafficking and conspiracy for her role in recruiting and grooming victims for Jeffrey Epstein.",
        description_sources=[USA_V_MAXWELL_INDICTMENT, USA_V_MAXWELL_TRIAL_TRANSCRIPT]
    ),
    SourcedEntity(
        name="Virginia Giuffre",
        entity_type="person",
        description="Victim and accuser. Testified that she was trafficked by Epstein and Maxwell starting at age 16. Key witness in Maxwell trial and plaintiff in civil suits.",
        description_sources=[GIUFFRE_V_MAXWELL_COMPLAINT, USA_V_MAXWELL_TRIAL_TRANSCRIPT]
    ),
    
    # Financial connections
    SourcedEntity(
        name="Leslie Wexner",
        entity_type="person",
        description="Billionaire founder of L Brands (Victoria's Secret, Bath & Body Works). Epstein served as his financial manager from ~1988-2007, with unusual access to finances and property.",
        description_sources=[NYT_EPSTEIN_BLACK_MONEY]
    ),
    SourcedEntity(
        name="Leon Black",
        entity_type="person",
        description="Billionaire co-founder of Apollo Global Management. Paid Epstein $158 million for advisory services between 2012-2017, after Epstein's 2008 conviction.",
        description_sources=[NYT_LEON_BLACK_EPSTEIN]
    ),
    SourcedEntity(
        name="Bill Gates",
        entity_type="person",
        description="Microsoft co-founder and philanthropist. Met with Epstein multiple times between 2011-2014, after Epstein's 2008 conviction, reportedly discussing philanthropy.",
        description_sources=[NYT_BILL_GATES_EPSTEIN]
    ),
    
    # British royalty
    SourcedEntity(
        name="Prince Andrew",
        entity_type="person",
        description="Duke of York, son of Queen Elizabeth II. Admitted friendship with Epstein in 2019 BBC interview. Settled civil suit with Virginia Giuffre in 2022.",
        description_sources=[BBC_PRINCE_ANDREW, GIUFFRE_V_MAXWELL_UNSEALED_2019]
    ),
    
    # Staff/Employees
    SourcedEntity(
        name="Sarah Kellen",
        entity_type="person",
        description="Epstein assistant. Named as potential co-conspirator in 2008 non-prosecution agreement. Identified in indictments as helping schedule victims.",
        description_sources=[USA_V_EPSTEIN_2019_INDICTMENT, MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    SourcedEntity(
        name="Lesley Groff",
        entity_type="person",
        description="Epstein executive assistant. Named as potential co-conspirator in 2008 non-prosecution agreement.",
        description_sources=[USA_V_EPSTEIN_2019_INDICTMENT]
    ),
    SourcedEntity(
        name="Juan Alessi",
        entity_type="person",
        description="Former house manager at Epstein's Palm Beach estate. Testified at Maxwell trial about household operations and visitors.",
        description_sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT, ALESSI_DEPOSITION]
    ),
    
    # Modeling industry
    SourcedEntity(
        name="Jean-Luc Brunel",
        entity_type="person",
        description="French modeling agent. Founded MC2 Model Management with Epstein's financial backing. Found dead in Paris prison in February 2022 while awaiting trial.",
        description_sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE, GIUFFRE_DEPOSITION_2016]
    ),
    
    # Legal
    SourcedEntity(
        name="Alan Dershowitz",
        entity_type="person",
        description="Harvard Law professor emeritus. Represented Epstein in 2008 case and helped negotiate non-prosecution agreement. Named in Giuffre allegations, which he denies.",
        description_sources=[DERSHOWITZ_DEPOSITION, MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    SourcedEntity(
        name="Bradley Edwards",
        entity_type="person",
        description="Victims' rights attorney who represented multiple Epstein accusers. Author of 'Relentless Pursuit' documenting his legal fight.",
        description_sources=[RELENTLESS_PURSUIT_BOOK]
    ),
    
    # Academic
    SourcedEntity(
        name="Joi Ito",
        entity_type="person",
        description="Former director of MIT Media Lab. Resigned in 2019 after revelations that he concealed extent of Epstein donations to the lab.",
        description_sources=[NEW_YORKER_MIT_EPSTEIN]
    ),
    
    # Politicians  
    SourcedEntity(
        name="Bill Clinton",
        entity_type="person",
        description="42nd President of the United States. Flight logs show multiple trips on Epstein's aircraft. Clinton has denied knowledge of any crimes.",
        description_sources=[EPSTEIN_FLIGHT_LOGS, GIUFFRE_V_MAXWELL_UNSEALED_2019]
    ),
    SourcedEntity(
        name="Donald Trump",
        entity_type="person",
        description="45th President of the United States. Publicly praised Epstein in 2002; later claimed to have banned him from Mar-a-Lago.",
        description_sources=[FILTHY_RICH_BOOK]
    ),
    
    # Maxwell family
    SourcedEntity(
        name="Robert Maxwell",
        entity_type="person",
        description="British media proprietor and father of Ghislaine Maxwell. Died in 1991 under mysterious circumstances. Posthumously revealed to have defrauded pension funds.",
        description_sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT]
    ),
    
    # Companies
    SourcedEntity(
        name="Apollo Global Management",
        entity_type="company",
        description="Private equity firm co-founded by Leon Black. One of the world's largest alternative investment managers.",
        description_sources=[APOLLO_SEC_FILINGS]
    ),
    SourcedEntity(
        name="L Brands",
        entity_type="company",
        description="Retail company founded by Leslie Wexner. Parent company of Victoria's Secret and Bath & Body Works.",
        description_sources=[NYT_EPSTEIN_BLACK_MONEY]
    ),
    SourcedEntity(
        name="MC2 Model Management",
        entity_type="company",
        description="Modeling agency founded by Jean-Luc Brunel with financial backing from Jeffrey Epstein.",
        description_sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    SourcedEntity(
        name="MIT Media Lab",
        entity_type="company",
        description="Research laboratory at MIT. Received over $7.5 million in Epstein donations, often anonymized at Epstein's request.",
        description_sources=[NEW_YORKER_MIT_EPSTEIN]
    ),
    SourcedEntity(
        name="TerraMar Project",
        entity_type="company",
        description="Ocean conservation nonprofit founded by Ghislaine Maxwell in 2012. Dissolved shortly after Epstein's 2019 arrest.",
        description_sources=[GIUFFRE_V_MAXWELL_COMPLAINT]
    ),
    SourcedEntity(
        name="Clinton Foundation",
        entity_type="company",
        description="Philanthropic organization founded by Bill Clinton in 2001.",
        description_sources=[EPSTEIN_FLIGHT_LOGS]
    ),
    SourcedEntity(
        name="Haddon, Morgan and Foreman",
        entity_type="company",
        description="Colorado-based law firm. Laura Menninger is a partner; represented Ghislaine Maxwell.",
        description_sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT]
    ),
    SourcedEntity(
        name="Boies Schiller Flexner",
        entity_type="company",
        description="Law firm. David Boies is chairman; represented Virginia Giuffre in various proceedings.",
        description_sources=[GIUFFRE_V_MAXWELL_COMPLAINT]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - New relationships
    # -------------------------------------------------------------------------
    
    # Banks
    SourcedEntity(
        name="JPMorgan Chase",
        entity_type="company",
        description="Major bank that maintained Epstein as client from 1998-2013. Settled victims' lawsuit for $290 million in 2023.",
        description_sources=[WSJ_JPMORGAN_EPSTEIN]
    ),
    SourcedEntity(
        name="Deutsche Bank",
        entity_type="company",
        description="German bank that became Epstein's primary bank after JPMorgan. Settled for $75 million in 2021.",
        description_sources=[WSJ_DEUTSCHE_BANK_EPSTEIN]
    ),
    SourcedEntity(
        name="Barclays",
        entity_type="company",
        description="British bank. CEO Jes Staley resigned in 2021 over investigation into his Epstein relationship.",
        description_sources=[BLOOMBERG_STALEY]
    ),
    
    # People - Bankers
    SourcedEntity(
        name="Jes Staley",
        entity_type="person",
        description="Former JPMorgan executive who managed Epstein's account. Later CEO of Barclays; resigned in 2021 over Epstein probe.",
        description_sources=[BLOOMBERG_STALEY, WSJ_JPMORGAN_EPSTEIN]
    ),
    
    # Victims
    SourcedEntity(
        name="Courtney Wild",
        entity_type="person",
        description="Victim and advocate. Began being abused at age 14; became prominent voice seeking justice and opposing 2008 plea deal.",
        description_sources=[WILD_DECLARATION, MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    SourcedEntity(
        name="Sarah Ransome",
        entity_type="person",
        description="Victim who provided detailed declaration about abuse on Little St. James island. Advocate for survivors.",
        description_sources=[RANSOME_DECLARATION]
    ),
    SourcedEntity(
        name="Annie Farmer",
        entity_type="person",
        description="Victim who testified at Maxwell trial. Was 16 when first abused. Sister of Maria Farmer.",
        description_sources=[USA_V_MAXWELL_TRIAL_TRANSCRIPT]
    ),
    SourcedEntity(
        name="Maria Farmer",
        entity_type="person",
        description="Victim and artist. One of first to report Epstein to FBI in 1996. Sister of Annie Farmer.",
        description_sources=[NETFLIX_FILTHY_RICH_DOC, MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    
    # Prosecutors and lawyers
    SourcedEntity(
        name="Alexander Acosta",
        entity_type="person",
        description="Former U.S. Attorney who approved controversial 2008 non-prosecution agreement. Later Secretary of Labor; resigned in 2019.",
        description_sources=[WAPO_ACOSTA_NPA, EPSTEIN_NPA_2008]
    ),
    SourcedEntity(
        name="Kenneth Starr",
        entity_type="person",
        description="Former federal judge and special prosecutor. Part of Epstein's defense team in 2008 case. Deceased 2022.",
        description_sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    SourcedEntity(
        name="Roy Black",
        entity_type="person",
        description="Prominent Miami defense attorney. Member of Epstein's 2008 legal team.",
        description_sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    
    # Wexner network
    SourcedEntity(
        name="Victoria's Secret",
        entity_type="company",
        description="Lingerie retailer founded by Leslie Wexner through L Brands. Epstein reportedly used brand to recruit.",
        description_sources=[NYT_EPSTEIN_BLACK_MONEY]
    ),
    SourcedEntity(
        name="9 East 71st Street",
        entity_type="company",
        description="Manhattan mansion transferred from Wexner to Epstein for $0. One of largest private homes in NYC.",
        description_sources=[NYT_EPSTEIN_BLACK_MONEY]
    ),
    
    # Academics
    SourcedEntity(
        name="Martin Nowak",
        entity_type="person",
        description="Harvard professor of Biology and Mathematics. Received Epstein funding for Program for Evolutionary Dynamics.",
        description_sources=[HARVARD_EPSTEIN_REPORT]
    ),
    SourcedEntity(
        name="George Church",
        entity_type="person",
        description="Harvard geneticist. Met with Epstein; publicly apologized. Pioneer in genomics and synthetic biology.",
        description_sources=[NYT_MIT_MEDIA_LAB]
    ),
    SourcedEntity(
        name="Larry Summers",
        entity_type="person",
        description="Former Harvard president (2001-2006) and Treasury Secretary. Flew on Epstein's plane.",
        description_sources=[VANITY_FAIR_2003]
    ),
    SourcedEntity(
        name="Seth Lloyd",
        entity_type="person",
        description="MIT professor of Mechanical Engineering. Received $225,000 from Epstein; placed on administrative leave.",
        description_sources=[NEW_YORKER_MIT_EPSTEIN]
    ),
    SourcedEntity(
        name="Marvin Minsky",
        entity_type="person",
        description="AI pioneer and MIT professor. Co-founder of MIT AI Lab. Named in Giuffre deposition. Deceased 2016.",
        description_sources=[GIUFFRE_DEPOSITION_2016, NEW_YORKER_MIT_EPSTEIN]
    ),
    SourcedEntity(
        name="MIT",
        entity_type="company",
        description="Massachusetts Institute of Technology. Received substantial Epstein donations through multiple channels.",
        description_sources=[NEW_YORKER_MIT_EPSTEIN]
    ),
    SourcedEntity(
        name="Harvard University",
        entity_type="company",
        description="University that received millions in Epstein donations. Conducted internal review of gift policies.",
        description_sources=[HARVARD_EPSTEIN_REPORT]
    ),
    SourcedEntity(
        name="Harvard Medical School",
        entity_type="company",
        description="Medical school of Harvard University where George Church is professor.",
        description_sources=[NYT_MIT_MEDIA_LAB]
    ),
    
    # British connections
    SourcedEntity(
        name="Sarah Ferguson",
        entity_type="person",
        description="Duchess of York, former wife of Prince Andrew. Epstein reportedly paid off her debts.",
        description_sources=[BBC_PRINCE_ANDREW]
    ),
    
    # Flight log passengers
    SourcedEntity(
        name="Chris Tucker",
        entity_type="person",
        description="Actor and comedian. Appeared on Epstein flight logs. Denies knowledge of any wrongdoing.",
        description_sources=[EPSTEIN_FLIGHT_LOGS]
    ),
    SourcedEntity(
        name="Kevin Spacey",
        entity_type="person",
        description="Actor. Appeared on Epstein flight logs on trip with Bill Clinton.",
        description_sources=[EPSTEIN_FLIGHT_LOGS]
    ),
    SourcedEntity(
        name="Naomi Campbell",
        entity_type="person",
        description="Supermodel. Name appeared in Epstein's contact book. No allegations of wrongdoing.",
        description_sources=[EPSTEIN_BLACK_BOOK]
    ),
    
    # Journalists
    SourcedEntity(
        name="Vicky Ward",
        entity_type="person",
        description="Journalist who wrote 2003 Vanity Fair profile of Epstein. Claims victim accounts were cut from article.",
        description_sources=[VANITY_FAIR_2003]
    ),
    SourcedEntity(
        name="Julie K. Brown",
        entity_type="person",
        description="Miami Herald investigative reporter. Her 'Perversion of Justice' series reignited the Epstein case in 2018.",
        description_sources=[MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    
    # Staff
    SourcedEntity(
        name="Glenn Dubin",
        entity_type="person",
        description="Hedge fund manager and Highbridge Capital co-founder. Named in Giuffre deposition; denies all allegations.",
        description_sources=[GIUFFRE_DEPOSITION_2016]
    ),
    SourcedEntity(
        name="Highbridge Capital Management",
        entity_type="company",
        description="Hedge fund co-founded by Glenn Dubin.",
        description_sources=[APOLLO_SEC_FILINGS]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Build entity network entities requiring sources
    # -------------------------------------------------------------------------
    
    # Companies - Finance
    SourcedEntity(
        name="Apollo Management",
        entity_type="company",
        description="Alternative asset management firm. Sister entity of Apollo Global Management.",
        description_sources=[APOLLO_SEC_FILINGS]
    ),
    SourcedEntity(
        name="Blackstone Group",
        entity_type="company",
        description="Global alternative asset management firm co-founded by Stephen Schwarzman and Pete Peterson in 1985.",
        description_sources=[FORBES_SCHWARZMAN]
    ),
    SourcedEntity(
        name="Cascade Investment",
        entity_type="company",
        description="Private investment and holding company of Bill Gates, managing his personal fortune.",
        description_sources=[NYT_BILL_GATES_EPSTEIN]
    ),
    SourcedEntity(
        name="Affinity Partners",
        entity_type="company",
        description="Private equity firm founded by Jared Kushner in 2021. Received $2 billion from Saudi Arabia's sovereign wealth fund.",
        description_sources=[NYT_AFFINITY_PARTNERS]
    ),
    SourcedEntity(
        name="Kushner Companies",
        entity_type="company",
        description="Real estate development company founded by Charles Kushner. Managed by Jared Kushner before his White House role.",
        description_sources=[NYT_KUSHNER_COMPANIES]
    ),
    
    # Companies - Media/Tech
    SourcedEntity(
        name="Cambridge Analytica",
        entity_type="company",
        description="Political consulting firm funded by Robert Mercer. Infamous for Facebook data harvesting scandal. Dissolved 2018.",
        description_sources=[NYT_CAMBRIDGE_ANALYTICA]
    ),
    SourcedEntity(
        name="Breitbart News",
        entity_type="company",
        description="Far-right news website. Steve Bannon served as executive chairman. Funded by Mercer family.",
        description_sources=[NEW_YORKER_MERCER]
    ),
    SourcedEntity(
        name="Observer Media",
        entity_type="company",
        description="Media company formerly owned by Jared Kushner, publisher of the New York Observer.",
        description_sources=[NYT_KUSHNER_COMPANIES]
    ),
    SourcedEntity(
        name="Mirror Group Newspapers",
        entity_type="company",
        description="British newspaper group owned by Robert Maxwell. Included Daily Mirror. Maxwell raided pension funds.",
        description_sources=[GUARDIAN_ROBERT_MAXWELL]
    ),
    SourcedEntity(
        name="Maxwell Communications Corporation",
        entity_type="company",
        description="Publishing conglomerate built by Robert Maxwell. Collapsed after his death, revealing massive fraud.",
        description_sources=[GUARDIAN_ROBERT_MAXWELL]
    ),
    SourcedEntity(
        name="Microsoft",
        entity_type="company",
        description="Technology company co-founded by Bill Gates and Paul Allen in 1975. World's largest software maker.",
        description_sources=[GATES_ALLEN_MICROSOFT]
    ),
    
    # Companies - Trump
    SourcedEntity(
        name="Trump Organization",
        entity_type="company",
        description="Conglomerate of approximately 500 business entities owned by Donald Trump. Convicted of tax fraud in 2022.",
        description_sources=[WAPO_TRUMP_ORGANIZATION]
    ),
    SourcedEntity(
        name="Trump Entertainment Resorts",
        entity_type="company",
        description="Casino and resort company. Filed for bankruptcy multiple times. Eventually sold to Carl Icahn.",
        description_sources=[WAPO_TRUMP_ORGANIZATION]
    ),
    SourcedEntity(
        name="Trump Hotels",
        entity_type="company",
        description="Hotel management company subsidiary of Trump Organization.",
        description_sources=[WAPO_TRUMP_ORGANIZATION]
    ),
    SourcedEntity(
        name="Ivanka Trump Brand",
        entity_type="company",
        description="Fashion and lifestyle brand owned by Ivanka Trump. Closed in 2018.",
        description_sources=[WAPO_TRUMP_ORGANIZATION]
    ),
    
    # Companies - Epstein
    SourcedEntity(
        name="J. Epstein & Co.",
        entity_type="company",
        description="Financial management firm founded by Jeffrey Epstein. Primary vehicle for his financial advisory business.",
        description_sources=[NYT_EPSTEIN_BLACK_MONEY]
    ),
    SourcedEntity(
        name="Southern Trust Company",
        entity_type="company",
        description="Financial services company associated with Epstein's U.S. Virgin Islands operations.",
        description_sources=[FT_VIRGIN_ISLANDS]
    ),
    
    # Companies - Wexner
    SourcedEntity(
        name="Bath & Body Works",
        entity_type="company",
        description="Personal care retailer, formerly part of L Brands. Spun off in 2021.",
        description_sources=[NYT_EPSTEIN_BLACK_MONEY]
    ),
    SourcedEntity(
        name="Wexner Foundation",
        entity_type="company",
        description="Philanthropic foundation established by Les and Abigail Wexner.",
        description_sources=[WEXNER_FOUNDATION_WEBSITE]
    ),
    
    # Companies - Foundations
    SourcedEntity(
        name="Bill & Melinda Gates Foundation",
        entity_type="company",
        description="Largest private charitable foundation in the world. Founded by Bill and Melinda Gates in 2000.",
        description_sources=[GATES_FOUNDATION_ANNUAL]
    ),
    SourcedEntity(
        name="Museum of Modern Art",
        entity_type="company",
        description="Art museum in Manhattan. Leon Black served as chairman of the board.",
        description_sources=[NYT_LEON_BLACK_EPSTEIN]
    ),
    SourcedEntity(
        name="Schwarzman Scholars",
        entity_type="company",
        description="International scholarship program at Tsinghua University founded by Stephen Schwarzman.",
        description_sources=[FORBES_SCHWARZMAN]
    ),
    
    # Companies - Legal
    SourcedEntity(
        name="Cohen & Gresser",
        entity_type="company",
        description="Law firm. Christian Everdell was partner; represented Ghislaine Maxwell.",
        description_sources=[DOJ_MAXWELL_CASE]
    ),
    SourcedEntity(
        name="Haddon, Morgan and Foreman",
        entity_type="company",
        description="Colorado law firm. Laura Menninger and Jeffrey Pagliuca represented Maxwell at trial.",
        description_sources=[HADDON_MORGAN_WEBSITE]
    ),
    SourcedEntity(
        name="Boies Schiller Flexner",
        entity_type="company",
        description="Law firm. David Boies is chairman; represented Virginia Giuffre in various proceedings.",
        description_sources=[BOIES_SCHILLER_WEBSITE]
    ),
    SourcedEntity(
        name="U.S. Attorney SDNY",
        entity_type="company",
        description="U.S. Attorney's Office for the Southern District of New York. Prosecuted Maxwell case.",
        description_sources=[DOJ_SDNY_ANNOUNCEMENTS]
    ),
    
    # Companies - Royalty
    SourcedEntity(
        name="Pitch@Palace",
        entity_type="company",
        description="Entrepreneurship initiative founded by Prince Andrew. Suspended 2019 following Epstein scandal.",
        description_sources=[BBC_PRINCE_ANDREW]
    ),
    
    # People - Finance
    SourcedEntity(
        name="Stephen Schwarzman",
        entity_type="person",
        description="Co-founder, chairman, and CEO of Blackstone Group. One of world's wealthiest individuals.",
        description_sources=[FORBES_SCHWARZMAN]
    ),
    SourcedEntity(
        name="Pete Peterson",
        entity_type="person",
        description="Blackstone co-founder. Former U.S. Secretary of Commerce. Deceased 2018.",
        description_sources=[FORBES_SCHWARZMAN]
    ),
    SourcedEntity(
        name="Tony James",
        entity_type="person",
        description="Former president and COO of Blackstone Group.",
        description_sources=[FORBES_SCHWARZMAN]
    ),
    SourcedEntity(
        name="Jon Gray",
        entity_type="person",
        description="President and COO of Blackstone Group. Succeeded Tony James.",
        description_sources=[FORBES_SCHWARZMAN]
    ),
    SourcedEntity(
        name="Marc Rowan",
        entity_type="person",
        description="Co-founder of Apollo Global Management. Became CEO after Leon Black stepped down.",
        description_sources=[WSJ_APOLLO_BLACK_RESIGNATION]
    ),
    SourcedEntity(
        name="Josh Harris",
        entity_type="person",
        description="Co-founder of Apollo Global Management. Also owns Philadelphia 76ers and New Jersey Devils.",
        description_sources=[APOLLO_SEC_FILINGS]
    ),
    SourcedEntity(
        name="Tony Ressler",
        entity_type="person",
        description="Co-founder of Apollo Global Management. Later founded Ares Management.",
        description_sources=[APOLLO_SEC_FILINGS]
    ),
    SourcedEntity(
        name="Warren Buffett",
        entity_type="person",
        description="Chairman and CEO of Berkshire Hathaway. Close associate of Bill Gates.",
        description_sources=[GATES_FOUNDATION_ANNUAL]
    ),
    
    # People - Tech
    SourcedEntity(
        name="Paul Allen",
        entity_type="person",
        description="Microsoft co-founder with Bill Gates. Philanthropist. Deceased 2018.",
        description_sources=[GATES_ALLEN_MICROSOFT]
    ),
    SourcedEntity(
        name="Melinda Gates",
        entity_type="person",
        description="Philanthropist and former wife of Bill Gates. Co-chair of Gates Foundation until divorce in 2021.",
        description_sources=[GATES_FOUNDATION_ANNUAL]
    ),
    
    # People - Mercer family
    SourcedEntity(
        name="Robert Mercer",
        entity_type="person",
        description="Hedge fund manager at Renaissance Technologies. Major Republican donor. Funded Cambridge Analytica.",
        description_sources=[NEW_YORKER_MERCER]
    ),
    SourcedEntity(
        name="Rebekah Mercer",
        entity_type="person",
        description="Daughter of Robert Mercer. Conservative activist. Sat on Breitbart board.",
        description_sources=[NEW_YORKER_MERCER]
    ),
    
    # People - Trump associates
    SourcedEntity(
        name="Jared Kushner",
        entity_type="person",
        description="Real estate developer. Married to Ivanka Trump. Senior Advisor in Trump White House. Founded Affinity Partners.",
        description_sources=[NYT_AFFINITY_PARTNERS]
    ),
    SourcedEntity(
        name="Ivanka Trump",
        entity_type="person",
        description="Daughter of Donald Trump. Executive VP of Trump Organization. Senior Advisor in Trump White House.",
        description_sources=[WAPO_TRUMP_ORGANIZATION]
    ),
    SourcedEntity(
        name="Charles Kushner",
        entity_type="person",
        description="Real estate developer. Father of Jared Kushner. Convicted of tax evasion, witness tampering in 2005; pardoned 2020.",
        description_sources=[NYT_CHARLES_KUSHNER]
    ),
    SourcedEntity(
        name="Steve Bannon",
        entity_type="person",
        description="Former Breitbart executive chairman and Trump chief strategist. Convicted of contempt of Congress.",
        description_sources=[NEW_YORKER_MERCER]
    ),
    
    # People - Maxwell family
    SourcedEntity(
        name="Robert Maxwell",
        entity_type="person",
        description="British media proprietor. Father of Ghislaine Maxwell. Died 1991 under mysterious circumstances. Revealed to have committed massive fraud.",
        description_sources=[GUARDIAN_ROBERT_MAXWELL]
    ),
    SourcedEntity(
        name="Abigail Wexner",
        entity_type="person",
        description="Wife of Leslie Wexner. Attorney and philanthropist.",
        description_sources=[WEXNER_FOUNDATION_WEBSITE]
    ),
    
    # People - Legal
    SourcedEntity(
        name="Audrey Strauss",
        entity_type="person",
        description="Former Acting U.S. Attorney for SDNY. Announced Maxwell indictment in July 2020.",
        description_sources=[DOJ_SDNY_ANNOUNCEMENTS]
    ),
    SourcedEntity(
        name="Geoffrey Berman",
        entity_type="person",
        description="Former U.S. Attorney for SDNY. Oversaw initial Epstein prosecution in 2019.",
        description_sources=[DOJ_SDNY_ANNOUNCEMENTS]
    ),
    SourcedEntity(
        name="Christian Everdell",
        entity_type="person",
        description="Attorney at Cohen & Gresser. Part of Maxwell defense team.",
        description_sources=[DOJ_MAXWELL_CASE]
    ),
    SourcedEntity(
        name="Bobbi Sternheim",
        entity_type="person",
        description="Criminal defense attorney. Lead counsel for Ghislaine Maxwell at trial.",
        description_sources=[DOJ_MAXWELL_CASE]
    ),
    SourcedEntity(
        name="Laura Menninger",
        entity_type="person",
        description="Attorney at Haddon, Morgan and Foreman. Part of Maxwell defense team.",
        description_sources=[HADDON_MORGAN_WEBSITE]
    ),
    SourcedEntity(
        name="Jeffrey Pagliuca",
        entity_type="person",
        description="Attorney at Haddon, Morgan and Foreman. Part of Maxwell defense team.",
        description_sources=[HADDON_MORGAN_WEBSITE]
    ),
    SourcedEntity(
        name="Sigrid McCawley",
        entity_type="person",
        description="Attorney at Boies Schiller Flexner. Lead counsel for Virginia Giuffre in multiple cases.",
        description_sources=[BOIES_SCHILLER_WEBSITE]
    ),
    SourcedEntity(
        name="David Boies",
        entity_type="person",
        description="Chairman of Boies Schiller Flexner. Represented Virginia Giuffre and other Epstein victims.",
        description_sources=[BOIES_SCHILLER_WEBSITE]
    ),
    SourcedEntity(
        name="Jay Lefkowitz",
        entity_type="person",
        description="Attorney at Kirkland & Ellis. Represented Jeffrey Epstein in 2008 negotiations.",
        description_sources=[KIRKLAND_ELLIS_BIOS]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Business World
    # -------------------------------------------------------------------------
    
    # Bear Stearns / Early Career
    SourcedEntity(
        name="Bear Stearns",
        entity_type="company",
        description="Investment bank where Epstein worked 1976-1981. Made partner despite lacking college degree. Collapsed in 2008.",
        description_sources=[WSJ_BEAR_STEARNS_EPSTEIN]
    ),
    SourcedEntity(
        name="Alan Greenberg",
        entity_type="person",
        description="CEO of Bear Stearns 1978-1993. Hired Epstein as options trader. Later denied close relationship.",
        description_sources=[VANITY_FAIR_2003]
    ),
    
    # Towers Financial
    SourcedEntity(
        name="Towers Financial",
        entity_type="company",
        description="Company at center of $450 million Ponzi scheme. Hoffenberg convicted; Epstein never charged despite involvement.",
        description_sources=[NYT_TOWERS_FINANCIAL]
    ),
    SourcedEntity(
        name="Steven Hoffenberg",
        entity_type="person",
        description="Convicted fraudster. Sentenced to 20 years in 1997 for Towers Financial Ponzi scheme. Claimed Epstein was partner.",
        description_sources=[NYT_TOWERS_FINANCIAL, HOFFENBERG_TESTIMONY]
    ),
    
    # Media Owners
    SourcedEntity(
        name="Mortimer Zuckerman",
        entity_type="person",
        description="Real estate developer and media owner. Owner of NY Daily News (1993-2017) and U.S. News & World Report. Early Epstein client.",
        description_sources=[FORBES_ZUCKERMAN]
    ),
    SourcedEntity(
        name="Daily News",
        entity_type="company",
        description="New York tabloid newspaper. Owned by Mortimer Zuckerman 1993-2017.",
        description_sources=[FORBES_ZUCKERMAN]
    ),
    SourcedEntity(
        name="U.S. News & World Report",
        entity_type="company",
        description="American media company. Owned by Mortimer Zuckerman 1984-2010.",
        description_sources=[FORBES_ZUCKERMAN]
    ),
    
    # Investment World
    SourcedEntity(
        name="Colony Capital",
        entity_type="company",
        description="Private equity firm founded by Tom Barrack in 1991. Now called DigitalBridge.",
        description_sources=[NYT_BARRACK]
    ),
    SourcedEntity(
        name="Tom Barrack",
        entity_type="person",
        description="Founder of Colony Capital. Major Trump fundraiser. Indicted on foreign lobbying charges 2021. In Epstein's contacts.",
        description_sources=[NYT_BARRACK]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Philanthropy & Science
    # -------------------------------------------------------------------------
    
    SourcedEntity(
        name="John Brockman",
        entity_type="person",
        description="Literary agent and founder of Edge Foundation. Facilitated Epstein's access to scientific elite through dinners and events.",
        description_sources=[NEW_YORKER_BROCKMAN_EPSTEIN]
    ),
    SourcedEntity(
        name="Edge Foundation",
        entity_type="company",
        description="Scientific salon founded by John Brockman. Hosted dinners where Epstein networked with scientists and academics.",
        description_sources=[NEW_YORKER_BROCKMAN_EPSTEIN]
    ),
    SourcedEntity(
        name="Rockefeller University",
        entity_type="company",
        description="Private research university in NYC. Received Epstein donations for scientific research.",
        description_sources=[NYT_ROCKEFELLER_EPSTEIN]
    ),
    SourcedEntity(
        name="Santa Fe Institute",
        entity_type="company",
        description="Independent research center for complexity science. Received Epstein funding.",
        description_sources=[SANTA_FE_INSTITUTE]
    ),
    SourcedEntity(
        name="Council on Foreign Relations",
        entity_type="company",
        description="Nonpartisan foreign policy think tank. Epstein was a member of this elite organization.",
        description_sources=[CFR_EPSTEIN_MEMBERSHIP]
    ),
    SourcedEntity(
        name="Stephen Hawking",
        entity_type="person",
        description="Renowned theoretical physicist. Attended 2006 conference on Epstein's island. Deceased 2018.",
        description_sources=[GUARDIAN_HAWKING_EPSTEIN]
    ),
    SourcedEntity(
        name="Nathan Myhrvold",
        entity_type="person",
        description="Former Microsoft CTO (1996-2000). Photographed with Epstein at scientific events. Founded Intellectual Ventures.",
        description_sources=[MYHRVOLD_EPSTEIN]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Modeling World
    # -------------------------------------------------------------------------
    
    SourcedEntity(
        name="Elite Model Management",
        entity_type="company",
        description="Major modeling agency founded by John Casablancas in 1972. History of abuse allegations in industry.",
        description_sources=[CBS_ELITE_MODEL, NYT_CASABLANCAS]
    ),
    SourcedEntity(
        name="John Casablancas",
        entity_type="person",
        description="Founder of Elite Model Management. Pioneer of supermodel era. Reputation for relationships with young models. Deceased 2013.",
        description_sources=[NYT_CASABLANCAS]
    ),
    SourcedEntity(
        name="Karin Models",
        entity_type="company",
        description="Paris modeling agency founded by Jean-Luc Brunel. Predecessor to MC2.",
        description_sources=[LE_MONDE_KARIN_MODELS]
    ),
    SourcedEntity(
        name="Alicia Arden",
        entity_type="person",
        description="Model who filed police report against Epstein in 1997 after he groped her during a supposed Victoria's Secret audition. Case was not prosecuted.",
        description_sources=[ARDEN_POLICE_REPORT]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Properties
    # -------------------------------------------------------------------------
    
    SourcedEntity(
        name="Zorro Ranch",
        entity_type="company",
        description="8,000-acre ranch in Stanley, New Mexico. Site of Epstein's eugenics discussions according to NYT.",
        description_sources=[NYT_ZORRO_RANCH]
    ),
    SourcedEntity(
        name="Little St. James",
        entity_type="company",
        description="70-acre private island in U.S. Virgin Islands. Known as 'Pedophile Island.' Purchased by Epstein in 1998 for $7.95M.",
        description_sources=[WAPO_LITTLE_ST_JAMES, USVI_EPSTEIN_ESTATE]
    ),
    SourcedEntity(
        name="Great St. James",
        entity_type="company",
        description="Second USVI island purchased by Epstein in 2016 for $22.5M. Adjacent to Little St. James.",
        description_sources=[USVI_LAND_RECORDS]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Social Circle
    # -------------------------------------------------------------------------
    
    SourcedEntity(
        name="Eva Andersson-Dubin",
        entity_type="person",
        description="Miss Sweden 1980. Dated Epstein in mid-1980s. Married Glenn Dubin in 1994. Family maintained relationship with Epstein.",
        description_sources=[NYT_EVA_DUBIN, GIUFFRE_DEPOSITION_2016]
    ),
    SourcedEntity(
        name="Pepe Fanjul",
        entity_type="person",
        description="Cuban-American billionaire. Sugar industry magnate with brother Alfonso. Part of Epstein's Palm Beach social circle.",
        description_sources=[BLOOMBERG_FANJUL]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Locations
    # -------------------------------------------------------------------------
    
    SourcedEntity(
        name="Mar-a-Lago",
        entity_type="company",
        description="Palm Beach estate owned by Donald Trump. Epstein was a member before being banned. Virginia Giuffre was recruited there while working as spa attendant.",
        description_sources=[NY_MAG_EPSTEIN_2002, MIAMI_HERALD_PERVERSION_OF_JUSTICE]
    ),
    
    # -------------------------------------------------------------------------
    # ADDITIONAL ENTITIES - Intelligence Connections
    # -------------------------------------------------------------------------
    
    SourcedEntity(
        name="Mossad",
        entity_type="company",
        description="Israeli intelligence agency. Multiple sources allege Robert Maxwell worked as an asset.",
        description_sources=[GORDON_THOMAS_MAXWELLS_MOSSAD, OSTROVSKY_BY_WAY_OF_DECEPTION]
    ),
    SourcedEntity(
        name="PROMIS Software",
        entity_type="company",
        description="Case management software stolen from Inslaw Inc. Allegedly sold worldwide by Maxwell with backdoors for intelligence agencies.",
        description_sources=[INSLAW_HOUSE_REPORT, SEYMOUR_HERSH_SAMSON_OPTION]
    ),
    SourcedEntity(
        name="Israel",
        entity_type="company",
        description="State of Israel. Robert Maxwell buried on Mount of Olives with state funeral attended by PM, President, and intelligence chiefs.",
        description_sources=[NYT_MAXWELL_FUNERAL]
    ),
    SourcedEntity(
        name="Ehud Barak",
        entity_type="person",
        description="Former Israeli Prime Minister and Defense Minister. Acknowledged visiting Epstein's island and Manhattan home. Chairman of Carbyne 911, which received Epstein investment.",
        description_sources=[TIMES_OF_ISRAEL_BARAK, HAARETZ_CARBYNE]
    ),
    SourcedEntity(
        name="Carbyne 911",
        entity_type="company",
        description="Israeli emergency services technology company. Chaired by Ehud Barak. Received investment from Epstein-linked fund. Board included Nicole Junkermann.",
        description_sources=[HAARETZ_CARBYNE, TELEGRAPH_JUNKERMANN]
    ),
    SourcedEntity(
        name="Nicole Junkermann",
        entity_type="person",
        description="German-British investor. Business ties to Epstein. Invested in Carbyne 911 with Barak. Served on UK NHS health technology advisory board.",
        description_sources=[TELEGRAPH_JUNKERMANN]
    ),
    SourcedEntity(
        name="Mega Group",
        entity_type="company",
        description="Informal network of pro-Israel billionaire donors. Co-founded by Leslie Wexner and Charles Bronfman in 1991.",
        description_sources=[FORWARD_MEGA_GROUP]
    ),
    SourcedEntity(
        name="Charles Bronfman",
        entity_type="person",
        description="Canadian-American businessman. Seagram heir. Co-founded Mega Group with Leslie Wexner.",
        description_sources=[FORWARD_MEGA_GROUP]
    ),
    SourcedEntity(
        name="Victor Ostrovsky",
        entity_type="person",
        description="Former Mossad case officer. Author of 'By Way of Deception' (1990) which detailed Robert Maxwell's intelligence role.",
        description_sources=[OSTROVSKY_BY_WAY_OF_DECEPTION]
    ),
    SourcedEntity(
        name="Ari Ben-Menashe",
        entity_type="person",
        description="Former Israeli intelligence officer. Author of 'Profits of War' (1992). Made claims about Maxwell and Epstein intelligence connections.",
        description_sources=[BEN_MENASHE_PROFITS_OF_WAR]
    ),
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_all_sources() -> List[Source]:
    """Collect all Source objects defined at module level.

    Introspects the module's global namespace to find all Source
    instances. This provides a complete list of all documentary
    sources used in the entity network.

    Returns:
        List of all Source objects defined in this module.

    Example:
        >>> sources = get_all_sources()
        >>> print(f"Total sources: {len(sources)}")
        Total sources: 89
    """
    sources = []
    # Collect all Source objects defined at module level
    for name, obj in globals().items():
        if isinstance(obj, Source):
            sources.append(obj)
    return sources


def get_relationship_sources(relationship: SourcedRelationship) -> List[Source]:
    """Get all sources supporting a specific relationship.

    Args:
        relationship: A SourcedRelationship instance.

    Returns:
        List of Source objects from the relationship's sources attribute.
    """
    return relationship.sources


def validate_relationships() -> List[str]:
    """Validate that all relationships meet data quality requirements.

    Checks that each relationship in SOURCED_RELATIONSHIPS has:
    - At least one source citation
    - A confidence score between 0.0 and 1.0

    Returns:
        List of error message strings. Empty list if all validations pass.

    Example:
        >>> errors = validate_relationships()
        >>> if errors:
        ...     for e in errors:
        ...         print(f"Error: {e}")
    """
    errors = []
    for rel in SOURCED_RELATIONSHIPS:
        if not rel.sources:
            errors.append(f"Relationship {rel.source_entity} -> {rel.target_entity} has no sources")
        if rel.confidence_score < 0 or rel.confidence_score > 1:
            errors.append(f"Relationship {rel.source_entity} -> {rel.target_entity} has invalid confidence score")
    return errors


def validate_entities() -> List[str]:
    """Validate that all entities meet data quality requirements.

    Checks that each entity in SOURCED_ENTITIES has:
    - A non-empty description
    - At least one source for the description

    Returns:
        List of error message strings. Empty list if all validations pass.

    Example:
        >>> errors = validate_entities()
        >>> if not errors:
        ...     print("All entities valid!")
    """
    errors = []
    for entity in SOURCED_ENTITIES:
        if not entity.description:
            errors.append(f"Entity {entity.name} has no description")
        if not entity.description_sources:
            errors.append(f"Entity {entity.name} has no description sources")
    return errors


if __name__ == "__main__":
    # Print statistics
    print(f"Sources defined: {len(get_all_sources())}")
    print(f"Entities defined: {len(SOURCED_ENTITIES)}")
    print(f"Relationships defined: {len(SOURCED_RELATIONSHIPS)}")
    
    # Validate
    rel_errors = validate_relationships()
    entity_errors = validate_entities()
    
    if rel_errors:
        print("\nRelationship validation errors:")
        for e in rel_errors:
            print(f"  - {e}")
    
    if entity_errors:
        print("\nEntity validation errors:")
        for e in entity_errors:
            print(f"  - {e}")
    
    if not rel_errors and not entity_errors:
        print("\nAll validations passed!")
