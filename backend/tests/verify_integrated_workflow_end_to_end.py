import asyncio
import os
import sqlite3
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath("backend"))

import pandas as pd
from app.agents.orchestrator import agent_orchestrator
from app.db.base import Base
from app.db.models import (
    Account,
    Asset,
    Candle,
    LedgerEntry,
    Order,
    Position,
    Quote,
    RiskConfig,
)
from app.decisions.pipeline import decision_pipeline
from app.execution.paper_broker import paper_broker
from app.market.indicators import compute_all_indicators

print("================================================================================")
print("   PHASE 5: COMPLETE END-TO-END INTEGRATED SYSTEM & WORKFLOW AUDIT             ")
print("================================================================================")

PROD_DB_PATH = os.path.abspath("backend/hedgelab.db")
ISOLATED_DB_PATH = os.path.abspath("backend/test_isolated_workflow.db")

# Step 10 Pre-Check: Active Production Database Baseline
prod_conn = sqlite3.connect(PROD_DB_PATH)
prod_cur = prod_conn.cursor()
prod_cur.execute("SELECT cash_balance FROM accounts WHERE id=1")
prod_cash = prod_cur.fetchone()[0]
prod_cur.execute("SELECT COUNT(*) FROM positions")
prod_pos_count = prod_cur.fetchone()[0]
prod_conn.close()
print(f"[Production Baseline] Cash: INR {prod_cash:,.2f} | Open Positions: {prod_pos_count}")

# Setup Isolated Test Environment
if os.path.exists(ISOLATED_DB_PATH):
    os.remove(ISOLATED_DB_PATH)

isolated_engine = create_engine(f"sqlite:///{ISOLATED_DB_PATH}", connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=isolated_engine)
IsolatedSession = sessionmaker(bind=isolated_engine, autoflush=False, autocommit=False)
db = IsolatedSession()

# Step 1: Load Verified Historical Dataset into Isolated DB
csv_path = os.path.abspath("backend/data/historical/RELIANCE.csv")
df_csv = pd.read_csv(csv_path)
print(f"\n[Step 1: Historical Data] Loaded {len(df_csv)} bars from {csv_path}")

STARTING_CAPITAL = 1_000_000.0
acc = Account(id=1, name="Integrated Simulation Account", cash_balance=STARTING_CAPITAL, starting_cash=STARTING_CAPITAL)
db.add(acc)
asset = Asset(symbol="RELIANCE", name="Reliance Industries Limited", sector="Energy & Conglomerate", currency="INR", is_active=True)
db.add(asset)
latest_bar = df_csv.iloc[-1]
quote = Quote(symbol="RELIANCE", price=float(latest_bar["Close"]), previous=float(df_csv.iloc[-2]["Close"]), change=0.0, change_pct=0.0, volume=float(latest_bar["Volume"]))
db.add(quote)
risk_cfg = RiskConfig(id=1, fee_pct=0.10, max_order_pct=10.0, max_allocation_pct=25.0, drawdown_halt_pct=10.0, auto_execute=True)
db.add(risk_cfg)

# Insert candles
for _, r in df_csv.iterrows():
    c = Candle(
        symbol="RELIANCE",
        timestamp=pd.to_datetime(r["Date"]),
        open=float(r["Open"]),
        high=float(r["High"]),
        low=float(r["Low"]),
        close=float(r["Close"]),
        volume=float(r["Volume"]),
        is_synthetic=False,
        dataset_id="ds_reliance_daily"
    )
    db.add(c)
db.commit()

# Step 2: Compute Quantitative Indicators (using corrected daily log return volatility)
df_calc = df_csv.rename(columns={"Close": "close", "Open": "open", "High": "high", "Low": "low", "Volume": "volume"})
indicators = compute_all_indicators(df_calc)
print(f"\n[Step 2: Indicators] Computed RSI14={indicators['rsi_14']:.2f}, SMA20=INR {indicators['sma_20']:.2f}, Annualized Volatility={indicators['volatility']*100:.2f}%")
assert 0.15 < indicators["volatility"] < 0.35, "Volatility must reflect corrected ~25.10%"
assert indicators["rsi_14"] > 0

# Step 3 & 4: Run Actual Six-Agent Committee Workflow & Verify Metadata
print("\n[Step 3 & 4: Six-Agent Committee Workflow]")
run_id = "INT_TEST_001"
committee_res = asyncio.run(agent_orchestrator.run_multi_agent_analysis(
    db=db,
    symbol="RELIANCE",
    pipeline_run_id=run_id
))

agent_names = ["market_analyst", "sentiment_analyst", "macro_analyst", "quant_analyst", "risk_officer", "portfolio_manager"]
for a in agent_names:
    card = committee_res[a]
    print(f"  Agent {a:<20}: Mode={card.get('execution_mode'):<12} | Prov={card.get('provider'):<8} | Latency={card.get('latency_ms', 0):>6.1f}ms | Stance={str(card.get('value'))[:25]}")
    assert card.get("execution_mode") in ("local_llm", "deterministic_fallback")
    assert card.get("summary") is not None
    # Verify macro provenance disclosure
    if a == "macro_analyst":
        assert card.get("macro_data_status") == "FEED_UNAVAILABLE"
        print(f"       -> Macro provenance disclosure verified: {card.get('macro_data_status')}")

