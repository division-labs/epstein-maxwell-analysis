# Data Quality Corrections

## Overview

Automated data quality corrections have been implemented in the entity extraction pipeline to prevent common OCR artifacts, incomplete names, and misclassifications from entering the database.

## Implementation

The corrections are applied in `catalog_to_postgres.py` before entities are inserted into the `extracted_names` and `extracted_locations` tables.

### Function: `apply_entity_corrections(entity_name, entity_type)`

This function is called for every extracted entity and applies the following corrections:

## Correction Types

### 1. OCR Date Concatenation Artifacts

**Problem**: OCR incorrectly concatenates "Date:" form field labels with names.

**Corrections Applied**:
- `Jeffrey Epstein Date` → `Jeffrey Epstein`
- `Epstein Date` → `Jeffrey Epstein`
- `Jeffrey Epstein Death Date` → `Jeffrey Epstein`
- `Jeff Epstein Date` → `Jeffrey Epstein`
- `Maxwell Epstein Date` → `Jeffrey Epstein`
- `J. Epstein Date` → `Jeffrey Epstein`
- `Jeffery Epstein Date` → `Jeffrey Epstein`
- `--Jeffrey Epstein Supposedly Sealed Order Date` → `Jeffrey Epstein`

**Total**: 8 variants consolidated

### 2. Incomplete Name Canonicalization

**Problem**: Entity extraction captures surnames without full names, creating duplicate entities.

**Corrections Applied**:
- `Nathan` → `Alison J. Nathan`
- `Jeffrey` → `Jeffrey Epstein`
- `JEFFREY` → `Jeffrey Epstein`
- `Jeff` → `Jeffrey Epstein`
- `Strauss` → `Audrey Strauss`
- `Alex` → `Alex Acosta`
- `Acosta` → `Alex Acosta`
- `Chris` → `Christian Everdell`
- `Berman` → `Geoffrey S. Berman`

**Total**: 9 surname/nickname-to-fullname mappings

### 3. Non-Person Entity Filtering

**Problem**: OCR errors and legal abbreviations extracted as person entities.

**Entities Excluded**:
- `Replies` - Email system text ("Replies to this mailbox are not monitored")
- `Cir` - Legal abbreviation for "Circuit" (e.g., "2d Cir. 2015")
- `Se` - Legal abbreviation for "Section"
- `Tuesda` - OCR error (truncated "Tuesday")
- `Frida` - OCR error (truncated "Friday")
- `Bates` - Document numbering system ("Bates numbers" for discovery)
- `SHU OBS` - Special Housing Unit Observation (prison terminology)

**Total**: 7 non-person entities filtered

### 4. Location Reclassification

**Problem**: Address components misclassified as person names.

**Reclassifications**:
- `Saint Andrew` → `One Saint Andrew's Plaza` (location)
- `Saint Andrew's` → `One Saint Andrew's Plaza` (location)
- `Saint Andrews` → `One Saint Andrew's Plaza` (location)

**Context**: "One Saint Andrew's Plaza" is the address of the U.S. Attorney's Office for the Southern District of New York (Silvio J. Mollo Building).

**Total**: 3 variants reclassified from person names to locations

## Impact

These corrections ensure:

1. **Cleaner data from the start**: No need for post-processing cleanup
2. **Accurate entity counts**: Names are properly consolidated at extraction time
3. **Correct entity types**: Locations are classified correctly
4. **No false entities**: Non-person entities are filtered out immediately

## Adding New Corrections

To add new corrections, edit `catalog_to_postgres.py` and update the relevant dictionaries:

```python
# For canonical name mappings:
ENTITY_CANONICAL_MAPPINGS = {
    'Variant Name': 'Canonical Name',
}

# For non-person entity filtering:
NON_PERSON_ENTITIES = {
    'Entity to Exclude',
}

# For location reclassification:
LOCATION_ENTITIES = {
    'Name Misclassified as Location',
}
```

## Testing

Run the test script to verify corrections:

```bash
python3 -c "
from scripts.catalog_to_postgres import apply_entity_corrections

# Test a correction
result, rtype = apply_entity_corrections('Jeffrey Epstein Date', 'name')
print(f'Result: {result}, Type: {rtype}')
"
```

## Statistics

- **Total canonical mappings**: 17
- **Total non-person filters**: 7
- **Total location reclassifications**: 3
- **Total corrections applied**: 27 entity variants handled

## Future Enhancements

Potential additional corrections to consider:

1. Other truncated day names (following "Tuesda" pattern)
2. Additional legal abbreviations (following "Cir", "Se" pattern)
3. More OCR concatenation patterns
4. Other incomplete name variants
5. Additional address component patterns
