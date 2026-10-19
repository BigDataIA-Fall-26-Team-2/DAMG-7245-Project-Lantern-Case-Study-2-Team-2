"""CS2 P0 validated records and P1 tier/citation/period acceptance checks."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schema import validate_record
from src.schema_cs2 import BlockV2, FinancialFact, upgrade_cs1_record

SAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'cs2'


def sample(name):
    return json.loads((SAMPLES / name).read_text().splitlines()[0])


def test_sample_round_trip_and_cs1_upgrade():
    record = sample('records.jsonl')
    validated = BlockV2.model_validate(record)
    assert json.loads(validated.to_jsonl()) == record
    legacy = {k: v for k, v in record.items() if k not in
              {'deal_id', 'source_type', 'tier', 'citation', 'lineage', 'ingest_flags'}}
    legacy['schema'] = 'lantern/1.0'
    assert validate_record(legacy).schema_version == 'lantern/1.0'
    assert upgrade_cs1_record(legacy).model_dump(by_alias=True) == record
    for line in (SAMPLES / 'facts.jsonl').read_text().splitlines():
        fact = FinancialFact.model_validate_json(line)
        assert FinancialFact.model_validate_json(fact.to_jsonl()) == fact


@pytest.mark.parametrize('field,value', [
    ('deal_id', 'deal_b'), ('tier', 4), ('tier', True), ('doc_id', 'AAPL'),
    ('schema', 'lantern/1.0'), ('bbox', [0, 0, float('nan'), 10]),
    ('text', ' '), ('cik', None), ('ingest_flags', ['']),
])
def test_invalid_record_is_rejected(field, value):
    record = sample('records.jsonl')
    record[field] = value
    with pytest.raises(ValidationError):
        BlockV2.model_validate(record)


def test_mismatched_citation_hash_and_mutated_write_are_rejected():
    record = sample('records.jsonl')
    bad = copy.deepcopy(record)
    bad['lineage']['source_sha256'] = '0' * 64
    with pytest.raises(ValidationError, match='sha256'):
        BlockV2.model_validate(bad)
    bad = copy.deepcopy(record)
    bad['citation']['page'] = 2
    with pytest.raises(ValidationError, match='page/bbox'):
        BlockV2.model_validate(bad)
    block = BlockV2.model_validate(record)
    block.citation.bbox[0] = -1
    with pytest.raises(ValidationError):
        block.to_jsonl()


def test_private_scope_must_match_data_room_document():
    record = sample('records.jsonl')
    record.update(doc_id='DR-deal_a-001', deal_id='deal_a', source_type='dataroom',
                  tier=4, cik=None, ticker=None, form=None)
    assert BlockV2.model_validate(record).deal_id == 'deal_a'
    record['deal_id'] = 'deal_b'
    with pytest.raises(ValidationError, match='own deal scope'):
        BlockV2.model_validate(record)


@pytest.mark.parametrize('source,tier,doc_id,citation', [
    ('edgar_xbrl', 1, '0000320193-25-000079',
     {'kind': 'ixbrl_element', 'element_id': 'revenue-2025'}),
    ('edgar_xbrl', 1, '0000320193-25-000079',
     {'kind': 'ixbrl_context', 'concept': 'us-gaap:Revenues',
      'context_ref': 'FY2025', 'unit_ref': 'USD'}),
    ('dataroom', 3, 'DR-kestrel-001', {'kind': 'sheet_cell', 'sheet': 'Income', 'cell': 'B2'}),
    ('synthetic_web', 5, 'WEB-1234abcd', {'kind': 'web_span', 'start': 0, 'end': 10}),
])
def test_non_pdf_locator_kinds(source, tier, doc_id, citation):
    record = sample('records.jsonl')
    scope = 'kestrel' if source == 'dataroom' else 'public'
    citation['source_path'] = 'tests/fixtures/example-source'
    record.update(source_type=source, tier=tier, doc_id=doc_id, deal_id=scope,
                  citation=citation, source_path=citation['source_path'], page=None, bbox=None)
    assert BlockV2.model_validate(record).citation.kind == citation['kind']
    del citation[next(k for k in citation if k not in ('kind', 'source_path'))]
    with pytest.raises(ValidationError):
        BlockV2.model_validate(record)


@pytest.mark.parametrize('changes', [
    {'tier': 4}, {'tier': 5}, {'value': float('inf')}, {'value': None},
    {'start': None}, {'start': '2026-01-01'}, {'unit': ''}, {'citation': None},
    {'period_type': 'instant'}, {'metric': 'Revenue Total'},
    {'source_type': 'derived'},
])
def test_invalid_or_unverified_fact_is_rejected(changes):
    fact = sample('facts.jsonl')
    fact.update(changes)
    with pytest.raises(ValidationError):
        FinancialFact.model_validate(fact)
