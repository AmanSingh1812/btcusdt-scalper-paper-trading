"""Parameter sweep to find a working scalper config after the initial
design (PF 0.544, -81% CAGR) failed - see README for the diagnosis."""
import sys

import pandas as pd

import scalper_engine as se

SL_MULTS = [0.4, 0.6, 0.8, 1.0]
RRS = [1.0, 1.5, 2.0]
THRESHOLDS = [3, 4]


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


def main():
    df = pd.read_parquet("data/btcusdt_5m.parquet").sort_values("open_time").reset_index(drop=True)
    df = se.compute_indicators(df)
    print(f"{'threshold':>9} {'sl_mult':>7} {'rr':>5} {'trades':>7} {'win%':>6} {'PF':>6} {'CAGR%':>8} {'maxDD%':>8}")
    for threshold in THRESHOLDS:
        for sl_mult in SL_MULTS:
            for rr in RRS:
                trades, _ = se.run_backtest(df, score_threshold=threshold, sl_atr_mult=sl_mult, rr=rr)
                m = metrics(trades, se.INITIAL_CAPITAL)
                print(f"{threshold:>9} {sl_mult:>7} {rr:>5} {m['trades']:>7} {m['win_rate']:>6.2f} "
                      f"{m['pf']:>6.3f} {m['cagr']:>8.2f} {m['max_dd']:>8.2f}")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
