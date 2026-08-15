"""Bekki startup presence: local time, optional weather, and light mood."""

import os
import random
from datetime import datetime

import requests

import location


MOODS = {
    "bright": {
        "label": "元气满满",
        "emoji": "✨",
        "lines": [
            "今天的豆豆能量很足，随时可以开工～",
            "状态加载完成，今天也一起做点厉害的事吧！",
        ],
    },
    "gentle": {
        "label": "温柔陪伴",
        "emoji": "🩵",
        "lines": [
            "今天想慢慢陪你，把事情一件件处理好。",
            "不用着急，我会在这里陪你慢慢来～",
        ],
    },
    "curious": {
        "label": "好奇模式",
        "emoji": "🔍",
        "lines": [
            "今天有点好奇，会遇到什么新问题呢？",
            "我的探索雷达已经打开啦，想研究什么都可以！",
        ],
    },
    "cozy": {
        "label": "悠闲模式",
        "emoji": "🌙",
        "lines": [
            "今天适合舒服一点，有事就慢慢说给我听吧。",
            "先放松一下，剩下的我们一起想办法～",
        ],
    },
}

WEATHER_CODES = {
    0: "晴朗",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴天",
    45: "有雾",
    48: "有雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    61: "小雨",
    63: "下雨",
    65: "较强降雨",
    71: "小雪",
    73: "下雪",
    75: "较强降雪",
    80: "有阵雨",
    81: "有阵雨",
    82: "有强阵雨",
    95: "有雷暴",
}


def _time_period(hour):
    if 5 <= hour < 9:
        return "清晨", "早上好"
    if 9 <= hour < 12:
        return "上午", "上午好"
    if 12 <= hour < 14:
        return "中午", "中午好"
    if 14 <= hour < 18:
        return "下午", "下午好"
    if 18 <= hour < 23:
        return "晚上", "晚上好"
    return "深夜", "这么晚还没休息呀"


def _choose_mood(hour):
    if hour >= 23 or hour < 5:
        choices = ["cozy", "gentle", "cozy"]
    elif 5 <= hour < 12:
        choices = ["bright", "bright", "curious", "gentle"]
    else:
        choices = list(MOODS)

    mood_id = random.choice(choices)
    return mood_id, MOODS[mood_id]


def _configured_coordinates():
    latitude = os.getenv("WEATHER_LATITUDE", "").strip()
    longitude = os.getenv("WEATHER_LONGITUDE", "").strip()
    if not latitude or not longitude:
        return None

    try:
        return float(latitude), float(longitude)
    except ValueError:
        return None


def _geocode_configured_city(detected):
    if detected.get("source") != "user_configuration":
        return None

    query = detected.get("location_name", "").strip()
    if not query or query.lower() in {"unknown", "unknown city"}:
        return None

    try:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1, "language": "en"},
            timeout=4,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results:
            return None
        return float(results[0]["latitude"]), float(results[0]["longitude"])
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None


def get_current_weather():
    """Return optional weather data; failure never blocks Bekki startup."""

    detected = location.detect_location()
    coordinates = _configured_coordinates() or _geocode_configured_city(detected)
    if coordinates is None:
        return None

    configured_unit = os.getenv("WEATHER_UNIT", "").lower().strip()
    if configured_unit in {"fahrenheit", "f"}:
        temperature_unit = "fahrenheit"
        temperature_symbol = "°F"
    elif configured_unit in {"celsius", "c"}:
        temperature_unit = "celsius"
        temperature_symbol = "°C"
    elif detected.get("country_code") == "US":
        temperature_unit = "fahrenheit"
        temperature_symbol = "°F"
    else:
        temperature_unit = "celsius"
        temperature_symbol = "°C"

    latitude, longitude = coordinates
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
                "temperature_unit": temperature_unit,
                "timezone": "auto",
            },
            timeout=4,
        )
        response.raise_for_status()
        current = response.json().get("current", {})
        temperature = current.get("temperature_2m")
        code = int(current.get("weather_code"))
        if temperature is None:
            return None
        return {
            "temperature": round(float(temperature)),
            "temperature_symbol": temperature_symbol,
            "description": WEATHER_CODES.get(code, "天气状况未知"),
        }
    except (requests.RequestException, TypeError, ValueError):
        return None


def create_startup_greeting():
    now = datetime.now()
    period, salutation = _time_period(now.hour)
    mood_id, mood = _choose_mood(now.hour)
    weather = get_current_weather()

    lines = [
        "👋 " + salutation + "～我是 Bekki 🩵",
        "",
        "现在是当地" + period + "，今天是「" + mood["label"] + "」 " + mood["emoji"],
    ]

    if weather is not None:
        lines.append(
            "外面"
            + weather["description"]
            + "，大约 "
            + str(weather["temperature"])
            + weather["temperature_symbol"]
            + "。"
        )

    lines.extend(
        [
            random.choice(mood["lines"]),
            "",
            "我可以聊天、搜索、读文件、看图片和读取桌面。",
        ]
    )

    print("[PRESENCE]", mood_id, "weather=" + str(weather is not None))
    return "\n".join(lines)