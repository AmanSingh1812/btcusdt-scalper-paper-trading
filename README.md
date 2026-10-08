# BTCUSDT Scalper — Live Paper Trading

A free, fully automated **paper-trading simulator** for a fast, time-capped
scalping strategy on BTCUSDT, 5-minute bars. Runs entirely on GitHub
Actions — no server, no laptop, no exchange account, and **no real money
at any point**. Sibling project to [`../swing trading/paper-trading-bot`](../swing%20trading/paper-trading-bot),
which trades a slower PDH/PDL reversal strategy on 15-minute bars with no
hold-time limit.

See [`STATUS.md`](STATUS.md) for current position, equity, and recent
trades — rewritten every run.

## What makes this a scalper, not a copy of the swing bot with faster bars

- **5-minute bars** instead of 15-minute.
- **Tight R:R** (1.5R / 2.5R partials) instead of the swing bot's 2R/4R.
- **A hard time-stop** (`MAX_HOLD_BARS` = 48 bars = 4 hours) — the swing
  bot has no such cap and has been observed holding a position for 2+
  days live; a strategy that can do that is not a scalper. If neither the
  take-profit nor the stop is hit within 4 hours, the position is closed
  at market.
- Smaller near-zone (0.2% of level vs 0.4%), matching tighter 5m price action.

**Honest limitation, same as the swing bot**: this runs on a best-effort
GitHub Actions schedule (minutes to hours between runs), not a live tick
feed. A script that only reacts whenever it happens to run cannot be a
true tick-level scalper. What this actually is, is a fast mean-reversion/
confluence system evaluated on 5-minute bars with short, bounded holds —
"scalper" describes the strategy's character (tight targets, capped
duration, high trade frequency), not a claim about execution latency.

## v1 failed, and why - a from-scratch oscillator scalper had no edge

The first design was a vanilla mean-reversion scalper: fade price when
it's stretched beyond a Bollinger Band with RSI/Stochastic at an extreme,
confirmed by volume and a rejection candle. Tested exhaustively - 24
combinations of stop distance, R:R, and score threshold (`sweep.py`) -
and **every single one lost money** (best profit factor 0.59, most far
worse), with win rate rising only as stops widened (the classic sign of
"no real edge, just absorbing noise with more room," not genuine
predictive power). Reversing the signal direction entirely (momentum
continuation instead of fade, `test_reversed.py`) also lost, similarly,
in both directions. Conclusion: naive RSI/Bollinger/Stochastic combos
have no exploitable edge on 5m BTCUSDT - an extremely liquid,
heavily-arbitraged, 24/7 algorithmically-traded market where such textbook
signals are well known to get arbitraged away.

## v2 (deployed): adapt an already-validated signal instead of guessing again

Rather than keep searching for a new signal from scratch, v2 adapts the
swing bot's PDH/PDL confluence-reversal signal — which has real, validated
multi-year edge (CAGR 8-16%/yr, PF 1.4-1.9 over 9 years on 15m bars) — onto
the faster timeframe with scalping-appropriate exits (above). Same core
confluence score (candlestick pattern, chart pattern via pivots, volume,
market structure, momentum), same HTF trend filter and breakout
protection, same PDH/PDL concept.

**Backtest, full available history (2017-08 to present, 9.1 years),
`backtest.py` / `sweep.py`-style direct sizing tests:**

| Position size | Trades | Win rate | PF | CAGR | Max DD |
|---|---|---|---|---|---|
| 15% | 1362 | 71.07% | 2.965 | 3.90%/yr | -0.94% |
| 30% | 1362 | 71.07% | 2.926 | 7.93%/yr | -1.88% |
| **50% (deployed)** | **1362** | **71.07%** | **2.874** | **13.52%/yr** | **-3.13%** |
| 75% | 1362 | 71.07% | 2.808 | 20.87%/yr | -4.67% |
| 100% | 1362 | 71.07% | 2.742 | 28.64%/yr | -6.21% |

50% sizing was chosen because it clears the swing bot's own 12%/year
target (13.52%/yr) at roughly **5x less drawdown** (-3.13% vs the swing
bot's -15.82% at 60% sizing). Every single calendar year 2017-2026 was
profitable at every sizing level tested (year PF ranged 1.36-4.70) -
including 2018's crypto winter and 2022's bear market, the exact regimes
that hurt the swing bot's ML-filter investigation. This is a meaningfully
more consistent, lower-drawdown record than the swing bot's own, likely
because: (1) smaller R:R targets are easier to hit, raising win rate from
the swing bot's ~45-58% to ~71%, and (2) the hard time-stop caps the
worst-case loss duration/magnitude that an unlimited hold exposes you to.

A real bug was caught and fixed during this build: the fired-flag
one-shot suppression (prevents spamming re-entries while price sits at a
level) never actually reset — `arr["near_pdh"][i] is False` can never be
`True` for a numpy bool via Python's `is` operator, and the new-day reset
was missing entirely. This silently limited the whole backtest to at most
one trade per side, ever (caught when a 2-year run produced only 3
trades). Fixed by properly tracking `new_day` and comparing booleans
without `is`.

## How it works

- `paper_trade.py` runs on a GitHub Actions schedule (`.github/workflows/paper_trade.yml`).
- Each run pulls newly-closed 5m BTCUSDT candles from Binance's free
  public market-data API (`data-api.binance.vision` - the geo-unrestricted
  mirror; `api.binance.com` returns HTTP 451 from GitHub's US-hosted runners).
- Recomputes indicators and replays `scalper_engine.step_bar` - the SAME
  function used for backtesting - over bars closed since the last run.
- **On the very first run**, this replays the entire available history
  once to build up pivot/signal state, THEN immediately archives that
  replay's trades to `data/trades_backtest_reference.csv` and resets
  equity/the live trade log to a clean $100 - applying a lesson learned
  the hard way on the swing bot (whose first deployment showed its
  backtest-replay equity as if it were the live balance, and needed a
  separate reset afterward). Here it's done correctly from the start.

## Running it yourself

```bash
pip install -r requirements.txt
python fetch_data.py        # full history, or pass years-back e.g. `python fetch_data.py 2`
python backtest.py          # full-history backtest report
python paper_trade.py       # one live-trading cycle
```

No API keys or secrets needed anywhere in this repo.

## Disclaimer

This is a research/educational simulator. Past and simulated performance
is not indicative of future results. Nothing here is financial advice.
The 50% position sizing chosen here is aggressive by conventional risk
management standards - it is not a recommendation for real capital.
