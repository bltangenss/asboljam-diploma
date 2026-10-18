"""Generate the Kazakhstan SYNTHETIC demo dataset (data/kz).

Scenario: a fictional catering business with three branches in Qyzylorda.
All sales, stock, recipes, menu and purchase prices, branch and supplier names
are SYNTHETIC. Public facts only shape the scenario (sources: data/kz/README.md):
official RK days off and transfers for 2024-2025, Ramadan dates, an approximate
Qyzylorda climate and 2025 national average price levels.

The output is reproducible on any platform: sampling uses only
random.Random.random(), whose sequence Python keeps stable across versions, and
intermediate values are rounded before they influence sampling or output.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 2025
START, END, SNAPSHOT = date(2024, 1, 1), date(2025, 12, 31), date(2026, 1, 1)
ORIGIN = 'SYNTHETIC'

LAW = 'Закон РК «О праздниках в Республике Казахстан»'
TRANSFER = LAW + ', ст. 5: выходной, совпавший с праздником, переносится на следующий рабочий день'
CALENDAR_2024 = 'Производственный календарь РК на 2024 год: день отдыха перенесён с субботы 04.05.2024'
ORDER_2025 = 'Приказ Министра труда и социальной защиты населения РК № 436 от 21.11.2024'
NEW_YEAR = ('Жаңа жыл', 'Новый год')
CHRISTMAS = ('Православиелік Рождество', 'Православное Рождество')
WOMEN = ('Халықаралық әйелдер күні', 'Международный женский день')
NAURYZ = ('Наурыз мейрамы', 'Наурыз мейрамы')
UNITY = ('Қазақстан халқының бірлігі мерекесі', 'Праздник единства народа Казахстана')
DEFENDER = ('Отан қорғаушы күні', 'День защитника Отечества')
VICTORY = ('Жеңіс күні', 'День Победы')
KURBAN = ('Құрбан айт (бірінші күні)', 'Курбан айт (первый день)')
CAPITAL = ('Астана күні', 'День Столицы')
CONSTITUTION = ('Конституция күні', 'День Конституции')
REPUBLIC = ('Республика күні', 'День Республики')
INDEPENDENCE = ('Тәуелсіздік күні', 'День Независимости')


def _moved(names):
    return ('Ауыстырылған демалыс: ' + names[0], 'Перенесённый выходной: ' + names[1])


# Official RK non-working days 2024-2025 and weekend days that became working days.
DAYS_OFF = (
    ('2024-01-01', 'holiday', NEW_YEAR, LAW), ('2024-01-02', 'holiday', NEW_YEAR, LAW),
    ('2024-01-07', 'holiday', CHRISTMAS, LAW), ('2024-03-08', 'holiday', WOMEN, LAW),
    ('2024-03-21', 'holiday', NAURYZ, LAW), ('2024-03-22', 'holiday', NAURYZ, LAW),
    ('2024-03-23', 'holiday', NAURYZ, LAW), ('2024-03-25', 'transferred_day_off', _moved(NAURYZ), TRANSFER),
    ('2024-05-01', 'holiday', UNITY, LAW),
    ('2024-05-04', 'working_day', ('Жұмыс күні (демалыс 8 мамырға ауыстырылды)',
                                   'Рабочий день (выходной перенесён на 8 мая)'), CALENDAR_2024),
    ('2024-05-07', 'holiday', DEFENDER, LAW),
    ('2024-05-08', 'transferred_day_off', ('Ауыстырылған демалыс (4 мамырдан)',
                                           'Перенесённый выходной (с 4 мая)'), CALENDAR_2024),
    ('2024-05-09', 'holiday', VICTORY, LAW), ('2024-06-16', 'holiday', KURBAN, LAW),
    ('2024-07-06', 'holiday', CAPITAL, LAW), ('2024-07-08', 'transferred_day_off', _moved(CAPITAL), TRANSFER),
    ('2024-08-30', 'holiday', CONSTITUTION, LAW), ('2024-10-25', 'holiday', REPUBLIC, LAW),
    ('2024-12-16', 'holiday', INDEPENDENCE, LAW),
    ('2025-01-01', 'holiday', NEW_YEAR, LAW), ('2025-01-02', 'holiday', NEW_YEAR, LAW),
    ('2025-01-03', 'transferred_day_off', ('Ауыстырылған демалыс (5 қаңтардан)',
                                           'Перенесённый выходной (с 5 января)'), ORDER_2025),
    ('2025-01-05', 'working_day', ('Жұмыс күні (демалыс 3 қаңтарға ауыстырылды)',
                                   'Рабочий день (выходной перенесён на 3 января)'), ORDER_2025),
    ('2025-01-07', 'holiday', CHRISTMAS, LAW), ('2025-03-08', 'holiday', WOMEN, LAW),
    ('2025-03-10', 'transferred_day_off', _moved(WOMEN), TRANSFER),
    ('2025-03-21', 'holiday', NAURYZ, LAW), ('2025-03-22', 'holiday', NAURYZ, LAW),
    ('2025-03-23', 'holiday', NAURYZ, LAW), ('2025-03-24', 'transferred_day_off', _moved(NAURYZ), TRANSFER),
    ('2025-03-25', 'transferred_day_off', _moved(NAURYZ), TRANSFER),
    ('2025-05-01', 'holiday', UNITY, LAW), ('2025-05-07', 'holiday', DEFENDER, LAW),
    ('2025-05-09', 'holiday', VICTORY, LAW), ('2025-06-06', 'holiday', KURBAN, LAW),
    ('2025-07-06', 'holiday', CAPITAL, LAW), ('2025-07-07', 'transferred_day_off', _moved(CAPITAL), TRANSFER),
    ('2025-08-30', 'holiday', CONSTITUTION, LAW),
    ('2025-09-01', 'transferred_day_off', _moved(CONSTITUTION), TRANSFER),
    ('2025-10-25', 'holiday', REPUBLIC, LAW), ('2025-10-27', 'transferred_day_off', _moved(REPUBLIC), TRANSFER),
    ('2025-12-16', 'holiday', INDEPENDENCE, LAW),
)
WORKING_WEEKENDS = {date.fromisoformat(text) for text, kind, _, _ in DAYS_OFF if kind == 'working_day'}
# Ramadan by the Spiritual Administration of Muslims of Kazakhstan (DUMK) calendar.
RAMADAN = ((date(2024, 3, 11), date(2024, 4, 9)), (date(2025, 3, 1), date(2025, 3, 29)))
# Oraza ait by the DUMK calendar; Kurban ait is an official day off listed in DAYS_OFF.
ORAZA_AIT = (date(2024, 4, 10), date(2025, 3, 30))
# School holidays by the Ministry of Education orders for 2023/24, 2024/25 and 2025/26
# (autumn, winter, spring, summer); the extra first-grade week is not a whole-school holiday.
SCHOOL_HOLIDAYS = (
    (date(2024, 1, 1), date(2024, 1, 7)), (date(2024, 3, 21), date(2024, 3, 31)),
    (date(2024, 5, 26), date(2024, 8, 31)), (date(2024, 10, 28), date(2024, 11, 3)),
    (date(2024, 12, 30), date(2025, 1, 8)), (date(2025, 3, 21), date(2025, 3, 31)),
    (date(2025, 5, 26), date(2025, 9, 1)), (date(2025, 10, 27), date(2025, 11, 2)),
    (date(2025, 12, 29), date(2026, 1, 7)),
)
# Demo convention for salary and advance days; replace with the enterprise's own schedule.
PAYDAYS = (5, 6, 7, 20, 21, 22)
# Qyzylorda: latitude, longitude (east positive); local time UTC+5 throughout 2024-2026.
QYZYLORDA = (44.8488, 65.4823)
UTC_OFFSET_MINUTES = 300
HEAT_ALERT_C = 33
# Days off after the sales history that the forecast day needs (law: 1-2 January, New Year).
FORECAST_DAYS_OFF = {date(2026, 1, 1): 'holiday', date(2026, 1, 2): 'holiday'}
# Approximate monthly mean air temperature in Qyzylorda, degrees C, January..December.
CLIMATE = (-6.5, -4.5, 3.5, 13.0, 20.0, 25.5, 27.5, 25.5, 18.5, 10.0, 2.0, -4.0)

# Branches: station canteen, business-centre cafe, family restaurant.
BRANCHES = (
    dict(id='1', name='Вокзал маңындағы асхана', scale=1.0, weekday=(0.95, 0.93, 0.95, 0.98, 1.08, 1.06, 1.05),
         ramadan=0.96, summer=1.08, heat=1.0, cold=1.0, closed=('2024-08-13', '2025-08-12')),
    dict(id='2', name='Бизнес-орталықтағы кафе', scale=0.78, weekday=(1.06, 1.08, 1.08, 1.07, 1.02, 0.52, 0.38),
         ramadan=0.88, summer=0.9, heat=0.93, cold=0.94,
         closed=('2024-02-10', '2024-05-11', '2024-08-10', '2024-11-09',
                 '2025-02-08', '2025-05-10', '2025-08-09', '2025-11-08')),
    dict(id='3', name='Отбасылық мейрамхана', scale=1.12, weekday=(0.80, 0.78, 0.82, 0.88, 1.10, 1.40, 1.32),
         ramadan=1.06, summer=1.0, heat=0.95, cold=0.94, closed=('2024-04-15', '2024-04-16')),
)
# Demand factor per day type and branch (branches 1, 2, 3). New Year's Eve is a working day.
SPECIAL = {
    'day_off': (1.12, 0.50, 1.30), 'new_year': (0.85, 0.35, 0.90), 'new_year_2': (1.05, 0.45, 1.25),
    'nauryz': (1.15, 0.50, 1.50), 'kurban': (1.10, 0.55, 1.35), 'women': (1.05, 0.60, 1.60),
    'new_year_eve': (1.00, 0.75, 1.45),
}
# Dish-specific festive demand, by meal id and day type.
FESTIVE = {
    '1': {'day_off': 1.25, 'new_year_2': 1.3, 'nauryz': 1.6, 'kurban': 1.5, 'women': 1.2},
    '9': {'women': 1.3, 'new_year_2': 1.2, 'new_year_eve': 1.3},
    '10': {'nauryz': 1.5, 'kurban': 1.4},
}
# Relative popularity of a dish in a branch.
AFFINITY = {
    '1': {'11': 1.4, '10': 1.1, '12': 1.2, '1': 0.8, '7': 0.9},
    '2': {'9': 1.3, '6': 1.2, '3': 1.15, '2': 1.1, '1': 0.6, '10': 0.7, '12': 0.8, '7': 0.8},
    '3': {'1': 1.5, '7': 1.4, '4': 1.2, '9': 1.1, '11': 0.5, '12': 0.4, '6': 0.8},
}

# id, name, unit, reference cost KZT, shelf life days, yield factor, storage capacity, stock class
INGREDIENTS = (
    ('1', 'Сиыр еті / Говядина', 'kg', 3400, 4, '0.75', 80, 'meat'),
    ('2', 'Қой еті / Баранина', 'kg', 3600, 4, '0.75', 80, 'meat'),
    ('3', 'Жылқы еті / Конина', 'kg', 3400, 4, '0.78', 50, 'meat'),
    ('4', 'Тауық еті / Курица', 'kg', 1700, 3, '0.8', 80, 'meat'),
    ('5', 'Күріш / Рис', 'kg', 430, 365, '1.0', 200, 'dry'),
    ('6', 'Бидай ұны / Мука пшеничная', 'kg', 240, 180, '1.0', 250, 'dry'),
    ('7', 'Картоп / Картофель', 'kg', 210, 60, '0.8', 250, 'root'),
    ('8', 'Пияз / Лук репчатый', 'kg', 160, 60, '0.85', 150, 'root'),
    ('9', 'Сәбіз / Морковь', 'kg', 190, 30, '0.82', 120, 'root'),
    ('10', 'Қызанақ / Помидоры', 'kg', 1200, 7, '0.92', 50, 'fresh'),
    ('11', 'Қияр / Огурцы', 'kg', 950, 7, '0.95', 40, 'fresh'),
    ('12', 'Күнбағыс майы / Подсолнечное масло', 'L', 880, 365, '1.0', 80, 'dry'),
    ('13', 'Сүт / Молоко', 'L', 520, 5, '1.0', 60, 'dairy'),
    ('14', 'Қант / Сахар', 'kg', 430, 365, '1.0', 60, 'dry'),
)
# id, name, menu price KZT in January 2024, base daily demand, temperature profile, recipe (ingredient, net per portion)
MEALS = (
    ('1', 'Бешбармақ', 2600, 22, 'festive', (('3', '0.16'), ('6', '0.08'), ('8', '0.03'))),
    ('2', 'Палау / Плов', 1800, 38, None, (('5', '0.09'), ('2', '0.08'), ('9', '0.07'), ('8', '0.03'), ('12', '0.02'))),
    ('3', 'Лағман', 1900, 30, None, (('6', '0.1'), ('1', '0.07'), ('10', '0.04'), ('8', '0.03'), ('12', '0.015'))),
    ('4', 'Мәнті / Манты', 1900, 28, None, (('6', '0.09'), ('2', '0.09'), ('8', '0.06'), ('12', '0.005'))),
    ('5', 'Сорпа', 1600, 20, 'soup', (('2', '0.09'), ('7', '0.08'), ('8', '0.02'), ('9', '0.02'))),
    ('6', 'Тауық кеспесі / Куриная лапша', 1200, 26, 'soup',
     (('4', '0.08'), ('6', '0.04'), ('7', '0.05'), ('9', '0.02'), ('8', '0.02'))),
    ('7', 'Қуырдақ', 2300, 16, None, (('1', '0.14'), ('7', '0.12'), ('8', '0.04'), ('12', '0.02'))),
    ('8', 'Тауық еті картоппен / Курица с картофелем', 1700, 24, None,
     (('4', '0.14'), ('7', '0.16'), ('8', '0.02'), ('12', '0.012'))),
    ('9', 'Көкөніс салаты / Овощной салат', 900, 22, 'salad',
     (('10', '0.1'), ('11', '0.08'), ('8', '0.02'), ('12', '0.008'))),
    ('10', 'Бауырсақ', 400, 40, None, (('6', '0.08'), ('13', '0.04'), ('12', '0.03'), ('14', '0.004'))),
    ('11', 'Самса', 450, 45, None, (('6', '0.07'), ('1', '0.05'), ('8', '0.03'), ('12', '0.005'))),
    ('12', 'Сүтті күріш ботқасы / Рисовая молочная каша', 700, 18, 'porridge',
     (('5', '0.05'), ('13', '0.2'), ('14', '0.01'))),
)
RECIPE_VERSION = 'KZ_2024_1'
DISH_OF_THE_DAY = ('2', '3', '4', '6', '7', '8')
PRICE_STEPS = ((date(2024, 9, 1), 1.06), (date(2025, 4, 1), 1.08), (date(2025, 10, 1), 1.05))

# id, name, default lead time days
SUPPLIERS = (
    ('1', 'Ет жеткізушісі', 0), ('2', 'Көкөніс базасы', 0), ('3', 'Көтерме азық-түлік қоймасы', 0),
    ('4', 'Шағын азық-түлік дүкені', 0), ('5', 'Облыстық көтерме база (келесі күні)', 1),
)
# supplier, ingredient, pack quantity, price factor to the reference cost, min packs, max packs, lead time
OFFERS = (
    *(('1', ingredient, 1, 1.03, 2, 60, 0) for ingredient in ('1', '2', '3', '4')),
    ('2', '7', 10, 0.93, 1, 20, 0), ('2', '8', 10, 0.93, 1, 20, 0), ('2', '9', 10, 0.93, 1, 20, 0),
    ('2', '10', 5, 0.95, 1, 8, 0), ('2', '11', 5, 0.95, 1, 6, 0),
    ('3', '5', 25, 0.92, 1, 6, 0), ('3', '6', 25, 0.9, 1, 8, 0), ('3', '12', 5, 0.94, 1, 12, 0),
    ('3', '13', 10, 0.95, 1, 5, 0), ('3', '14', 10, 0.93, 1, 4, 0),
    *(('4', ingredient[0], 1, 1.15, 1, 25, 0) for ingredient in INGREDIENTS),
    *(('5', ingredient, 10, 0.9, 1, 10, 1) for ingredient in ('1', '2', '3', '4')),
    ('5', '5', 50, 0.86, 1, 4, 1), ('5', '6', 50, 0.84, 1, 4, 1), ('5', '12', 10, 0.88, 1, 6, 1),
)
# Lots excluded on the snapshot date as expired: (branch, ingredient, quantity).
EXPIRED_LOTS = (('1', '13', '3.5'), ('3', '4', '2.4'))

ORIGIN_NOTE = 'Деректің шығу тегі: SYNTHETIC'
DICTIONARY = (
    ('branches.csv', 'branch_id', 'int64', 'input', 'Шартты бөлімше идентификаторы'),
    ('branches.csv', 'branch_name', 'object', 'input', 'Бөлімшенің шартты атауы; нақты кәсіпорын емес'),
    ('calendar.csv', 'date', 'object', 'input', 'Күн, YYYY-MM-DD'),
    ('calendar.csv', 'branch_id', 'int64', 'input', 'Шартты бөлімше идентификаторы'),
    ('calendar.csv', 'weekday', 'int64', 'input', 'Апта күні: дүйсенбі 0 ... жексенбі 6'),
    ('calendar.csv', 'temperature_forecast_c', 'float64', 'input',
     'Қызылорда климатына ұқсатылған синтетикалық орташа тәуліктік температура болжамы, °C'),
    ('calendar.csv', 'synthetic_event', 'int64', 'input',
     'ҚР ресми мерекесі немесе ауыстырылған демалыс күні 1, басқа күн 0; тізім reference_rk_days_off.csv ішінде'),
    ('calendar.csv', 'is_open', 'int64', 'input', 'Бөлімше ашық 1, жабық 0 (санитарлық күн немесе жөндеу)'),
    ('daily_sales.csv', 'date', 'object', 'input', 'Бақылау күні, YYYY-MM-DD'),
    ('daily_sales.csv', 'branch_id', 'int64', 'input', 'Шартты бөлімше идентификаторы'),
    ('daily_sales.csv', 'meal_id', 'int64', 'input', 'Тағам идентификаторы'),
    ('daily_sales.csv', 'units_sold', 'int64', 'target', 'Бақыланған сатылымның имитациясы; мақсатты айнымалы'),
    ('daily_sales.csv', 'available_portions', 'int64', 'audit_only_current_day',
     'Сол күні дайындалған порциялар; келесі күндердің кіріс белгісі емес'),
    ('daily_sales.csv', 'stockout_flag', 'int64', 'audit_only_current_day',
     'Сұраныс дайын порциядан асты; талдау белгісі, ағымдағы күнге кіріс емес'),
    ('daily_sales.csv', 'is_open', 'int64', 'input', 'Жұмыс күні 1, жабық 0'),
    ('daily_sales.csv', 'promo', 'int64', 'input', 'Алдын ала жоспарланған акция, мысалы «күн тағамы» −10%'),
    ('daily_sales.csv', 'price_kzt', 'float64', 'input', 'Сол күнгі мәзір бағасы, теңге'),
    ('ingredients.csv', 'ingredient_id', 'int64', 'input', 'Ингредиент идентификаторы'),
    ('ingredients.csv', 'ingredient_name', 'object', 'input', 'Ингредиент атауы: қазақша / орысша'),
    ('ingredients.csv', 'unit', 'object', 'input', 'Базалық өлшем: kg немесе L'),
    ('ingredients.csv', 'reference_cost_kzt', 'int64', 'input',
     '2025 жылғы орташа бөлшек баға деңгейіне жуықталған шартты құн, теңге'),
    ('ingredients.csv', 'shelf_life_days', 'int64', 'input', 'Үлгілік параметр; тағам қауіпсіздігі нұсқаулығы емес'),
    ('ingredients.csv', 'yield_factor', 'float64', 'input', 'Таза мөлшер / жалпы мөлшер, 0 < eta <= 1'),
    ('ingredients.csv', 'storage_capacity', 'int64', 'input', 'Бөлімшедегі шартты сақтау шегі, базалық бірлік'),
    ('inventory_lots.csv', 'branch_id', 'int64', 'input', 'Шартты бөлімше идентификаторы'),
    ('inventory_lots.csv', 'ingredient_id', 'int64', 'input', 'Ингредиент идентификаторы'),
    ('inventory_lots.csv', 'lot_id', 'object', 'input', 'Қойма партиясының коды; X — мерзімі өткен партия'),
    ('inventory_lots.csv', 'snapshot_date', 'object', 'input', 'Қор кесіндісінің күні'),
    ('inventory_lots.csv', 'expiry_date', 'object', 'input', 'Соңғы пайдалануға болатын күн, үлгілік шарт'),
    ('inventory_lots.csv', 'on_hand_qty', 'float64', 'input', 'Партияның қолдағы мөлшері, базалық бірлік'),
    ('inventory_lots.csv', 'unit', 'object', 'input', 'Базалық өлшем: kg немесе L'),
    ('meals.csv', 'meal_id', 'int64', 'input', 'Тағам идентификаторы'),
    ('meals.csv', 'meal_name', 'object', 'input', 'Тағам атауы: қазақша, қажет болса / орысша'),
    ('meals.csv', 'base_price_kzt', 'int64', 'input', '2024 жылғы қаңтардағы мәзір бағасы, теңге'),
    ('recipes.csv', 'meal_id', 'int64', 'input', 'Тағам идентификаторы'),
    ('recipes.csv', 'ingredient_id', 'int64', 'input', 'Ингредиент идентификаторы'),
    ('recipes.csv', 'net_qty_per_portion', 'float64', 'input', 'Бір порциядағы таза мөлшер; жалпы мөлшер үшін шығымға бөлу'),
    ('recipes.csv', 'recipe_version', 'object', 'input', 'Рецепттің шартты нұсқасы'),
    ('supplier_offers.csv', 'supplier_id', 'int64', 'input', 'Жеткізуші идентификаторы'),
    ('supplier_offers.csv', 'ingredient_id', 'int64', 'input', 'Ингредиент идентификаторы'),
    ('supplier_offers.csv', 'pack_qty', 'int64', 'input', 'Бір қаптамадағы базалық мөлшер'),
    ('supplier_offers.csv', 'unit_cost_kzt', 'float64', 'input', 'Базалық бірліктің сатып алу бағасы, теңге'),
    ('supplier_offers.csv', 'min_packs', 'int64', 'input', 'Белсенді тапсырыстағы ең аз қаптама саны'),
    ('supplier_offers.csv', 'max_packs', 'int64', 'input', 'Бір ұсыныс бойынша қаптама санының шегі'),
    ('supplier_offers.csv', 'lead_time_days', 'int64', 'input', 'Жеткізу мерзімі, күн; 0 — сол күні'),
    ('suppliers.csv', 'supplier_id', 'int64', 'input', 'Жеткізуші идентификаторы'),
    ('suppliers.csv', 'supplier_name', 'object', 'input', 'Жеткізушінің шартты атауы; нақты компания емес'),
    ('suppliers.csv', 'lead_time_days', 'int64', 'input', 'Жеткізу мерзімі, күн; 0 — сол күні'),
    ('day_factors.csv', 'date', 'object', 'input', 'Күн, YYYY-MM-DD; болжам күні де бар, өйткені фактор алдын ала белгілі'),
    ('day_factors.csv', 'branch_id', 'int64', 'input', 'Шартты бөлімше идентификаторы'),
    ('day_factors.csv', 'factor', 'object', 'input',
     'Фактор коды, apps/api/factors.py: мерекелер, ауыстырулар, Наурыз, Ораза, ауызашар, айт, мектеп демалысы, '
     'жалақы күндері (демо шарты), температура болжамы, аптап ыстық, күн бату, бөлімшенің жұмысы'),
    ('day_factors.csv', 'value', 'float64', 'input',
     'Белгі 0/1 немесе сан; ауызашар мен күн бату — жергілікті уақыт бойынша минут; температура — °C'),
    ('reference_rk_days_off.csv', 'date', 'object', 'reference', 'Күн, YYYY-MM-DD'),
    ('reference_rk_days_off.csv', 'kind', 'object', 'reference',
     'holiday — мереке; transferred_day_off — ауыстырылған демалыс; working_day — жұмыс күніне айналған демалыс'),
    ('reference_rk_days_off.csv', 'name_kk', 'object', 'reference', 'Атауы қазақша'),
    ('reference_rk_days_off.csv', 'name_ru', 'object', 'reference', 'Атауы орысша'),
    ('reference_rk_days_off.csv', 'basis', 'object', 'reference', 'Құқықтық негіз'),
)


class Sampler:
    def __init__(self, seed: int):
        self.random = random.Random(seed)

    def uniform(self, low: float, high: float) -> float:
        return round(low + (high - low) * self.random.random(), 9)

    def integer(self, low: int, high: int) -> int:
        return low + min(int(self.random.random() * (high - low + 1)), high - low)

    def normal(self, sigma: float) -> float:
        first = max(self.random.random(), 1e-12)
        second = self.random.random()
        return round(sigma * math.sqrt(-2 * math.log(first)) * math.cos(2 * math.pi * second), 9)

    def poisson(self, mean: float) -> int:
        threshold, count, probability = self.random.random(), 0, math.exp(-mean)
        cumulative = probability
        while threshold > cumulative and count < 10000:
            count += 1
            probability *= mean / count
            cumulative += probability
        return count


def day_types():
    types = {}
    for text, kind, names, _ in DAYS_OFF:
        if kind == 'working_day':
            continue
        day = date.fromisoformat(text)
        if names == NEW_YEAR:
            types[day] = 'new_year' if day.day == 1 else 'new_year_2'
        elif 'Наурыз' in names[0]:
            types[day] = 'nauryz'
        elif names == KURBAN:
            types[day] = 'kurban'
        elif names == WOMEN:
            types[day] = 'women'
        else:
            types[day] = 'day_off'
    return types


def climate(day: date) -> float:
    """Linear interpolation between mid-month climate normals."""
    anchor = date(day.year, day.month, 15)
    if day >= anchor:
        following = date(day.year + (day.month == 12), day.month % 12 + 1, 15)
        start, end, low, high = anchor, following, CLIMATE[day.month - 1], CLIMATE[day.month % 12]
    else:
        previous = date(day.year - (day.month == 1), (day.month - 2) % 12 + 1, 15)
        start, end, low, high = previous, anchor, CLIMATE[(day.month - 2) % 12], CLIMATE[day.month - 1]
    return round(low + (high - low) * (day - start).days / (end - start).days, 6)


def menu_price(base: int, day: date) -> int:
    price = base
    for start, factor in PRICE_STEPS:
        if day >= start:
            step = 50 if price * factor >= 1000 else 10
            price = int(price * factor / step + 0.5) * step
    return price


def promo_price(price: int) -> int:
    return int(price * 0.9 / 10 + 0.5) * 10


def price_dip(day: date) -> float:
    started = [start for start, _ in PRICE_STEPS if start <= day]
    if not started or (day - started[-1]).days > 120:
        return 1.0
    return round(1 - 0.05 * math.exp(-(day - started[-1]).days / 40), 6)


def temperature_factor(profile: str | None, temperature: float) -> float:
    if profile == 'soup':
        return min(max(1 + 0.018 * (8 - temperature), 0.65), 1.45)
    if profile == 'salad':
        return min(max(1 + 0.02 * (temperature - 12), 0.6), 1.5)
    if profile == 'porridge':
        return min(max(1 + 0.008 * (8 - temperature), 0.85), 1.2)
    if profile == 'festive':
        return min(max(1 + 0.006 * (8 - temperature), 0.9), 1.15)
    return 1.0


def systematic_demand(branch: dict, meal: tuple, day: date, temperature: float, special: str | None,
                      promo: bool) -> float:
    """Expected demand without random shocks; the chef plans production from it."""
    index = int(branch['id']) - 1
    weekday = (sum(branch['weekday'][:5]) / 5 if day in WORKING_WEEKENDS and branch['id'] != '1'
               else branch['weekday'][day.weekday()])
    value = meal[3] * branch['scale'] * AFFINITY[branch['id']].get(meal[0], 1.0) * weekday
    value *= 1 + 0.035 * (day - START).days / 365.25
    if special:
        value *= SPECIAL[special][index] * FESTIVE.get(meal[0], {}).get(special, 1.0)
    if any(first <= day <= last for first, last in RAMADAN):
        value *= branch['ramadan'] * (1.25 if meal[0] == '10' and branch['id'] == '3' else 1.0)
    if day.month in (6, 7, 8):
        value *= branch['summer']
    value *= temperature_factor(meal[4], temperature)
    if temperature >= 33:
        value *= branch['heat']
    elif temperature <= -15:
        value *= branch['cold']
    value *= price_dip(day)
    if promo:
        value *= 1.3 if branch['id'] == '2' else 1.2
    return round(value, 6)


def sunset_minutes(day: date) -> int:
    """Sunset in Qyzylorda local time, minutes after midnight (NOAA solar approximation)."""
    latitude, longitude = QYZYLORDA
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    equation = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                         - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    declination = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
                   - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
                   - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(latitude)
    hour_angle = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(declination))
                                        - math.tan(phi) * math.tan(declination)))
    return round(720 - 4 * (longitude - hour_angle) - equation + UTC_OFFSET_MINUTES)


def day_factor_rows(days: list, temperatures: dict) -> list:
    """Known-in-advance day factors for every branch through the forecast day (no random draws)."""
    kinds = {**{date.fromisoformat(text): kind for text, kind, _, _ in DAYS_OFF}, **FORECAST_DAYS_OFF}
    day_off = {day for day, kind in kinds.items() if kind in ('holiday', 'transferred_day_off')}
    types = day_types()
    kurban = {date.fromisoformat(text) for text, _, names, _ in DAYS_OFF if names == KURBAN}
    # The forecast day has no observed temperature: persist the last anomaly from the climate normal.
    temperature = dict(temperatures)
    temperature[SNAPSHOT] = round(climate(SNAPSHOT) + 0.75 * (temperatures[END] - climate(END)), 1)
    rows = []
    for day in days + [SNAPSHOT]:
        working = (day.weekday() < 5 and day not in day_off) or day in WORKING_WEEKENDS
        ramadan = any(first <= day <= last for first, last in RAMADAN)
        common = (
            ('public_holiday', int(kinds.get(day) == 'holiday')),
            ('transferred_day_off', int(kinds.get(day) == 'transferred_day_off')),
            ('working_weekend', int(day in WORKING_WEEKENDS)),
            ('pre_holiday', int(working and day + timedelta(days=1) in day_off)),
            ('nauryz', int(types.get(day) == 'nauryz')),
            ('ramadan', int(ramadan)),
            ('iftar_minutes', sunset_minutes(day) if ramadan else None),
            ('ait', int(day in ORAZA_AIT or day in kurban)),
            ('school_holiday', int(any(first <= day <= last for first, last in SCHOOL_HOLIDAYS))),
            ('payday', int(day.day in PAYDAYS)),
            ('temperature_forecast_c', f'{temperature[day] + 0.0:.1f}'),
            ('heat_alert', int(temperature[day] >= HEAT_ALERT_C)),
            ('sunset_minutes', sunset_minutes(day)),
        )
        for branch in BRANCHES:
            closed = {date.fromisoformat(text) for text in branch['closed']}
            for code, value in common + (('is_open', int(day not in closed)),):
                if value is not None:
                    rows.append([day.isoformat(), branch['id'], code, value, ORIGIN])
    return rows


def decimal_text(value) -> str:
    text = format(value, 'f') if not isinstance(value, str) else value
    return text.rstrip('0').rstrip('.') if '.' in text else text


def csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return ('\ufeff' + buffer.getvalue()).encode('utf-8')


def build() -> dict[str, bytes]:
    sampler = Sampler(SEED)
    special_days = day_types()
    days = [START + timedelta(days=offset) for offset in range((END - START).days + 1)]
    temperatures, anomaly = {}, 0.0
    for day in days:
        anomaly = round(0.75 * anomaly + sampler.normal(2.6), 9)
        temperatures[day] = round(climate(day) + anomaly + sampler.normal(0.8), 1)
    files: dict[str, list[list]] = {name: [] for name in (
        'branches', 'meals', 'ingredients', 'recipes', 'suppliers', 'supplier_offers',
        'calendar', 'daily_sales', 'inventory_lots', 'oracle')}
    files['branches'] = [[branch['id'], branch['name'], ORIGIN] for branch in BRANCHES]
    files['meals'] = [[meal[0], meal[1], meal[2], ORIGIN] for meal in MEALS]
    files['ingredients'] = [[item[0], item[1], item[2], item[3], item[4], item[5], item[6], ORIGIN]
                            for item in INGREDIENTS]
    files['recipes'] = [[meal[0], ingredient, quantity, RECIPE_VERSION, ORIGIN]
                        for meal in MEALS for ingredient, quantity in meal[5]]
    files['suppliers'] = [[supplier[0], supplier[1], supplier[2], ORIGIN] for supplier in SUPPLIERS]
    reference = {item[0]: item[3] for item in INGREDIENTS}
    files['supplier_offers'] = [[offer[0], offer[1], offer[2], decimal_text(f'{reference[offer[1]] * offer[3]:.2f}'),
                                 offer[4], offer[5], offer[6], ORIGIN] for offer in OFFERS]
    recent = {branch['id']: {meal[0]: [] for meal in MEALS} for branch in BRANCHES}
    for branch in BRANCHES:
        closed = {date.fromisoformat(text) for text in branch['closed']}
        shock, bias = 0.0, {meal[0]: 0.0 for meal in MEALS}
        for day in days:
            shock = round(0.5 * shock + sampler.normal(0.07), 9)
            special = special_days.get(day) or ('new_year_eve' if (day.month, day.day) == (12, 31) else None)
            is_open = day not in closed
            files['calendar'].append([day.isoformat(), branch['id'], day.weekday(), f'{temperatures[day] + 0.0:.1f}',
                                      int(special_days.get(day) is not None), int(is_open), ORIGIN])
            ordinary = is_open and special is None and day.weekday() < 5
            daily_dish = (DISH_OF_THE_DAY[sampler.integer(0, len(DISH_OF_THE_DAY) - 1)]
                          if branch['id'] == '2' and ordinary else None)
            for meal in MEALS:
                price = menu_price(meal[2], day)
                bias[meal[0]] = round(0.8 * bias[meal[0]] + sampler.normal(0.03), 9)
                if not is_open:
                    files['daily_sales'].append([day.isoformat(), branch['id'], meal[0], 0, 0, 0, 0, 0, price, ORIGIN])
                    files['oracle'].append([day.isoformat(), branch['id'], meal[0], 0, ORIGIN])
                    continue
                promo = meal[0] == daily_dish if branch['id'] == '2' else (
                    special is None and sampler.random.random() < 0.02)
                expected = systematic_demand(branch, meal, day, temperatures[day], special, promo)
                mean = round(expected * math.exp(shock + sampler.normal(0.11)), 6)
                latent = sampler.poisson(mean)
                planned = expected * 1.25 * math.exp(bias[meal[0]] + sampler.normal(0.1))
                available = max(3, math.ceil(round(planned, 6)))
                sold = min(latent, available)
                stockout = int(latent > available)
                if day > END - timedelta(days=7):
                    recent[branch['id']][meal[0]].append(expected)
                files['daily_sales'].append([day.isoformat(), branch['id'], meal[0], sold, available, stockout, 1,
                                             int(promo), promo_price(price) if promo else price, ORIGIN])
                files['oracle'].append([day.isoformat(), branch['id'], meal[0], latent, ORIGIN])
    catalog = {item[0]: item for item in INGREDIENTS}
    for branch in BRANCHES:
        need = {item[0]: 0.0 for item in INGREDIENTS}
        for meal in MEALS:
            portions = sum(recent[branch['id']][meal[0]]) / max(len(recent[branch['id']][meal[0]]), 1)
            for ingredient, quantity in meal[5]:
                need[ingredient] += portions * float(quantity) / float(catalog[ingredient][5])
        for item in INGREDIENTS:
            daily, stock_class = round(need[item[0]], 6), item[7]
            low, high, first, last = {'meat': (0.15, 0.4, 0, 2), 'dairy': (0.2, 0.5, 0, 3),
                                      'fresh': (0.2, 0.6, 1, 4), 'root': (0.6, 1.5, 10, 40),
                                      'dry': (1.5, 4.0, 60, 300)}[stock_class]
            lots = 2 if stock_class in ('meat', 'root') and sampler.random.random() < 0.35 else 1
            for number in range(1, lots + 1):
                share = sampler.uniform(low, high) / number
                quantity = min(max(round(daily * share, 2), 0.3), round(item[6] * 0.7, 2))
                expiry = SNAPSHOT + timedelta(days=sampler.integer(first, last))
                files['inventory_lots'].append([branch['id'], item[0], f'B{branch["id"]}-I{int(item[0]):02d}-L{number}',
                                                SNAPSHOT.isoformat(), expiry.isoformat(), decimal_text(f'{quantity:.2f}'),
                                                item[2], ORIGIN])
        for expired_branch, ingredient, quantity in EXPIRED_LOTS:
            if expired_branch == branch['id']:
                files['inventory_lots'].append([branch['id'], ingredient, f'B{branch["id"]}-I{int(ingredient):02d}-X1',
                                                SNAPSHOT.isoformat(), (SNAPSHOT - timedelta(days=1)).isoformat(),
                                                quantity, catalog[ingredient][2], ORIGIN])
    headers = {
        'branches': 'branch_id branch_name data_origin',
        'meals': 'meal_id meal_name base_price_kzt data_origin',
        'ingredients': ('ingredient_id ingredient_name unit reference_cost_kzt shelf_life_days '
                        'yield_factor storage_capacity data_origin'),
        'recipes': 'meal_id ingredient_id net_qty_per_portion recipe_version data_origin',
        'suppliers': 'supplier_id supplier_name lead_time_days data_origin',
        'supplier_offers': 'supplier_id ingredient_id pack_qty unit_cost_kzt min_packs max_packs lead_time_days data_origin',
        'calendar': 'date branch_id weekday temperature_forecast_c synthetic_event is_open data_origin',
        'daily_sales': ('date branch_id meal_id units_sold available_portions stockout_flag is_open promo '
                        'price_kzt data_origin'),
        'inventory_lots': 'branch_id ingredient_id lot_id snapshot_date expiry_date on_hand_qty unit data_origin',
        'oracle': 'date branch_id meal_id latent_demand_ORACLE_ONLY data_origin',
    }
    output = {name: csv_bytes(headers[name].split(), rows) for name, rows in files.items()}
    factor_rows = day_factor_rows(days, temperatures)
    output['day_factors'] = csv_bytes(['date', 'branch_id', 'factor', 'value', 'data_origin'], factor_rows)
    output['reference_rk_days_off'] = csv_bytes(
        ['date', 'kind', 'name_kk', 'name_ru', 'basis'],
        [[text, kind, names[0], names[1], basis] for text, kind, names, basis in DAYS_OFF])
    dictionary = []
    for file in dict.fromkeys(row[0] for row in DICTIONARY):
        dictionary += [list(row) for row in DICTIONARY if row[0] == file]
        if file != 'reference_rk_days_off.csv':
            dictionary.append([file, 'data_origin', 'object', 'provenance', ORIGIN_NOTE])
    output['data_dictionary'] = csv_bytes(['file', 'field', 'dtype', 'role', 'description_kk'], dictionary)
    sales = files['daily_sales']
    open_rows = [row for row in sales if row[6] == 1]
    output['metadata'] = (json.dumps({
        'origin': ORIGIN, 'scenario': 'Қызылорда: 3 бөлімше, 12 тағам, 14 ингредиент',
        'generator': 'scripts/generate_kz_demo.py', 'seed': SEED,
        'date_from': START.isoformat(), 'date_to': END.isoformat(), 'inventory_snapshot': SNAPSHOT.isoformat(),
        'rows': {**{name: len(rows) for name, rows in files.items() if name != 'oracle'},
                 'day_factors': len(factor_rows)},
        'oracle_rows': len(files['oracle']),
        'shares': {'stockout_rows_of_open': round(sum(row[5] for row in open_rows) / len(open_rows), 4),
                   'promo_rows_of_open': round(sum(row[7] for row in open_rows) / len(open_rows), 4)},
        'warning': ('Not observations from a real enterprise. Names, prices, recipes, stock and sales are SYNTHETIC; '
                    'shelf life is illustrative, not a food-safety instruction. Never train with oracle data.'),
    }, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return output


def generate(output: Path, oracle: Path | None = None) -> dict:
    """Write the dataset; latent demand is written only when an oracle path is given."""
    files = build()
    output.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if name != 'oracle':
            (output / (name + ('.json' if name == 'metadata' else '.csv'))).write_bytes(content)
        elif oracle is not None:
            oracle.parent.mkdir(parents=True, exist_ok=True)
            oracle.write_bytes(content)
    return json.loads(files['metadata'].decode('utf-8'))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'kz')
    parser.add_argument('--oracle', type=Path, help='Optional research-only latent demand CSV; never a training input')
    args = parser.parse_args()
    summary = generate(args.output, args.oracle)
    print(json.dumps({'rows': summary['rows'], 'shares': summary['shares']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
