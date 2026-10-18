"""Day factors that may explain observed sales, all known before the forecast day.

Seventeen factors are imported as rows of the optional `day_factors` CSV (date, branch,
factor code, value). Three are derived from the sales history already imported. A factor
enters the factor model only with a value on the target day and enough training coverage;
otherwise it is skipped with a stated reason, never filled with an invented value.
"""
from decimal import Decimal

# code, group, kind, minimum, maximum, sparse, kk name, ru name, source hint
#   kind 'flag' takes 0/1; 'number' takes a decimal within [minimum, maximum].
#   sparse: a missing day means "not applicable" (iftar outside Ramadan), not missing data.
_IMPORTED = (
    ('public_holiday', 'calendar', 'flag', 0, 1, False, 'Мемлекеттік мереке', 'Государственный праздник',
     'adilet.zan.kz: «Қазақстан Республикасындағы мерекелер туралы» заң'),
    ('transferred_day_off', 'calendar', 'flag', 0, 1, False, 'Ауыстырылған демалыс', 'Перенесённый выходной',
     'ҚР Үкіметінің демалыс күндерін ауыстыру қаулылары'),
    ('working_weekend', 'calendar', 'flag', 0, 1, False, 'Жұмыс күніне айналған демалыс', 'Рабочая суббота',
     'ҚР Үкіметінің демалыс күндерін ауыстыру қаулылары'),
    ('pre_holiday', 'calendar', 'flag', 0, 1, False, 'Мереке алдындағы қысқартылған күн', 'Предпраздничный сокращённый день',
     'Еңбек кодексі: мереке алдындағы жұмыс күні бір сағатқа қысқарады'),
    ('nauryz', 'culture', 'flag', 0, 1, False, 'Наурыз мейрамы', 'Наурыз',
     'adilet.zan.kz: 21–23 наурыз'),
    ('ramadan', 'culture', 'flag', 0, 1, False, 'Ораза айы', 'Месяц Рамадан',
     'ҚМДБ (muftyat.kz) жылдық күнтізбесі'),
    ('iftar_minutes', 'culture', 'number', 0, 1439, True, 'Ауызашар уақыты, минут', 'Время ауызашара, минуты от полуночи',
     'ҚМДБ кестесі немесе қала бойынша күн бату уақыты'),
    ('ait', 'culture', 'flag', 0, 1, False, 'Ораза айт және Құрбан айт', 'Ораза айт и Курбан айт',
     'ҚМДБ күнтізбесі; Құрбан айт — ресми демалыс'),
    ('school_holiday', 'school', 'flag', 0, 1, False, 'Мектеп демалысы', 'Школьные каникулы',
     'ҚР Оқу-ағарту министрлігінің оқу жылы туралы бұйрығы'),
    ('payday', 'economy', 'flag', 0, 1, False, 'Жалақы және аванс күндері', 'Дни зарплаты и аванса',
     'Кәсіпорын немесе аймақтағы жалақы төлеу тәртібі'),
    ('temperature_forecast_c', 'weather', 'number', -60, 60, False, 'Ауа температурасының болжамы, °C', 'Прогноз температуры воздуха, °C',
     'Қазгидромет болжамы (нақты емес, алдын ала болжам)'),
    ('precipitation_mm', 'weather', 'number', 0, 500, False, 'Жауын-шашын болжамы, мм', 'Прогноз осадков, мм',
     'Қазгидромет болжамы'),
    ('heat_alert', 'weather', 'flag', 0, 1, False, 'Аптап ыстық ескертуі', 'Предупреждение о сильной жаре',
     'Қазгидромет және ТЖМ ескертулері'),
    ('sunset_minutes', 'weather', 'number', 0, 1439, False, 'Күн бату уақыты, минут', 'Время заката, минуты от полуночи',
     'Астрономиялық есеп (қаланың ендігі мен бойлығы)'),
    ('station_trains', 'traffic', 'number', 0, 2000, False, 'Вокзалдағы пойыздар саны', 'Поездов через вокзал',
     'ҚТЖ кестесі'),
    ('office_occupancy_pct', 'traffic', 'number', 0, 100, False, 'Бизнес-орталықтың толуы, %', 'Заполненность бизнес-центра, %',
     'Бизнес-орталық әкімшілігі (турникет деректері)'),
    ('is_open', 'operations', 'flag', 0, 1, False, 'Бөлімше жұмыс істейді', 'Филиал работает',
     'Бөлімшенің жұмыс кестесі'),
)
# Derived from daily_sales; documented next to the imported ones so the list is complete.
_DERIVED = (
    ('menu_price_ratio', 'operations', 'Мәзір бағасы (28 күндік орташаға қатысы)', 'Цена в меню к средней за 28 дней',
     'daily_sales.price_kzt; болжам күніне соңғы белгілі баға алынады'),
    ('promo', 'operations', 'Жоспарланған акция', 'Запланированная акция',
     'daily_sales.promo; болжам күніне жоспар берілмесе, акциясыз деп алынады'),
    ('stockout_recent', 'operations', 'Соңғы 7 күндегі тағам таусылу үлесі', 'Доля дней «блюдо закончилось» за 7 дней',
     'daily_sales.stockout_flag, тек өткен күндер'),
)

IMPORTED = {code: {'code': code, 'group': group, 'kind': kind, 'minimum': Decimal(low), 'maximum': Decimal(high),
                   'sparse': sparse, 'name': {'kk': kk, 'ru': ru}, 'source_hint': hint, 'origin': 'day_factors'}
            for code, group, kind, low, high, sparse, kk, ru, hint in _IMPORTED}
DERIVED = {code: {'code': code, 'group': group, 'kind': 'number', 'sparse': False,
                  'name': {'kk': kk, 'ru': ru}, 'source_hint': hint, 'origin': 'daily_sales'}
           for code, group, kk, ru, hint in _DERIVED}
ORDER = [code for code, *_ in _IMPORTED] + [code for code, *_ in _DERIVED]
# A non-sparse factor needs a value on at least this share of training days.
MIN_COVERAGE = 0.9


def check_value(code, number):
    """Return an error code for a factor value, or None when it is acceptable."""
    factor = IMPORTED.get(code)
    if factor is None:
        return 'UNKNOWN_FACTOR'
    if not factor['minimum'] <= number <= factor['maximum']:
        return 'FACTOR_OUT_OF_RANGE'
    if factor['kind'] == 'flag' and number not in (0, 1):
        return 'FACTOR_NOT_FLAG'
    return None


def catalogue():
    """Public description of all twenty factors in a stable order."""
    result = []
    for code in ORDER:
        factor = IMPORTED.get(code) or DERIVED[code]
        item = {key: factor[key] for key in ('code', 'group', 'kind', 'sparse', 'name', 'source_hint', 'origin')}
        if code in IMPORTED:
            item['minimum'], item['maximum'] = str(factor['minimum']), str(factor['maximum'])
        result.append(item)
    return result
