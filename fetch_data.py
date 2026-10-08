"""
Fetch BTCUSDT 5-minute klines from Binance's free, geo-unrestricted
market-data mirror (same endpoint the swing bot uses - api.binance.com
returns HTTP 451 from US-hosted infra like GitHub Actions runners).
"""
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
BASE_URL = "https://data-api.binance.vision/api/v3/klines"
EARLIEST_AVAILABLE = datetime(2017, 8, 17, tzinfo=timezone.utc)
PARQUET_FILE = "data/btcusdt_5m.parquet"

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_asset_volume", "num_trades", "taker_buy_base", "taker_buy_quote", "ignore",
]


def fetch_klines(start_ms: int, end_ms: int) -> list:
    rows = []
    cur = start_ms
    limit = 1000
    while cur < end_ms:
        params = {"symbol": SYMBOL, "interval": INTERVAL, "startTime": cur, "endTime": end_ms, "limit": limit}
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        rows.extend(data)
        cur = data[-1][0] + 1
        if len(data) < limit:
            break
        time.sleep(0.15)
    return rows


def update_dataset(years_back=None) -> pd.DataFrame:
    import os
    os.makedirs("data", exist_ok=True)
    if os.path.exists(PARQUET_FILE):
        df = pd.read_parquet(PARQUET_FILE)
        start_ms = int(df["open_time"].max().timestamp() * 1000) + 1
    else:
        df = pd.DataFrame(columns=["open_time", "close_time", "open", "high", "low", "close", "volume"])
        start_dt = EARLIEST_AVAILABLE if years_back is None else max(
            EARLIEST_AVAILABLE, datetime.now(timezone.utc) - pd.Timedelta(days=365 * years_back))
        start_ms = int(start_dt.timestamp() * 1000)

    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = fetch_klines(start_ms, end_ms)
    if rows:
        new = pd.DataFrame(rows, columns=COLUMNS)
        new["open_time"] = pd.to_datetime(new["open_time"], unit="ms", utc=True)
        new["close_time"] = pd.to_datetime(new["close_time"], unit="ms", utc=True)
        for c in ["open", "high", "low", "close", "volume"]:
            new[c] = new[c].astype(float)
        new = new[["open_time", "close_time", "open", "high", "low", "close", "volume"]]
        df = pd.concat([df, new], ignore_index=True)
        # defensive: concatenating datetime64 columns of differing unit precision
        # (e.g. existing parquet at [us] vs freshly-parsed [ns]) can silently
        # degrade the result to dtype=object - force back to a real datetime64
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
        df = df.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)
        df.to_parquet(PARQUET_FILE, index=False)
        print(f"Fetched {len(new)} new bar(s); dataset now {len(df)} bars, {df['open_time'].min()} to {df['open_time'].max()}", file=sys.stderr)
    else:
        print("No new closed bars available.", file=sys.stderr)
    return df


if __name__ == "__main__":
    years_back = float(sys.argv[1]) if len(sys.argv) > 1 else None
    update_dataset(years_back)
