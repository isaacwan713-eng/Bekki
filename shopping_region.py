"""Country-level shopping region detection for Bekki.

The public IP itself is never returned, logged, or stored. Only coarse country,
currency, and time-zone context is exposed to the shopping-site selector.
"""

import json
import os
import subprocess
from functools import lru_cache

import requests


def _configured_region():
    code = os.getenv("SHOPPING_COUNTRY_CODE", "").upper().strip()
    name = os.getenv("SHOPPING_COUNTRY", "").strip()
    currency = os.getenv("SHOPPING_CURRENCY", "").upper().strip()
    if not any((code, name, currency)):
        return None
    return {
        "country_code": code,
        "country_name": name,
        "currency": currency,
        "time_zone": "",
        "source": "user_configuration",
        "confidence": "high",
    }


def _ip_region():
    try:
        response = requests.get("https://ipwho.is/", timeout=6)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict) or data.get("success") is False:
        return None
    code = str(data.get("country_code", "")).upper().strip()
    if not code:
        return None
    currency_data = data.get("currency", {})
    timezone_data = data.get("timezone", {})
    return {
        "country_code": code,
        "country_name": str(data.get("country", "")).strip(),
        "currency": (
            str(currency_data.get("code", "")).upper().strip()
            if isinstance(currency_data, dict)
            else ""
        ),
        "time_zone": (
            str(timezone_data.get("id", "")).strip()
            if isinstance(timezone_data, dict)
            else ""
        ),
        "source": "ip_country",
        "confidence": "medium",
    }


def _windows_region():
    if os.name != "nt":
        return None
    script = r"""
$ErrorActionPreference = 'Stop'
$region = [System.Globalization.RegionInfo]::CurrentRegion
[PSCustomObject]@{
  country_code = $region.TwoLetterISORegionName
  country_name = $region.EnglishName
  currency = $region.ISOCurrencySymbol
  time_zone = (Get-TimeZone).Id
} | ConvertTo-Json -Compress
"""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(completed.stdout.strip()) if completed.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("country_code"):
        return None
    return {
        "country_code": str(data.get("country_code", "")).upper().strip(),
        "country_name": str(data.get("country_name", "")).strip(),
        "currency": str(data.get("currency", "")).upper().strip(),
        "time_zone": str(data.get("time_zone", "")).strip(),
        "source": "windows_region",
        "confidence": "low",
    }


@lru_cache(maxsize=1)
def detect_shopping_region():
    return (
        _configured_region()
        or _ip_region()
        or _windows_region()
        or {
            "country_code": "",
            "country_name": "Unknown",
            "currency": "",
            "time_zone": "",
            "source": "unknown",
            "confidence": "unknown",
        }
    )

