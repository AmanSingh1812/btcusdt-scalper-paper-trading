"""
Live paper-trading runner for the BTCUSDT scalper (5-minute bars, PDH/PDL
confluence with tight R:R and a 4-hour hard time-stop - see README and
scalper_engine.py for how this differs from the swing bot).

Meant to run on a schedule (.github/workflows/paper_trade.yml) with no
human present. Each run:
  1. Appends newly-closed 5m bars from Binance's free public API.
  2. Recomputes indicators and walks forward over bars closed since the
     last run using scalper_engine.step_bar - the SAME function used for
     backtesting.
  3. Appends any closed trades, rewrites STATUS.md.

On the very first run (no state.json), this replays the full available
history (2017-08 onward) once to build up pivot/signal state, THEN resets
equity and the trade log to a clean $100 - the backtest-replay's equity
growth is archived for reference, never shown as the "live" balance. This
applies a lesson learned the hard way on the swing bot (its first
deployment showed $146.93 as the live balance when that was actually
backtest-replay growth, and had to be reset after the fact).

This is a SIMULATOR ONLY. No real orders, no exchange account, no API keys.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

import scalper_engine as se
from fetch_data import update_dataset

DATA_DIR = "data"
STATE_FILE = os.path.join(DATA_DIR, "state.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")
BACKTEST_REFERENCE_FILE = os.path.join(DATA_DIR, "trades_backtest_reference.csv")
STATUS_FILE = "STATUS.md"

STEP_KWARGS = dict(score_threshold=se.SCORE_THRESHOLD, rr1=se.RR1, rr2=se.RR2, tp2_enabled=se.TP2_ENABLED,
                    use_htf_filter=True, enable_breakout_protection=True, max_hold_bars=se.MAX_HOLD_BARS)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            raw = json.load(f)
        position = raw["position"]
        if position is not None:
            position["entry_time"] = pd.Timestamp(position["entry_time"])
        return dict(
            pivot_high_vals=raw["pivot_high_vals"], pivot_high_bars=raw["pivot_high_bars"],
            pivot_low_vals=raw["pivot_low_vals"], pivot_low_bars=raw["pivot_low_bars"],
            sell_fired=raw["sell_fired"], buy_fired=raw["buy_fired"], equity=raw["equity"],
            position=position,
        ), raw["last_processed_index"], raw["live_since"]
    return se.new_state(), -1, None


def save_state(state, last_processed_index, live_since):
    position = dict(state["position"]) if state["position"] is not None else None
    if position is not None:
        position["entry_time"] = pd.Timestamp(position["entry_time"]).isoformat()
    raw = dict(
        pivot_high_vals=state["pivot_high_vals"], pivot_high_bars=state["pivot_high_bars"],
        pivot_low_vals=state["pivot_low_vals"], pivot_low_bars=state["pivot_low_bars"],
        sell_fired=state["sell_fired"], buy_fired=state["buy_fired"], equity=state["equity"],
        position=position, last_processed_index=last_processed_index, live_since=live_since,
        engine="scalper-pdh-pdl-5m", qty_pct_of_equity=se.QTY_PCT_OF_EQUITY, **STEP_KWARGS,
    )
    with open(STATE_FILE, "w") as f:
        json.dump(raw, f, indent=2, default=str)


def append_trades(new_trades, path=TRADES_FILE):
    if not new_trades:
        return
    tdf = pd.DataFrame(new_trades)
    header = not os.path.exists(path)
    tdf.to_csv(path, mode="a", header=header, index=False)


def write_status(state, last_bar_time, signals_this_run):
    all_trades = pd.read_csv(TRADES_FILE, parse_dates=["entry_time", "exit_time"]) if os.path.exists(TRADES_FILE) else pd.DataFrame()
    lines = []
    lines.append("# BTCUSDT Scalper — Live Paper Trading (5m PDH/PDL confluence, time-capped)\n")
    lines.append(f"_Simulator only. No real money, no exchange account, no API keys. 5-minute bars, "
                 f"tight {se.RR1}R/{se.RR2}R partials, hard {se.MAX_HOLD_BARS}-bar ({se.MAX_HOLD_BARS*5} min) "
                 f"time-stop, {se.QTY_PCT_OF_EQUITY*100:.0f}% position sizing - see README for the full "
                 f"v1-failed/v2-fixed backtest story. Last updated: {datetime.now(timezone.utc).isoformat()}_\n")
    lines.append("## Current State\n")
    lines.append(f"- Equity: **{state['equity']:.2f} USDT** (started at {se.INITIAL_CAPITAL:.2f})")
    lines.append(f"- Last processed bar: {last_bar_time}")
    pos = state["position"]
    if pos is None:
        lines.append("- Position: **flat**")
    else:
        lines.append(f"- Position: **{pos['side'].upper()}** {pos['qty_remaining']:.6f} BTC @ {pos['entry_px']:.2f} "
                      f"(SL {pos['sl']:.2f}, TP1 {pos['tp1']:.2f}, TP2 {pos['tp2']:.2f}, TP1 filled: {pos['tp1_filled']})")
    if signals_this_run:
        shown = signals_this_run[-10:]
        prefix = f"(showing last 10 of {len(signals_this_run)}) " if len(signals_this_run) > 10 else ""
        lines.append(f"- Signal(s) this run: {prefix}{shown}")
    lines.append("")

    if len(all_trades):
        wins = all_trades[all_trades["pnl"] > 0]
        gross_loss = -all_trades[all_trades["pnl"] <= 0]["pnl"].sum()
        pf = wins["pnl"].sum() / gross_loss if gross_loss > 0 else float("inf")
        years = max((all_trades["exit_time"].max() - all_trades["entry_time"].min()).days / 365.25, 0.01)
        cagr = ((state["equity"] / se.INITIAL_CAPITAL) ** (1 / years) - 1) * 100
        eq_curve = se.INITIAL_CAPITAL + all_trades.sort_values("exit_time")["pnl"].cumsum()
        max_dd = ((eq_curve - eq_curve.cummax()) / eq_curve.cummax()).min() * 100
        lines.append("## Genuine Live Stats (since deployment)\n")
        lines.append(f"- Total trades: {len(all_trades)}")
        lines.append(f"- Win rate: {len(wins)/len(all_trades)*100:.2f}%")
        lines.append(f"- Total PnL: {all_trades['pnl'].sum():.2f} USDT ({all_trades['pnl'].sum()/se.INITIAL_CAPITAL*100:.2f}%)")
        lines.append(f"- Profit factor: {pf:.3f}")
        lines.append(f"- CAGR: {cagr:.2f}%/year")
        lines.append(f"- Max drawdown: {max_dd:.2f}%\n")

        lines.append("## Most Recent Trades\n")
        lines.append("| Entry time | Side | Exit reason | Entry | Exit | Bars held | PnL |")
        lines.append("|---|---|---|---|---|---|---|")
        for _, t in all_trades.tail(15).iloc[::-1].iterrows():
            lines.append(f"| {t['entry_time']} | {t['side']} | {t['reason']} | {t['entry_px']:.2f} | "
                         f"{t['exit_px']:.2f} | {t['bars_held']:.0f} | {t['pnl']:.2f} |")
    else:
        lines.append("## Genuine Live Stats (since deployment)\n")
        lines.append("No trades yet since deployment - equity is exactly the $100 starting balance.\n")

    lines.append("\n## Backtest reference (not live balance)\n")
    lines.append(f"Full 9-year backtest at {se.QTY_PCT_OF_EQUITY*100:.0f}% sizing: 1362 trades, 71.07% win rate, "
                 f"PF 2.965, CAGR 3.90-28.64%/yr depending on sizing, max DD -0.94% to -6.21%. See README for the "
                 f"full sizing table and the v1 (failed) vs v2 (fixed) investigation. The deployment starts clean "
                 f"at $100 - this backtest record is not replayed into the live balance.")

    with open(STATUS_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    df_raw = update_dataset()
    df = se.compute_indicators(df_raw.copy())
    arr = se.prepare_arrays(df)

    state, last_processed_index, live_since = load_state()
    is_first_run = live_since is None

    now = datetime.now(timezone.utc)
    new_trades = []
    signals = []
    processed_upto = last_processed_index
    for i in range(last_processed_index + 1, arr["n"]):
        close_time = df["open_time"].iloc[i] + pd.Timedelta(minutes=5)
        if close_time.to_pydatetime() > now:
            break
        state, trades, signal_info = se.step_bar(i, arr, state, **STEP_KWARGS)
        new_trades.extend(trades)
        if signal_info["buy_signal"]:
            signals.append(f"BUY score {signal_info['buy_score']}/6 @ {arr['close'][i]:.2f} ({arr['open_time'][i]})")
        if signal_info["sell_signal"]:
            signals.append(f"SELL score {signal_info['sell_score']}/6 @ {arr['close'][i]:.2f} ({arr['open_time'][i]})")
        processed_upto = i

    if is_first_run:
        # Archive the full backtest-replay's trades for reference, then reset
        # to a clean $100 live balance - applying the lesson learned from the
        # swing bot (see module docstring) from the START, not as a later fix.
        print(f"First run: replayed full history ({len(new_trades)} backtest trades), "
              f"archiving and resetting live balance to $100...", file=sys.stderr)
        append_trades(new_trades, path=BACKTEST_REFERENCE_FILE)
        state["equity"] = se.INITIAL_CAPITAL
        new_trades = []
        live_since = str(df["open_time"].iloc[processed_upto]) if processed_upto >= 0 else None
    else:
        append_trades(new_trades)

    save_state(state, processed_upto, live_since)
    last_bar_time = df["open_time"].iloc[processed_upto] if processed_upto >= 0 else "none yet"
    write_status(state, last_bar_time, signals)

    print(f"Processed through bar index {processed_upto} ({last_bar_time}); "
          f"{len(new_trades)} trade(s) closed this run; equity={state['equity']:.2f}; "
          f"position={'flat' if state['position'] is None else state['position']['side']}", file=sys.stderr)
    for s in signals[-10:]:
        print(f"SIGNAL: {s}", file=sys.stderr)


if __name__ == "__main__":
    main()
