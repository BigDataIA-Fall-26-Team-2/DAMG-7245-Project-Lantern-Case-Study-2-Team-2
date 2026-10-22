"""CS2 record and financial-fact validation; CS1 exports retain their schema."""

import argparse
import json
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from src.schema import ACCESSION_RE, CIK_RE, Block

Scope = Literal['public', 'deal_a', 'deal_b', 'kestrel']
SourceType = Literal['edgar_filing', 'edgar_xbrl', 'edgar_8k_exhibit', 'dataroom', 'synthetic_web', 'derived']
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
Number = Annotated[float, Field(allow_inf_nan=False)]
Tier = Annotated[int, Field(strict=True, ge=1, le=6)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


def check_box(box):
    if len(box) != 4 or min(box) < 0 or box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError('bbox must be nonnegative [x0, top, x1, bottom] with positive area')
    return box


class SourceCitation(Contract):
    source_path: NonEmpty

    @field_validator('source_path')
    @classmethod
    def forward_slashes(cls, value):
        if '\\' in value:
            raise ValueError('source_path must use forward slashes')
        return value


class PdfCitation(SourceCitation):
    kind: Literal['pdf_bbox']
    page: Annotated[int, Field(strict=True, ge=1)]
    bbox: list[Number]

    @field_validator('bbox')
    @classmethod
    def valid_box(cls, value):
        return check_box(value)


class ElementCitation(SourceCitation):
    kind: Literal['ixbrl_element']
    element_id: NonEmpty


class ContextCitation(SourceCitation):
    kind: Literal['ixbrl_context']
    concept: NonEmpty
    context_ref: NonEmpty
    unit_ref: NonEmpty


class SheetCitation(SourceCitation):
    kind: Literal['sheet_cell']
    sheet: NonEmpty
    cell: Annotated[str, StringConstraints(pattern=r'^\$?[A-Z]+\$?[1-9][0-9]*$')]


class WebCitation(SourceCitation):
    kind: Literal['web_span']
    start: Annotated[int, Field(strict=True, ge=0)]
    end: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode='after')
    def ordered_span(self):
        if self.end <= self.start:
            raise ValueError('web span end must exceed start')
        return self


Citation = Annotated[PdfCitation | ElementCitation | ContextCitation | SheetCitation | WebCitation,
                     Field(discriminator='kind')]


class Lineage(Contract):
    parents: list[NonEmpty]
    source_sha256: Sha256


def check_source(doc_id, deal_id, source_type, tier, lineage):
    if source_type.startswith('edgar_'):
        if not ACCESSION_RE.fullmatch(doc_id) or deal_id != 'public':
            raise ValueError('EDGAR records require an accession doc_id and public scope')
        expected = 1 if source_type == 'edgar_xbrl' else 2
        if tier != expected:
            raise ValueError(f'{source_type} requires tier {expected}')
    elif source_type == 'dataroom':
        import re
        if deal_id == 'public' or not re.fullmatch(rf'DR-{deal_id}-[0-9]{{3}}', doc_id):
            raise ValueError('data-room doc_id must be DR-<deal_id>-<NNN> in its own deal scope')
        if tier not in (3, 4):
            raise ValueError('data-room records must be seller financials (3) or management claims (4)')
    elif source_type == 'synthetic_web':
        import re
        if not re.fullmatch(r'WEB-[0-9a-f]{8}', doc_id) or tier != 5:
            raise ValueError('synthetic web requires WEB-<sha8> doc_id and tier 5')
    elif not lineage.parents:
        raise ValueError('derived records require parent IDs')


