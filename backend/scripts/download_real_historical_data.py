import os

import yfinance as yf

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historical")
os.makedirs(DATA_DIR, exist_ok=True)

ASSETS = {
    "RELIANCE": {
        "ticker": "RELIANCE.NS",
        "name": "Reliance Industries Limited",
        "sector": "Energy & Conglomerate",
        "exchange": "NSE",
        "filename": "RELIANCE.csv"
    },
    "TCS": {
        "ticker": "TCS.NS",
        "name": "Tata Consultancy Services Limited",
        "sector": "IT Services & Consulting",
        "exchange": "NSE",
        "filename": "TCS.csv"
    },
    "INFY": {
        "ticker": "INFY.NS",
        "name": "Infosys Limited",
        "sector": "IT Services & Consulting",
        "exchange": "NSE",
        "filename": "INFY.csv"
    },
    "HDFCBANK": {
        "ticker": "HDFCBANK.NS",
        "name": "HDFC Bank Limited",
        "sector": "Banking & Financial Services",
        "exchange": "NSE",
        "filename": "HDFCBANK.csv"
    },
    "NIFTY50": {
        "ticker": "^NSEI",
        "name": "NIFTY 50 Benchmark Index",
        "sector": "Benchmark Index",
        "exchange": "NSE",
        "filename": "NIFTY50.csv"
    }
}


def download_historical_data():
    print(f"Downloading genuine 1-year daily historical market data into '{DATA_DIR}'...")
    results = {}
    for symbol, info in ASSETS.items():
        print(f"Fetching {symbol} ({info['ticker']})...")
        ticker = yf.Ticker(info["ticker"])
        hist = ticker.history(period="1y")

        if hist.empty:
            raise RuntimeError(f"Failed to fetch data for {symbol} ({info['ticker']})")

        # Normalize format: Date, Open, High, Low, Close, Volume
        hist.index = hist.index.strftime("%Y-%m-%d")
        clean_df = hist.reset_index().rename(columns={"index": "Date"})
        clean_df = clean_df[["Date", "Open", "High", "Low", "Close", "Volume"]]

        # Clean any invalid entries
        clean_df = clean_df.dropna(subset=["Open", "High", "Low", "Close"])
        clean_df["Open"] = clean_df["Open"].round(2)
        clean_df["High"] = clean_df["High"].round(2)
        clean_df["Low"] = clean_df["Low"].round(2)
        clean_df["Close"] = clean_df["Close"].round(2)
        clean_df["Volume"] = clean_df["Volume"].astype(int)

        out_path = os.path.join(DATA_DIR, info["filename"])
        clean_df.to_csv(out_path, index=False)
        print(f"  -> Saved {len(clean_df)} records to {out_path} (Range: {clean_df['Date'].iloc[0]} to {clean_df['Date'].iloc[-1]})")

        results[symbol] = {
            "symbol": symbol,
            "records": len(clean_df),
            "start_date": clean_df["Date"].iloc[0],
            "end_date": clean_df["Date"].iloc[-1],
            "latest_close": clean_df["Close"].iloc[-1],
            "path": out_path
        }

    print("\nAll genuine historical market datasets successfully saved.")
    return results


if __name__ == "__main__":
    download_historical_data()
