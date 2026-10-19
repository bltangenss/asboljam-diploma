"""Official Kazakhstan calendars used to build day factors for any city.

Each list ends where official publication ends; later days get no calendar factor rather
than a guess. Sources:
- Holidays: Law of the RK «On holidays in the Republic of Kazakhstan»; transfers by
  Government decrees / Ministry of Labour orders (2024 production calendar; order No 436 of
  21.11.2024 for 2025; 2026 production calendar as updated on 29.06.2026). From 01.07.2026
  Constitution Day moved from 30 August to 15 March, so 30-31.08.2026 are working days.
- Ramadan and Oraza ait: annual calendars of the Spiritual Administration of Muslims of
  Kazakhstan (DUMK); Kurban ait (first day) is an official day off.
- School holidays: Ministry of Education orders for 2023/24, 2024/25, 2025/26, 2026/27; the
  extra first-grade week is not a whole-school holiday and is excluded.
"""
from datetime import date, timedelta

# (date, kind, tag): kind is holiday, transferred_day_off or working_day; transferred days
# carry the tag of the holiday they replace (Nauryz transfers count as Nauryz days).
DAYS_OFF = (
    ('2024-01-01', 'holiday', 'new_year'), ('2024-01-02', 'holiday', 'new_year'),
    ('2024-01-07', 'holiday', 'christmas'), ('2024-03-08', 'holiday', 'women'),
    ('2024-03-21', 'holiday', 'nauryz'), ('2024-03-22', 'holiday', 'nauryz'),
    ('2024-03-23', 'holiday', 'nauryz'), ('2024-03-25', 'transferred_day_off', 'nauryz'),
    ('2024-05-01', 'holiday', 'unity'), ('2024-05-04', 'working_day', 'defender'),
    ('2024-05-07', 'holiday', 'defender'), ('2024-05-08', 'transferred_day_off', 'defender'),
    ('2024-05-09', 'holiday', 'victory'), ('2024-06-16', 'holiday', 'kurban'),
    ('2024-07-06', 'holiday', 'capital'), ('2024-07-08', 'transferred_day_off', 'capital'),
    ('2024-08-30', 'holiday', 'constitution'), ('2024-10-25', 'holiday', 'republic'),
    ('2024-12-16', 'holiday', 'independence'),
    ('2025-01-01', 'holiday', 'new_year'), ('2025-01-02', 'holiday', 'new_year'),
    ('2025-01-03', 'transferred_day_off', 'new_year'), ('2025-01-05', 'working_day', 'new_year'),
    ('2025-01-07', 'holiday', 'christmas'), ('2025-03-08', 'holiday', 'women'),
    ('2025-03-10', 'transferred_day_off', 'women'),
    ('2025-03-21', 'holiday', 'nauryz'), ('2025-03-22', 'holiday', 'nauryz'),
    ('2025-03-23', 'holiday', 'nauryz'), ('2025-03-24', 'transferred_day_off', 'nauryz'),
    ('2025-03-25', 'transferred_day_off', 'nauryz'),
    ('2025-05-01', 'holiday', 'unity'), ('2025-05-07', 'holiday', 'defender'),
    ('2025-05-09', 'holiday', 'victory'), ('2025-06-06', 'holiday', 'kurban'),
    ('2025-07-06', 'holiday', 'capital'), ('2025-07-07', 'transferred_day_off', 'capital'),
    ('2025-08-30', 'holiday', 'constitution'), ('2025-09-01', 'transferred_day_off', 'constitution'),
    ('2025-10-25', 'holiday', 'republic'), ('2025-10-27', 'transferred_day_off', 'republic'),
    ('2025-12-16', 'holiday', 'independence'),
    ('2026-01-01', 'holiday', 'new_year'), ('2026-01-02', 'holiday', 'new_year'),
    ('2026-01-07', 'holiday', 'christmas'), ('2026-03-08', 'holiday', 'women'),
    ('2026-03-09', 'transferred_day_off', 'women'),
    ('2026-03-21', 'holiday', 'nauryz'), ('2026-03-22', 'holiday', 'nauryz'),
    ('2026-03-23', 'holiday', 'nauryz'), ('2026-03-24', 'transferred_day_off', 'nauryz'),
    ('2026-03-25', 'transferred_day_off', 'nauryz'),
    ('2026-05-01', 'holiday', 'unity'), ('2026-05-07', 'holiday', 'defender'),
    ('2026-05-09', 'holiday', 'victory'), ('2026-05-11', 'transferred_day_off', 'victory'),
    ('2026-05-27', 'holiday', 'kurban'), ('2026-07-06', 'holiday', 'capital'),
    ('2026-10-25', 'holiday', 'republic'), ('2026-10-26', 'transferred_day_off', 'republic'),
    ('2026-12-16', 'holiday', 'independence'),
)
HOLIDAYS_KNOWN_THROUGH = date(2026, 12, 31)
# Fixed by law every year; used only to mark the day before the first unpublished year.
FIXED_HOLIDAYS = {(1, 1), (1, 2), (1, 7), (3, 8), (3, 21), (3, 22), (3, 23), (5, 1), (5, 7), (5, 9),
                  (7, 6), (10, 25), (12, 16)}

