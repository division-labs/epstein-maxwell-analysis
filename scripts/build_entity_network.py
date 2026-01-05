#!/usr/bin/env python3
"""Build a network graph of people, business entities, and their associates.

This script analyzes extracted names from the document corpus and enriches them
with business entity relationships and known associates. It creates a normalized
database schema (long format) where each relationship is a separate row, allowing
efficient traversal and querying of the network.

The script follows relationships two degrees out:
- Degree 1: Person -> Direct business entities and associates
- Degree 2: Direct associates -> Their business entities and associates

Schema Design (Long/Normalized):
    entities: Core entities (people, companies, organizations)
    relationships: Connections between entities (works_at, partner_of, invested_in, etc.)
    entity_mentions: Links entities to source documents
    
Usage:
    python3 scripts/build_entity_network.py --dsn "postgresql://user@localhost/postgres" --seed "Kushner,Leon Black" --verbose
    
    # Or use existing extracted names as seeds
    python3 scripts/build_entity_network.py --dsn "postgresql://user@localhost/postgres" --from-database --min-mentions 10 --verbose
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

try:
    import psycopg
    from psycopg import Connection
except ImportError:
    psycopg = None
    if TYPE_CHECKING:
        from psycopg import Connection

from db_utils import (
    table_exists, get_db_connection, connect_db,
    create_entity_network_tables,
    ENTITY_NETWORK_ENTITIES_SQL as CREATE_ENTITIES_TABLE,
    ENTITY_NETWORK_RELATIONSHIPS_SQL as CREATE_RELATIONSHIPS_TABLE,
    ENTITY_NETWORK_MENTIONS_SQL as CREATE_MENTIONS_TABLE
)


# ============================================================================
# KNOWN BUSINESS RELATIONSHIPS (Seed Data)
# ============================================================================

# This knowledge base should be expanded over time with research
# Format: {person_name: {entities: [companies/funds], associates: [people]}}
KNOWN_ENTITIES = {
    # Apollo Global Management network
    "Leon Black": {
        "entities": ["Apollo Global Management", "Museum of Modern Art", "Apollo Management"],
        "associates": ["Tony Ressler", "Josh Harris", "Marc Rowan", "Jeffrey Epstein"],
        "roles": {"Apollo Global Management": "founder", "Museum of Modern Art": "board_chairman"}
    },
    "Tony Ressler": {
        "entities": ["Apollo Global Management", "Ares Management", "Atlanta Hawks"],
        "associates": ["Leon Black", "Josh Harris", "Marc Rowan"],
        "roles": {"Apollo Global Management": "co_founder", "Ares Management": "founder"}
    },
    "Josh Harris": {
        "entities": ["Apollo Global Management", "Philadelphia 76ers", "New Jersey Devils"],
        "associates": ["Leon Black", "Tony Ressler", "Marc Rowan"],
        "roles": {"Apollo Global Management": "co_founder"}
    },
    "Marc Rowan": {
        "entities": ["Apollo Global Management"],
        "associates": ["Leon Black", "Tony Ressler", "Josh Harris"],
        "roles": {"Apollo Global Management": "co_founder"}
    },
    
    # Kushner network
    "Jared Kushner": {
        "entities": ["Kushner Companies", "Affinity Partners", "Observer Media"],
        "associates": ["Charles Kushner", "Ivanka Trump", "Donald Trump"],
        "roles": {"Kushner Companies": "ceo", "Affinity Partners": "founder"}
    },
    "Charles Kushner": {
        "entities": ["Kushner Companies"],
        "associates": ["Jared Kushner"],
        "roles": {"Kushner Companies": "founder"}
    },
    
    # Blackstone network
    "Stephen Schwarzman": {
        "entities": ["Blackstone Group", "Schwarzman Scholars"],
        "associates": ["Pete Peterson", "Tony James", "Jon Gray"],
        "roles": {"Blackstone Group": "co_founder"}
    },
    "Pete Peterson": {
        "entities": ["Blackstone Group", "Council on Foreign Relations"],
        "associates": ["Stephen Schwarzman"],
        "roles": {"Blackstone Group": "co_founder"}
    },
    
    # Vanguard (adding for completeness, though it's investor-owned)
    "Vanguard Group": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    
    # Key Epstein connections
    "Jeffrey Epstein": {
        "entities": ["Southern Trust Company", "J. Epstein & Co."],
        "associates": ["Ghislaine Maxwell", "Leon Black", "Leslie Wexner", "Bill Gates"],
        "roles": {"J. Epstein & Co.": "founder", "Southern Trust Company": "founder"}
    },
    "Ghislaine Maxwell": {
        "entities": ["TerraMar Project"],
        "associates": ["Jeffrey Epstein", "Robert Maxwell"],
        "roles": {"TerraMar Project": "founder"}
    },
    "Leslie Wexner": {
        "entities": ["L Brands", "Victoria's Secret", "Bath & Body Works", "Wexner Foundation"],
        "associates": ["Jeffrey Epstein", "Abigail Wexner"],
        "roles": {"L Brands": "founder", "Victoria's Secret": "founder", "Bath & Body Works": "founder", "Wexner Foundation": "founder"}
    },
    
    # Financial institutions
    "Goldman Sachs": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "JPMorgan Chase": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    
    # Additional connections
    "Bill Gates": {
        "entities": ["Microsoft", "Bill & Melinda Gates Foundation", "Cascade Investment"],
        "associates": ["Jeffrey Epstein", "Melinda Gates", "Paul Allen", "Warren Buffett"],
        "roles": {"Microsoft": "co_founder", "Bill & Melinda Gates Foundation": "founder"}
    },
    
    # Clinton network
    "Bill Clinton": {
        "entities": ["Clinton Foundation", "Clinton Global Initiative"],
        "associates": ["Hillary Clinton", "Jeffrey Epstein", "Ron Burkle", "Frank Giustra", "Doug Band", "Ghislaine Maxwell"],
        "roles": {"Clinton Foundation": "founder"}
    },
    "Hillary Clinton": {
        "entities": ["Clinton Foundation", "Clinton Global Initiative"],
        "associates": ["Bill Clinton", "Huma Abedin", "Cheryl Mills"],
        "roles": {"Clinton Foundation": "co_founder"}
    },
    "Doug Band": {
        "entities": ["Teneo Holdings", "Clinton Global Initiative"],
        "associates": ["Bill Clinton", "Jeffrey Epstein"],
        "roles": {"Teneo Holdings": "co_founder"}
    },
    "Ron Burkle": {
        "entities": ["Yucaipa Companies", "Soho House"],
        "associates": ["Bill Clinton", "Jeffrey Epstein"],
        "roles": {"Yucaipa Companies": "founder"}
    },
    "Frank Giustra": {
        "entities": ["Lionsgate Entertainment", "Clinton Giustra Enterprise Partnership"],
        "associates": ["Bill Clinton", "Jeffrey Epstein"],
        "roles": {"Lionsgate Entertainment": "founder"}
    },
    
    # Trump network
    "Donald Trump": {
        "entities": ["Trump Organization", "Trump Entertainment Resorts", "Trump Hotels"],
        "associates": ["Jared Kushner", "Ivanka Trump", "Jeffrey Epstein", "Steve Bannon", "Stephen Schwarzman"],
        "roles": {"Trump Organization": "chairman"}
    },
    "Ivanka Trump": {
        "entities": ["Ivanka Trump Brand", "Trump Organization"],
        "associates": ["Donald Trump", "Jared Kushner"],
        "roles": {"Trump Organization": "executive_vp"}
    },
    "Steve Bannon": {
        "entities": ["Breitbart News", "Cambridge Analytica"],
        "associates": ["Donald Trump", "Robert Mercer", "Rebekah Mercer"],
        "roles": {"Breitbart News": "executive_chairman", "Cambridge Analytica": "board_member"}
    },
    
    # British connections
    "Prince Andrew": {
        "entities": ["Pitch@Palace"],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell", "Sarah Ferguson"],
        "roles": {"Pitch@Palace": "founder"}
    },
    "Sarah Ferguson": {
        "entities": [],
        "associates": ["Prince Andrew", "Jeffrey Epstein"],
        "roles": {}
    },
    "Robert Maxwell": {
        "entities": ["Mirror Group Newspapers", "Maxwell Communications Corporation"],
        "associates": ["Ghislaine Maxwell"],
        "roles": {"Mirror Group Newspapers": "owner", "Maxwell Communications Corporation": "founder"}
    },
    
    # Wexner network expanded
    "Abigail Wexner": {
        "entities": ["Wexner Foundation"],
        "associates": ["Leslie Wexner", "Jeffrey Epstein"],
        "roles": {"Wexner Foundation": "board_member"}
    },
    
    # Additional financial figures
    "Steven Cohen": {
        "entities": ["Point72 Asset Management", "SAC Capital Advisors", "New York Mets"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Point72 Asset Management": "founder"}
    },
    "Thomas Pritzker": {
        "entities": ["Hyatt Hotels", "Pritzker Organization"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Hyatt Hotels": "executive_chairman"}
    },
    "Glenn Dubin": {
        "entities": ["Highbridge Capital Management"],
        "associates": ["Jeffrey Epstein", "Eva Andersson-Dubin", "Henry Kravis"],
        "roles": {"Highbridge Capital Management": "co_founder"}
    },
    "Eva Andersson-Dubin": {
        "entities": [],
        "associates": ["Glenn Dubin", "Jeffrey Epstein"],
        "roles": {}
    },
    "Henry Kravis": {
        "entities": ["KKR & Co", "Kohlberg Kravis Roberts"],
        "associates": ["George Roberts", "Jerome Kohlberg", "Glenn Dubin"],
        "roles": {"KKR & Co": "co_founder"}
    },
    "George Roberts": {
        "entities": ["KKR & Co"],
        "associates": ["Henry Kravis", "Jerome Kohlberg"],
        "roles": {"KKR & Co": "co_founder"}
    },
    
    # Hedge fund managers
    "Alan Dershowitz": {
        "entities": ["Harvard Law School"],
        "associates": ["Jeffrey Epstein", "Leslie Wexner"],
        "roles": {"Harvard Law School": "professor"}
    },
    "Jean-Luc Brunel": {
        "entities": ["MC2 Model Management", "Karin Models"],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {"MC2 Model Management": "founder"}
    },
    
    # Modeling/Entertainment
    "Naomi Campbell": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    
    # Real estate moguls
    "Mort Zuckerman": {
        "entities": ["Boston Properties", "U.S. News & World Report", "New York Daily News"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Boston Properties": "co_founder"}
    },
    
    # Tech titans
    "Paul Allen": {
        "entities": ["Microsoft", "Vulcan Inc", "Allen Institute"],
        "associates": ["Bill Gates", "Jeffrey Epstein"],
        "roles": {"Microsoft": "co_founder"}
    },
    "Reid Hoffman": {
        "entities": ["LinkedIn", "PayPal"],
        "associates": ["Bill Gates", "Jeffrey Epstein"],
        "roles": {"LinkedIn": "co_founder"}
    },
    "Elon Musk": {
        "entities": ["Tesla", "SpaceX", "PayPal", "Neuralink"],
        "associates": ["Ghislaine Maxwell"],
        "roles": {"Tesla": "ceo", "SpaceX": "ceo"}
    },
    
    # Banking executives
    "Jes Staley": {
        "entities": ["Barclays", "JPMorgan Chase"],
        "associates": ["Jeffrey Epstein", "Jamie Dimon"],
        "roles": {"Barclays": "ceo"}
    },
    "Jamie Dimon": {
        "entities": ["JPMorgan Chase"],
        "associates": ["Jes Staley", "Jeffrey Epstein"],
        "roles": {"JPMorgan Chase": "ceo"}
    },
    "Lloyd Blankfein": {
        "entities": ["Goldman Sachs"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Goldman Sachs": "ceo"}
    },
    
    # Scientists/Academics
    "Marvin Minsky": {
        "entities": ["MIT", "MIT Media Lab"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"MIT": "professor"}
    },
    "Lawrence Krauss": {
        "entities": ["Arizona State University"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Arizona State University": "professor"}
    },
    "Stephen Hawking": {
        "entities": ["University of Cambridge"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"University of Cambridge": "professor"}
    },
    "Joi Ito": {
        "entities": ["MIT Media Lab"],
        "associates": ["Jeffrey Epstein", "Reid Hoffman"],
        "roles": {"MIT Media Lab": "director"}
    },
    
    # Legal representatives
    "Roy Black": {
        "entities": ["Black, Srebnick, Kornspan & Stumpf"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Black, Srebnick, Kornspan & Stumpf": "founding_partner"}
    },
    "Kenneth Starr": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    
    # Mercer network
    "Robert Mercer": {
        "entities": ["Renaissance Technologies", "Cambridge Analytica", "Breitbart News"],
        "associates": ["Rebekah Mercer", "Steve Bannon", "Donald Trump"],
        "roles": {"Renaissance Technologies": "co_ceo"}
    },
    "Rebekah Mercer": {
        "entities": ["Mercer Family Foundation", "Cambridge Analytica"],
        "associates": ["Robert Mercer", "Steve Bannon", "Donald Trump"],
        "roles": {"Mercer Family Foundation": "director"}
    },
    
    # Additional Apollo connections
    "Michael Milken": {
        "entities": ["Drexel Burnham Lambert", "Milken Institute"],
        "associates": ["Leon Black"],
        "roles": {"Milken Institute": "founder"}
    },
    
    # Fashion/Retail
    "Peter Nygård": {
        "entities": ["Nygård International"],
        "associates": [],
        "roles": {"Nygård International": "founder"}
    },
    
    # Foreign dignitaries
    "Ehud Barak": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    
    # Media moguls
    "Rupert Murdoch": {
        "entities": ["News Corp", "Fox Corporation", "21st Century Fox"],
        "associates": ["Ghislaine Maxwell"],
        "roles": {"News Corp": "chairman"}
    },
    "Michael Bloomberg": {
        "entities": ["Bloomberg L.P."],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Bloomberg L.P.": "founder"}
    },
    
    # Socialites
    "Eva Dubin": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Glenn Dubin"],
        "roles": {}
    },
    
    # Aviation
    "David Copperfield": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    
    # Additional associates
    "Sarah Kellen": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Nadia Marcinkova": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Lesley Groff": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Adriana Ross": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    
    # Lawyers
    "Alan Dershowtiz": {
        "entities": ["Harvard Law School"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Harvard Law School": "professor"}
    },
    
    # Business magnates
    "Carl Icahn": {
        "entities": ["Icahn Enterprises"],
        "associates": ["Donald Trump"],
        "roles": {"Icahn Enterprises": "founder"}
    },
    "Nelson Peltz": {
        "entities": ["Trian Fund Management"],
        "associates": [],
        "roles": {"Trian Fund Management": "founding_partner"}
    },
    
    # Philanthropy
    "Lynn Forester de Rothschild": {
        "entities": ["E.L. Rothschild"],
        "associates": ["Jeffrey Epstein", "Bill Clinton", "Hillary Clinton"],
        "roles": {"E.L. Rothschild": "ceo"}
    },
    
    # Key victims and witnesses
    "Virginia Giuffre": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell", "Prince Andrew", "Alan Dershowitz"],
        "roles": {}
    },
    "Maria Farmer": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Annie Farmer": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell", "Maria Farmer"],
        "roles": {}
    },
    
    # More Epstein staff/associates
    "Juan Alessi": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Cecilia Stein": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Emmy Tayler": {
        "entities": [],
        "associates": ["Ghislaine Maxwell", "Jeffrey Epstein"],
        "roles": {}
    },
    
    # Additional Clinton orbit
    "Terry McAuliffe": {
        "entities": ["Democratic National Committee"],
        "associates": ["Bill Clinton", "Hillary Clinton"],
        "roles": {"Democratic National Committee": "chairman"}
    },
    "John Podesta": {
        "entities": ["Center for American Progress"],
        "associates": ["Bill Clinton", "Hillary Clinton"],
        "roles": {"Center for American Progress": "founder"}
    },
    "Tony Podesta": {
        "entities": ["Podesta Group"],
        "associates": ["John Podesta", "Bill Clinton"],
        "roles": {"Podesta Group": "founder"}
    },
    "George Stephanopoulos": {
        "entities": ["ABC News"],
        "associates": ["Bill Clinton", "Jeffrey Epstein"],
        "roles": {"ABC News": "anchor"}
    },
    
    # Additional Trump orbit
    "Paul Manafort": {
        "entities": ["Black, Manafort, Stone and Kelly"],
        "associates": ["Donald Trump", "Roger Stone"],
        "roles": {"Black, Manafort, Stone and Kelly": "partner"}
    },
    "Roger Stone": {
        "entities": ["Black, Manafort, Stone and Kelly"],
        "associates": ["Donald Trump", "Paul Manafort"],
        "roles": {"Black, Manafort, Stone and Kelly": "partner"}
    },
    "Michael Cohen": {
        "entities": ["Trump Organization"],
        "associates": ["Donald Trump"],
        "roles": {"Trump Organization": "attorney"}
    },
    "Thomas Barrack": {
        "entities": ["Colony Capital"],
        "associates": ["Donald Trump", "Jared Kushner"],
        "roles": {"Colony Capital": "founder"}
    },
    
    # British politicians and royalty expanded
    "Tony Blair": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Lady Victoria Hervey": {
        "entities": [],
        "associates": ["Prince Andrew", "Ghislaine Maxwell", "Jeffrey Epstein"],
        "roles": {}
    },
    
    # International political figures
    "Ehud Olmert": {
        "entities": [],
        "associates": ["Ehud Barak", "Jeffrey Epstein"],
        "roles": {}
    },
    
    # More scientists and academics
    "Murray Gell-Mann": {
        "entities": ["Santa Fe Institute"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Santa Fe Institute": "founder"}
    },
    "Roger Schank": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Seth Lloyd": {
        "entities": ["MIT"],
        "associates": ["Jeffrey Epstein", "Joi Ito"],
        "roles": {"MIT": "professor"}
    },
    "Frank Wilczek": {
        "entities": ["MIT"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"MIT": "professor"}
    },
    "George Church": {
        "entities": ["Harvard Medical School"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Harvard Medical School": "professor"}
    },
    "Martin Nowak": {
        "entities": ["Harvard University"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Harvard University": "professor"}
    },
    
    # More financiers and hedge fund managers
    "Larry Summers": {
        "entities": ["Harvard University", "World Bank"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Harvard University": "president"}
    },
    "Larry Fink": {
        "entities": ["BlackRock"],
        "associates": [],
        "roles": {"BlackRock": "ceo"}
    },
    "Israel Englander": {
        "entities": ["Millennium Management"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Millennium Management": "founder"}
    },
    "David Koch": {
        "entities": ["Koch Industries"],
        "associates": ["Charles Koch"],
        "roles": {"Koch Industries": "executive_vp"}
    },
    "Charles Koch": {
        "entities": ["Koch Industries"],
        "associates": ["David Koch"],
        "roles": {"Koch Industries": "chairman"}
    },
    
    # Media figures
    "Katie Couric": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Charlie Rose": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Barbara Walters": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    
    # Real estate moguls expanded
    "Aby Rosen": {
        "entities": ["RFR Holding"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"RFR Holding": "co_founder"}
    },
    
    # Additional legal team
    "Gerald Lefcourt": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Jay Lefkowitz": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Bradley Edwards": {
        "entities": ["Edwards Pottinger LLC"],
        "associates": ["Virginia Giuffre"],
        "roles": {"Edwards Pottinger LLC": "founding_partner"}
    },
    "David Boies": {
        "entities": ["Boies Schiller Flexner"],
        "associates": ["Virginia Giuffre"],
        "roles": {"Boies Schiller Flexner": "chairman"}
    },
    "Paul Cassell": {
        "entities": ["University of Utah"],
        "associates": ["Virginia Giuffre", "Bradley Edwards"],
        "roles": {"University of Utah": "professor"}
    },
    "Sigrid McCawley": {
        "entities": ["Boies Schiller Flexner"],
        "associates": ["Virginia Giuffre", "David Boies"],
        "roles": {"Boies Schiller Flexner": "partner"}
    },
    
    # Bronfman family
    "Edgar Bronfman Sr": {
        "entities": ["Seagram"],
        "associates": ["Edgar Bronfman Jr"],
        "roles": {"Seagram": "ceo"}
    },
    "Edgar Bronfman Jr": {
        "entities": ["Warner Music Group"],
        "associates": ["Edgar Bronfman Sr"],
        "roles": {"Warner Music Group": "ceo"}
    },
    
    # Art world
    "Peter Beard": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    
    # Tech expanded
    "Sergey Brin": {
        "entities": ["Google", "Alphabet"],
        "associates": ["Larry Page"],
        "roles": {"Google": "co_founder"}
    },
    "Larry Page": {
        "entities": ["Google", "Alphabet"],
        "associates": ["Sergey Brin"],
        "roles": {"Google": "co_founder"}
    },
    "Eric Schmidt": {
        "entities": ["Google", "Alphabet"],
        "associates": ["Larry Page", "Sergey Brin"],
        "roles": {"Google": "ceo"}
    },
    
    # Additional modeling industry
    "Karyna Shuliak": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    
    # Law enforcement/prosecutors
    "Alexander Acosta": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Geoffrey Berman": {
        "entities": ["U.S. Attorney SDNY"],
        "associates": [],
        "roles": {"U.S. Attorney SDNY": "attorney"}
    },
    "Audrey Strauss": {
        "entities": ["U.S. Attorney SDNY"],
        "associates": ["Geoffrey Berman"],
        "roles": {"U.S. Attorney SDNY": "attorney"}
    },
    
    # Additional Wexner circle
    "Abigail Koppel": {
        "entities": [],
        "associates": ["Leslie Wexner", "Abigail Wexner"],
        "roles": {}
    },
    
    # Other billionaires
    "David Geffen": {
        "entities": ["Geffen Records", "DreamWorks"],
        "associates": ["Barry Diller"],
        "roles": {"Geffen Records": "founder"}
    },
    "Barry Diller": {
        "entities": ["IAC", "Expedia Group"],
        "associates": ["David Geffen"],
        "roles": {"IAC": "chairman"}
    },
    
    # Modeling agencies
    "Gerald Marie": {
        "entities": ["Elite Model Management"],
        "associates": ["Jean-Luc Brunel"],
        "roles": {"Elite Model Management": "executive"}
    },
    
    # Additional French connections
    "Jean-Paul Agon": {
        "entities": ["L'Oréal"],
        "associates": [],
        "roles": {"L'Oréal": "ceo"}
    },
    
    # Additional Victoria's Secret connections
    "Ed Razek": {
        "entities": ["L Brands"],
        "associates": ["Leslie Wexner"],
        "roles": {"L Brands": "cmo"}
    },
    
    # Additional associates from flight logs
    "Chris Tucker": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Bill Clinton"],
        "roles": {}
    },
    "Kevin Spacey": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Bill Clinton"],
        "roles": {}
    },
    
    # Middle Eastern figures
    "Mohammed bin Salman": {
        "entities": ["Saudi Arabia"],
        "associates": ["Jared Kushner", "Thomas Barrack"],
        "roles": {}
    },
    "Mohammed bin Zayed": {
        "entities": ["United Arab Emirates"],
        "associates": ["Jared Kushner", "Thomas Barrack"],
        "roles": {}
    },
    "Adnan Khashoggi": {
        "entities": [],
        "associates": ["Donald Trump"],
        "roles": {}
    },
    
    # French connections
    "Emmanuel Macron": {
        "entities": [],
        "associates": [],
        "roles": {}
    },
    "Bernard Arnault": {
        "entities": ["LVMH"],
        "associates": [],
        "roles": {"LVMH": "chairman"}
    },
    "François Pinault": {
        "entities": ["Kering", "Christie's"],
        "associates": [],
        "roles": {"Kering": "founder"}
    },
    "Vincent Bolloré": {
        "entities": ["Bolloré Group"],
        "associates": [],
        "roles": {"Bolloré Group": "chairman"}
    },
    
    # Russian oligarchs
    "Roman Abramovich": {
        "entities": ["Chelsea FC"],
        "associates": [],
        "roles": {"Chelsea FC": "owner"}
    },
    "Oleg Deripaska": {
        "entities": ["Rusal", "Basic Element"],
        "associates": ["Paul Manafort"],
        "roles": {"Rusal": "founder"}
    },
    "Viktor Vekselberg": {
        "entities": ["Renova Group"],
        "associates": [],
        "roles": {"Renova Group": "chairman"}
    },
    "Dmitry Rybolovlev": {
        "entities": [],
        "associates": ["Donald Trump"],
        "roles": {}
    },
    "Igor Sechin": {
        "entities": ["Rosneft"],
        "associates": [],
        "roles": {"Rosneft": "ceo"}
    },
    
    # Asian business leaders
    "Jack Ma": {
        "entities": ["Alibaba Group"],
        "associates": [],
        "roles": {"Alibaba Group": "founder"}
    },
    "Masayoshi Son": {
        "entities": ["SoftBank Group"],
        "associates": ["Jared Kushner"],
        "roles": {"SoftBank Group": "founder"}
    },
    "Li Ka-shing": {
        "entities": ["CK Hutchison Holdings"],
        "associates": [],
        "roles": {"CK Hutchison Holdings": "founder"}
    },
    "Mukesh Ambani": {
        "entities": ["Reliance Industries"],
        "associates": [],
        "roles": {"Reliance Industries": "chairman"}
    },
    
    # Italian connections
    "Silvio Berlusconi": {
        "entities": ["Mediaset", "Fininvest"],
        "associates": ["Donald Trump"],
        "roles": {"Fininvest": "chairman"}
    },
    "Giorgio Armani": {
        "entities": ["Giorgio Armani S.p.A."],
        "associates": [],
        "roles": {"Giorgio Armani S.p.A.": "founder"}
    },
    
    # Swiss/German business
    "Klaus Schwab": {
        "entities": ["World Economic Forum"],
        "associates": [],
        "roles": {"World Economic Forum": "founder"}
    },
    "Josef Ackermann": {
        "entities": ["Deutsche Bank"],
        "associates": [],
        "roles": {"Deutsche Bank": "former_ceo"}
    },
    
    # Spanish connections
    "Amancio Ortega": {
        "entities": ["Inditex", "Zara"],
        "associates": [],
        "roles": {"Inditex": "founder"}
    },
    
    # Swedish connections
    "Stefan Persson": {
        "entities": ["H&M"],
        "associates": [],
        "roles": {"H&M": "chairman"}
    },
    
    # Canadian connections
    "Frank Giustra": {
        "entities": ["Lionsgate Entertainment", "Clinton Giustra Enterprise Partnership"],
        "associates": ["Bill Clinton", "Jeffrey Epstein"],
        "roles": {"Lionsgate Entertainment": "founder"}
    },
    "Peter Munk": {
        "entities": ["Barrick Gold"],
        "associates": ["Frank Giustra"],
        "roles": {"Barrick Gold": "founder"}
    },
    "Edgar Bronfman Jr": {
        "entities": ["Warner Music Group"],
        "associates": ["Edgar Bronfman Sr"],
        "roles": {"Warner Music Group": "ceo"}
    },
    
    # Australian connections
    "James Packer": {
        "entities": ["Crown Resorts"],
        "associates": ["Mariah Carey", "Benjamin Netanyahu"],
        "roles": {"Crown Resorts": "major_shareholder"}
    },
    "Rupert Murdoch": {
        "entities": ["News Corp", "Fox Corporation", "21st Century Fox"],
        "associates": ["Ghislaine Maxwell"],
        "roles": {"News Corp": "chairman"}
    },
    
    # Mexican connections
    "Carlos Slim": {
        "entities": ["Grupo Carso"],
        "associates": ["Bill Clinton"],
        "roles": {"Grupo Carso": "founder"}
    },
    
    # Colombian connections  
    "Alejandro Santo Domingo": {
        "entities": ["SABMiller"],
        "associates": [],
        "roles": {}
    },
    
    # Israeli connections
    "Benjamin Netanyahu": {
        "entities": [],
        "associates": ["Jared Kushner", "James Packer"],
        "roles": {}
    },
    "Yair Netanyahu": {
        "entities": [],
        "associates": ["Benjamin Netanyahu"],
        "roles": {}
    },
    "Arnon Milchan": {
        "entities": ["New Regency Productions"],
        "associates": ["Benjamin Netanyahu"],
        "roles": {"New Regency Productions": "founder"}
    },
    "Beny Steinmetz": {
        "entities": ["Steinmetz Diamond Group"],
        "associates": [],
        "roles": {"Steinmetz Diamond Group": "founder"}
    },
    
    # South African connections
    "Johann Rupert": {
        "entities": ["Richemont"],
        "associates": [],
        "roles": {"Richemont": "chairman"}
    },
    "Nicky Oppenheimer": {
        "entities": ["De Beers"],
        "associates": [],
        "roles": {"De Beers": "former_chairman"}
    },
    
    # Brazilian connections
    "Jorge Paulo Lemann": {
        "entities": ["3G Capital"],
        "associates": [],
        "roles": {"3G Capital": "co_founder"}
    },
    
    # Additional European royalty
    "Prince Albert II": {
        "entities": [],
        "associates": [],
        "roles": {}
    },
    "Princess Beatrice": {
        "entities": [],
        "associates": ["Prince Andrew"],
        "roles": {}
    },
    "Princess Eugenie": {
        "entities": [],
        "associates": ["Prince Andrew"],
        "roles": {}
    },
    
    # Additional British figures
    "Lord Jacob Rothschild": {
        "entities": ["RIT Capital Partners"],
        "associates": [],
        "roles": {"RIT Capital Partners": "chairman"}
    },
    "Lord Mandelson": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {}
    },
    "Nat Rothschild": {
        "entities": ["Volex"],
        "associates": ["Lord Jacob Rothschild"],
        "roles": {}
    },
    
    # Turkish connections
    "Cem Uzan": {
        "entities": [],
        "associates": ["Donald Trump"],
        "roles": {}
    },
    
    # Greek shipping magnates
    "Philip Niarchos": {
        "entities": [],
        "associates": [],
        "roles": {}
    },
    
    # Additional French political figures
    "Nicolas Sarkozy": {
        "entities": [],
        "associates": [],
        "roles": {}
    },
    "Dominique Strauss-Kahn": {
        "entities": ["International Monetary Fund"],
        "associates": [],
        "roles": {"International Monetary Fund": "former_managing_director"}
    },
    
    # Additional Middle Eastern
    "Yousef Al Otaiba": {
        "entities": [],
        "associates": ["Jared Kushner", "Thomas Barrack"],
        "roles": {}
    },
    
    # Kazakh oligarchs
    "Viktor Khrapunov": {
        "entities": [],
        "associates": [],
        "roles": {}
    },
    
    # Ukrainian oligarchs
    "Ihor Kolomoyskyi": {
        "entities": ["PrivatBank"],
        "associates": [],
        "roles": {"PrivatBank": "founder"}
    },
    "Dmytro Firtash": {
        "entities": [],
        "associates": ["Paul Manafort"],
        "roles": {}
    },
    
    # Additional entities as placeholders
    "Victoria's Secret": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "MIT Media Lab": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "organization"
    },
    "Harvard Law School": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "organization"
    },
    "BlackRock": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "Millennium Management": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "Colony Capital": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "Santa Fe Institute": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "organization"
    },
    "Democratic National Committee": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "organization"
    },
    "LVMH": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "Alibaba Group": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "SoftBank Group": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "World Economic Forum": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "organization"
    },
    "Barrick Gold": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "3G Capital": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    
    # Additional victims and witnesses (case-relevant)
    "Sarah Ransome": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Johanna Sjoberg": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell", "Prince Andrew"],
        "roles": {}
    },
    "Michelle Licata": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Courtney Wild": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell", "Bradley Edwards"],
        "roles": {}
    },
    
    # Additional prosecutors and law enforcement
    "Maurene Comey": {
        "entities": ["U.S. Attorney SDNY"],
        "associates": ["James Comey"],
        "roles": {"U.S. Attorney SDNY": "assistant_us_attorney"}
    },
    "Alison Moe": {
        "entities": ["U.S. Attorney SDNY"],
        "associates": ["Maurene Comey", "Lara Pomerantz"],
        "roles": {"U.S. Attorney SDNY": "assistant_us_attorney"}
    },
    "Lara Pomerantz": {
        "entities": ["U.S. Attorney SDNY"],
        "associates": ["Maurene Comey", "Alison Moe"],
        "roles": {"U.S. Attorney SDNY": "assistant_us_attorney"}
    },
    "James Comey": {
        "entities": ["FBI"],
        "associates": ["Maurene Comey"],
        "roles": {"FBI": "former_director"}
    },
    "William Barr": {
        "entities": ["U.S. Department of Justice"],
        "associates": [],
        "roles": {"U.S. Department of Justice": "former_attorney_general"}
    },
    
    # Maxwell defense attorneys
    "Christian Everdell": {
        "entities": ["Cohen & Gresser"],
        "associates": ["Ghislaine Maxwell", "Bobbi Sternheim"],
        "roles": {"Cohen & Gresser": "partner"}
    },
    "Bobbi Sternheim": {
        "entities": [],
        "associates": ["Ghislaine Maxwell", "Christian Everdell"],
        "roles": {}
    },
    "Laura Menninger": {
        "entities": ["Haddon, Morgan and Foreman"],
        "associates": ["Ghislaine Maxwell"],
        "roles": {"Haddon, Morgan and Foreman": "partner"}
    },
    "Jeffrey Pagliuca": {
        "entities": [],
        "associates": ["Ghislaine Maxwell"],
        "roles": {}
    },
    
    # Additional staff and associates
    "Haley Robson": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Rachel Chandler": {
        "entities": [],
        "associates": ["Jeffrey Epstein", "Ghislaine Maxwell"],
        "roles": {}
    },
    "Jean-Michel Gathy": {
        "entities": ["Denniston International Architects & Planners"],
        "associates": ["Jeffrey Epstein"],
        "roles": {"Denniston International Architects & Planners": "architect"}
    },
    
    # Additional financial institutions
    "Deutsche Bank": {
        "entities": [],
        "associates": [],
        "roles": {},
        "entity_type": "company"
    },
    "Southern Trust Company": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {},
        "entity_type": "company"
    },
    "Financial Trust Company": {
        "entities": [],
        "associates": ["Jeffrey Epstein"],
        "roles": {},
        "entity_type": "company"
    },
    
    # Investigative journalists
    "Julie K. Brown": {
        "entities": ["Miami Herald"],
        "associates": [],
        "roles": {"Miami Herald": "investigative_reporter"}
    },
}

# Relationship type definitions
RELATIONSHIP_TYPES = {
    # Corporate/Business relationships
    "founder": "Founded or co-founded",
    "co_founder": "Co-founder",
    "ceo": "Chief Executive Officer",
    "co_ceo": "Co-Chief Executive Officer",
    "cfo": "Chief Financial Officer",
    "cmo": "Chief Marketing Officer",
    "chairman": "Chairman",
    "board_chairman": "Chairman of the Board",
    "board_member": "Board Member",
    "executive_chairman": "Executive Chairman",
    "executive_vp": "Executive Vice President",
    "executive": "Executive",
    "president": "President",
    "investor": "Invested in or owns stake",
    "major_shareholder": "Major shareholder",
    "owner": "Owner",
    "advisor": "Advisor or consultant",
    "partner": "Business partner",
    "founding_partner": "Founding partner",
    "employee": "Employee or worked at",
    "associate": "Known associate",
    "director": "Director",
    
    # Former roles
    "former_ceo": "Former CEO",
    "former_chairman": "Former Chairman",
    "former_managing_director": "Former Managing Director",
    
    # Financial relationships
    "banker": "Banker or banking relationship",
    "financial_advisor": "Financial advisor",
    "accountant": "Accountant",
    "wealth_manager": "Wealth manager",
    "trustee": "Trustee",
    
    # Legal relationships
    "prosecutor": "Prosecutor",
    "assistant_us_attorney": "Assistant U.S. Attorney",
    "defense_attorney": "Defense attorney",
    "attorney": "Attorney or legal counsel",
    "victim": "Victim",
    "witness": "Witness",
    "complainant": "Complainant",
    "defendant": "Defendant",
    "judge": "Judge",
    
    # Employment/Staff relationships
    "personal_assistant": "Personal assistant",
    "executive_assistant": "Executive assistant",
    "pilot": "Pilot",
    "recruiter": "Recruiter",
    "household_staff": "Household staff",
    "scheduler": "Scheduler",
    "bookkeeper": "Bookkeeper",
    
    # Political/Government relationships
    "politician": "Politician",
    "political_associate": "Political associate",
    "government_official": "Government official",
    "diplomat": "Diplomat",
    "former_president": "Former President",
    "former_attorney_general": "Former Attorney General",
    "former_director": "Former Director",
    
    # Social/Personal relationships
    "social_contact": "Social contact",
    "friend": "Friend",
    "acquaintance": "Acquaintance",
    "romantic_partner": "Romantic partner",
    
    # Family relationships
    "daughter": "Daughter",
    "son": "Son",
    "spouse": "Spouse",
    "sibling": "Sibling",
    "parent": "Parent",
    "child": "Child",
    "relative": "Relative",
    
    # Investigative/Media relationships
    "investigative_reporter": "Investigative reporter",
    "journalist": "Journalist",
    "anchor": "News anchor",
    "law_enforcement": "Law enforcement",
    "fbi_agent": "FBI agent",
    "investigator": "Investigator",
    
    # Academic/Professional relationships
    "professor": "Professor",
    "scientist": "Scientist",
    "researcher": "Researcher",
    "academic": "Academic",
    "architect": "Architect",
    "designer": "Designer",
    
    # Other relationships
    "benefactor": "Benefactor or donor",
    "client": "Client",
    "contractor": "Contractor",
    "vendor": "Vendor",
}


# ============================================================================
# ENTITY EXTRACTION & NETWORK BUILDING
# ============================================================================

class EntityNetworkBuilder:
    """Builds and manages the entity relationship network."""
    
    def __init__(self, conn, verbose: bool = False):
        """Initialize the network builder.
        
        Args:
            conn: Database connection.
            verbose: Enable verbose logging.
        """
        self.conn = conn
        self.verbose = verbose
        self.entity_cache: Dict[str, int] = {}  # name -> entity_id
        self.processed_entities: Set[str] = set()
        
    def log(self, message: str):
        """Print message if verbose mode enabled."""
        if self.verbose:
            print(message)
    
    def initialize_database(self):
        """Create database tables if they don't exist."""
        self.log("Initializing database schema...")
        with self.conn.cursor() as cur:
            cur.execute(CREATE_ENTITIES_TABLE)
            cur.execute(CREATE_RELATIONSHIPS_TABLE)
            cur.execute(CREATE_MENTIONS_TABLE)
        self.log("Database schema ready.")
    
    def get_or_create_entity(
        self,
        name: str,
        entity_type: str = "person",
        description: Optional[str] = None
    ) -> int:
        """Get existing entity ID or create new entity.
        
        Args:
            name: Entity name.
            entity_type: Type of entity (person, company, organization, fund).
            description: Optional description.
            
        Returns:
            Entity ID.
        """
        # Check cache
        if name in self.entity_cache:
            return self.entity_cache[name]
        
        with self.conn.cursor() as cur:
            # Try to find existing
            cur.execute(
                "SELECT entity_id FROM entity_network_entities WHERE entity_name = %s",
                (name,)
            )
            result = cur.fetchone()
            
            if result:
                entity_id = result[0]
            else:
                # Create new
                cur.execute(
                    """INSERT INTO entity_network_entities 
                       (entity_name, entity_type, description)
                       VALUES (%s, %s, %s)
                       RETURNING entity_id""",
                    (name, entity_type, description)
                )
                entity_id = cur.fetchone()[0]
                self.log(f"  Created entity: {name} ({entity_type})")
            
            self.entity_cache[name] = entity_id
            return entity_id
    
    def add_relationship(
        self,
        source_name: str,
        target_name: str,
        relationship_type: str,
        degree: int,
        source_reference: str = "seed_data",
        confidence: float = 1.0
    ):
        """Add a relationship between two entities.
        
        Args:
            source_name: Source entity name.
            target_name: Target entity name.
            relationship_type: Type of relationship.
            degree: Degree of separation (1 or 2).
            source_reference: Where this data came from.
            confidence: Confidence score (0.0-1.0).
        """
        source_id = self.entity_cache.get(source_name)
        target_id = self.entity_cache.get(target_name)
        
        if not source_id or not target_id:
            self.log(f"  Warning: Skipping relationship {source_name} -> {target_name} (entity not found)")
            return
        
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO entity_network_relationships 
                   (source_entity_id, target_entity_id, relationship_type, 
                    confidence_score, degree, source_reference)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (source_entity_id, target_entity_id, relationship_type)
                   DO UPDATE SET 
                       confidence_score = EXCLUDED.confidence_score,
                       degree = LEAST(entity_network_relationships.degree, EXCLUDED.degree)
                """,
                (source_id, target_id, relationship_type, confidence, degree, source_reference)
            )
    
    def build_from_seed_data(self, seed_names: List[str]):
        """Build network from seed names and known relationships.
        
        Args:
            seed_names: List of people/entities to start from.
        """
        self.log(f"\n{'='*80}")
        self.log(f"BUILDING ENTITY NETWORK FROM SEEDS")
        self.log(f"{'='*80}\n")
        self.log(f"Processing {len(seed_names)} seed entities...\n")
        
        # Degree 1: Process seed entities
        for name in seed_names:
            if name in self.processed_entities:
                continue
            
            self.log(f"[DEGREE 1] Processing: {name}")
            self._process_entity(name, degree=1)
            self.processed_entities.add(name)
        
        # Degree 2: Process associates of seed entities
        self.log(f"\n{'='*80}")
        self.log(f"FOLLOWING CONNECTIONS TO DEGREE 2")
        self.log(f"{'='*80}\n")
        
        degree_2_entities = set()
        for name in seed_names:
            if name in KNOWN_ENTITIES:
                associates = KNOWN_ENTITIES[name].get("associates", [])
                degree_2_entities.update(associates)
        
        for name in degree_2_entities:
            if name in self.processed_entities:
                continue
            
            self.log(f"[DEGREE 2] Processing: {name}")
            self._process_entity(name, degree=2)
            self.processed_entities.add(name)
    
    def _process_entity(self, name: str, degree: int):
        """Process a single entity and its relationships.
        
        Args:
            name: Entity name to process.
            degree: Current degree of separation.
        """
        # Check if we have data for this entity
        if name not in KNOWN_ENTITIES:
            # Create entity even if we don't have relationship data
            self.get_or_create_entity(name, "person")
            return
        
        data = KNOWN_ENTITIES[name]
        
        # Determine entity type
        entity_type = data.get("entity_type", "person")
        
        # Create the main entity
        entity_id = self.get_or_create_entity(name, entity_type)
        
        # Add business entity relationships
        for business_entity in data.get("entities", []):
            # Create business entity
            self.get_or_create_entity(business_entity, "company")
            
            # Determine relationship type from roles
            roles = data.get("roles", {})
            rel_type = roles.get(business_entity, "associated_with")
            
            # Add relationship
            self.add_relationship(
                name,
                business_entity,
                rel_type,
                degree=degree,
                source_reference="known_relationships"
            )
            
            self.log(f"    {name} --[{rel_type}]--> {business_entity}")
        
        # Add associate relationships
        for associate in data.get("associates", []):
            # Create associate entity
            self.get_or_create_entity(associate, "person")
            
            # Add bidirectional relationship
            self.add_relationship(
                name,
                associate,
                "associate",
                degree=degree,
                source_reference="known_relationships"
            )
            
            self.log(f"    {name} --[associate]--> {associate}")
    
    def link_to_document_mentions(self):
        """Link entities to documents where they were mentioned."""
        self.log(f"\n{'='*80}")
        self.log("LINKING ENTITIES TO DOCUMENT MENTIONS")
        self.log(f"{'='*80}\n")
        
        # Get all entity names
        with self.conn.cursor() as cur:
            cur.execute("SELECT entity_id, entity_name FROM entity_network_entities")
            entities = cur.fetchall()
        
        mention_count = 0
        
        for entity_id, entity_name in entities:
            # Find mentions in extracted_names table
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT file_path, occurrence_count 
                       FROM extracted_names 
                       WHERE name_string = %s""",
                    (entity_name,)
                )
                mentions = cur.fetchall()
            
            # Insert mentions
            if mentions:
                self.log(f"  {entity_name}: {len(mentions)} documents")
                with self.conn.cursor() as cur:
                    cur.executemany(
                        """INSERT INTO entity_network_mentions 
                           (entity_id, file_path, mention_count)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (entity_id, file_path)
                           DO UPDATE SET mention_count = EXCLUDED.mention_count""",
                        [(entity_id, file_path, count) for file_path, count in mentions]
                    )
                mention_count += len(mentions)
        
        self.log(f"\nLinked {mention_count} document mentions")
    
    def get_seed_names_from_database(self, min_mentions: int = 10) -> List[str]:
        """Get high-confidence names from database to use as seeds.
        
        Args:
            min_mentions: Minimum number of document mentions required.
            
        Returns:
            List of names to use as seeds.
        """
        self.log(f"Fetching seed names from database (min {min_mentions} mentions)...")
        
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT name_string, COUNT(*) as doc_count, SUM(occurrence_count) as total_mentions
                   FROM extracted_names
                   GROUP BY name_string
                   HAVING COUNT(*) >= %s
                   ORDER BY total_mentions DESC
                   LIMIT 100""",
                (min_mentions,)
            )
            results = cur.fetchall()
        
        seed_names = [name for name, _, _ in results]
        
        # Filter to only include names we have data for
        known_seeds = [name for name in seed_names if name in KNOWN_ENTITIES]
        
        self.log(f"Found {len(seed_names)} candidates, {len(known_seeds)} have known relationships")
        
        return known_seeds if known_seeds else seed_names[:20]  # Fallback to top 20
    
    def print_statistics(self):
        """Print network statistics."""
        self.log(f"\n{'='*80}")
        self.log("NETWORK STATISTICS")
        self.log(f"{'='*80}\n")
        
        with self.conn.cursor() as cur:
            # Entity counts by type
            cur.execute(
                """SELECT entity_type, COUNT(*) 
                   FROM entity_network_entities 
                   GROUP BY entity_type 
                   ORDER BY COUNT(*) DESC"""
            )
            type_counts = cur.fetchall()
            
            self.log("Entities by type:")
            for entity_type, count in type_counts:
                self.log(f"  {entity_type}: {count}")
            
            # Total relationships
            cur.execute("SELECT COUNT(*) FROM entity_network_relationships")
            total_rels = cur.fetchone()[0]
            self.log(f"\nTotal relationships: {total_rels}")
            
            # Relationships by type
            cur.execute(
                """SELECT relationship_type, COUNT(*) 
                   FROM entity_network_relationships 
                   GROUP BY relationship_type 
                   ORDER BY COUNT(*) DESC"""
            )
            rel_type_counts = cur.fetchall()
            
            self.log("\nRelationships by type:")
            for rel_type, count in rel_type_counts:
                self.log(f"  {rel_type}: {count}")
            
            # Relationships by degree
            cur.execute(
                """SELECT degree, COUNT(*) 
                   FROM entity_network_relationships 
                   GROUP BY degree 
                   ORDER BY degree"""
            )
            degree_counts = cur.fetchall()
            
            self.log("\nRelationships by degree:")
            for degree, count in degree_counts:
                self.log(f"  Degree {degree}: {count}")
            
            # Total mentions
            cur.execute("SELECT COUNT(*) FROM entity_network_mentions")
            total_mentions = cur.fetchone()[0]
            self.log(f"\nTotal document mentions: {total_mentions}")
        
        self.log(f"\n{'='*80}\n")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build entity relationship network from extracted names"
    )
    parser.add_argument(
        "--dsn",
        help="PostgreSQL DSN (overrides DATABASE_URL env var)"
    )
    parser.add_argument(
        "--seed",
        help="Comma-separated list of seed names to start from (e.g., 'Kushner,Leon Black')"
    )
    parser.add_argument(
        "--from-database",
        action="store_true",
        help="Use extracted names from database as seeds"
    )
    parser.add_argument(
        "--min-mentions",
        type=int,
        default=10,
        help="Minimum mentions required for database seeds (default: 10)"
    )
    parser.add_argument(
        "--link-mentions",
        action="store_true",
        help="Link entities to document mentions"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing entity network data before building (requires --confirm)"
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
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Check for --confirm on destructive operations
    if args.clear and not args.confirm and not args.dry_run:
        print("ERROR: --clear requires --confirm flag for safety.", file=sys.stderr)
        print("Use --dry-run to preview what would be cleared.", file=sys.stderr)
        print("\nExample: python3 scripts/build_entity_network.py --clear --confirm", file=sys.stderr)
        return 1
    
    # Handle dry-run mode
    if args.dry_run:
        print("[DRY RUN] Would perform the following operations:")
        if args.clear:
            print("  - Clear existing entity network data (TRUNCATE entity_network_* tables)")
        print("  - Initialize database schema (CREATE TABLE IF NOT EXISTS)")
        if args.from_database:
            print(f"  - Load seed names from database (min_mentions={args.min_mentions})")
        elif args.seed:
            print(f"  - Use seed names: {args.seed}")
        else:
            print("  - Use default seed names: Jeffrey Epstein, Ghislaine Maxwell, Leon Black, Jared Kushner, Leslie Wexner")
        print("  - Build entity network from seed data")
        if args.link_mentions:
            print("  - Link entities to document mentions")
        return 0
    
    # Connect to database using centralized utility
    conn = connect_db(args.dsn)
    
    try:
        # Initialize builder
        builder = EntityNetworkBuilder(conn, verbose=args.verbose)
        
        # Clear existing data if requested
        if args.clear:
            if args.verbose:
                print("Clearing existing entity network data...")
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE entity_network_mentions CASCADE")
                cur.execute("TRUNCATE TABLE entity_network_relationships CASCADE")
                cur.execute("TRUNCATE TABLE entity_network_entities CASCADE")
            if args.verbose:
                print("Existing data cleared.")
        
        builder.initialize_database()
        
        # Determine seed names
        if args.from_database:
            seed_names = builder.get_seed_names_from_database(args.min_mentions)
        elif args.seed:
            seed_names = [name.strip() for name in args.seed.split(",")]
        else:
            # Default: use high-profile names from known entities
            seed_names = ["Jeffrey Epstein", "Ghislaine Maxwell", "Leon Black", 
                         "Jared Kushner", "Leslie Wexner"]
        
        # Build network
        builder.build_from_seed_data(seed_names)
        
        # Link to document mentions if requested
        if args.link_mentions:
            builder.link_to_document_mentions()
        
        # Print statistics
        builder.print_statistics()
        
        print("\nNetwork building complete!")
        print("\nQuery examples:")
        print("  -- Find all relationships for a person:")
        print("  SELECT e1.entity_name as source, r.relationship_type, e2.entity_name as target")
        print("  FROM entity_network_relationships r")
        print("  JOIN entity_network_entities e1 ON r.source_entity_id = e1.entity_id")
        print("  JOIN entity_network_entities e2 ON r.target_entity_id = e2.entity_id")
        print("  WHERE e1.entity_name = 'Leon Black';")
        print()
        print("  -- Find all companies someone is connected to:")
        print("  SELECT e2.entity_name, r.relationship_type")
        print("  FROM entity_network_relationships r")
        print("  JOIN entity_network_entities e1 ON r.source_entity_id = e1.entity_id")
        print("  JOIN entity_network_entities e2 ON r.target_entity_id = e2.entity_id")
        print("  WHERE e1.entity_name = 'Jeffrey Epstein' AND e2.entity_type = 'company';")
        print()
        print("  -- Find common connections between two people:")
        print("  SELECT DISTINCT e3.entity_name, e3.entity_type")
        print("  FROM entity_network_relationships r1")
        print("  JOIN entity_network_relationships r2 ON r1.target_entity_id = r2.target_entity_id")
        print("  JOIN entity_network_entities e1 ON r1.source_entity_id = e1.entity_id")
        print("  JOIN entity_network_entities e2 ON r2.source_entity_id = e2.entity_id")
        print("  JOIN entity_network_entities e3 ON r1.target_entity_id = e3.entity_id")
        print("  WHERE e1.entity_name = 'Jeffrey Epstein' AND e2.entity_name = 'Leon Black';")
        
    finally:
        conn.close()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
