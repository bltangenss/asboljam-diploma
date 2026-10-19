"""Build known-in-advance day factors for any city of Kazakhstan.

Calendar, religious and school factors come from apps.api.kz_calendar and stop where
official publication stops. Sunset and iftar come from solar geometry for the city's
coordinates in its legal local time on that date. Payday, opening days, trains and office
occupancy are enterprise data and are never generated here.
"""
from datetime import date, datetime, timedelta
import math
from zoneinfo import ZoneInfo

from . import kz_calendar as calendar
from .cities import city as find_city

CALENDAR_CODES = ('public_holiday', 'transferred_day_off', 'working_weekend', 'pre_holiday', 'nauryz',
                  'ramadan', 'iftar_minutes', 'ait', 'school_holiday', 'sunset_minutes')
MAX_DAYS = 1100


class FactorBuildError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def sunset_minutes(day: date, latitude: float, longitude: float, zone: str) -> int:
    """Sunset in local legal time, minutes after midnight (NOAA solar approximation)."""
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    equation = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                         - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    declination = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
                   - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
                   - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(latitude)
    hour_angle = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(declination))
                                        - math.tan(phi) * math.tan(declination)))
    offset = datetime(day.year, day.month, day.day, 12, tzinfo=ZoneInfo(zone)).utcoffset()
    return round(720 - 4 * (longitude - hour_angle) - equation + offset.total_seconds() / 60)


def _range(start: date, end: date) -> list:
    if end < start:
        raise FactorBuildError('FACTOR_RANGE_INVALID', 'Аяқталу күні басталу күнінен бұрын.')
    if (end - start).days + 1 > MAX_DAYS:
        raise FactorBuildError('FACTOR_RANGE_TOO_LONG', f'Бір ретте ең көбі {MAX_DAYS} күн.')
    return [start + timedelta(days=step) for step in range((end - start).days + 1)]


def calendar_rows(city_code: str, start: date, end: date) -> list:
    """(date, code, value) rows; a code is omitted on days its official source does not cover."""
    place = find_city(city_code)
    if place is None:
        raise FactorBuildError('CITY_UNKNOWN', 'Қала анықтамалықта жоқ.')
    rows = []
    for day in _range(start, end):
        if day < calendar.CALENDAR_KNOWN_FROM:
            continue
        sunset = sunset_minutes(day, place['latitude'], place['longitude'], place['timezone'])
        kind = calendar.day_kind(day)
        ramadan = calendar.in_ranges(day, calendar.RAMADAN)
        working = (day.weekday() < 5 and not calendar.is_day_off(day)) or day in calendar.WORKING_WEEKENDS
        values = {
            'public_holiday': int(bool(kind) and kind[0] == 'holiday'),
            'transferred_day_off': int(bool(kind) and kind[0] == 'transferred_day_off'),
            'working_weekend': int(day in calendar.WORKING_WEEKENDS),
            'pre_holiday': int(working and calendar.is_day_off(day + timedelta(days=1))),
            'nauryz': int(bool(kind) and kind[0] != 'working_day' and kind[1] == 'nauryz'),
            'ramadan': int(ramadan),
            'iftar_minutes': sunset if ramadan else None,
            'ait': int(day in calendar.ORAZA_AIT or day in calendar.KURBAN_AIT),
            'school_holiday': int(calendar.in_ranges(day, calendar.SCHOOL_HOLIDAYS)),
            'sunset_minutes': sunset,
        }
        for code in CALENDAR_CODES:
            if values[code] is not None and day <= calendar.known_through(code):
                rows.append((day, code, values[code]))
    return rows