class BlockV2(Block):
    model_config = ConfigDict(extra='forbid', populate_by_name=True, validate_assignment=True)

    schema_version: Literal['lantern/2.0'] = Field(alias='schema')
    company: NonEmpty
    cik: str | None
    ticker: str | None
    form: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    page: Annotated[int, Field(strict=True, ge=1)] | None
    bbox: list[Number] | None
    deal_id: Scope
    source_type: SourceType
    tier: Tier
    citation: Citation
    lineage: Lineage
    ingest_flags: list[NonEmpty]

    @field_validator('schema_version')
    @classmethod
    def check_schema_version(cls, value):
        return value

    @field_validator('doc_id')
    @classmethod
    def check_doc_id(cls, value):
        if not value.strip():
            raise ValueError('doc_id cannot be empty')
        return value

    @field_validator('cik')
    @classmethod
    def check_cik(cls, value):
        if value is not None and not CIK_RE.fullmatch(value):
            raise ValueError('cik must be null or 10 digits')
        return value

    @field_validator('page')
    @classmethod
    def check_page(cls, value):
        return value

    @field_validator('bbox')
    @classmethod
    def check_bbox(cls, value):
        return None if value is None else check_box(value)

    @model_validator(mode='after')
    def check_cs2(self):
        check_source(self.doc_id, self.deal_id, self.source_type, self.tier, self.lineage)
        if self.source_type.startswith('edgar_') and self.cik is None:
            raise ValueError('EDGAR records require cik')
        if self.sha256 != self.lineage.source_sha256:
            raise ValueError('lineage source_sha256 must match record sha256')
        if self.source_path != self.citation.source_path:
            raise ValueError('citation source_path must match record source_path')
        if self.citation.kind == 'pdf_bbox':
            if self.page != self.citation.page or self.bbox != self.citation.bbox:
                raise ValueError('PDF citation page/bbox must match record page/bbox')
        if self.text is not None and not self.text.strip() and self.table is None:
            raise ValueError('record text cannot be empty without a table')
        return self

    def to_jsonl(self):
        validated = type(self).model_validate(self.model_dump(by_alias=True))
        return json.dumps(validated.model_dump(by_alias=True), ensure_ascii=False)


class FinancialFact(Contract):
    fact_id: NonEmpty
    deal_id: Scope
    entity_id: NonEmpty
    concept: NonEmpty | None
    metric: Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$')]
    value: Number
    unit: NonEmpty
    period_type: Literal['instant', 'duration']
    start: date | None
    end: date
    dims: dict[NonEmpty, NonEmpty]
    decimals: int | Literal['INF'] | None
    tier: Annotated[int, Field(strict=True, ge=1, le=3)]
    source_type: SourceType
    doc_id: NonEmpty
    citation: Citation
    extractor: NonEmpty
    lineage: Lineage

    @model_validator(mode='after')
    def check_fact(self):
        check_source(self.doc_id, self.deal_id, self.source_type, self.tier, self.lineage)
        if self.source_type == 'derived':
            raise ValueError('calculator outputs belong outside the facts table')
        if self.period_type == 'duration' and (self.start is None or self.start > self.end):
            raise ValueError('duration facts require start <= end')
        if self.period_type == 'instant' and self.start is not None:
            raise ValueError('instant facts require start=null')
        if self.tier == 1 and (self.concept is None or self.citation.kind not in
                              ('pdf_bbox', 'ixbrl_element', 'ixbrl_context')):
            raise ValueError('XBRL facts require a concept and an XBRL/PDF locator')
        if self.citation.kind == 'ixbrl_context' and self.citation.concept != self.concept:
            raise ValueError('citation concept must match fact concept')
        return self

    def to_jsonl(self):
        validated = type(self).model_validate(self.model_dump())
        return validated.model_dump_json()


def upgrade_cs1_record(obj):
    old = Block.model_validate(obj)
    result = old.model_dump(by_alias=True)
    result.update(schema='lantern/2.0', deal_id='public', source_type='edgar_filing', tier=2,
                  citation={'kind': 'pdf_bbox', 'source_path': old.source_path,
                            'page': old.page, 'bbox': old.bbox},
                  lineage={'parents': [], 'source_sha256': old.sha256}, ingest_flags=[])
    return BlockV2.model_validate(result)


def main():
    parser = argparse.ArgumentParser(description='Validate CS2 records or financial facts without network access')
    parser.add_argument('kind', choices=['records', 'facts'])
    parser.add_argument('path')
    args = parser.parse_args()
    model = BlockV2 if args.kind == 'records' else FinancialFact
    count, errors = 0, []
    with open(args.path, encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                model.model_validate_json(line)
                count += 1
            except ValueError as error:
                errors.append(f'line {line_number}: {error}')
    print(f'{count} valid {args.kind}; {len(errors)} errors')
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
