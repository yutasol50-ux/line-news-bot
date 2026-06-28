#!/usr/bin/env python3
"""Open-Meteoで2地点（自宅=座間/職場=港区）の今日・明日の天気を取得。APIキー不要。"""
import requests

JST = "Asia/Tokyo"

LOCATIONS = [
    {"label": "自宅・座間", "lat": 35.4886, "lon": 139.4078},
    {"label": "職場・港区", "lat": 35.6581, "lon": 139.7516},
]

# WMO天気コード → (日本語, 絵文字)
WMO = {
    0: ("快晴", "☀️"), 1: ("晴れ", "🌤️"), 2: ("薄曇り", "⛅"), 3: ("曇り", "☁️"),
    45: ("霧", "🌫️"), 48: ("霧", "🌫️"),
    51: ("霧雨", "🌦️"), 53: ("霧雨", "🌦️"), 55: ("霧雨", "🌧️"),
    56: ("着氷性の霧雨", "🌧️"), 57: ("着氷性の霧雨", "🌧️"),
    61: ("小雨", "🌦️"), 63: ("雨", "🌧️"), 65: ("強い雨", "🌧️"),
    66: ("みぞれ", "🌧️"), 67: ("みぞれ", "🌧️"),
    71: ("小雪", "🌨️"), 73: ("雪", "🌨️"), 75: ("大雪", "❄️"), 77: ("細氷", "🌨️"),
    80: ("にわか雨", "🌦️"), 81: ("にわか雨", "🌧️"), 82: ("激しいにわか雨", "⛈️"),
    85: ("にわか雪", "🌨️"), 86: ("にわか雪", "❄️"),
    95: ("雷雨", "⛈️"), 96: ("雷雨(雹)", "⛈️"), 99: ("雷雨(雹)", "⛈️"),
}


def _describe(code: int) -> str:
    name, emoji = WMO.get(code, ("不明", "❔"))
    return f"{emoji}{name}"


def _fetch_one(loc: dict) -> dict | None:
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["lat"], "longitude": loc["lon"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": JST, "forecast_days": 2,
            },
            timeout=15,
        )
        resp.raise_for_status()
        d = resp.json()["daily"]
        return {
            "label": loc["label"],
            "code": d["weather_code"][0],
            "tmax": d["temperature_2m_max"][0],
            "tmin": d["temperature_2m_min"][0],
            "pop": d["precipitation_probability_max"][0],
            # 明日（使う場合用）
            "tomorrow_code": d["weather_code"][1],
            "tomorrow_pop": d["precipitation_probability_max"][1],
        }
    except Exception as e:
        print(f"[WARN] 天気取得失敗 {loc['label']}: {e}")
        return None


def get_weather_block() -> str | None:
    """整形済みの天気ブロック文字列を返す。全滅したらNone。"""
    results = [r for r in (_fetch_one(loc) for loc in LOCATIONS) if r]
    if not results:
        return None

    lines = ["☀️ 天気"]
    max_pop = 0
    for r in results:
        pop = r["pop"] if r["pop"] is not None else 0
        max_pop = max(max_pop, pop)
        lines.append(
            f"〔{r['label']}〕{_describe(r['code'])} "
            f"{r['tmax']:.0f}/{r['tmin']:.0f}℃ ☔{pop}%"
        )

    if max_pop >= 50:
        lines.append("傘、持ってった方がいいよ。")
    elif max_pop >= 30:
        lines.append("折りたたみ傘があると安心かも。")
    else:
        lines.append("傘はたぶん要らないよ。")
    return "\n".join(lines)


if __name__ == "__main__":
    print(get_weather_block() or "(天気取得失敗)")
