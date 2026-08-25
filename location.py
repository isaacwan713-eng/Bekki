"""Cached local runtime profile for region, units, time zone, and search defaults."""

import ctypes
import json
import locale
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROFILE_SCHEMA_VERSION = 1
PROFILE_TTL = timedelta(days=7)

COUNTRY_NAMES = {
    "AU": "Australia",
    "CA": "Canada",
    "CN": "China",
    "DE": "Germany",
    "ES": "Spain",
    "FR": "France",
    "GB": "United Kingdom",
    "HK": "Hong Kong",
    "IE": "Ireland",
    "IN": "India",
    "IT": "Italy",
    "JP": "Japan",
    "KR": "South Korea",
    "MX": "Mexico",
    "NZ": "New Zealand",
    "SG": "Singapore",
    "TW": "Taiwan",
    "US": "United States",
}


def _runtime_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _profile_path():
    return _runtime_root() / "data" / "location.json"


def _now():
    return datetime.now().astimezone()


def _iso(value):
    return value.isoformat(timespec="seconds")


def _parse_time(value):
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _windows_country_code():
    if os.name != "nt":
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        geoid = int(kernel32.GetUserGeoID(16))
        if geoid <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(16)
        if kernel32.GetGeoInfoW(geoid, 4, buffer, len(buffer), 0) > 0:
            code = buffer.value.upper().strip()
            if len(code) == 2 and code.isalpha():
                return code
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return ""


def _locale_country_code():
    candidates = []
    try:
        candidates.append(locale.getlocale()[0])
    except (TypeError, ValueError):
        pass
    candidates.extend(
        os.getenv(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANG")
    )
    for value in candidates:
        text = str(value or "").replace("-", "_")
        parts = text.split("_", 1)
        if len(parts) == 2:
            code = parts[1].split(".", 1)[0].upper().strip()
            if len(code) == 2 and code.isalpha():
                return code
    return ""


def _system_time_zone():
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tzutil", "/g"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            value = str(result.stdout or "").strip()
            if value:
                return value[:120]
        except (OSError, subprocess.SubprocessError):
            pass
    zone = str(getattr(_now().tzinfo, "key", "") or "").strip()
    return (zone or str(_now().tzname() or "local"))[:120]


def _offset_text():
    offset = _now().utcoffset() or timedelta(0)
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _country_defaults(country_code):
    code = str(country_code or "").upper().strip()
    if code == "US":
        return {
            "unit_system": "US_CUSTOMARY",
            "distance_unit": "mile",
            "temperature_unit": "fahrenheit",
            "weight_unit": "pound",
            "volume_unit": "fluid_ounce",
            "currency": "USD",
            "preferred_search_engines": ["google", "bing"],
        }
    currencies = {
        "AU": "AUD", "CA": "CAD", "CN": "CNY", "GB": "GBP",
        "HK": "HKD", "IN": "INR", "JP": "JPY", "KR": "KRW",
        "MX": "MXN", "NZ": "NZD", "SG": "SGD", "TW": "TWD",
    }
    return {
        "unit_system": "METRIC",
        "distance_unit": "kilometer",
        "temperature_unit": "celsius",
        "weight_unit": "kilogram",
        "volume_unit": "liter",
        "currency": currencies.get(code, ""),
        "preferred_search_engines": ["google", "bing"],
    }


def _system_signature(country_code=None, time_zone=None):
    return "|".join(
        (
            str(country_code or "").upper().strip(),
            str(time_zone or "").strip(),
            _offset_text(),
        )
    )


def _read_profile():
    path = _profile_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_profile(profile):
    path = _profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    data = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _profile_is_fresh(profile, detected_country, detected_zone):
    if not isinstance(profile, dict):
        return False
    if profile.get("schema_version") != PROFILE_SCHEMA_VERSION:
        return False
    expires_at = _parse_time(profile.get("expires_at"))
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if _now() >= expires_at.astimezone():
        return False
    signature = _system_signature(detected_country, detected_zone)
    return str(profile.get("system_signature") or "") == signature


def _detect_profile():
    country_code = _windows_country_code() or _locale_country_code()
    time_zone = _system_time_zone()
    now = _now()
    profile = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "country_code": country_code,
        "country_name": COUNTRY_NAMES.get(country_code, country_code),
        "location_name": COUNTRY_NAMES.get(country_code, country_code),
        "time_zone": time_zone,
        "utc_offset": _offset_text(),
        **_country_defaults(country_code),
        "source": "windows_system_profile" if os.name == "nt" else "system_profile",
        "confidence": "high" if country_code and time_zone else "medium",
        "detected_at": _iso(now),
        "expires_at": _iso(now + PROFILE_TTL),
    }
    profile["system_signature"] = _system_signature(country_code, time_zone)
    return profile


def initialize_location_profile(force_refresh=False):
    detected_country = _windows_country_code() or _locale_country_code()
    detected_zone = _system_time_zone()
    cached = _read_profile()
    if not force_refresh and _profile_is_fresh(
        cached, detected_country, detected_zone
    ):
        return cached
    profile = _detect_profile()
    try:
        _write_profile(profile)
    except OSError as error:
        print("[BEKKI LOCATION CACHE WRITE SKIPPED]", repr(error))
    return profile


def detect_location(force_refresh=False):
    """Compatibility API used by Casper and shopping-region code."""
    return dict(initialize_location_profile(force_refresh=force_refresh))


def get_localization_context():
    profile = initialize_location_profile()
    compact = {
        key: profile.get(key)
        for key in (
            "country_code",
            "country_name",
            "location_name",
            "time_zone",
            "utc_offset",
            "unit_system",
            "distance_unit",
            "temperature_unit",
            "weight_unit",
            "volume_unit",
            "currency",
            "preferred_search_engines",
            "source",
            "confidence",
            "expires_at",
        )
    }
    return (
        "Cached runtime localization profile (explicit current user requests "
        "override these defaults for that turn):\n"
        + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )


def get_runtime_profile():
    return detect_location()

