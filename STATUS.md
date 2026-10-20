# BTCUSDT Scalper — Live Paper Trading (5m PDH/PDL confluence, time-capped)

_Simulator only. No real money, no exchange account, no API keys. 5-minute bars, tight 1.5R/2.5R partials, hard 48-bar (240 min) time-stop, 100% position sizing - see README for the full v1-failed/v2-fixed backtest story. Last updated: 2026-10-20T00:46:03.068334+00:00_

## Current State

- Equity: **99.89 USDT** (started at 100.00)
- Last processed bar: 2026-10-20 00:40:00+00:00
- Position: **flat**

## Genuine Live Stats (since deployment)

- Total trades: 6
- Win rate: 50.00%
- Total PnL: -0.11 USDT (-0.11%)
- Profit factor: 0.745
- CAGR: -4.79%/year
- Max drawdown: -0.28%

## Most Recent Trades

| Entry time | Side | Exit reason | Entry | Exit | Bars held | PnL |
|---|---|---|---|---|---|---|
| 2026-10-19 15:30:00 | short | TIME | 82214.48 | 81952.01 | 48 | 0.24 |
| 2026-10-18 22:00:00 | short | SL | 81601.99 | 81705.34 | 9 | -0.21 |
| 2026-10-18 01:05:00 | short | SL | 81570.46 | 81621.37 | 3 | -0.07 |
| 2026-10-16 01:15:00 | short | TP2 | 82370.55 | 82130.87 | 7 | 0.05 |
| 2026-10-16 01:15:00 | short | TP1 | 82370.55 | 82226.75 | 2 | 0.02 |
| 2026-10-11 03:10:00 | short | SL | 82976.76 | 83150.68 | 43 | -0.14 |

## Backtest reference (not live balance)

Full 9-year backtest at 100% sizing: 1362 trades, 71.07% win rate, PF 2.965, CAGR 3.90-28.64%/yr depending on sizing, max DD -0.94% to -6.21%. See README for the full sizing table and the v1 (failed) vs v2 (fixed) investigation. The deployment starts clean at $100 - this backtest record is not replayed into the live balance.
