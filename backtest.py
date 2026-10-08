"""Backtest runner for the scalper engine - full report over available data."""
import sys

import pandas as pd

import scalper_engine as se


def yearly_breakdown(trades: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    trades = trades.sort_values("exit_time").copy()
    trades["year"] = pd.to_datetime(trades["exit_time"]).dt.year
    rows = []
    equity = initial_capital
    for year, grp in trades.groupby("year"):
        start_eq = equity
        equity += grp["pnl"].sum()
        pf = grp[grp.pnl > 0]["pnl"].sum() / -grp[grp.pnl <= 0]["pnl"].sum() if grp[grp.pnl <= 0]["pnl"].sum() != 0 else float("inf")
        rows.append(dict(year=year, trades=len(grp), win_rate=(grp["pnl"] > 0).mean() * 100,
                          pnl_pct=(equity - start_eq) / start_eq * 100, profit_factor=pf, end_equity=equity))
    return pd.DataFrame(rows)


def summarize(trades: list, initial_capital: float, label: str = ""):
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        print(f"\n=== {label}: no trades ===")
        return
    tdf = tdf.sort_values("exit_time").reset_index(drop=True)
    wins, losses = tdf[tdf.pnl > 0], tdf[tdf.pnl <= 0]
    pf = wins["pnl"].sum() / -losses["pnl"].sum() if losses["pnl"].sum() != 0 else float("inf")
    final_equity = initial_capital + tdf["pnl"].sum()
    eq_curve = initial_capital + tdf["pnl"].cumsum()
    max_dd = ((eq_curve - eq_curve.cummax()) / eq_curve.cummax()).min() * 100
    span_days = (pd.to_datetime(tdf["exit_time"].iloc[-1]) - pd.to_datetime(tdf["entry_time"].iloc[0])).days
    years = max(span_days / 365.25, 0.01)
    cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100 if final_equity > 0 else float("-inf")

    print(f"\n=== {label} ===")
    print(f"Span: {tdf['entry_time'].iloc[0]} to {tdf['exit_time'].iloc[-1]} ({years:.2f} years)")
    print(f"Trades: {len(tdf)}  Win rate: {(tdf.pnl>0).mean()*100:.2f}%  Avg hold: {tdf['bars_held'].mean():.1f} bars ({tdf['bars_held'].mean()*5:.0f} min)")
    print(f"Total PnL: {tdf['pnl'].sum():.2f} ({tdf['pnl'].sum()/initial_capital*100:.2f}%)")
    print(f"Profit factor: {pf:.3f}  CAGR: {cagr:.2f}%/yr  Max DD: {max_dd:.2f}%")
    print(f"Final equity: {final_equity:.2f}")
    print("Exit reasons:", tdf["reason"].value_counts().to_dict())
    print("\nYear-by-year:")
    print(yearly_breakdown(tdf, initial_capital).to_string(index=False))


def main():
    df = pd.read_parquet("data/btcusdt_5m.parquet").sort_values("open_time").reset_index(drop=True)
    print(f"Backtesting {len(df)} bars, {df['open_time'].min()} to {df['open_time'].max()}", file=sys.stderr)
    df = se.compute_indicators(df)
    trades, final_equity = se.run_backtest(df)
    summarize(trades, se.INITIAL_CAPITAL, f"Scalper engine (qty={se.QTY_PCT_OF_EQUITY*100:.0f}% equity)")


if __name__ == "__main__":
    main()
