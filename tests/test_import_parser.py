"""Parser regressions use only the repository's synthetic fixtures; no database writes."""
import csv
import io
import json
import unittest
from pathlib import Path

from apps.api.importing import SCHEMAS, parse_csv


RAW = Path(__file__).resolve().parents[1] / 'data' / 'raw'


def first_synthetic_row(kind):
    # The research dataset has no optional day factors; the KZ demo provides a sample.
    path = RAW / f'{kind}.csv' if kind != 'day_factors' else RAW.parent / 'kz' / 'day_factors.csv'
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return next(csv.DictReader(stream))


def csv_text(row):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return stream.getvalue()


class ImportParserTests(unittest.TestCase):
    def test_malformed_and_oversized_headers_fail_without_echoing_input(self):
        for source in ('"PRIVATE_HEADER_UNTERMINATED', 'PRIVATE_HEADER_' + 'x' * (csv.field_size_limit() + 1)):
            with self.subTest(size=len(source)):
                rows, errors = parse_csv('daily_sales', source)
                self.assertEqual(rows, [])
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0]['code'], 'INVALID_CSV')
                self.assertGreaterEqual(errors[0]['row_number'], 1)
                self.assertNotIn('PRIVATE_HEADER', json.dumps(errors))

    def test_all_nine_synthetic_schemas_still_parse(self):
        # Nine operational schemas plus the optional day factors.
        self.assertEqual(len(SCHEMAS), 10)
        self.assertEqual(list(SCHEMAS)[-1], 'day_factors')
        for kind in SCHEMAS:
            with self.subTest(kind=kind):
                sample = first_synthetic_row(kind)
                rows, errors = parse_csv(kind, csv_text(sample))
                self.assertEqual(errors, [])
                self.assertEqual(len(rows), 1)
                self.assertEqual(set(rows[0]), set(SCHEMAS[kind].split()))
                self.assertEqual(rows[0]['data_origin'], 'SYNTHETIC')
                for field in rows[0]:
                    if field.endswith('_id'):
                        self.assertEqual(rows[0][field], sample[field])
                        self.assertIsInstance(rows[0][field], str)

    def test_real_origin_remains_rejected_for_every_schema(self):
        for kind in SCHEMAS:
            with self.subTest(kind=kind):
                sample = first_synthetic_row(kind)
                sample['data_origin'] = 'REAL'
                rows, errors = parse_csv(kind, csv_text(sample))
                self.assertEqual(rows, [])
                self.assertTrue(any(error['field'] == 'data_origin' and error['code'] == 'INVALID_VALUE'
                                    for error in errors))

    def test_malformed_later_record_preserves_existing_partial_preview_policy(self):
        source = csv_text(first_synthetic_row('daily_sales')) + '"PRIVATE_RECORD_UNTERMINATED'
        rows, errors = parse_csv('daily_sales', source)
        self.assertEqual(len(rows), 1)
        self.assertEqual([error['code'] for error in errors], ['INVALID_CSV'])
        self.assertNotIn('PRIVATE_RECORD', json.dumps(errors))

    def test_unknown_header_returns_only_canonical_expected_columns(self):
        rows, errors = parse_csv('daily_sales', 'PRIVATE_UNKNOWN_HEADER\nPRIVATE_VALUE\n')
        self.assertEqual(rows, [])
        self.assertEqual(errors[0]['code'], 'INVALID_COLUMNS')
        self.assertEqual(errors[0]['expected'], SCHEMAS['daily_sales'].split())
        self.assertNotIn('PRIVATE_', json.dumps(errors))


if __name__ == '__main__':
    unittest.main()
