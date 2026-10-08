"""
Scalping engine for BTCUSDT, v2.

v1 (vanilla RSI/Bollinger/Stochastic mean-reversion off a stretched
extreme) was tested exhaustively - 24 SL/RR/threshold combinations, both
the original fade direction AND the reversed momentum-continuation
direction - and every single one lost money (best PF 0.59, most far
worse), with win rate rising only as stops widened (the classic sign of
"no real edge, just absorbing noise with more room," not a real signal).
BTCUSDT on 5-minute bars is an extremely liquid, heavily-arbitraged
market; naive textbook oscillator combos are well known not to have an
exploitable edge there out of the box. See sweep.py / test_reversed.py
for the full evidence.

v2 instead adapts the swing bot's PDH/PDL confluence-reversal signal
(../swing trading/paper-trading-bot/backtest_pdh_pdl.py) - which has
real, validated multi-year edge (CAGR 8-16%/yr, PF 1.4-1.9 over 9 years)
- onto a faster timeframe with scalping-appropriate exits, rather than
inventing another untested signal from scratch:
  - 5-minute bars instead of 15-minute
  - Smaller near-zone (0.2% vs 0.4%) to match tighter 5m price action
  - Smaller R:R (1.5R/2.5R partials vs 2R/4R) for quicker exits
  - A hard MAX_HOLD_BARS time-stop (new - the swing bot has none and has
    been observed holding positions for 2+ days; that cannot be a scalp)
  - Same core confluence score (candlestick pattern, chart pattern via
    pivots, volume, market structure, momentum), same HTF trend filter
    and breakout protection, same PDH/PDL confluence concept
"""
import numpy as np
import pandas as pd

MINTICK = 0.01
INITIAL_CAPITAL = 100.0
QTY_PCT_OF_EQUITY = 0.50  # see README - clears the swing bot's 12%/yr target (13.52%/yr) at
# -3.13% max DD over the full 9-year backtest, vs. the swing bot's -15.82% DD for a similar CAGR

ATR_LEN = 14
ZONE_PCT = 0.2
PIVOT_LEFT, PIVOT_RIGHT = 3, 3
MAX_PIVOT_HISTORY = 10
PATTERN_TOL_PCT = 0.3
PATTERN_LOOKBACK = 100
RSI_LEN = 14
RSI_OB, RSI_OS = 70, 30
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
VOL_MA_LEN = 20
VOL_MULT = 1.3
HTF_RULE, HTF_EMA_LEN = "1h", 50
BREAKOUT_ATR_MULT, BREAKOUT_VOL_MULT = 1.5, 2.0

SCORE_THRESHOLD = 3
RR1, RR2 = 1.5, 2.5
TP2_ENABLED = True
SL_ATR_MULT = 1.0
BUFFER_TICKS = 5
MAX_HOLD_BARS = 48  # 48 * 5min = 4 hours - the scalping-defining cap, absent from the swing bot
COMMISSION_PCT = 0.0004
SLIPPAGE_TICKS = 2


def ema(s: pd.Series, length: int) -> pd.Series:
    return s.ewm(span=length, adjust=False).mean()


def rma(s: pd.Series, length: int) -> pd.Series:
    return s.ewm(alpha=1 / length, adjust=False).mean()


