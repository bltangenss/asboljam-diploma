"""Count-anchor HTTP transactions and immutable plan evidence on artificial data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import io
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.db import Audit, Plan, Record, StockCountAnchor, StockLedger, StockMovement, User
from apps.api.importing import insert_rows, rows_for
from apps.api.stock_dependencies import capture_dependencies, dependency_freshness
import test_stock_api as fixture


class StockAnchorApiTests(unittest.TestCase):
    # Reuse the isolated fixture without inheriting/rerunning its existing suite.
    setUp = fixture.StockApiTests.setUp
    client = fixture.StockApiTests.client
    open = fixture.StockApiTests.open
    post_preview = fixture.StockApiTests.post_preview
    movement = fixture.StockApiTests.movement
    forecast = fixture.StockApiTests.forecast
    queue_plan = fixture.StockApiTests.queue_plan
    compute_plan = fixture.StockApiTests.compute_plan
    approve = fixture.StockApiTests.approve

    def options(self, **changes):
        return dict(branch_id='001', count_date='2026-01-02', expected_version=1,
                    reason='Independent complete count reviewed by manager') | changes

    def count(self, count_date='2026-01-02', amount='12'):
        with self.factory.begin() as db:
            source = rows_for(db, 'A', 'inventory_lots', '001')[0]
            insert_rows(db, 'A', 'inventory_lots', [source | dict(snapshot_date=count_date, on_hand_qty=amount)])

    def correct(self, count_date='2026-01-01', amount='11'):
        with self.factory.begin() as db:
            record = next(row for row in db.scalars(select(Record).where(
                Record.organization_id == 'A', Record.kind == 'inventory_lots'))
                if row.data['snapshot_date'] == count_date)
            record.data = record.data | {'on_hand_qty': amount}

    def preview(self, **changes):
        body = self.options(**changes)
        response = self.client().post('/api/v1/stock/count-anchors/preview', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return body | dict(expected_fingerprint=response.json()['preview_fingerprint'], acknowledge_differences=True)

    def anchor(self, key='anchor-1', **changes):
        response = self.client().post('/api/v1/stock/count-anchors', json=self.preview(**changes),
                                      headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def counts(self):
        with self.factory() as db:
            return dict(anchors=db.scalar(select(func.count()).select_from(StockCountAnchor)),
                movements=db.scalar(select(func.count()).select_from(StockMovement)),
                audit=db.scalar(select(func.count()).select_from(Audit).where(Audit.action.like('stock.%'))),
                version=db.scalar(select(StockLedger.version)))

    def test_scope_role_csrf_native_and_strict_confirmation(self):
        self.open(); self.count(); body=self.options(); c=self.client()
        for role in ('Awarehouse', 'Aanalyst'):
            self.assertEqual(self.client(role).post('/api/v1/stock/count-anchors/preview', json=body).status_code, 403)
        self.assertEqual(c.post('/api/v1/stock/count-anchors/preview', json=body,
                               headers={'X-CSRF-Token':'wrong'}).status_code, 403)
        self.assertEqual(c.post('/api/v1/stock/count-anchors/preview', json=body | {'branch_id':'foreign'}).status_code, 403)
        native=c.post('/api/v1/auth/token',json=dict(email='Amanager@fixture.invalid',password=fixture.PASSWORD)).json()
        self.assertEqual(c.post('/api/v1/stock/count-anchors/preview',json=body,
                               headers={'Authorization':'Bearer '+native['access_token']}).status_code,403)
        request=self.preview(); before=self.counts()
        for bad in (False, 1, 'true', None):
            response=c.post('/api/v1/stock/count-anchors',json=request | {'acknowledge_differences':bad},
                            headers={'Idempotency-Key':'invalid-ack'})
            self.assertEqual(response.status_code,422,response.text)
        without_ack={key:value for key,value in request.items() if key!='acknowledge_differences'}
        self.assertEqual(c.post('/api/v1/stock/count-anchors',json=without_ack,
                               headers={'Idempotency-Key':'missing-ack'}).status_code,422)
        self.assertEqual(self.counts(),before)
        self.anchor()
        self.assertEqual(self.client('Aanalyst').get('/api/v1/stock/count-anchors?branch_id=001').json()['total'],1)
        self.assertEqual(self.client('Bmanager').get('/api/v1/stock/count-anchors?branch_id=001').json()['total'],0)

    def test_corrected_initial_count_recovers_procurement_and_keeps_approved_export(self):
        self.open(); self.forecast(); old_plan=self.compute_plan(); c=self.client()
        approved=self.approve(old_plan,'approved-before-correction')
        self.assertEqual(approved.status_code,200,approved.text)
        old_export=c.get('/api/v1/plans/'+old_plan+'/export').content
        with self.factory() as db:
            old_result=deepcopy(db.get(Plan,old_plan).result)
            baseline=deepcopy(db.scalar(select(StockLedger)).baseline_rows)
        self.correct(amount='9')
        blocked=c.post('/api/v1/procurement',json=dict(branch_id='001',forecast_id='forecast',budget='0'))
        self.assertEqual(blocked.status_code,409,blocked.text)
        preview=c.post('/api/v1/stock/count-anchors/preview',json=self.options(count_date='2026-01-01')).json()
        self.assertEqual(preview['differences'][0]['difference'],'-1')
        anchor=self.anchor(count_date='2026-01-01')
        new_plan=self.compute_plan()
        approved_new=self.approve(new_plan,'after-anchor')
        self.assertEqual(approved_new.status_code,200,approved_new.text)
        evidence=approved_new.json()['stock_evidence']
        self.assertEqual(evidence['count_anchor']['id'],anchor['anchor_id'])
        rows=list(csv.DictReader(io.StringIO(c.get('/api/v1/plans/'+new_plan+'/export').content.decode('utf-8-sig'))))
        self.assertTrue(rows)
        self.assertTrue(all(row['stock_count_anchor_id']==anchor['anchor_id'] for row in rows))
        self.assertTrue(all(row['stock_count_anchor_date']=='2026-01-01' for row in rows))
        self.assertEqual(c.get('/api/v1/plans/'+old_plan+'/export').content,old_export)
        self.assertEqual(self.approve(old_plan,'approved-before-correction').json(),approved.json())
        with self.factory() as db:
            self.assertEqual(db.get(Plan,old_plan).result,old_result)
            self.assertEqual(db.scalar(select(StockLedger)).baseline_rows,baseline)
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)),0)
        position=c.get('/api/v1/stock/ledger?branch_id=001&opening_date=2026-01-01').json()
        self.assertEqual(position['opening']['rows'][0]['on_hand_qty'],'9')
        self.assertEqual((position['baseline_freshness'],position['effective_freshness']),('changed','unchanged'))

    def test_future_anchor_ignores_old_target_and_only_relevant_anchor_invalidates_dependency(self):
        self.open(); self.forecast(); plan=self.compute_plan(); c=self.client()
        with self.factory() as db:
            before=capture_dependencies(db,'A','001','2026-01-01',['01'])
            future=capture_dependencies(db,'A','001','2026-01-02',['01'])
        self.count(amount='10'); anchor=self.anchor()
        with self.factory() as db:
            self.assertEqual(dependency_freshness(db,'A',before),'unchanged')
            self.assertEqual(dependency_freshness(db,'A',future),'changed')
            selected=capture_dependencies(db,'A','001','2026-01-02',['01'])
            self.assertEqual(selected['stock']['count_anchor']['id'],anchor['anchor_id'])
        self.assertEqual(c.get('/api/v1/plans/'+plan).json()['input_freshness'],'unchanged')
        self.assertEqual(self.approve(plan,'old-target').status_code,200)
        self.count('2026-01-03',amount='10'); self.anchor(key='later-anchor',count_date='2026-01-03',expected_version=2)
        with self.factory() as db:self.assertEqual(dependency_freshness(db,'A',selected),'unchanged')
        # Corrections to a superseded baseline do not taint the selected new count.
        self.correct(amount='9')
        with self.factory() as db:self.assertEqual(dependency_freshness(db,'A',selected),'unchanged')
        self.correct(count_date='2026-01-02',amount='9')
        with self.factory() as db:self.assertEqual(dependency_freshness(db,'A',selected),'changed')

    def test_changed_preview_atomic_rejection_and_exact_replay_after_later_count_correction(self):
        self.open(); self.count(); c=self.client(); request=self.preview(); before=self.counts()
        self.correct('2026-01-02','11')
        stale=c.post('/api/v1/stock/count-anchors',json=request,headers={'Idempotency-Key':'count-preview'})
        self.assertEqual(stale.status_code,409,stale.text)
        self.assertEqual(stale.json()['detail']['code'],'STOCK_PREVIEW_STALE')
        self.assertEqual(self.counts(),before)
        request=self.preview()
        first=c.post('/api/v1/stock/count-anchors',json=request,headers={'Idempotency-Key':'count-preview'})
        self.assertEqual(first.status_code,200,first.text)
        self.correct('2026-01-02','10')
        replay=c.post('/api/v1/stock/count-anchors',json=request,headers={'Idempotency-Key':'count-preview'})
        self.assertEqual(replay.json(),first.json())
        conflict=c.post('/api/v1/stock/count-anchors',json=request | {'reason':'Changed reason'},headers={'Idempotency-Key':'count-preview'})
        self.assertEqual(conflict.status_code,409,conflict.text)
        self.assertEqual(self.counts()['anchors'],1)
        # Receipt replay still checks current access after the original commit.
        with self.factory.begin() as db:db.get(User,'Amanager').role='analyst'
        self.assertEqual(c.post('/api/v1/stock/count-anchors',json=request,
                               headers={'Idempotency-Key':'count-preview'}).status_code,403)

    def test_concurrent_anchor_and_movement_have_one_winner_and_no_partial_audit(self):
        self.open(); self.count(); c=self.client()
        anchor_request=self.preview()
        movement=self.movement()
        movement_preview=c.post('/api/v1/stock/movements/preview',json=movement).json()
        requests=[('/stock/count-anchors',anchor_request,'anchor-race'),
                  ('/stock/movements',movement | {'expected_fingerprint':movement_preview['preview_fingerprint']},'move-race')]
        def execute(item):
            route,body,key=item
            with TestClient(self.app) as parallel:
                parallel.cookies.update(c.cookies);parallel.headers.update(c.headers)
                return parallel.post('/api/v1'+route,json=body,headers={'Idempotency-Key':key})
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(execute,requests))
        self.assertEqual(sorted(response.status_code for response in responses),[200,409],
                         [response.text for response in responses])
        counts=self.counts()
        self.assertEqual(counts['anchors']+counts['movements'],1)
        self.assertEqual((counts['version'],counts['audit']),(2,2))
        winner=requests[next(index for index,response in enumerate(responses) if response.status_code==200)]
        self.assertEqual(execute(winner).status_code,200)
        self.assertEqual(self.counts(),counts)

    def test_anchor_separates_sequence_from_version_and_rejects_old_period_reversal(self):
        self.open(); moved=self.post_preview('/stock/movements',self.movement(),'first-movement')
        self.count(amount='11'); self.correct(amount='9'); self.anchor(expected_version=2)
        c=self.client()
        old=c.get('/api/v1/stock/ledger?branch_id=001&opening_date=2026-01-01').json()
        new=c.get('/api/v1/stock/ledger?branch_id=001&opening_date=2026-01-02').json()
        self.assertEqual(old['opening']['rows'][0]['on_hand_qty'],'10')
        self.assertEqual(new['opening']['rows'][0]['on_hand_qty'],'11')
        reverse=self.movement(expected_version=3,business_date='2026-01-02',kind='reversal',lines=None,
                              reverses_id=moved['movement_id'],source_reference='reverse-old')
        refused=c.post('/api/v1/stock/movements/preview',json=reverse)
        self.assertEqual(refused.status_code,409,refused.text)
        self.assertEqual(refused.json()['detail']['code'],'STOCK_REVERSAL_BEFORE_ANCHOR')
        posted=self.post_preview('/stock/movements',self.movement(expected_version=3,
            business_date='2026-01-02',source_reference='after-count'),'after-anchor-movement')
        self.assertEqual((posted['version'],posted['sequence']),(4,2))
        history=c.get('/api/v1/stock/movements?branch_id=001').json()
        self.assertEqual(history['total'],2)
        self.assertEqual([row['sequence'] for row in history['items']],[2,1])
        after=c.get('/api/v1/stock/ledger?branch_id=001&opening_date=2026-01-03').json()
        self.assertEqual(after['opening']['rows'][0]['on_hand_qty'],'13')


if __name__=='__main__':
    unittest.main()
