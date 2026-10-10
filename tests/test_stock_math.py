"""Physical stock invariants without a business source or fabricated savings."""
from copy import deepcopy
from decimal import Decimal
import unittest

from apps.api.stock import (StockError, apply_document, check_recipe_allocation, fingerprint,
                           opening_state, quantity, recipe_requirements, reconciliation,
                           replay, reverse_entries)


CATALOG = {'flour':{'unit':'kg','yield_factor':'0.8'},'milk':{'unit':'L','yield_factor':'1'}}
BASE = [{'branch_id':'001','ingredient_id':'flour','lot_id':'0001','snapshot_date':'2026-01-01',
         'expiry_date':'2026-01-03','on_hand_qty':'10.000','unit':'kg','data_origin':'SYNTHETIC'}]


def opening(rows=BASE):
    return opening_state(rows,branch_id='001',snapshot_date='2026-01-01',data_origin='SYNTHETIC',ingredients=CATALOG)


def line(amount='1',**overrides):
    return dict(ingredient_id='flour',lot_id='0001',expiry_date='2026-01-03',unit='kg',quantity=amount,**overrides)


def post(state,lines,kind='waste',date='2026-01-01',**kwargs):
    return apply_document(state,lines,kind=kind,business_date=date,ingredients=CATALOG,**kwargs)


