import os
import shutil

import pandas as pd
import yfinance as yf

DATA_DIR = os.path.abspath("backend/data/historical")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive_midday_snapshots")
os.makedirs(ARCHIVE_DIR, exist_ok=True)

ASSETS = {
    "RELIANCE": {"ticker": "RELIANCE.NS", "filename": "RELIANCE.csv"},
    "TCS": {"ticker": "TCS.NS", "filename": "TCS.csv"},
    "INFY": {"ticker": "INFY.NS", "filename": "INFY.csv"},
    "HDFCBANK": {"ticker": "HDFCBANK.NS", "filename": "HDFCBANK.csv"},
    "NIFTY50": {"ticker": "^NSEI", "filename": "NIFTY50.csv"},
}

print("=== Archiving Midday In-Progress Snapshots ===")
for sym, info in ASSETS.items():
    src = os.path.join(DATA_DIR, info["filename"])
    dst = os.path.join(ARCHIVE_DIR, f"{sym}_midday_snapshot_20261021.csv")
    if os.path.exists(src):
        shutil.copy2(src, dst)
        df_old = pd.read_csv(src)
        print(f"Archived {sym}: {dst} (Last row: {df_old.iloc[-1].to_dict()})")

print("\n=== Fetching Finalized End-of-Day Daily Records from Yahoo Finance ===")
finalized_records = {}
for sym, info in ASSETS.items():
    print(f"Fetching {sym} ({info['ticker']})...")
    ticker = yf.Ticker(info["ticker"])
    hist = ticker.history(period="1y")
    if hist.empty:
        raise RuntimeError(f"Could not fetch {sym}")
    
    hist.index = hist.index.strftime("%Y-%m-%d")
    clean_df = hist.reset_index().rename(columns={"index": "Date"})
    clean_df = clean_df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna()
    clean_df["Open"] = clean_df["Open"].round(2)
    clean_df["High"] = clean_df["High"].round(2)
    clean_df["Low"] = clean_df["Low"].round(2)
    clean_df["Close"] = clean_df["Close"].round(2)
    clean_df["Volume"] = clean_df["Volume"].astype(int)
    
    out_path = os.path.join(DATA_DIR, info["filename"])
    clean_df.to_csv(out_path, index=False)
    
    last_r = clean_df.iloc[-1]
    finalized_records[sym] = {
        "rows": len(clean_df),
        "date": last_r["Date"],
        "open": last_r["Open"],
        "high": last_r["High"],
        "low": last_r["Low"],
        "close": last_r["Close"],
        "volume": last_r["Volume"]
    }
    print(f"  -> Saved {len(clean_df)} finalized rows to {out_path}")
    print(f"     Final bar {last_r['Date']}: O={last_r['Open']}, H={last_r['High']}, L={last_r['Low']}, C={last_r['Close']}, V={last_r['Volume']}")

print("\nFinalized records successfully updated.")
