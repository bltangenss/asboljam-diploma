"""Saved cooking decisions: real isolated database/API/worker/solver, no live business data."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import unittest
import uuid

from sqlalchemy import func, select

from apps.api.db import Audit, Forecast, Job, Organization, OrganizationSource, Plan, ProductionPlan, ProductionPlanReceipt, Record, StockMovement, User
from apps.api.data_policy import execution_context
from apps.api.lineage import capture_lineage
from apps.api.importing import rows_for
from apps.worker import main as worker
from apps.worker.calculation_process import calculate_snapshot
import test_import_lineage as fixture


class ProductionPlanTests(unittest.TestCase):
    setUpClass = classmethod(fixture.ImportLineageTests.setUpClass.__func__)
    setUp = fixture.ImportLineageTests.setUp
    client = fixture.ImportLineageTests.client
    compute_forecast = fixture.ImportLineageTests.compute_forecast
    correct_sale = fixture.ImportLineageTests.correct_sale

    def payload(self, forecast, portions=30, **changes):
        return dict(branch_id='1', forecast_id=forecast, name='Lunch variant',
                    reason='Expected additional guests', portions=[{'meal_id': '1', 'portions': portions}]) | changes

    def save(self, client, forecast, portions=30, key=None, **changes):
        response = client.post('/api/v1/production-plans', json=self.payload(forecast, portions, **changes),
            headers={'Idempotency-Key': key or uuid.uuid4().hex})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def counts(self):
        with self.factory() as db:
            return tuple(db.scalar(select(func.count()).select_from(table))
                for table in (ProductionPlan, ProductionPlanReceipt, StockMovement, Plan))

    def enqueue(self, client, forecast, production, **changes):
        return client.post('/api/v1/procurement', json=dict(branch_id='1', forecast_id=forecast,
            budget='10000', production_plan_id=production) | changes)

    def calculate(self, client, forecast, production, **changes):
        response = self.enqueue(client, forecast, production, **changes)
        self.assertEqual(response.status_code, 202, response.text)
        identifier = response.json()['run_id']
        self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        run = client.get('/api/v1/runs/' + identifier).json()
        self.assertEqual(run['status'], 'succeeded', run)
        return client.get('/api/v1/plans/' + identifier).json()

    def test_save_exact_zero_and_variants_does_not_post_stock_or_change_forecast(self):
        c = self.client(); forecast = self.compute_forecast(c)
        before = c.get('/api/v1/forecasts/' + forecast).json()
        zero = self.save(c, forecast, 0)
        large = self.save(c, forecast, 30, name='Next variant')
        self.assertNotEqual(zero['id'], large['id'])
        self.assertEqual(zero['portions'][0]['portions'], 0)
        self.assertEqual(zero['portions'][0]['forecast_point'], 2)
        self.assertEqual(zero['target_date'], '2026-01-01')
        self.assertEqual(zero['basis'], 'manual_portions')
        self.assertEqual(zero['input_freshness'], 'unchanged')
        self.assertEqual(self.counts(), (2, 2, 0, 0))
        self.assertEqual(c.get('/api/v1/forecasts/' + forecast).json(), before)
        self.assertEqual(c.patch('/api/v1/production-plans/' + zero['id'], json={'portions': []}).status_code, 405)
        listing = c.get('/api/v1/production-plans', params={'branch_id': '1','forecast_id': forecast,'limit': 1}).json()
        self.assertEqual(listing['total'], 2); self.assertEqual(listing['next_cursor'], '1')
        self.assertEqual(listing['items'][0]['id'], large['id'])

    def test_strict_portions_reason_name_and_exact_meal_set(self):
        c = self.client(); forecast = self.compute_forecast(c)
        for value in (True, False, '5', 1.5, -1, 1000000001, None):
            with self.subTest(value=value):
                result = c.post('/api/v1/production-plans', json=self.payload(forecast, value), headers={'Idempotency-Key': uuid.uuid4().hex})
                self.assertEqual(result.status_code, 422, result.text)
        for changes in ({'portions': []}, {'portions': [{'meal_id':'other','portions':1}]},
                {'portions': [{'meal_id':'1','portions':1}, {'meal_id':'1','portions':2}]},
                {'reason':'   '}, {'name':'   '}, {'reason':'x'*1001}, {'name':'x'*121}):
            result = c.post('/api/v1/production-plans', json=self.payload(forecast) | changes, headers={'Idempotency-Key': uuid.uuid4().hex})
            self.assertEqual(result.status_code, 422, result.text)
            if changes.get('portions'):
                self.assertEqual(result.json()['detail']['code'], 'PRODUCTION_MEALS_MISMATCH')
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        accepted = self.save(c, forecast, name='  Lunch  ', reason='  Three guests  ')
        self.assertEqual(accepted['name'], 'Lunch'); self.assertEqual(accepted['reason'], 'Three guests')

    def test_replay_recovers_original_receipt_after_source_correction_and_conflict_rejects(self):
        c = self.client(); forecast = self.compute_forecast(c); key = uuid.uuid4().hex
        original = self.save(c, forecast, key=key)
        self.correct_sale(11)
        replay = self.save(c, forecast, key=key)
        self.assertEqual(replay, original)
        detail = c.get('/api/v1/production-plans/' + original['id']).json()
        self.assertEqual(detail['input_freshness'], 'changed')
        self.assertEqual(detail['portions'], original['portions'])
        conflicting = c.post('/api/v1/production-plans', json=self.payload(forecast, 40), headers={'Idempotency-Key':key})
        self.assertEqual(conflicting.status_code,409)
        self.assertEqual(conflicting.json()['detail']['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.counts(), (1,1,0,0))

    def test_missing_key_stale_and_unknown_forecast_cannot_save_or_calculate(self):
        c=self.client(); forecast=self.compute_forecast(c)
        result=c.post('/api/v1/production-plans',json=self.payload(forecast))
        self.assertEqual(result.json()['detail']['code'],'IDEMPOTENCY_REQUIRED')
        saved=self.save(c,forecast)
        self.correct_sale(10)
        result=c.post('/api/v1/production-plans',json=self.payload(forecast),headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(result.json()['detail']['code'],'INPUTS_CHANGED')
        self.assertEqual(self.enqueue(c,forecast,saved['id']).json()['detail']['code'],'INPUTS_CHANGED')
        with self.factory() as db:
            row=db.get(Forecast,forecast); row.result={k:v for k,v in row.result.items() if k!='input_lineage'}; db.commit()
        result=c.post('/api/v1/production-plans',json=self.payload(forecast),headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(result.json()['detail']['code'],'INPUTS_UNVERIFIED')

    def test_roles_tenant_branch_and_replay_revalidate_current_access(self):
        c=self.client(); forecast=self.compute_forecast(c); key=uuid.uuid4().hex; saved=self.save(c,forecast,key=key)
        other=self.client('B')
        self.assertEqual(other.get('/api/v1/production-plans/'+saved['id']).status_code,404)
        self.assertEqual(self.enqueue(other,forecast,saved['id']).status_code,404)
        self.assertEqual(c.get('/api/v1/production-plans?branch_id=2').status_code,403)
        for role in ('analyst','warehouse'):
            with self.factory() as db:
                user=db.get(User,'A-user');user.role=role;db.commit()
            self.assertEqual(c.get('/api/v1/production-plans/'+saved['id']).status_code,200)
            response=c.post('/api/v1/production-plans',json=self.payload(forecast),headers={'Idempotency-Key':key})
            self.assertEqual(response.status_code,403)
        with self.factory() as db:
            user=db.get(User,'A-user');user.role='manager';user.branch_ids=['2'];db.commit()
        self.assertEqual(c.get('/api/v1/production-plans/'+saved['id']).status_code,404)
        self.assertEqual(c.post('/api/v1/production-plans',json=self.payload(forecast),headers={'Idempotency-Key':key}).status_code,403)

    def test_exact_manual_quantity_reaches_real_solver_and_export_without_quantiles(self):
        c=self.client(); forecast=self.compute_forecast(c); saved=self.save(c,forecast,30)
        plan=self.calculate(c,forecast,saved['id'])
        # 30 * 0.1 / 0.9 = 3.333..., existing stock1, packs1 -> buy3, cost300.
        self.assertEqual(plan['total_cost'],'300')
        self.assertEqual(plan['lines'][0]['packs'],3)
        self.assertEqual(plan['demand_basis'],'production_plan')
        self.assertEqual(plan['production_plan_evidence']['portions'],saved['portions'])
        self.assertEqual(plan['status'],'ready')
        self.assertTrue(plan['constraints_valid'])
        with self.factory() as db:
            job=db.get(Job,plan['id'])
            self.assertEqual(job.snapshot['forecast_result']['predictions'][0]['point_forecast'],2)
            self.assertEqual(db.get(Forecast,forecast).result,job.snapshot['forecast_result'])
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)),0)
        rows=list(csv.DictReader(io.StringIO(c.get('/api/v1/plans/'+plan['id']+'/export').text)))
        portions=[r for r in rows if r['row_type']=='production_portion']
        self.assertEqual(portions[0]['portions'],'30')
        self.assertEqual(portions[0]['production_plan_reason'],saved['reason'])
        self.assertEqual(portions[0]['production_plan_name'],saved['name'])

    def test_zero_plan_preserves_explicit_portion_evidence_even_without_purchase(self):
        c=self.client(); forecast=self.compute_forecast(c); saved=self.save(c,forecast,0)
        plan=self.calculate(c,forecast,saved['id'],budget='0')
        self.assertEqual(plan['total_cost'],'0');self.assertEqual(plan['lines'],[])
        self.assertEqual(plan['shortage_count'],0)
        rows=list(csv.DictReader(io.StringIO(c.get('/api/v1/plans/'+plan['id']+'/export').text)))
        self.assertEqual([r['portions'] for r in rows if r['row_type']=='production_portion'],['0'])

    def test_binding_and_quantile_strategy_fail_closed(self):
        c=self.client(); forecast=self.compute_forecast(c); saved=self.save(c,forecast)
        for strategy in ('p50','p90_stress'):
            result=self.enqueue(c,forecast,saved['id'],strategy=strategy)
            self.assertEqual(result.json()['detail']['code'],'PRODUCTION_STRATEGY_INVALID')
        another=self.compute_forecast(c)
        self.assertEqual(self.enqueue(c,another,saved['id']).json()['detail']['code'],'PRODUCTION_PLAN_MISMATCH')
        self.assertEqual(self.enqueue(c,forecast,'not-found').status_code,404)

    def test_human_approval_shortage_ack_and_new_variant_do_not_change_old_export(self):
        c=self.client(); forecast=self.compute_forecast(c); saved=self.save(c,forecast,30)
        plan=self.calculate(c,forecast,saved['id'],budget='0')
        path='/api/v1/plans/'+plan['id']; payload={'expected_version':1,'reason':'Reviewed remaining deficit'}
        failed=c.post(path+'/approve',json=payload,headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(failed.json()['detail']['code'],'SHORTAGE_ACK_REQUIRED')
        result=c.post(path+'/approve',json=dict(payload,acknowledge_shortage=True),headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(result.status_code,200,result.text)
        original=c.get(path+'/export').content
        self.save(c,forecast,1,name='Independent later choice')
        self.correct_sale(10)
        self.assertEqual(c.get(path+'/export').content,original)
        self.assertEqual(c.get(path).json()['status'],'approved')
        self.assertEqual(self.counts()[2],0)
        with self.factory() as db:
            actions=list(db.scalars(select(Audit.action)))
            self.assertEqual(actions.count('production_plan.saved'),2)
            self.assertEqual(actions.count('plan.approved'),1)

    def test_worker_fences_stale_source_and_tampered_manual_snapshot(self):
        c=self.client(); forecast=self.compute_forecast(c); saved=self.save(c,forecast)
        run=self.enqueue(c,forecast,saved['id']).json()['run_id']
        with self.factory() as db:
            job=db.get(Job,run); altered=deepcopy(job.snapshot)
            altered['production_plan_evidence']['portions'][0]['portions']=999
            job.snapshot=altered;db.commit()
        worker.run_once(self.factory,calculator=worker.inline_calculation)
        self.assertEqual(c.get('/api/v1/runs/'+run).json()['status'],'failed')
        run=self.enqueue(c,forecast,saved['id']).json()['run_id']
        self.correct_sale(13)
        worker.run_once(self.factory,calculator=worker.inline_calculation)
        self.assertEqual(c.get('/api/v1/runs/'+run).json()['status'],'failed')
        self.assertEqual(self.counts()[3],0)

    def test_worker_rechecks_manual_evidence_and_source_at_publication(self):
        c=self.client(); forecast=self.compute_forecast(c); saved=self.save(c,forecast)
        run=self.enqueue(c,forecast,saved['id']).json()['run_id']
        def calculate(payload,snapshot,kind):
            result=calculate_snapshot(payload,snapshot,kind)
            self.correct_sale(14)
            return result
        worker.run_once(self.factory,calculator=calculate)
        self.assertEqual(c.get('/api/v1/runs/'+run).json()['status'],'failed')
        self.assertEqual(self.counts()[3],0)

    def test_original_forecast_mode_export_does_not_gain_production_columns(self):
        c=self.client(); forecast=self.compute_forecast(c)
        plan=self.calculate(c,forecast,None)
        original=c.get('/api/v1/plans/'+plan['id']+'/export').content
        self.assertNotIn(b'production_plan',original)
        self.save(c,forecast)
        self.assertEqual(c.get('/api/v1/plans/'+plan['id']+'/export').content,original)
        self.assertNotIn('production_plan_evidence',plan)

    def test_concurrent_retries_create_one_document_receipt_and_audit(self):
        c=self.client();forecast=self.compute_forecast(c);key=uuid.uuid4().hex
        def save(_):
            return c.post('/api/v1/production-plans',json=self.payload(forecast),headers={'Idempotency-Key':key})
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses=list(pool.map(save,range(3)))
        self.assertTrue(all(r.status_code==201 for r in responses),[(r.status_code,r.text) for r in responses])
        self.assertEqual(len({r.json()['id'] for r in responses}),1)
        self.assertEqual(responses[0].json(),responses[1].json())
        self.assertEqual(self.counts(),(1,1,0,0))
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='production_plan.saved')),1)

    def test_real_test_source_context_and_private_authorization_are_preserved(self):
        c=self.client();forecast=self.compute_forecast(c)
        with self.factory() as db:
            db.get(Organization,'A').data_policy='real_only'
            db.add(OrganizationSource(organization_id='A',source_id='generated-test',mapping_version='fixture-v1',
                branch_id='1',authorization_reference='private-fixture-reference',purpose='test_fixture',actor_id='operator'))
            for row in db.scalars(select(Record).where(Record.organization_id=='A')):
                row.data=dict(row.data,data_origin='REAL')
            db.flush()
            context=execution_context(db,'A','1','2025-12-31')
            row=db.get(Forecast,forecast)
            row.result=dict(row.result,data_origin='REAL',execution_context=context,
                input_lineage=capture_lineage(db,'A',[dict(kind='daily_sales',rows=rows_for(db,'A','daily_sales','1'),branch_id='1',date_lte='2025-12-31')]))
            db.commit()
        saved=self.save(c,forecast)
        self.assertEqual(saved['data_origin'],'REAL');self.assertEqual(saved['usage_mode'],'TEST')
        self.assertNotIn('authorization_reference',saved['execution_context']['source'])
        plan=self.calculate(c,forecast,saved['id'])
        self.assertEqual(plan['execution_context']['target_date'],'2026-01-01')
        self.assertNotIn('authorization_reference',plan['production_plan_evidence']['execution_context']['source'])
        with self.factory() as db:
            self.assertEqual(db.get(ProductionPlan,saved['id']).document['execution_context']['source']['authorization_reference'],'private-fixture-reference')
            db.get(OrganizationSource,'A').mapping_version='changed-v2';db.commit()
        self.assertEqual(self.enqueue(c,forecast,saved['id']).json()['detail']['code'],'SOURCE_CONTEXT_CHANGED')

    def test_worker_rejects_incorrect_result_basis_even_when_other_fields_match(self):
        c=self.client();forecast=self.compute_forecast(c);saved=self.save(c,forecast)
        run=self.enqueue(c,forecast,saved['id']).json()['run_id']
        def calculate(payload,snapshot,kind):
            result=calculate_snapshot(payload,snapshot,kind)
            result['production_plan_evidence']['portions'][0]['portions']=31
            return result
        worker.run_once(self.factory,calculator=calculate)
        self.assertEqual(c.get('/api/v1/runs/'+run).json()['status'],'failed')
        self.assertEqual(self.counts()[3],0)


if __name__=='__main__':
    unittest.main()
