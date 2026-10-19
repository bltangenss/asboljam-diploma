"""Daily working choices preserve old variants, decisions and exact retry receipts."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import func, select

from apps.api.db import Audit, Forecast, Idempotency, Plan, ProductionPlan, StockMovement, User, WorkingPlanSelection
import test_production_plans as fixture


class WorkingPlanTests(unittest.TestCase):
    setUpClass = classmethod(fixture.ProductionPlanTests.setUpClass.__func__)
    setUp = fixture.ProductionPlanTests.setUp
    client = fixture.ProductionPlanTests.client
    compute_forecast = fixture.ProductionPlanTests.compute_forecast
    correct_sale = fixture.ProductionPlanTests.correct_sale
    payload = fixture.ProductionPlanTests.payload
    save = fixture.ProductionPlanTests.save
    enqueue = fixture.ProductionPlanTests.enqueue
    calculate = fixture.ProductionPlanTests.calculate

    def choose(self, client, saved, expected=0, key=None, **changes):
        return client.post('/api/v1/working-plan', json=dict(branch_id='1', production_plan_id=saved['id'],
            expected_version=expected, reason_code='expected_attendance', reason='Additional guests confirmed') | changes,
            headers={'Idempotency-Key': key or uuid.uuid4().hex})

    def view(self, client, **changes):
        return client.get('/api/v1/working-plan', params={'branch_id': '1', 'target_date': '2026-01-01'} | changes)

    def counts(self):
        with self.factory() as db:
            return tuple(db.scalar(select(func.count()).select_from(model)) for model in
                         (WorkingPlanSelection, Idempotency, StockMovement, Plan))

    def test_empty_read_has_no_side_effect_and_selecting_preserves_history(self):
        client = self.client()
        self.assertEqual(self.view(client).json(), {'version': 0, 'selection': None, 'history': []})
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        forecast = self.compute_forecast(client)
        first = self.save(client, forecast, 0)
        second = self.save(client, forecast, 9)
        forecast_before = client.get('/api/v1/forecasts/' + forecast).json()
        result = self.choose(client, first, reason='  Kitchen review  ')
        self.assertEqual(result.status_code, 201, result.text)
        selected = result.json()['selection']
        self.assertEqual((selected['reason'], selected['version']), ('Kitchen review', 1))
        self.assertEqual((selected['forecast_id'], selected['target_date'], selected['actor_id']),
                         (forecast, '2026-01-01', 'A-user'))
        self.assertEqual((selected['data_origin'], selected['usage_mode']), ('SYNTHETIC', 'DEMO'))
        latest = self.choose(client, second, expected=1, reason_code='kitchen_capacity').json()
        self.assertEqual(latest['version'], 2)
        self.assertEqual(latest['selection']['production_plan_id'], second['id'])
        self.assertEqual(latest['history'][1], selected)
        self.assertEqual(self.view(client).json(), latest)
        self.assertEqual(self.view(client, target_date='2025-12-31').json()['version'], 0)
        self.assertEqual(client.get('/api/v1/production-plans/' + first['id']).json(), first)
        self.assertEqual(client.get('/api/v1/forecasts/' + forecast).json(), forecast_before)
        self.assertEqual(self.counts(), (2, 2, 0, 0))
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action == 'working_plan.selected')), 2)

    def test_selection_never_rebinds_existing_purchase_or_changes_export(self):
        client = self.client(); forecast = self.compute_forecast(client)
        first = self.save(client, forecast, 2)
        purchase = self.calculate(client, forecast, first['id'])
        path = '/api/v1/plans/' + purchase['id']
        approved = client.post(path + '/approve', json={'expected_version': 1, 'reason': 'Human purchase decision'},
                               headers={'Idempotency-Key': uuid.uuid4().hex})
        self.assertEqual(approved.status_code, 200, approved.text)
        export_before = client.get(path + '/export').content
        plan_before = client.get(path).json()
        second = self.save(client, forecast, 200)
        self.assertEqual(self.choose(client, second).status_code, 201)
        self.assertEqual(client.get(path + '/export').content, export_before)
        self.assertEqual(client.get(path).json(), plan_before)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)), 0)

    def test_retry_is_exact_after_later_choice_and_changed_source(self):
        client = self.client(); forecast = self.compute_forecast(client)
        first = self.save(client, forecast); second = self.save(client, forecast, 8)
        key = uuid.uuid4().hex
        original = self.choose(client, first, key=key).json()
        self.assertEqual(self.choose(client, second, expected=1).status_code, 201)
        self.correct_sale(4)
        replay = self.choose(client, first, key=key)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json(), original)
        conflict = self.choose(client, second, key=key)
        self.assertEqual((conflict.status_code, conflict.json()['detail']['code']), (409, 'IDEMPOTENCY_CONFLICT'))
        self.assertEqual(self.counts(), (2, 2, 0, 0))

    def test_stale_version_stale_sources_and_unknown_sources_are_rejected(self):
        client = self.client(); forecast = self.compute_forecast(client); saved = self.save(client, forecast)
        self.assertEqual(self.choose(client, saved).status_code, 201)
        outdated = self.choose(client, saved)
        self.assertEqual(outdated.json()['detail']['code'], 'WORKING_PLAN_VERSION_CONFLICT')
        self.correct_sale(7)
        changed = self.choose(client, saved, expected=1)
        self.assertEqual(changed.json()['detail']['code'], 'INPUTS_CHANGED')
        with self.factory() as db:
            production = db.get(ProductionPlan, saved['id'])
            production.input_lineage = {}
            db.commit()
        # The forecast remains stale, and historical reads remain available.
        self.assertEqual(self.view(client).json()['version'], 1)
        newer = self.compute_forecast(client); current = self.save(client, newer)
        with self.factory() as db:
            db.get(ProductionPlan, current['id']).input_lineage = {}
            db.commit()
        unknown = self.choose(client, current, expected=1)
        self.assertEqual(unknown.json()['detail']['code'], 'INPUTS_UNVERIFIED')
        self.assertEqual(self.counts(), (1, 1, 0, 0))

    def test_roles_branch_organization_and_replay_check_current_permissions(self):
        client = self.client(); forecast = self.compute_forecast(client); saved = self.save(client, forecast)
        key = uuid.uuid4().hex
        self.assertEqual(self.choose(client, saved, key=key).status_code, 201)
        other = self.client('B')
        self.assertEqual(self.view(other).json()['selection'], None)
        self.assertEqual(self.choose(other, saved).status_code, 404)
        self.assertEqual(self.view(client, branch_id='2').status_code, 403)
        for role in ('analyst', 'warehouse'):
            with self.factory() as db:
                db.get(User, 'A-user').role = role; db.commit()
            self.assertEqual(self.view(client).status_code, 200)
            self.assertEqual(self.choose(client, saved, key=key).status_code, 403)
        with self.factory() as db:
            user = db.get(User, 'A-user'); user.role = 'manager'; user.branch_ids = ['2']; db.commit()
        self.assertEqual(self.choose(client, saved, key=key).status_code, 403)
        self.assertEqual(self.view(client).status_code, 403)

    def test_payload_reason_key_csrf_and_date_validation(self):
        client = self.client(); forecast = self.compute_forecast(client); saved = self.save(client, forecast)
        for changes in ({'expected_version': True}, {'expected_version': '0'}, {'expected_version': -1},
                        {'reason_code': 'because'}, {'reason': '  '}, {'reason_code': 'other', 'reason': ''},
                        {'reason': 'x' * 1001}, {'surprise': True}):
            self.assertEqual(self.choose(client, saved, **changes).status_code, 422)
        body = dict(branch_id='1', production_plan_id=saved['id'], expected_version=0,
                    reason_code='other', reason='Explicit explanation')
        self.assertEqual(client.post('/api/v1/working-plan', json=body).json()['detail']['code'], 'IDEMPOTENCY_REQUIRED')
        self.assertEqual(client.post('/api/v1/working-plan', json=body,
            headers={'Idempotency-Key': uuid.uuid4().hex, 'X-CSRF-Token': 'invalid'}).status_code, 403)
        self.assertEqual(client.post('/api/v1/working-plan', json=body,
            headers={'Idempotency-Key': uuid.uuid4().hex, 'Origin': 'https://foreign.example'}).status_code, 403)
        self.assertEqual(self.view(client, target_date='not-a-day').status_code, 422)
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_concurrent_choices_only_one_wins_and_same_command_retries_once(self):
        first_client = self.client(); second_client = self.client()
        forecast = self.compute_forecast(first_client); saved = self.save(first_client, forecast)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: self.choose(client, saved), (first_client, second_client)))
        self.assertCountEqual([result.status_code for result in results], [201, 409])
        self.assertEqual(self.counts(), (1, 1, 0, 0))
        key = uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: self.choose(client, saved, expected=1, key=key),
                                    (first_client, second_client)))
        self.assertEqual([result.status_code for result in results], [201, 201])
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(self.counts(), (2, 2, 0, 0))

    def test_failure_between_selection_and_receipt_rolls_everything_back(self):
        client = self.client(); forecast = self.compute_forecast(client); saved = self.save(client, forecast)
        with patch('apps.api.working_plan.Audit', side_effect=RuntimeError('Controlled audit failure')):
            with self.assertRaises(RuntimeError):
                self.choose(client, saved)
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        self.assertEqual(self.choose(client, saved).status_code, 201)


if __name__ == '__main__':
    unittest.main()