class StockMathTests(unittest.TestCase):
    def error(self,code,call):
        with self.assertRaises(StockError) as raised:
            call()
        self.assertEqual(raised.exception.code,code)

    def test_exact_decimal_receipt_waste_and_signed_adjustment_never_change_input(self):
        baseline=opening();before=deepcopy(baseline)
        result,entries=post(baseline,[line('0.1')],'receipt')
        self.assertEqual(result[('flour','0001')]['on_hand_qty'],'10.1')
        result,_=post(result,[line('0.2')],'adjustment')
        result,_=post(result,[line('-0.3')],'adjustment')
        self.assertEqual(result[('flour','0001')]['on_hand_qty'],'10')
        self.assertEqual(entries[0]['quantity_delta'],'0.1');self.assertEqual(baseline,before)

    def test_unknown_balance_is_not_zero_but_explicit_receipt_introduces_lot(self):
        new=dict(line(),lot_id='new')
        for kind in ['waste','adjustment','recipe_usage']:
            self.error('STOCK_BALANCE_UNKNOWN',lambda:post(opening(),[new],kind))
        state,_=post(opening(),[new],'receipt')
        self.assertEqual(state[('flour','new')]['on_hand_qty'],'1')

    def test_invalid_later_line_and_overdraw_leave_every_lot_unchanged(self):
        state=opening();before=deepcopy(state)
        self.error('STOCK_BALANCE_UNKNOWN',lambda:post(state,[line('2'),dict(line('1'),lot_id='missing')]))
        self.error('STOCK_INSUFFICIENT',lambda:post(state,[line('10.000000001')]))
        self.assertEqual(state,before)

    def test_quantity_rejects_nonfinite_float_negative_outflow_overprecision_and_extremes(self):
        for value in [1.0,True,'NaN','-Infinity','1E1000000','-1000000000001','0.0000000001']:
            with self.subTest(value=value),self.assertRaises(StockError):
                quantity(value)
        for value in ['0','-1']:
            self.error('STOCK_QUANTITY_INVALID',lambda:post(opening(),[line(value)]))
        self.assertEqual(quantity('1.0000000000'),Decimal(1))

    def test_lot_metadata_units_and_duplicate_lines_cannot_be_silently_changed(self):
        self.error('STOCK_UNIT_MISMATCH',lambda:post(opening(),[dict(line(),unit='L')]))
        self.error('STOCK_LOT_METADATA_CHANGED',lambda:post(opening(),[dict(line(),expiry_date='2026-01-04')]))
        self.error('STOCK_DUPLICATE_LOT',lambda:post(opening(),[line(),line()]))
        self.error('STOCK_DUPLICATE_LOT',lambda:opening(BASE+BASE))

    def test_expiry_boundary_allows_same_day_use_and_expired_waste_only(self):
        state,_=post(opening(),[line()],'recipe_usage','2026-01-03')
        self.assertEqual(state[('flour','0001')]['on_hand_qty'],'9')
        for kind in ['recipe_usage','receipt']:
            self.error('STOCK_LOT_EXPIRED',lambda:post(opening(),[line()],kind,'2026-01-04'))
        state,_=post(opening(),[line()],'waste','2026-01-04')
        self.assertEqual(state[('flour','0001')]['on_hand_qty'],'9')

    def test_linked_inverse_preserves_original_entries_and_refuses_negative_stock(self):
        state,entries=post(opening(),[line('2')],'receipt')
        original=deepcopy(entries)
        inverse=reverse_entries(entries)
        result,_=post(state,inverse,'reversal',reversal=True)
        self.assertEqual(result,opening());self.assertEqual(entries,original)
        consumed,_=post(state,[line('11')])
        self.error('STOCK_INSUFFICIENT',lambda:post(consumed,inverse,'reversal',reversal=True))

    def test_opening_boundary_excludes_target_day_events_and_replays_new_receipt_lot(self):
        state=opening();movements=[]
        for sequence,(kind,lines,date) in enumerate([
                ('receipt',[dict(line('3'),lot_id='new')],'2026-01-01'),
                ('waste',[line('2')],'2026-01-02')],1):
            state,entries=post(state,lines,kind,date)
            movements.append(dict(sequence=sequence,kind=kind,business_date=date,entries=entries))
        on_day,selected=replay(opening(),movements,baseline_date='2026-01-01',target_date='2026-01-02',ingredients=CATALOG)
        self.assertEqual(on_day[('flour','0001')]['on_hand_qty'],'10')
        self.assertEqual(on_day[('flour','new')]['on_hand_qty'],'3');self.assertEqual(len(selected),1)
        initial,_=replay(opening(),movements,baseline_date='2026-01-01',target_date='2026-01-01',ingredients=CATALOG)
        self.assertEqual(initial,opening())

    def test_history_rejects_backdated_and_missing_sequence_without_mutating_baseline(self):
        _,entries=post(opening(),[line()])
        for sequence,date in [(2,'2026-01-01'),(1,'2025-12-31')]:
            self.error('STOCK_HISTORY_INVALID',lambda:replay(opening(),[
                dict(sequence=sequence,kind='waste',business_date=date,entries=entries)],
                baseline_date='2026-01-01',target_date='2026-01-02',ingredients=CATALOG))

    def test_recipe_yield_applies_once_and_evidence_survives_source_change(self):
        recipes=[dict(meal_id='burger',ingredient_id='flour',recipe_version='v1',net_qty_per_portion='0.08')]
        requirements,evidence=recipe_requirements(recipes,CATALOG,{'burger':10},{'burger':'v1'})
        self.assertEqual(requirements,[dict(ingredient_id='flour',unit='kg',gross_required='1')])
        _,entries=post(opening(),[line('1')],'recipe_usage')
        check_recipe_allocation(entries,requirements)
        self.error('STOCK_RECIPE_ALLOCATION',lambda:check_recipe_allocation([{**entries[0],'quantity_delta':'-0.8'}],requirements))
        recipes[0]['net_qty_per_portion']='10'
        self.assertEqual(evidence['rows'][0]['net_qty_per_portion'],'0.08')

    def test_recipe_rounds_once_after_aggregation_not_once_per_portion_or_recipe(self):
        catalog={'flour':{'unit':'kg','yield_factor':'0.3'}}
        recipes=[dict(meal_id=meal,ingredient_id='flour',recipe_version='v1',net_qty_per_portion='0.1') for meal in ['a','b','c']]
        required,_=recipe_requirements(recipes,catalog,{meal:1 for meal in ['a','b','c']},{meal:'v1' for meal in ['a','b','c']})
        self.assertEqual(required[0]['gross_required'],'1')
        required,_=recipe_requirements(recipes,catalog,{'a':1},{'a':'v1'})
        self.assertEqual(required[0]['gross_required'],'0.333333334')

    def test_dated_recipes_use_each_captured_yield_and_enforce_captured_unit(self):
        recipes=[dict(meal_id='a',ingredient_id='flour',recipe_version='v1',net_qty_per_portion='0.08',
                      captured_yield_factor='0.8',unit='kg'),
                 dict(meal_id='b',ingredient_id='flour',recipe_version='v2',net_qty_per_portion='0.08',
                      captured_yield_factor='0.4',unit='kg')]
        requirements,evidence=recipe_requirements(recipes,{'flour':{'unit':'kg','yield_factor':'1'}},
                                                {'a':10,'b':10},{'a':'v1','b':'v2'})
        self.assertEqual(requirements[0]['gross_required'],'3')
        self.assertEqual([row['yield_factor'] for row in evidence['rows']],['0.8','0.4'])
        recipes[1]['unit']='L'
        self.error('STOCK_UNIT_MISMATCH',lambda:recipe_requirements(recipes,CATALOG,
                   {'a':10,'b':10},{'a':'v1','b':'v2'}))

    def test_recipe_selection_ambiguity_and_invalid_yield_are_rejected(self):
        recipe=dict(meal_id='meal',ingredient_id='flour',recipe_version='v1',net_qty_per_portion='1')
        self.error('STOCK_RECIPE_AMBIGUOUS',lambda:recipe_requirements([recipe,recipe],CATALOG,{'meal':1},{'meal':'v1'}))
        self.error('STOCK_RECIPE_REQUIRED',lambda:recipe_requirements([recipe],CATALOG,{'meal':1},{'meal':'v2'}))
        for yield_factor in ['0','-0.1','1.01']:
            with self.subTest(yield_factor=yield_factor),self.assertRaises(StockError):
                recipe_requirements([recipe],{'flour':{'unit':'kg','yield_factor':yield_factor}},{'meal':1},{'meal':'v1'})

    def test_canonical_imported_version_labels_are_preserved_in_consumption(self):
        from apps.api.importing import parse_csv
        for version in ['v1.0','2026-Q1 v2','Рецепт 01', 'v'*200]:
            with self.subTest(version=version):
                rows,errors=parse_csv('recipes','meal_id,ingredient_id,net_qty_per_portion,recipe_version,data_origin\n'
                                      f'meal,flour,0.08,{version},SYNTHETIC\n')
                self.assertEqual(errors,[])
                required,evidence=recipe_requirements(rows,CATALOG,{'meal':10},{'meal':version})
                self.assertEqual(required[0]['gross_required'],'1')
                self.assertEqual(evidence['rows'][0]['recipe_version'],version)

    def test_reconciliation_distinguishes_unknown_zero_difference_and_metadata(self):
        baseline=opening();counted=deepcopy(baseline);counted[('flour','0001')]['on_hand_qty']='0'
        report=reconciliation(baseline,counted,baseline_date='2026-01-01',target_date='2026-01-02')
        self.assertEqual((report['status'],report['lines'][0]['difference']),('unresolved','-10'))
        missing=reconciliation(baseline,{},baseline_date='2026-01-01',target_date='2026-01-02')['lines'][0]
        self.assertIsNone(missing['difference']);self.assertEqual(missing['status'],'missing_count')
        counted[('flour','0001')]['unit']='L'
        changed=reconciliation(baseline,counted,baseline_date='2026-01-01',target_date='2026-01-02')['lines'][0]
        self.assertIsNone(changed['difference']);self.assertEqual(changed['status'],'lot_metadata_changed')
        matched=reconciliation(baseline,baseline,baseline_date='2026-01-01',target_date='2026-01-02')
        self.assertEqual(matched['status'],'matched')

    def test_baseline_scope_and_provenance_are_not_inferred(self):
        for field,value in [('branch_id','002'),('snapshot_date','2026-01-02'),('data_origin','REAL')]:
            self.error('STOCK_BASELINE_SCOPE',lambda:opening([{**BASE[0],field:value}]))
        self.error('STOCK_BASELINE_REQUIRED',lambda:opening([]))
        self.assertEqual(fingerprint(BASE),fingerprint(deepcopy(BASE)))


if __name__=='__main__':
    unittest.main()
