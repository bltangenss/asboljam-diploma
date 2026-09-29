"""REAL boundary tests use generated TEST fixtures, never enterprise evidence."""
import contextlib
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import select
from database_fixture import isolated_database_url
from apps.api import engine
from apps.api.data_policy import execution_context
from apps.api.db import Audit, Forecast, Job, Organization, OrganizationSource, Plan, make_engine, migrate, sessions
from apps.api.db import User
from apps.api.importing import insert_rows
from apps.worker import main as worker


def context():
    return dict(version='execution-v1', organization_id='A', branch_id='001',
        data_policy='real_only', data_origin='REAL', date_policy='explicit_closed_day',
        timezone='Asia/Qyzylorda', currency='KZT', as_of_utc='2026-04-22T20:30:00+00:00',
        as_of_date='2026-04-23', origin='2026-04-22', target_date='2026-04-23',
        inventory_snapshot_date='2026-04-23', horizon_days=1, usage_mode='TEST', historical=False,
        source=dict(source_id='generated-boundary-fixture', mapping_version='canonical-v1',
            branch_id='001', authorization_reference='generated-test-only', purpose='test_fixture', version=1))


def sales():
    first = date(2026, 1, 1)
    return [dict(branch_id='001', meal_id='01', date=(first + timedelta(days=day)).isoformat(),
                 units_sold=20 + day % 7, data_origin='REAL') for day in range(112)]


def procurement_inputs():
    captured = context()
    return dict(forecast_result=dict(branch_id='001', origin=captured['origin'], target_date=captured['target_date'],
            data_origin='REAL', execution_context=deepcopy(captured), predictions=[dict(meal_id='01', point_forecast=10)]),
        ingredients=[dict(ingredient_id='rice', ingredient_name='Generated rice', unit='kg', yield_factor='0.5', storage_capacity='100', data_origin='REAL'),
                     dict(ingredient_id='water', ingredient_name='Generated water', unit='L', yield_factor='1', storage_capacity='100', data_origin='REAL')],
        recipes=[dict(meal_id='01', ingredient_id='rice', net_qty_per_portion='0.25', recipe_version='v1', data_origin='REAL')],
        inventory=[dict(branch_id='001', ingredient_id='rice', lot_id='zero-count', on_hand_qty='0', unit='kg',
                        snapshot_date='2026-04-23', expiry_date='2026-04-23', data_origin='REAL')],
        offers=[], suppliers=[], branch_id='001', target_date='2026-04-23', budget='0', execution_context=captured)


class RealEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = sales()
        cls.forecast = engine.forecast(cls.rows, '001', '2026-04-22', execution_context=context())

    def test_real_forecast_preserves_captured_dates_origin_and_scientific_contract(self):
        result = self.forecast
        self.assertEqual(result['data_origin'], 'REAL')
        self.assertEqual(result['execution_context'], context())
        self.assertEqual(result['target_date'], '2026-04-23')
        self.assertEqual(result['metadata']['features'], engine.FEATURES)
        self.assertEqual(result['metadata']['test_days'], 28)
        self.assertLess(result['metadata']['train_end'], result['metadata']['test_start'])
        self.assertEqual(len({(row['test_start'], row['test_end']) for row in result['metrics']}), 1)
        self.assertIsNone(result['predictions'][0]['p90'])
        altered = deepcopy(context())
        copied = engine.forecast(self.rows, '001', '2026-04-22', execution_context=altered)
        altered['source']['source_id'] = 'changed-after-compute'
        self.assertEqual(copied['execution_context'], context())

    def test_audit_only_oracle_and_future_sales_never_enter_real_forecast_features(self):
        rows = deepcopy(self.rows)
        for row in rows:
            row.update(available_portions=999999, stockout_flag=1, promo=1, price_kzt='999999',
                       latent_demand_ORACLE_ONLY=555555, demand_multiplier=777777, base_daily_demand=888888)
        rows.append(dict(rows[-1], date='2026-04-23', units_sold=999999))
        result = engine.forecast(rows, '001', '2026-04-22', execution_context=context())
        self.assertEqual(result['predictions'], self.forecast['predictions'])
        self.assertEqual(result['metrics'], self.forecast['metrics'])
        self.assertEqual(result['metadata']['data_hash'], self.forecast['metadata']['data_hash'])

    def test_context_mismatches_fail_before_model_fitting(self):
        mutations = [dict(branch_id='other'), dict(data_origin='SYNTHETIC'), dict(data_policy='synthetic_only'),
            dict(origin='2026-04-23'), dict(target_date='2026-04-24'), dict(inventory_snapshot_date='2026-04-22'),
            dict(horizon_days=7), dict(as_of_date='2026-04-22'), dict(as_of_utc='2026-04-22T20:30:00'),
            dict(timezone='invalid-zone'), dict(usage_mode='DEMO'), dict(historical=True)]
        with patch.object(engine, '_evaluate') as evaluate:
            for mutation in mutations:
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'Invalid calculation execution context'):
                    engine.forecast(self.rows, '001', '2026-04-22', execution_context=dict(context(), **mutation))
        evaluate.assert_not_called()

    def test_mixed_missing_and_foreign_branch_sales_are_rejected(self):
        for mutation in (dict(data_origin='SYNTHETIC'), dict(data_origin=None), dict(branch_id='002')):
            with self.subTest(mutation=mutation):
                rows = deepcopy(self.rows)
                rows[0].update(mutation)
                with self.assertRaises(ValueError):
                    engine.forecast(rows, '001', '2026-04-22', execution_context=context())

    def test_incomplete_real_history_is_not_filled_with_zero(self):
        with self.assertRaisesRegex(ValueError, 'Missing daily sales'):
            engine.forecast(self.rows[:40] + self.rows[41:], '001', '2026-04-22', execution_context=context())
        with self.assertRaisesRegex(ValueError, 'at least 84'):
            engine.forecast(self.rows[-83:], '001', '2026-04-22', execution_context=context())

    def test_history_preflight_performs_no_model_fit(self):
        with patch.object(engine, '_fit_boosting') as fit:
            summary = engine.validate_forecast_history(self.rows, '001', '2026-04-22')
            self.assertEqual(summary, dict(history_start='2026-01-01', history_end='2026-04-22',
                                           meal_count=1, observations=112))
            with self.assertRaises(ValueError):
                engine.validate_forecast_history(self.rows[-83:], '001', '2026-04-22')
        fit.assert_not_called()

    def test_historical_context_is_preserved_without_consulting_current_clock(self):
        captured = dict(context(), as_of_utc='2026-05-01T00:00:00+00:00', as_of_date='2026-05-01', historical=True)
        result = engine.forecast(self.rows, '001', '2026-04-22', execution_context=captured)
        self.assertEqual(result['execution_context'], captured)
        self.assertEqual(result['predictions'], self.forecast['predictions'])

    def test_missing_real_stock_is_unknown_but_explicit_zero_is_a_shortage(self):
        arguments = procurement_inputs()
        arguments['inventory'] = [dict(arguments['inventory'][0], ingredient_id='water', unit='L')]
        with self.assertRaisesRegex(ValueError, 'unknown stock is not zero'):
            engine.procurement(**arguments)
        result = engine.procurement(**procurement_inputs())
        self.assertEqual(result['data_origin'], 'REAL')
        self.assertEqual(result['execution_context'], context())
        self.assertEqual(result['shortage_count'], 1)
        self.assertEqual(result['requirements'][0]['usable_stock'], '0')
        self.assertTrue(result['constraints_valid'])

    def test_procurement_rejects_every_conflicting_origin_and_source_context(self):
        for kind in ('ingredients', 'recipes', 'inventory', 'offers', 'suppliers'):
            for origin in ('SYNTHETIC', None):
                with self.subTest(kind=kind, origin=origin):
                    arguments = procurement_inputs()
                    if arguments[kind]:
                        arguments[kind][0]['data_origin'] = origin
                    else:
                        arguments[kind].append({'data_origin': origin})
                    with self.assertRaisesRegex(ValueError, 'input origin'):
                        engine.procurement(**arguments)
        for mutation in (dict(data_origin='SYNTHETIC'), dict(execution_context=None), dict(branch_id='002'), dict(target_date='2026-04-24')):
            with self.subTest(source=mutation):
                arguments = procurement_inputs()
                arguments['forecast_result'].update(mutation)
                with self.assertRaises(ValueError):
                    engine.procurement(**arguments)

    def test_unused_unobserved_stock_and_its_offers_are_omitted_from_real_plan(self):
        arguments = procurement_inputs()
        arguments['budget'] = '10'
        arguments['suppliers'] = [dict(supplier_id='supplier', data_origin='REAL')]
        arguments['offers'] = [dict(supplier_id='supplier', ingredient_id=ingredient, pack_qty='1',
            unit_cost_kzt='1', min_packs=1, max_packs=10, lead_time_days=0, data_origin='REAL')
            for ingredient in ('rice', 'water')]
        result = engine.procurement(**arguments)
        self.assertEqual([row['ingredient_id'] for row in result['requirements']], ['rice'])
        self.assertEqual([row['ingredient_id'] for row in result['lines']], ['rice'])
        self.assertEqual(result['requirements'][0]['usable_stock'], '0')
        self.assertEqual(result['excluded_offers'], [dict(supplier_id='supplier', ingredient_id='water',
            reason='unobserved_stock_not_required')])
        self.assertTrue(result['constraints_valid'])
        self.assertEqual(result['shortage_count'], 0)

    def test_unused_explicit_zero_and_expired_counted_stock_remain_visible(self):
        for quantity, expiry, expired in (('0', '2026-04-23', False), ('7', '2026-04-22', True),
                                          ('7', '2026-04-23', False)):
            with self.subTest(quantity=quantity, expiry=expiry):
                arguments = procurement_inputs()
                arguments['inventory'].append(dict(arguments['inventory'][0], ingredient_id='water',
                    unit='L', lot_id='counted-water', on_hand_qty=quantity, expiry_date=expiry))
                result = engine.procurement(**arguments)
                stock = next(row for row in result['requirements'] if row['ingredient_id'] == 'water')
                self.assertEqual(stock['usable_stock'], '0' if expired else quantity)
                self.assertEqual(stock['gross_required'], '0')
                self.assertEqual('counted-water' in result['expired_lot_ids'], expired)

    def test_legacy_direct_engine_calls_do_not_invent_origin(self):
        result = engine.forecast(self.rows, '001', '2026-04-22')
        self.assertNotIn('data_origin', result)
        self.assertNotIn('execution_context', result)

    def test_synthetic_legacy_forecast_can_keep_fixed_demo_procurement_context(self):
        arguments = procurement_inputs()
        captured = dict(context(), data_policy='synthetic_only', data_origin='SYNTHETIC',
            date_policy='synthetic_fixed', timezone=None, usage_mode='DEMO', source=None,
            as_of_date='2026-04-22', origin='2025-12-31', target_date='2026-01-01',
            inventory_snapshot_date='2026-01-01')
        arguments.update(execution_context=captured, target_date='2026-01-01')
        arguments['forecast_result'].update(data_origin='SYNTHETIC', origin='2025-12-31', target_date='2026-01-01')
        arguments['forecast_result'].pop('execution_context')
        for key in ('ingredients', 'recipes', 'inventory', 'offers', 'suppliers'):
            for row in arguments[key]:
                row['data_origin'] = 'SYNTHETIC'
        arguments['inventory'][0]['snapshot_date'] = '2026-01-01'
        result = engine.procurement(**arguments)
        self.assertEqual(result['execution_context'], captured)
        self.assertEqual(result['data_origin'], 'SYNTHETIC')
        self.assertEqual([row['ingredient_id'] for row in result['requirements']], ['rice', 'water'])
        self.assertEqual(result['requirements'][1]['usable_stock'], '0')


class RealWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'execution.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.factory = sessions(self.engine)
        with self.factory() as db:
            db.add(Organization(id='A', name='Generated boundary fixture', timezone='Asia/Qyzylorda', currency='KZT',
                status='active', data_policy='real_only', provenance='test_fixture'))
            db.add(OrganizationSource(organization_id='A', actor_id='operator:test', **context()['source']))
            db.add(User(id='actor', organization_id='A', email='generated@test.invalid', password_hash='unused',
                        role='manager', branch_ids=['001']))
            insert_rows(db, 'A', 'branches', [dict(branch_id='001', branch_name='Generated fixture', data_origin='REAL')])
            db.commit()
            self.context = execution_context(db, 'A', '001', '2026-04-22',
                instant=datetime(2026, 4, 22, 20, 30, tzinfo=timezone.utc))
        self.assertEqual(self.context, context())
        self.snapshot = dict(execution_context=deepcopy(self.context), sales=[sales()[-1]],
            meals=[dict(meal_id='01', meal_name='Generated meal', data_origin='REAL')])
        self.result = dict(branch_id='001', origin='2026-04-22', target_date='2026-04-23', data_origin='REAL',
            execution_context=deepcopy(self.context), predictions=[dict(meal_id='01', point_forecast=22)])
        self.queue(self.snapshot)

    def queue(self, snapshot):
        with self.factory() as db:
            job = db.get(Job, 'job')
            if job is None:
                job = Job(id='job', organization_id='A', branch_id='001', actor_id='actor', kind='forecast',
                    payload=dict(branch_id='001', origin='2026-04-22', model='seasonal_naive_7'))
                db.add(job)
            job.snapshot = deepcopy(snapshot)
            job.status, job.error, job.result_id, job.started_at = 'queued', None, None, None
            db.commit()

    def assert_failed(self, code):
        with self.factory() as db:
            job = db.get(Job, 'job')
            self.assertEqual(job.status, 'failed')
            self.assertTrue(job.error.startswith(code), job.error)
            self.assertNotIn('generated-test-only', job.error)
            self.assertIsNone(job.result_id)
            self.assertIsNone(db.get(Forecast, 'job'))
            self.assertIsNone(db.get(Plan, 'job'))

    def procurement_job(self, snapshot=None):
        arguments = procurement_inputs()
        if snapshot is None:
            snapshot = {'execution_context': deepcopy(self.context),
                'forecast_result': arguments['forecast_result'], 'ingredients': arguments['ingredients'],
                'recipes': arguments['recipes'], 'inventory_lots': arguments['inventory'],
                'supplier_offers': arguments['offers'], 'suppliers': arguments['suppliers']}
        self.queue(snapshot)
        with self.factory() as db:
            source = db.get(Forecast, 'source')
            if source is None:
                source = Forecast(id='source', organization_id='A', branch_id='001')
                db.add(source)
            source.result = deepcopy(snapshot['forecast_result'])
            job = db.get(Job, 'job')
            job.kind = 'procurement'
            job.payload = dict(branch_id='001', forecast_id='source', budget='0', strategy='point')
            db.commit()
        return snapshot

    def test_real_job_preserves_test_origin_timezone_and_captured_context(self):
        with patch.object(worker, 'forecast', return_value=deepcopy(self.result)) as calculate:
            self.assertTrue(worker.run_once(self.factory))
        self.assertEqual(calculate.call_args.kwargs['execution_context'], context())
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'succeeded')
            result = db.get(Forecast, 'job').result
            self.assertEqual(result['execution_context'], context())
            self.assertEqual(result['data_origin'], 'REAL')
            self.assertEqual(result['target_date'], '2026-04-23')
            self.assertEqual(result['predictions'][0]['meal_name'], 'Generated meal')
            self.assertEqual(len(result['input_snapshot_sha256']), 64)

    def test_real_job_without_context_is_never_accepted_as_legacy_demo(self):
        self.queue({key: value for key, value in self.snapshot.items() if key != 'execution_context'})
        with patch.object(worker, 'forecast') as calculate:
            worker.run_once(self.factory)
        calculate.assert_not_called()
        self.assert_failed('JOB_INPUT_INVALID')

    def test_real_procurement_preserves_forecast_context_and_rejects_mixed_sources(self):
        original = self.procurement_job()
        for kind in ('ingredients', 'recipes', 'inventory_lots', 'supplier_offers', 'suppliers'):
            with self.subTest(kind=kind):
                snapshot = deepcopy(original)
                if snapshot[kind]:
                    snapshot[kind][0]['data_origin'] = 'SYNTHETIC'
                else:
                    snapshot[kind] = [{'data_origin': 'SYNTHETIC'}]
                self.procurement_job(snapshot)
                with patch.object(worker, 'procurement') as calculate:
                    worker.run_once(self.factory)
                calculate.assert_not_called()
                self.assert_failed('JOB_INPUT_INVALID')
        snapshot = deepcopy(original)
        snapshot['forecast_result']['execution_context']['source']['source_id'] = 'other-source'
        self.procurement_job(snapshot)
        with patch.object(worker, 'procurement') as calculate:
            worker.run_once(self.factory)
        calculate.assert_not_called()
        self.assert_failed('JOB_SCOPE_INVALID')
        self.procurement_job(original)
        self.assertTrue(worker.run_once(self.factory))
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'succeeded')
            result = db.get(Plan, 'job').result
            self.assertEqual(result['execution_context'], self.context)
            self.assertEqual(result['data_origin'], 'REAL')
            self.assertEqual(result['shortage_count'], 1)

    def test_snapshot_origin_branch_future_date_and_context_are_checked_before_compute(self):
        mutations = [('sales', 'data_origin', 'SYNTHETIC'), ('meals', 'data_origin', None),
                     ('sales', 'branch_id', '002'), ('sales', 'date', '2026-04-23')]
        for kind, key, value in mutations:
            with self.subTest(kind=kind, key=key):
                snapshot = deepcopy(self.snapshot)
                snapshot[kind][0][key] = value
                self.queue(snapshot)
                with patch.object(worker, 'forecast') as calculate:
                    worker.run_once(self.factory)
                calculate.assert_not_called()
                self.assert_failed('JOB_SCOPE_INVALID' if key == 'branch_id' else 'JOB_INPUT_INVALID')
        for key, value in (('organization_id', 'B'), ('branch_id', '002')):
            snapshot = deepcopy(self.snapshot)
            snapshot['execution_context'][key] = value
            self.queue(snapshot)
            with patch.object(worker, 'forecast') as calculate:
                worker.run_once(self.factory)
            calculate.assert_not_called()
            self.assert_failed('JOB_SCOPE_INVALID')

    def test_changed_source_registration_before_and_during_compute_blocks_publication(self):
        def change_source():
            with self.factory() as db:
                db.get(OrganizationSource, 'A').authorization_reference = 'changed-test-registration'
                db.commit()
        def calculate(*args, **kwargs):
            change_source()
            return deepcopy(self.result)
        with patch.object(worker, 'forecast', side_effect=calculate):
            worker.run_once(self.factory)
        self.assert_failed('JOB_ACCESS_REVOKED')
        self.queue(self.snapshot)
        with patch.object(worker, 'forecast') as calculate:
            worker.run_once(self.factory)
        calculate.assert_not_called()
        self.assert_failed('JOB_ACCESS_REVOKED')

    def test_conflicting_engine_result_is_not_relabelled_or_logged(self):
        for mutation in (dict(data_origin='SYNTHETIC'), dict(target_date='2026-04-24'),
                         dict(execution_context=dict(context(), source={'authorization_reference': 'private-fixture-sentinel'}))):
            with self.subTest(mutation=mutation):
                self.queue(self.snapshot)
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream), patch.object(worker, 'forecast', return_value=dict(self.result, **mutation)):
                    worker.run_once(self.factory)
                self.assert_failed('JOB_SCOPE_INVALID' if 'target_date' in mutation else 'JOB_INPUT_INVALID')
                self.assertNotIn('private-fixture-sentinel', stream.getvalue())
        with self.factory() as db:
            self.assertTrue(all(set(row.details) == {'code'} for row in db.scalars(select(Audit))))


if __name__ == '__main__':
    unittest.main()