RAMADAN = ((date(2024, 3, 11), date(2024, 4, 9)), (date(2025, 3, 1), date(2025, 3, 29)),
           (date(2026, 2, 19), date(2026, 3, 19)))
ORAZA_AIT = (date(2024, 4, 10), date(2025, 3, 30), date(2026, 3, 20))
RELIGIOUS_KNOWN_THROUGH = date(2026, 12, 31)

SCHOOL_HOLIDAYS = (
    (date(2023, 12, 29), date(2024, 1, 7)), (date(2024, 3, 21), date(2024, 3, 31)),
    (date(2024, 5, 26), date(2024, 8, 31)), (date(2024, 10, 28), date(2024, 11, 3)),
    (date(2024, 12, 30), date(2025, 1, 8)), (date(2025, 3, 21), date(2025, 3, 31)),
    (date(2025, 5, 26), date(2025, 9, 1)), (date(2025, 10, 27), date(2025, 11, 2)),
    (date(2025, 12, 29), date(2026, 1, 7)), (date(2026, 3, 19), date(2026, 3, 29)),
    (date(2026, 5, 26), date(2026, 8, 31)), (date(2026, 10, 26), date(2026, 11, 1)),
    (date(2026, 12, 28), date(2027, 1, 10)), (date(2027, 3, 22), date(2027, 3, 28)),
)
SCHOOL_KNOWN_FROM, SCHOOL_KNOWN_THROUGH = date(2024, 1, 1), date(2027, 5, 25)
CALENDAR_KNOWN_FROM = date(2024, 1, 1)

_KINDS = {date.fromisoformat(text): (kind, tag) for text, kind, tag in DAYS_OFF}
DAY_OFF = {day for day, (kind, _) in _KINDS.items() if kind in ('holiday', 'transferred_day_off')}
WORKING_WEEKENDS = {day for day, (kind, _) in _KINDS.items() if kind == 'working_day'}
KURBAN_AIT = {day for day, (kind, tag) in _KINDS.items() if kind == 'holiday' and tag == 'kurban'}


def day_kind(day: date) -> tuple | None:
    return _KINDS.get(day)


def is_day_off(day: date) -> bool:
    """Official non-working day, falling back to the fixed-date law after published years."""
    if day <= HOLIDAYS_KNOWN_THROUGH:
        return day in DAY_OFF
    return (day.month, day.day) in FIXED_HOLIDAYS


def in_ranges(day: date, ranges) -> bool:
    return any(first <= day <= last for first, last in ranges)


def known_through(code: str) -> date:
    if code in ('ramadan', 'iftar_minutes', 'ait'):
        return RELIGIOUS_KNOWN_THROUGH
    if code == 'school_holiday':
        return SCHOOL_KNOWN_THROUGH
    if code == 'sunset_minutes':
        return date.max - timedelta(days=1)
    return HOLIDAYS_KNOWN_THROUGH
