# BTCUSDT Scalper — Live Paper Trading (5m PDH/PDL confluence, time-capped)

_Simulator only. No real money, no exchange account, no API keys. 5-minute bars, tight 1.5R/2.5R partials, hard 48-bar (240 min) time-stop, 50% position sizing - see README for the full v1-failed/v2-fixed backtest story. Last updated: 2026-10-17T05:30:09.100485+00:00_

## Current State

- Equity: **99.93 USDT** (started at 100.00)
- Last processed bar: 2026-10-17 05:25:00+00:00
- Position: **flat**

## Genuine Live Stats (since deployment)

- Total trades: 3
- Win rate: 66.67%
- Total PnL: -0.07 USDT (-0.07%)
- Profit factor: 0.527
- CAGR: -6.07%/year
- Max drawdown: 0.00%

## Most Recent Trades

| Entry time | Side | Exit reason | Entry | Exit | Bars held | PnL |
|---|---|---|---|---|---|---|
| 2026-10-16 01:15:00 | short | TP2 | 82370.55 | 82130.87 | 7 | 0.05 |
| 2026-10-16 01:15:00 | short | TP1 | 82370.55 | 82226.75 | 2 | 0.02 |
| 2026-10-11 03:10:00 | short | SL | 82976.76 | 83150.68 | 43 | -0.14 |

## Backtest reference (not live balance)

Full 9-year backtest at 50% sizing: 1362 trades, 71.07% win rate, PF 2.965, CAGR 3.90-28.64%/yr depending on sizing, max DD -0.94% to -6.21%. See README for the full sizing table and the v1 (failed) vs v2 (fixed) investigation. The deployment starts clean at $100 - this backtest record is not replayed into the live balance.
