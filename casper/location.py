"""Safe local-region detection for Bekki.

Resolution order:
1. Explicit environment configuration.
2. Windows Home Location and time-zone settings.
3. Unknown-safe fallback.

This module does not use IP geolocation or transmit location data.
"""

import json
import os
import subprocess
from functools import lru_cache


EMERGENCY_NUMBERS = {
    "US": "911",
    "CA": "911",
    "GB": "999 or 112",
    "AU": "000",
    "NZ": "111",
    "CN": "120",
    "JP": "119",
    "KR": "119",
    "IN": "112",
}


def _environment_location():
    location_name = os.getenv("USER_LOCATION", "").strip()
    country_code = os.getenv("USER_COUNTRY_CODE", "").upper().strip()
    emergency_number = os.getenv("EMERGENCY_NUMBER", "").strip()

    if not any((location_name, country_code, emergency_number)):
        return None

    if not emergency_number and country_code:
        emergency_number = EMERGENCY_NUMBERS.get(country_code, "")

    return {
        "location_name": location_name or "Unknown city",
        "country_code": country_code,
        "country_name": "",
        "time_zone": "",
        "emergency_number": emergency_number,
        "source": "user_configuration",
        "confidence": "high",
    }


def _run_powershell(script):
    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        creationflags=creation_flags,
    )
    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    if not output:
        return None

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def _windows_location():
    if os.name != "nt":
        return None

    script = r"""
$ErrorActionPreference = 'Stop'
$geo = Get-ItemProperty -Path 'HKCU:\Control Panel\International\Geo'
$code = [string]$geo.Name
if ([string]::IsNullOrWhiteSpace($code)) {
    $code = [System.Globalization.RegionInfo]::CurrentRegion.TwoLetterISORegionName
}
$region = [System.Globalization.RegionInfo]::new($code)
$zone = (Get-TimeZone).Id
[PSCustomObject]@{
    country_code = $region.TwoLetterISORegionName
    country_name = $region.EnglishName
    time_zone = $zone
} | ConvertTo-Json -Compress
"""
    detected = _run_powershell(script)
    if not isinstance(detected, dict):
        return None

    country_code = str(detected.get("country_code", "")).upper().strip()
    country_name = str(detected.get("country_name", "")).strip()
    time_zone = str(detected.get("time_zone", "")).strip()

    if not country_code:
        return None

    return {
        "location_name": country_name or country_code,
        "country_code": country_code,
        "country_name": country_name,
        "time_zone": time_zone,
        "emergency_number": EMERGENCY_NUMBERS.get(country_code, ""),
        "source": "windows_home_location",
        "confidence": "medium",
    }


@lru_cache(maxsize=1)
def detect_location():
    """Return the best local region available without network access."""

    configured = _environment_location()
    if configured is not None:
        return configured

    windows = _windows_location()
    if windows is not None:
        return windows

    return {
        "location_name": "Unknown",
        "country_code": "",
        "country_name": "",
        "time_zone": "",
        "emergency_number": "",
        "source": "unknown",
        "confidence": "unknown",
    }


def get_localization_context():
    """Return prompt context with conservative emergency-number rules."""

    detected = detect_location()
    emergency_number = detected.get("emergency_number", "")

    lines = [
        "The user's language does not determine their physical location.",
        "Never infer a country merely because the user writes in Chinese, "
        "English, or another language.",
        "Detected location/region: " + detected.get("location_name", "Unknown"),
        "Country code: " + (detected.get("country_code") or "UNKNOWN"),
        "Time zone: " + (detected.get("time_zone") or "UNKNOWN"),
        "Location source: " + detected.get("source", "unknown"),
        "Location confidence: " + detected.get("confidence", "unknown"),
    ]

    if emergency_number:
        lines.extend(
            [
                "Local emergency number: " + emergency_number,
                "Use this number when urgent or emergency help is warranted.",
            ]
        )
    else:
        lines.extend(
            [
                "Local emergency number: UNKNOWN",
                "Say 'call your local emergency number now'; do not guess a "
                "number. Ask the user's country if a specific number is needed.",
            ]
        )

    if detected.get("source") == "windows_home_location":
        lines.append(
            "Windows Home Location identifies a country/region, not a precise "
            "city or live GPS position. Do not invent a city from it."
        )

    return "\n".join(lines)