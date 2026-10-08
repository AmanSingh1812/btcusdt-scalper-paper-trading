"""Quick test: reverse the entry direction (momentum continuation instead
of mean-reversion fade) to check if the signal has the right setup but the
wrong direction, before redesigning further."""
import pandas as pd

import scalper_engine as se
from scalper_engine import MINTICK, SLIPPAGE_TICKS, COMMISSION_PCT


def step_bar_reversed(i, arr, state, score_threshold, sl_atr_mult, rr, max_hold_bars):
    trades = []
    position = state["position"]
    if position is not None:
        bo, bh, bl = arr["open"][i], arr["high"][i], arr["low"][i]
        side, sl, tp = position["side"], position["sl"], position["tp"]
        bars_held = i - position["entry_bar"]
        force_exit = bars_held >= max_hold_bars
        hit_sl, hit_tp = (bl <= sl, bh >= tp) if side == "long" else (bh >= sl, bl <= tp)
        exit_reason = exit_px = None
        if hit_sl or hit_tp:
            sl_first = (abs(bo - sl) < abs(bo - tp)) if (hit_sl and hit_tp) else hit_sl
            exit_reason = "SL" if sl_first else "TP"
            exit_px = (sl - MINTICK * SLIPPAGE_TICKS if side == "long" else sl + MINTICK * SLIPPAGE_TICKS) if sl_first else tp
        elif force_exit:
            exit_reason, exit_px = "TIME", arr["close"][i]
        if exit_reason:
            price_pnl = (exit_px - position["entry_px"]) * position["qty"] if side == "long" else (position["entry_px"] - exit_px) * position["qty"]
            exit_comm = exit_px * position["qty"] * COMMISSION_PCT
            pnl = price_pnl - exit_comm - position["entry_comm"]
            state["equity"] += price_pnl - exit_comm
            trades.append(dict(side=side, entry_time=position["entry_time"], exit_time=arr["open_time"][i],
                                reason=exit_reason, qty=position["qty"], entry_px=position["entry_px"],
                                exit_px=exit_px, bars_held=bars_held, pnl=pnl))
            state["position"] = None
            position = None

    if position is None:
        sell_score = (int(arr["touch_upper_bb"][i]) + int(arr["rsi"][i] >= 70) + int(arr["stoch_turn_down"][i])
                      + int(arr["vol_confirm"][i]) + int(arr["bear_rejection"][i]))
        buy_score = (int(arr["touch_lower_bb"][i]) + int(arr["rsi"][i] <= 30) + int(arr["stoch_turn_up"][i])
                     + int(arr["vol_confirm"][i]) + int(arr["bull_rejection"][i]))
        # REVERSED: a "sell setup" (extended high) now opens a LONG (momentum continuation up);
        # a "buy setup" (extended low) now opens a SHORT (momentum continuation down)
        sell_qualified = sell_score >= score_threshold and bool(arr["above_vwap"][i])
        buy_qualified = buy_score >= score_threshold and bool(arr["below_vwap"][i])
        atr_i = arr["atr"][i]
        if (sell_qualified or buy_qualified) and pd.notna(atr_i):
            entry_close = arr["close"][i]
            if sell_qualified:  # -> go LONG
                sl_price = entry_close - sl_atr_mult * atr_i
                risk = entry_close - sl_price
                tp_price = entry_close + risk * rr
                if risk > 0:
                    fill_px = entry_close + MINTICK * SLIPPAGE_TICKS
                    qty = (state["equity"] * se.QTY_PCT_OF_EQUITY) / fill_px
                    entry_comm = fill_px * qty * COMMISSION_PCT
                    state["position"] = dict(side="long", entry_time=arr["open_time"][i], entry_bar=i,
                                              entry_px=fill_px, qty=qty, sl=sl_price, tp=tp_price, entry_comm=entry_comm)
                    state["equity"] -= entry_comm
            elif buy_qualified:  # -> go SHORT
                sl_price = entry_close + sl_atr_mult * atr_i
                risk = sl_price - entry_close
                tp_price = entry_close - risk * rr
                if risk > 0:
                    fill_px = entry_close - MINTICK * SLIPPAGE_TICKS
                    qty = (state["equity"] * se.QTY_PCT_OF_EQUITY) / fill_px
                    entry_comm = fill_px * qty * COMMISSION_PCT
                    state["position"] = dict(side="short", entry_time=arr["open_time"][i], entry_bar=i,
                                              entry_px=fill_px, qty=qty, sl=sl_price, tp=tp_price, entry_comm=entry_comm)
                    state["equity"] -= entry_comm
    return state, trades, None


def run(df, **kwargs):
    arr = se.prepare_arrays(df)
    state = se.new_state()
    all_trades = []
    for i in range(arr["n"]):
        state, trades, _ = step_bar_reversed(i, arr, state, **kwargs)
        all_trades.extend(trades)
    return all_trades, state["equity"]


def metrics(trades, initial_capital):
    tdf = pd.DataFrame(trades)
    if len(tdf) < 20:
        return dict(trades=len(tdf), win_rate=float("nan"), pf=float("nan"), cagr=float("nan"), max_dd=float("nan"))
    wins, losses = tdf[tdf.pnl > 0], tdf[tdf.pnl <= 0]
    pf = wins["pnl"].sum() / -losses["pnl"].sum() if losses["pnl"].sum() != 0 else float("inf")
    final_equity = initial_capital + tdf["pnl"].sum()
    eq_curve = initial_capital + tdf["pnl"].cumsum()
    max_dd = ((eq_curve - eq_curve.cummax()) / eq_curve.cummax()).min() * 100
    span_days = (pd.to_datetime(tdf["exit_time"].iloc[-1]) - pd.to_datetime(tdf["entry_time"].iloc[0])).days
    years = max(span_days / 365.25, 0.01)
    cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100 if final_equity > 0 else float("-inf")
    return dict(trades=len(tdf), win_rate=(tdf.pnl > 0).mean() * 100, pf=pf, cagr=cagr, max_dd=max_dd)


if __name__ == "__main__":
    df = pd.read_parquet("data/btcusdt_5m.parquet").sort_values("open_time").reset_index(drop=True)
    df = se.compute_indicators(df)
    for threshold in [3, 4]:
        for sl_mult in [0.6, 1.0]:
            for rr in [1.0, 1.5, 2.0]:
                trades, _ = run(df, score_threshold=threshold, sl_atr_mult=sl_mult, rr=rr, max_hold_bars=24)
                m = metrics(trades, se.INITIAL_CAPITAL)
                print(f"REVERSED threshold={threshold} sl={sl_mult} rr={rr}: {m}")