def compute_indicators(df: pd.DataFrame, zone_pct=ZONE_PCT, htf_rule=HTF_RULE, htf_ema_len=HTF_EMA_LEN) -> pd.DataFrame:
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = rma(tr, ATR_LEN)

    date = df["open_time"].dt.floor("D")
    daily = df.groupby(date).agg(day_high=("high", "max"), day_low=("low", "min")).shift(1)
    day_map = daily.reindex(date).reset_index(drop=True)
    df["pdh"] = day_map["day_high"].values
    df["pdl"] = day_map["day_low"].values
    df["new_day"] = date.ne(date.shift(1)).values
    df.loc[0, "new_day"] = True

    df["zone_dist_pdh"] = df["pdh"] * zone_pct / 100
    df["zone_dist_pdl"] = df["pdl"] * zone_pct / 100
    df["near_pdh"] = (h >= df["pdh"] - df["zone_dist_pdh"]) & (l <= df["pdh"] + df["zone_dist_pdh"])
    df["near_pdl"] = (l <= df["pdl"] + df["zone_dist_pdl"]) & (h >= df["pdl"] - df["zone_dist_pdl"])

    w = PIVOT_LEFT + PIVOT_RIGHT + 1
    rmax, rmin = h.rolling(w).max(), l.rolling(w).min()
    rmax_aligned, rmin_aligned = rmax.shift(-PIVOT_RIGHT), rmin.shift(-PIVOT_RIGHT)
    n = len(df)
    valid = np.zeros(n, dtype=bool)
    valid[PIVOT_LEFT: n - PIVOT_RIGHT] = True
    is_ph = valid & (h.values == rmax_aligned.values)
    is_pl = valid & (l.values == rmin_aligned.values)
    ph_confirmed_at, pl_confirmed_at = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    ph_confirmed_at[PIVOT_RIGHT:] = is_ph[: n - PIVOT_RIGHT]
    pl_confirmed_at[PIVOT_RIGHT:] = is_pl[: n - PIVOT_RIGHT]
    df["ph_confirmed"], df["pl_confirmed"] = ph_confirmed_at, pl_confirmed_at
    df["ph_peak_val"] = np.where(ph_confirmed_at, h.shift(PIVOT_RIGHT).values, np.nan)
    df["pl_peak_val"] = np.where(pl_confirmed_at, l.shift(PIVOT_RIGHT).values, np.nan)

    body0 = (c - o).abs()
    body1, body2 = body0.shift(1), body0.shift(2)
    range1 = (h - l).shift(1)
    upper0 = h - pd.concat([c, o], axis=1).max(axis=1)
    lower0 = pd.concat([c, o], axis=1).min(axis=1) - l
    is_bull0, is_bear0 = c > o, c < o
    is_bull1, is_bear1 = (c > o).shift(1), (c < o).shift(1)
    is_bull2, is_bear2 = (c > o).shift(2), (c < o).shift(2)
    avg_body = body0.rolling(14).mean()
    o1, c1, o2, c2 = o.shift(1), c.shift(1), o.shift(2), c.shift(2)
    h1, l1 = h.shift(1), l.shift(1)

    bear_engulf = is_bull1 & is_bear0 & (o >= c1) & (c <= o1) & (body0 > body1)
    shooting_star = (upper0 >= 2 * body0) & (lower0 <= body0 * 0.3) & (body0 <= avg_body * 0.8)
    evening_star = is_bull2 & (body2 > avg_body) & (body1 < body2 * 0.5) & is_bear0 & (c < (o2 + c2) / 2)
    bear_pin = (upper0 >= body0 * 2) & (lower0 <= body0 * 0.5) & is_bear0
    doji_bear = (body1 <= range1 * 0.1) & is_bear0 & (c < l1)
    bull_engulf = is_bear1 & is_bull0 & (o <= c1) & (c >= o1) & (body0 > body1)
    hammer = (lower0 >= 2 * body0) & (upper0 <= body0 * 0.3) & (body0 <= avg_body * 0.8)
    morning_star = is_bear2 & (body2 > avg_body) & (body1 < body2 * 0.5) & is_bull0 & (c > (o2 + c2) / 2)
    bull_pin = (lower0 >= body0 * 2) & (upper0 <= body0 * 0.5) & is_bull0
    doji_bull = (body1 <= range1 * 0.1) & is_bull0 & (c > h1)
    df["bearish_candle"] = (bear_engulf | shooting_star | evening_star | bear_pin | doji_bear).fillna(False)
    df["bullish_candle"] = (bull_engulf | hammer | morning_star | bull_pin | doji_bull).fillna(False)

    df["failed_breakout_pdh"] = ((h >= df["pdh"] + df["zone_dist_pdh"] * 0.5) & (c < df["pdh"])).fillna(False)
    df["failed_breakdown_pdl"] = ((l <= df["pdl"] - df["zone_dist_pdl"] * 0.5) & (c > df["pdl"])).fillna(False)

    vol_ma = v.rolling(VOL_MA_LEN).mean()
    df["vol_ma"] = vol_ma
    df["vol_confirm"] = (v > vol_ma * VOL_MULT).fillna(False)

    delta = c.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    rs = rma(gain, RSI_LEN) / rma(loss, RSI_LEN)
    rsi = 100 - 100 / (1 + rs)
    df["rsi"] = rsi
    rsi_prev = rsi.shift(1)
    df["rsi_bear_turn"] = ((rsi_prev >= RSI_OB) & (rsi < rsi_prev)).fillna(False)
    df["rsi_bull_turn"] = ((rsi_prev <= RSI_OS) & (rsi > rsi_prev)).fillna(False)

    macd_line = ema(c, MACD_FAST) - ema(c, MACD_SLOW)
    signal_line = ema(macd_line, MACD_SIGNAL)
    hist = macd_line - signal_line
    hist1, hist2 = hist.shift(1), hist.shift(2)
    df["macd_bear_turn"] = ((hist < hist1) & (hist1 >= hist2)).fillna(False)
    df["macd_bull_turn"] = ((hist > hist1) & (hist1 <= hist2)).fillna(False)
    df["momentum_bear"] = df["rsi_bear_turn"] | df["macd_bear_turn"]
    df["momentum_bull"] = df["rsi_bull_turn"] | df["macd_bull_turn"]

    htf = df.set_index("open_time")["close"].resample(htf_rule).agg(["last"]).dropna()
    htf["ema"] = ema(htf["last"], htf_ema_len)
    htf = htf.reset_index().rename(columns={"open_time": "htf_close_time", "last": "htf_close"})
    merged = pd.merge_asof(df[["open_time"]], htf, left_on="open_time", right_on="htf_close_time",
                            direction="backward", allow_exact_matches=False)
    df["htf_trend_up"] = (merged["htf_close"] > merged["ema"]).fillna(False).values

    df["strong_break_up"] = ((c > df["pdh"] + BREAKOUT_ATR_MULT * df["atr"]) & (v > vol_ma * BREAKOUT_VOL_MULT) & df["momentum_bull"]).fillna(False)
    df["strong_break_down"] = ((c < df["pdl"] - BREAKOUT_ATR_MULT * df["atr"]) & (v > vol_ma * BREAKOUT_VOL_MULT) & df["momentum_bear"]).fillna(False)

    return df


