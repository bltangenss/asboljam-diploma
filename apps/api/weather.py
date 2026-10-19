"""Daily weather forecasts for a city from Open-Meteo (no key for non-commercial use).

Past days come from the historical-forecast archive: model forecasts as issued, not later
measurements, so training sees the same kind of value as the forecast day. Today and up to
15 days ahead come from the live forecast. Commercial deployments must use a licensed
endpoint and key (WEATHER_FORECAST_URL, WEATHER_ARCHIVE_URL, WEATHER_API_KEY); the key is
never logged or returned.
"""
from datetime import date, timedelta
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
ARCHIVE_URL = 'https://historical-forecast-api.open-meteo.com/v1/forecast'
ARCHIVE_FROM = date(2022, 1, 1)
HORIZON_DAYS = 15
HEAT_ALERT_C = 33
DAILY = 'temperature_2m_mean,temperature_2m_max,precipitation_sum'
_cache: dict = {}


class WeatherError(RuntimeError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def enabled() -> bool:
    return os.environ.get('WEATHER_PROVIDER', 'open-meteo').strip().lower() == 'open-meteo'


def _get(url: str, params: dict, timeout: float) -> dict:
    key = os.environ.get('WEATHER_API_KEY', '').strip()
    query = urllib.parse.urlencode({**params, **({'apikey': key} if key else {})})
    request = urllib.request.Request(url + '?' + query, headers={'User-Agent': 'AsBoljam/1.1 (weather factors)'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(2_000_000).decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        # The URL may carry a key, so the message never includes it.
        raise WeatherError('WEATHER_UNAVAILABLE', 'Ауа райы қызметі жауап бермеді.') from None


def _daily(url: str, place: dict, start: date, end: date, timeout: float) -> dict:
    payload = _get(url, {'latitude': place['latitude'], 'longitude': place['longitude'], 'daily': DAILY,
                         'timezone': place['timezone'], 'start_date': start.isoformat(),
                         'end_date': end.isoformat()}, timeout)
    daily = payload.get('daily') if isinstance(payload, dict) else None
    if not isinstance(daily, dict) or not isinstance(daily.get('time'), list):
        raise WeatherError('WEATHER_INVALID', 'Ауа райы жауабы күтілген пішімде емес.')
    result = {}
    for index, text in enumerate(daily['time']):
        try:
            day = date.fromisoformat(text)
            mean, high, rain = (daily[name][index] for name in
                                ('temperature_2m_mean', 'temperature_2m_max', 'precipitation_sum'))
        except (KeyError, IndexError, TypeError, ValueError):
            raise WeatherError('WEATHER_INVALID', 'Ауа райы жауабы күтілген пішімде емес.') from None
        if None in (mean, high, rain):
            continue  # No forecast for that day: the factor stays missing, never zero.
        result[day] = {'temperature_mean': float(mean), 'temperature_max': float(high), 'precipitation': float(rain)}
    return result


def daily_forecasts(place: dict, start: date, end: date, *, today: date, timeout: float = 20) -> dict:
    """Forecast values per day; days outside archive and horizon are simply absent."""
    if not enabled():
        raise WeatherError('WEATHER_DISABLED', 'Ауа райы қызметі өшірілген.')
    result = {}
    past_end = min(end, today - timedelta(days=1))
    if start <= past_end and past_end >= ARCHIVE_FROM:
        result.update(_daily(ARCHIVE_URL if not os.environ.get('WEATHER_ARCHIVE_URL') else os.environ['WEATHER_ARCHIVE_URL'],
                             place, max(start, ARCHIVE_FROM), past_end, timeout))
    live_start, live_end = max(start, today), min(end, today + timedelta(days=HORIZON_DAYS))
    if live_start <= live_end:
        result.update(_daily(os.environ.get('WEATHER_FORECAST_URL') or FORECAST_URL, place, live_start, live_end, timeout))
    return result


def factor_values(forecast: dict) -> list:
    """Factor codes for one day's forecast."""
    return [('temperature_forecast_c', round(forecast['temperature_mean'], 1)),
            ('precipitation_mm', round(max(forecast['precipitation'], 0.0), 1)),
            ('heat_alert', int(forecast['temperature_max'] >= HEAT_ALERT_C))]


def week_ahead(place: dict, today: date, *, ttl: float = 1800) -> list:
    """Seven-day outlook for display, cached per city for half an hour."""
    key = (place['code'], today.isoformat())
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < ttl:
        return cached[1]
    values = daily_forecasts(place, today, today + timedelta(days=6), today=today)
    outlook = [{'date': day.isoformat(), **values[day]} for day in sorted(values)]
    _cache[key] = (time.monotonic(), outlook)
    return outlook