# Step 5 & 6: Execute Five-Stage Decision Pipeline (with Human Confirmation Flow: auto_execute=False)
print("\n[Step 5 & 6: Five-Stage Pipeline & Deterministic Risk Gate]")
pipeline_res = asyncio.run(decision_pipeline.execute_pipeline(
    db=db,
    symbol="RELIANCE",
    auto_execute=False
))
assert pipeline_res["status"] == "completed"
stages = pipeline_res["stages"]
assert len(stages) == 5
print(f"Stages: {' -> '.join(s['name'] for s in stages)}")
assert stages[3]["name"] == "Risk Gate" and stages[3]["state"] in ("done", "idle")
assert stages[4]["name"] == "Simulated Execution" and stages[4]["state"] == "idle"

staged_order_id = stages[4]["details"]["order_id"]
print(f"Order #{staged_order_id} staged as PROPOSAL: '{stages[4]['summary']}'")

# Step 7: Documented Confirmation Flow - Manually Confirm & Route Staged Proposal to Broker
print(f"\n[Step 7: Manual Proposal Confirmation Flow] Confirming Order #{staged_order_id}...")
confirm_res = paper_broker.execute_staged_proposal(db, staged_order_id)
assert confirm_res["status"] in ("APPROVED", "RESIZED")
executed_qty = confirm_res["executed"]
execution_id = confirm_res["execution_id"]
print(f"Proposal confirmed & executed: Execution #{execution_id} | Filled: {executed_qty} units")

# Step 8: Verify Accounting Reconciliation (Fees, Cash, Holdings, Ledger, Equity Identity)
print("\n[Step 8: Accounting Integrity & Reconciliation]")
db.refresh(acc)
pos = db.query(Position).filter(Position.account_id == 1, Position.symbol == "RELIANCE").first()
assert pos is not None and pos.quantity == executed_qty

order = db.query(Order).filter(Order.id == staged_order_id).first()
expected_cost = executed_qty * order.price
expected_fee = round(expected_cost * (0.10 / 100.0), 2)
expected_cash = STARTING_CAPITAL - (expected_cost + expected_fee)
assert abs(acc.cash_balance - expected_cash) < 0.01

# Ledger reconciliation
ledgers = db.query(LedgerEntry).filter(LedgerEntry.account_id == 1).all()
assert len(ledgers) == 2  # TRADE_BUY and FEE
print(f"Ledger entries verified: {[l.transaction_type for l in ledgers]}")

# Equity reconciliation
reconciled_equity = acc.cash_balance + (pos.quantity * order.price)
expected_equity = STARTING_CAPITAL - expected_fee
assert abs(reconciled_equity - expected_equity) < 0.01
print(f"Equity Identity Verified: Equity (INR {reconciled_equity:,.2f}) == Cash (INR {acc.cash_balance:,.2f}) + Holdings (INR {pos.quantity * order.price:,.2f})")

# Step 9: Verify Rejected Order Leaves Isolated Portfolio Unchanged
print("\n[Step 9: Risk Gate Veto of Rejected Order (Unverified Rumor)]")
pre_rej_cash = acc.cash_balance
pre_rej_qty = pos.quantity
rej_pipe = asyncio.run(decision_pipeline.execute_pipeline(
    db=db,
    symbol="RELIANCE",
    scenario_type="UNVERIFIED_RUMOR",
    auto_execute=True
))
assert rej_pipe["status"] == "rejected"
assert rej_pipe["stages"][3]["state"] == "bad"  # Risk Gate rejected
assert rej_pipe["stages"][4]["state"] == "bad"  # Execution blocked

db.refresh(acc)
db.refresh(pos)
assert acc.cash_balance == pre_rej_cash, "Cash balance altered by rejected order!"
assert pos.quantity == pre_rej_qty, "Holdings altered by rejected order!"
print(f"[OK] Verified zero state mutation on rejected order. Reason: {rej_pipe['stages'][3]['summary']}")

# Clean up isolated DB
db.close()
isolated_engine.dispose()
if os.path.exists(ISOLATED_DB_PATH):
    os.remove(ISOLATED_DB_PATH)
print("\n[OK] Isolated test database cleaned up.")

# Step 10: Confirm Active Production Portfolio is 100% Unchanged
prod_conn2 = sqlite3.connect(PROD_DB_PATH)
prod_cur2 = prod_conn2.cursor()
prod_cur2.execute("SELECT cash_balance FROM accounts WHERE id=1")
after_cash = prod_cur2.fetchone()[0]
prod_cur2.execute("SELECT COUNT(*) FROM positions")
after_pos = prod_cur2.fetchone()[0]
prod_conn2.close()

assert after_cash == prod_cash, f"Production cash modified! {after_cash} != {prod_cash}"
assert after_pos == prod_pos_count, f"Production positions modified! {after_pos} != {prod_pos_count}"
print(f"[Step 10: Production Integrity] Active Cash: INR {after_cash:,.2f} | Positions: {after_pos} (100% UNCHANGED)")

print("\n================================================================================")
print("   ONE COMPLETE INTEGRATED WORKFLOW 100% DEMONSTRATED AND VERIFIED              ")
print("================================================================================")