def prepare_arrays(df: pd.DataFrame) -> dict:
    cols = ["open", "high", "low", "close", "volume", "pdh", "pdl", "zone_dist_pdh", "zone_dist_pdl",
            "atr", "rsi", "vol_ma", "near_pdh", "near_pdl", "bearish_candle", "bullish_candle",
            "failed_breakout_pdh", "failed_breakdown_pdl", "vol_confirm", "momentum_bear", "momentum_bull",
            "htf_trend_up", "strong_break_up", "strong_break_down", "ph_confirmed", "pl_confirmed",
            "ph_peak_val", "pl_peak_val", "new_day"]
    arr = {c: df[c].values for c in cols}
    arr["open_time"] = df["open_time"].values
    arr["n"] = len(df)
    return arr


def new_state(initial_capital=INITIAL_CAPITAL) -> dict:
    return dict(pivot_high_vals=[], pivot_high_bars=[], pivot_low_vals=[], pivot_low_bars=[],
                sell_fired=False, buy_fired=False, equity=initial_capital, position=None)


def step_bar(i, arr, state, score_threshold=SCORE_THRESHOLD, rr1=RR1, rr2=RR2, tp2_enabled=TP2_ENABLED,
             use_htf_filter=True, enable_breakout_protection=True, sl_atr_mult=SL_ATR_MULT,
             buffer_ticks=BUFFER_TICKS, max_hold_bars=MAX_HOLD_BARS, ml_gate=None):
    tick_buffer = MINTICK * buffer_ticks
    trades = []

    if arr["ph_confirmed"][i]:
        state["pivot_high_vals"].append(arr["ph_peak_val"][i])
        state["pivot_high_bars"].append(i - PIVOT_RIGHT)
        if len(state["pivot_high_vals"]) > MAX_PIVOT_HISTORY:
            state["pivot_high_vals"].pop(0); state["pivot_high_bars"].pop(0)
    if arr["pl_confirmed"][i]:
        state["pivot_low_vals"].append(arr["pl_peak_val"][i])
        state["pivot_low_bars"].append(i - PIVOT_RIGHT)
        if len(state["pivot_low_vals"]) > MAX_PIVOT_HISTORY:
            state["pivot_low_vals"].pop(0); state["pivot_low_bars"].pop(0)

    phv, phb = state["pivot_high_vals"], state["pivot_high_bars"]
    plv, plb = state["pivot_low_vals"], state["pivot_low_bars"]
    ph_size, pl_size = len(phv), len(plv)

    structure_bear = structure_bull = False
    if ph_size >= 2 and pl_size >= 2:
        structure_bear, structure_bull = phv[-1] < phv[-2], plv[-1] > plv[-2]

    double_top = double_bottom = False
    if ph_size >= 2:
        d1, d2, dbar2 = phv[-1], phv[-2], phb[-2]
        double_top = abs(d1 - d2) <= d2 * PATTERN_TOL_PCT / 100 and (i - dbar2) <= PATTERN_LOOKBACK
    if pl_size >= 2:
        d1, d2, dbar2 = plv[-1], plv[-2], plb[-2]
        double_bottom = abs(d1 - d2) <= d2 * PATTERN_TOL_PCT / 100 and (i - dbar2) <= PATTERN_LOOKBACK

    chart_pattern_bear = double_top or arr["failed_breakout_pdh"][i]
    chart_pattern_bull = double_bottom or arr["failed_breakdown_pdl"][i]

    buy_score = int(arr["near_pdl"][i]) + int(arr["bullish_candle"][i]) + int(chart_pattern_bull) + int(arr["vol_confirm"][i]) + int(structure_bull) + int(arr["momentum_bull"][i])
    sell_score = int(arr["near_pdh"][i]) + int(arr["bearish_candle"][i]) + int(chart_pattern_bear) + int(arr["vol_confirm"][i]) + int(structure_bear) + int(arr["momentum_bear"][i])
    buy_qualified = buy_score >= score_threshold
    sell_qualified = sell_score >= score_threshold

    if enable_breakout_protection:
        sell_qualified = sell_qualified and not arr["strong_break_up"][i]
        buy_qualified = buy_qualified and not arr["strong_break_down"][i]
    if use_htf_filter:
        sell_qualified = sell_qualified and not arr["htf_trend_up"][i]
        buy_qualified = buy_qualified and arr["htf_trend_up"][i]

    if ml_gate is not None:
        common = dict(structure_bull=structure_bull, structure_bear=structure_bear,
                      double_top=double_top, double_bottom=double_bottom)
        if buy_qualified:
            buy_qualified = bool(ml_gate("buy", i, arr, common))
        if sell_qualified:
            sell_qualified = bool(ml_gate("sell", i, arr, common))

    if arr["new_day"][i]:
        state["sell_fired"] = False
        state["buy_fired"] = False
    if arr["high"][i] < arr["pdh"][i] - arr["zone_dist_pdh"][i] * 1.5:
        state["sell_fired"] = False
    if arr["low"][i] > arr["pdl"][i] + arr["zone_dist_pdl"][i] * 1.5:
        state["buy_fired"] = False

    position = state["position"]
    is_flat = position is None

    if position is not None:
        target = position["tp2"] if (position["tp1_filled"] and tp2_enabled) else position["tp1"]
        sl, side = position["sl"], position["side"]
        bo, bh, bl = arr["open"][i], arr["high"][i], arr["low"][i]
        bars_held = i - position["entry_bar"]
        force_exit = bars_held >= max_hold_bars

        hit_sl, hit_tp = (bl <= sl, bh >= target) if side == "long" else (bh >= sl, bl <= target)
        reason = exit_px = qty_exit = None
        if hit_sl or hit_tp:
            sl_first = (abs(bo - sl) < abs(bo - target)) if (hit_sl and hit_tp) else hit_sl
            if sl_first:
                exit_px = sl - MINTICK * SLIPPAGE_TICKS if side == "long" else sl + MINTICK * SLIPPAGE_TICKS
                qty_exit, reason = position["qty_remaining"], "SL"
            else:
                exit_px = target
                if position["tp1_filled"] or not tp2_enabled:
                    qty_exit, reason = position["qty_remaining"], ("TP2" if position["tp1_filled"] else "TP1(full)")
                else:
                    qty_exit, reason = position["qty_total"] * 0.5, "TP1"
        elif force_exit:
            exit_px, qty_exit, reason = arr["close"][i], position["qty_remaining"], "TIME"

        if reason is not None:
            price_pnl = (exit_px - position["entry_px"]) * qty_exit if side == "long" else (position["entry_px"] - exit_px) * qty_exit
            exit_comm = exit_px * qty_exit * COMMISSION_PCT
            state["equity"] += price_pnl - exit_comm
            entry_comm_share = position["entry_comm_total"] * (qty_exit / position["qty_total"])
            pnl = price_pnl - exit_comm - entry_comm_share
            trades.append(dict(side=side, entry_time=position["entry_time"], exit_time=arr["open_time"][i],
                                reason=reason, qty=qty_exit, entry_px=position["entry_px"], exit_px=exit_px,
                                bars_held=bars_held, pnl=pnl))
            position["qty_remaining"] -= qty_exit
            if reason in ("SL", "TP2", "TP1(full)", "TIME") or position["qty_remaining"] <= 1e-12:
                position = None
            else:
                position["tp1_filled"] = True
            state["position"] = position
            is_flat = position is None

    sell_signal = buy_signal = False
    if is_flat:
        sell_signal = sell_qualified and arr["near_pdh"][i] and not state["sell_fired"]
        buy_signal = buy_qualified and arr["near_pdl"][i] and not state["buy_fired"]
        if sell_signal:
            state["sell_fired"] = True
        if buy_signal:
            state["buy_fired"] = True

        atr_i, pdh_i, pdl_i = arr["atr"][i], arr["pdh"][i], arr["pdl"][i]
        if (sell_signal or buy_signal) and pd.notna(atr_i) and pd.notna(pdh_i) and pd.notna(pdl_i):
            entry_close = arr["close"][i]
            if sell_signal:
                valid_swing = ph_size >= 1 and phv[-1] > entry_close
                sl_price = (phv[-1] + tick_buffer) if valid_swing else (entry_close + sl_atr_mult * atr_i)
                risk = sl_price - entry_close
                tp1, tp2 = entry_close - risk * rr1, entry_close - risk * rr2
                if risk > 0:
                    fill_px = entry_close - MINTICK * SLIPPAGE_TICKS
                    qty = (state["equity"] * QTY_PCT_OF_EQUITY) / fill_px
                    entry_comm = fill_px * qty * COMMISSION_PCT
                    state["position"] = dict(side="short", entry_time=arr["open_time"][i], entry_bar=i, entry_px=fill_px,
                                              qty_total=qty, qty_remaining=qty, sl=sl_price, tp1=tp1, tp2=tp2,
                                              tp1_filled=False, entry_comm_total=entry_comm)
                    state["equity"] -= entry_comm
            else:
                valid_swing = pl_size >= 1 and plv[-1] < entry_close
                sl_price = (plv[-1] - tick_buffer) if valid_swing else (entry_close - sl_atr_mult * atr_i)
                risk = entry_close - sl_price
                tp1, tp2 = entry_close + risk * rr1, entry_close + risk * rr2
                if risk > 0:
                    fill_px = entry_close + MINTICK * SLIPPAGE_TICKS
                    qty = (state["equity"] * QTY_PCT_OF_EQUITY) / fill_px
                    entry_comm = fill_px * qty * COMMISSION_PCT
                    state["position"] = dict(side="long", entry_time=arr["open_time"][i], entry_bar=i, entry_px=fill_px,
                                              qty_total=qty, qty_remaining=qty, sl=sl_price, tp1=tp1, tp2=tp2,
                                              tp1_filled=False, entry_comm_total=entry_comm)
                    state["equity"] -= entry_comm

    signal_info = dict(buy_signal=buy_signal, sell_signal=sell_signal, buy_score=buy_score, sell_score=sell_score)
    return state, trades, signal_info


def run_backtest(df: pd.DataFrame, **kwargs):
    arr = prepare_arrays(df)
    state = new_state()
    all_trades = []
    for i in range(arr["n"]):
        state, trades, _ = step_bar(i, arr, state, **kwargs)
        all_trades.extend(trades)
    return all_trades, state["equity"]
