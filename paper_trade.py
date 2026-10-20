"""
Live paper-trading runner for the scalper strategy (5-minute bars, PDH/PDL
confluence with tight R:R and a 4-hour hard time-stop) across multiple
symbols: BTCUSDT, ETHUSDT, XRPUSDT. Each symbol runs completely
independently - its own data, own pivot/signal state, own $100 equity
pool, own trade log - so one symbol's performance never affects another's.

XRPUSDT needs its own tick size (0.0001, vs BTC/ETH's 0.01) - see
scalper_engine.TICK_SIZES and its comment for why this matters (using the
wrong tick size for XRP produced a fake "account blown up" backtest result
that was actually a units bug, not a real finding).

Meant to run on a schedule (.github/workflows/paper_trade.yml) with no
human present. Each run, per symbol:
  1. Appends newly-closed 5m bars from Binance's free public API.
  2. Recomputes indicators and walks forward over bars closed since the
     last run using scalper_engine.step_bar - the SAME function used for
     backtesting.
  3. Appends any closed trades.
Then writes one STATUS.md covering all symbols.

On a symbol's very first run (no {symbol}_state.json yet), this replays
its full available history once to build up pivot/signal state, THEN
resets equity and the trade log to a clean $100 - the backtest-replay's
equity growth is archived for reference, never shown as the "live"
balance (lesson learned on the swing bot's first deployment).

This is a SIMULATOR ONLY. No real orders, no exchange account, no API keys.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

import scalper_engine as se
from fetch_data import SYMBOLS, update_dataset

DATA_DIR = "data"
STATUS_FILE = "STATUS.md"

STEP_KWARGS = dict(score_threshold=se.SCORE_THRESHOLD, rr1=se.RR1, rr2=se.RR2, tp2_enabled=se.TP2_ENABLED,
                    use_htf_filter=True, enable_breakout_protection=True, max_hold_bars=se.MAX_HOLD_BARS)


def sym_path(symbol: str, name: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol.lower()}_{name}")


def load_state(symbol: str):
    path = sym_path(symbol, "state.json")
    if os.path.exists(path):
        with open(path) as f:
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


def save_state(symbol: str, state, last_processed_index, live_since):
    position = dict(state["position"]) if state["position"] is not None else None
    if position is not None:
        position["entry_time"] = pd.Timestamp(position["entry_time"]).isoformat()
    raw = dict(
        pivot_high_vals=state["pivot_high_vals"], pivot_high_bars=state["pivot_high_bars"],
        pivot_low_vals=state["pivot_low_vals"], pivot_low_bars=state["pivot_low_bars"],
        sell_fired=state["sell_fired"], buy_fired=state["buy_fired"], equity=state["equity"],
        position=position, last_processed_index=last_processed_index, live_since=live_since,
        engine="scalper-pdh-pdl-5m", symbol=symbol, tick_size=se.TICK_SIZES[symbol],
        qty_pct_of_equity=se.QTY_PCT_OF_EQUITY, **STEP_KWARGS,
    )
    with open(sym_path(symbol, "state.json"), "w") as f:
        json.dump(raw, f, indent=2, default=str)


def append_trades(symbol: str, new_trades, name="trades.csv"):
    if not new_trades:
        return
    path = sym_path(symbol, name)
    tdf = pd.DataFrame(new_trades)
    header = not os.path.exists(path)
    tdf.to_csv(path, mode="a", header=header, index=False)


def process_symbol(symbol: str):
    se.MINTICK = se.TICK_SIZES[symbol]
    df_raw = update_dataset(symbol)
    df = se.compute_indicators(df_raw.copy())
    arr = se.prepare_arrays(df)

    state, last_processed_index, live_since = load_state(symbol)
    is_first_run = live_since is None

    now = datetime.now(timezone.utc)
    new_trades, signals = [], []
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
        print(f"{symbol}: first run - replayed full history ({len(new_trades)} backtest trades), "
              f"archiving and resetting live balance to $100...", file=sys.stderr)
        append_trades(symbol, new_trades, name="trades_backtest_reference.csv")
        state["equity"] = se.INITIAL_CAPITAL
        new_trades = []
        live_since = str(df["open_time"].iloc[processed_upto]) if processed_upto >= 0 else None
    else:
        append_trades(symbol, new_trades)

    save_state(symbol, state, processed_upto, live_since)
    last_bar_time = df["open_time"].iloc[processed_upto] if processed_upto >= 0 else "none yet"
    print(f"{symbol}: processed through bar index {processed_upto} ({last_bar_time}); "
          f"{len(new_trades)} trade(s) closed this run; equity={state['equity']:.2f}; "
          f"position={'flat' if state['position'] is None else state['position']['side']}", file=sys.stderr)
    for s in signals[-5:]:
        print(f"{symbol} SIGNAL: {s}", file=sys.stderr)

    return dict(symbol=symbol, state=state, last_bar_time=last_bar_time, signals=signals)


def write_status(results: list):
    lines = ["# Multi-Symbol Scalper — Live Paper Trading (5m PDH/PDL confluence, time-capped)\n"]
    lines.append(f"_Simulator only. No real money, no exchange account, no API keys. Each symbol below runs "
                 f"completely independently - its own $100 equity pool, own trade log. 5-minute bars, tight "
                 f"{se.RR1}R/{se.RR2}R partials, hard {se.MAX_HOLD_BARS}-bar ({se.MAX_HOLD_BARS*5} min) time-stop, "
                 f"{se.QTY_PCT_OF_EQUITY*100:.0f}% position sizing. See README. "
                 f"Last updated: {datetime.now(timezone.utc).isoformat()}_\n")

    for r in results:
        symbol, state, last_bar_time, signals = r["symbol"], r["state"], r["last_bar_time"], r["signals"]
        lines.append(f"## {symbol}\n")
        lines.append(f"- Equity: **{state['equity']:.2f} USDT** (started at {se.INITIAL_CAPITAL:.2f})")
        lines.append(f"- Last processed bar: {last_bar_time}")
        pos = state["position"]
        if pos is None:
            lines.append("- Position: **flat**")
        else:
            lines.append(f"- Position: **{pos['side'].upper()}** {pos['qty_remaining']:.6f} @ {pos['entry_px']:.5f} "
                          f"(SL {pos['sl']:.5f}, TP1 {pos['tp1']:.5f}, TP2 {pos['tp2']:.5f}, TP1 filled: {pos['tp1_filled']})")
        if signals:
            shown = signals[-5:]
            prefix = f"(showing last 5 of {len(signals)}) " if len(signals) > 5 else ""
            lines.append(f"- Signal(s) this run: {prefix}{shown}")

        trades_path = sym_path(symbol, "trades.csv")
        all_trades = pd.read_csv(trades_path, parse_dates=["entry_time", "exit_time"]) if os.path.exists(trades_path) else pd.DataFrame()
        if len(all_trades):
            wins = all_trades[all_trades["pnl"] > 0]
            gross_loss = -all_trades[all_trades["pnl"] <= 0]["pnl"].sum()
            pf = wins["pnl"].sum() / gross_loss if gross_loss > 0 else float("inf")
            years = max((all_trades["exit_time"].max() - all_trades["entry_time"].min()).days / 365.25, 0.01)
            cagr = ((state["equity"] / se.INITIAL_CAPITAL) ** (1 / years) - 1) * 100
            eq_curve = se.INITIAL_CAPITAL + all_trades.sort_values("exit_time")["pnl"].cumsum()
            max_dd = ((eq_curve - eq_curve.cummax()) / eq_curve.cummax()).min() * 100
            lines.append(f"\n**Live stats**: {len(all_trades)} trades, {len(wins)/len(all_trades)*100:.2f}% win rate, "
                         f"PF {pf:.3f}, CAGR {cagr:.2f}%/yr, max DD {max_dd:.2f}%\n")
            lines.append("| Entry time | Side | Exit reason | Entry | Exit | Bars held | PnL |")
            lines.append("|---|---|---|---|---|---|---|")
            for _, t in all_trades.tail(5).iloc[::-1].iterrows():
                lines.append(f"| {t['entry_time']} | {t['side']} | {t['reason']} | {t['entry_px']:.5f} | "
                             f"{t['exit_px']:.5f} | {t['bars_held']:.0f} | {t['pnl']:.2f} |")
        else:
            lines.append("\n**Live stats**: no trades yet since deployment - equity is exactly the $100 starting balance.")
        lines.append("")

    with open(STATUS_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    results = [process_symbol(symbol) for symbol in SYMBOLS]
    write_status(results)


if __name__ == "__main__":
    main()
