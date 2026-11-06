"""
Lightweight, keyless news/sentiment signal combining:
  - Crypto-specific headlines from free RSS feeds (CoinDesk, CoinTelegraph),
    scored with a simple bullish/bearish keyword count - no paid API, no
    NLP model, deterministic and auditable. (CryptoPanic's API - which has
    built-in community sentiment votes - now requires a paid plan, so this
    uses free RSS instead; see README.)
  - GDELT's free global news "tone" (no signup) for broad geopolitical/macro
    "global incidents" (wars, crises, policy shocks) that move risk
    sentiment but might not mention crypto directly.

Combined into one score in roughly [-1, +1] (negative = bad for the market,
positive = good), cached locally and only refreshed every REFRESH_MINUTES to
avoid hammering free endpoints on every bot run.

Deliberately NOT backtested against historical headlines - no affordable
historical news archive with per-article timestamps exists - so this is a
forward-test-only feature. Its effect on trades is tracked separately (the
"trigger" column in trades.csv: "technical" vs "news") so results can be
judged honestly rather than blended into the validated technical track record.
"""
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

CACHE_FILE = "data/news_cache.json"
REFRESH_MINUTES = 10

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

BEARISH_WORDS = [
    "hack", "hacked", "exploit", "scam", "fraud", "ban", "banned", "crackdown",
    "lawsuit", "sues", "sec charges", "collapse", "crash", "plunge", "sell-off",
    "selloff", "liquidat", "bankrupt", "insolven", "default", "recession",
    "war", "invasion", "sanctions", "shutdown", "outage", "delist",
]
BULLISH_WORDS = [
    "approval", "approved", "etf approval", "rally", "surge", "soar", "adoption",
    "institutional", "all-time high", "record high", "breakout", "upgrade",
    "partnership", "integration", "bullish", "inflow", "accumulat",
]

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = '(war OR conflict OR crisis OR "interest rate" OR inflation OR recession OR sanctions OR "central bank")'


def _fetch_rss(url: str) -> list:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "news-sentiment-bot/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        titles = [el.text or "" for el in root.iter("title")]
        return titles[1:] if len(titles) > 1 else titles  # first <title> is usually the feed's own name
    except Exception:
        return []


def _score_headlines(headlines: list) -> float:
    if not headlines:
        return 0.0
    bear = bull = 0
    for h in headlines:
        hl = h.lower()
        bear += sum(1 for w in BEARISH_WORDS if w in hl)
        bull += sum(1 for w in BULLISH_WORDS if w in hl)
    total = bear + bull
    if total == 0:
        return 0.0
    confidence = min(total / 5, 1.0)  # a lone keyword hit shouldn't swing the score to an extreme
    return max(-1.0, min(1.0, (bull - bear) / total * confidence))


def _fetch_gdelt_tone() -> float:
    try:
        params = dict(query=GDELT_QUERY, mode="timelinetone", format="json", timespan="6h")
        resp = requests.get(GDELT_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        series = data.get("timeline", [{}])[0].get("data", [])
        if not series:
            return 0.0
        latest_tone = series[-1].get("value", 0.0)
        return max(-1.0, min(1.0, latest_tone / 10.0))
    except Exception:
        return 0.0


def compute_news_score(cache_file: str = CACHE_FILE, refresh_minutes: int = REFRESH_MINUTES) -> dict:
    now = datetime.now(timezone.utc)
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            cached_at = datetime.fromisoformat(cached["computed_at"])
            if (now - cached_at).total_seconds() < refresh_minutes * 60:
                return cached
        except Exception:
            pass

    headlines = []
    for url in RSS_FEEDS:
        headlines.extend(_fetch_rss(url))
    rss_score = _score_headlines(headlines)
    gdelt_score = _fetch_gdelt_tone()
    combined = max(-1.0, min(1.0, 0.6 * rss_score + 0.4 * gdelt_score))

    result = dict(computed_at=now.isoformat(), rss_score=round(rss_score, 3),
                   gdelt_score=round(gdelt_score, 3), combined=round(combined, 3),
                   headline_count=len(headlines))
    try:
        os.makedirs(os.path.dirname(cache_file) or ".", exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(result, f, indent=2)
    except Exception:
        pass
    return result
