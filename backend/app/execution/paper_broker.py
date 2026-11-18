import json
import math
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.errors import OrderExecutionError
from app.db.models import (
    Account,
    Execution,
    LedgerEntry,
    Order,
    Position,
    RiskConfig,
    RiskDecision,
)
from app.market.dhan_adapter import dhan_live_feed
from app.market.session_calendar import is_market_session_active
from app.risk.engine import risk_engine
from sqlalchemy import text
from sqlalchemy.orm import Session


def executable_quote_price(symbol: str) -> float | None:
    quote = dhan_live_feed.get_quote(symbol)
    if not quote or quote.get("freshness_status") not in ("FRESH", "LIVE", "FRESH_LIVE"):
        return None
    if quote.get("source") in ("0XRAMM_REST_V3", "YAHOO_FINANCE_EMBEDDED"):
        try:
            observed_at = datetime.fromisoformat(quote["market_timestamp"])
            age = (datetime.now(UTC) - observed_at).total_seconds()
        except (KeyError, TypeError, ValueError):
            return None
        if not 0 <= age <= settings.RAM_STALENESS_THRESHOLD_SECONDS:
            return None
    price = quote.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    return float(price) if math.isfinite(price) and price > 0 else None


class PaperBroker:
    """
    Deterministic simulated virtual broker.
    Executes approved/resized virtual orders with transaction safety,
    fee calculation, and persistent ledger updates.
    """

    def submit_and_process_order(
        self,
        db: Session,
        symbol: str,
        side: str,
        requested_qty: int,
        price: float,
        scenario_type: str | None = None,
        auto_execute: bool = True,
        reason: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Orchestrates:
        1. Independent Risk Gate Evaluation
        2. Order Record Persistence
        3. Virtual Fill Execution & Ledger Settlement (if approved/resized & auto_execute)
        """
        symbol = symbol.upper()
        side = side.upper()

        account = db.query(Account).first()
        if not account:
            raise OrderExecutionError("Primary simulation account not found.")

        hold_reason = ""
        if auto_execute and not scenario_type:
            market_open, session_message = is_market_session_active()
            observed_price = executable_quote_price(symbol) if market_open else None
            if observed_price is not None:
                price = observed_price
            elif not market_open:
                hold_reason = f"MARKET_CLOSED_EXECUTION_HELD: {session_message}"
            else:
                hold_reason = f"STALE_PRICE_EXECUTION_BLOCKED: No fresh usable quote for {symbol}."

        # 1. Independent Risk Gate Evaluation
        risk_result = risk_engine.evaluate_order(
            db=db,
            symbol=symbol,
            side=side,
            requested_qty=requested_qty,
            price=price,
            scenario_type=scenario_type
        )

        outcome = risk_result["outcome"]
        approved_qty = risk_result["approved_qty"]
        risk_reason = risk_result["reason"]
        fill_price = risk_result.get("fill_price", price)

        order_status = outcome  # APPROVED, RESIZED, or REJECTED
        if scenario_type:
            order_status = "SIMULATED_SCENARIO"
        elif not auto_execute and outcome in ("APPROVED", "RESIZED"):
            order_status = "PROPOSAL"

        if hold_reason and outcome in ("APPROVED", "RESIZED"):
            auto_execute = False
            order_status = "PROPOSAL"
            risk_reason = f"{risk_reason} [{hold_reason}]"

        # Calculate transaction fee (0.1%) on approved notional at fill price
        config = db.query(RiskConfig).first()
        fee_pct = config.fee_pct if config else 0.1
        fee = round((approved_qty * fill_price * (fee_pct / 100.0)), 2) if outcome != "REJECTED" else 0.0

        # 2. Persist Order Record
        order = Order(
            account_id=account.id,
            symbol=symbol,
            side=side,
            requested=requested_qty,
            executed=approved_qty if (auto_execute and not scenario_type and outcome in ("APPROVED", "RESIZED")) else 0,
            price=fill_price,
            fee=fee,
            status=order_status,
            reason=f"[SIMULATION] {risk_reason}" if scenario_type else (risk_reason if not reason else f"{risk_reason} {reason}".strip()),
            created_at=datetime.now(UTC)
        )
        db.add(order)
        db.flush()

        # Persist Risk Decision record
        decision_rec = RiskDecision(
            order_id=order.id,
            outcome=outcome,
            reason=risk_reason,
            evaluated_qty=requested_qty,
            approved_qty=approved_qty,
            rule_results_json=json.dumps(risk_result["rule_results"]),
            timestamp=datetime.now(UTC)
        )
        db.add(decision_rec)

        # 3. Virtual Fill Execution & Ledger Settlement (strictly isolated: never executed for simulated scenario shocks)
        execution_id = None
        if auto_execute and not scenario_type and outcome in ("APPROVED", "RESIZED") and approved_qty > 0:
            execution_id = self._execute_fill(db, account, order, approved_qty, fill_price, fee, final_status=outcome)

        if commit:
            db.commit()

        return {
            "order_id": order.id,
            "symbol": symbol,
            "side": side,
            "requested": requested_qty,
            "executed": order.executed,
            "price": fill_price,
            "fee": fee,
            "status": order.status,
            "outcome": outcome,
            "reason": order.reason,
            "risk_decision": risk_result,
            "execution_id": execution_id,
            "time": order.created_at.strftime("%H:%M")
        }

    def _execute_fill(
        self,
        db: Session,
        account: Account,
        order: Order,
        quantity: int,
        price: float,
        fee: float,
        final_status: str | None = None
    ) -> int:
        """Atomically settles positions, cash balances, and ledger entries."""
        now = datetime.now(UTC)
        order_val = round(quantity * price, 2)

        # 1. Update Position
        position = db.query(Position).filter(
            Position.account_id == account.id,
            Position.symbol == order.symbol
        ).first()

        if order.side == "BUY":
            total_cash_outflow = round(order_val + fee, 2)
            account.cash_balance = round(account.cash_balance - total_cash_outflow, 2)

            if position:
                total_qty = position.quantity + quantity
                new_avg = ((position.average_entry * position.quantity) + (price * quantity)) / total_qty
                position.quantity = total_qty
                position.average_entry = round(new_avg, 2)
            else:
                position = Position(
                    account_id=account.id,
                    symbol=order.symbol,
                    quantity=quantity,
                    average_entry=price
                )
                db.add(position)

            # Record ledger entries
            ledger_trade = LedgerEntry(
                account_id=account.id,
                transaction_type="TRADE_BUY",
                amount=-order_val,
                balance_after=round(account.cash_balance + fee, 2),
                description=f"Bought {quantity} {order.symbol} @ ₹{price:,.2f}",
                reference_id=f"ORD_{order.id}",
                created_at=now
            )
            db.add(ledger_trade)

            if fee > 0:
                ledger_fee = LedgerEntry(
                    account_id=account.id,
                    transaction_type="FEE",
                    amount=-fee,
                    balance_after=account.cash_balance,
                    description=f"Commission for order #{order.id}",
                    reference_id=f"ORD_{order.id}_FEE",
                    created_at=now
                )
                db.add(ledger_fee)

        elif order.side == "SELL":
            if not position or position.quantity < quantity:
                raise OrderExecutionError(f"Cannot sell {quantity} {order.symbol}; insufficient holdings.")
            total_cash_inflow = round(order_val - fee, 2)
            account.cash_balance = round(account.cash_balance + total_cash_inflow, 2)

            position.quantity -= quantity
            if position.quantity <= 0:
                db.delete(position)

            # Record ledger entries
            ledger_trade = LedgerEntry(
                account_id=account.id,
                transaction_type="TRADE_SELL",
                amount=order_val,
                balance_after=round(account.cash_balance + fee, 2),
                description=f"Sold {quantity} {order.symbol} @ ₹{price:,.2f}",
                reference_id=f"ORD_{order.id}",
                created_at=now
            )
            db.add(ledger_trade)

            if fee > 0:
                ledger_fee = LedgerEntry(
                    account_id=account.id,
                    transaction_type="FEE",
                    amount=-fee,
                    balance_after=account.cash_balance,
                    description=f"Commission for order #{order.id}",
                    reference_id=f"ORD_{order.id}_FEE",
                    created_at=now
                )
                db.add(ledger_fee)

        # 2. Record execution
        execution = Execution(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=price,
            fee=fee,
            timestamp=now
        )
        db.add(execution)
        db.flush()

        if final_status:
            order.status = final_status
        else:
            order.status = "APPROVED" if order.status == "APPROVED" else "RESIZED"
        return execution.id

    def execute_staged_proposal(self, db: Session, order_id: int) -> dict[str, Any]:
        """
        Manually confirms and executes an order previously staged as 'PROPOSAL' by the decision pipeline.
        Demonstrates the documented human-in-the-loop confirmation flow.
        """
        if db.get_bind().dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise OrderExecutionError(f"Order #{order_id} not found.")
        if order.status != "PROPOSAL":
            raise OrderExecutionError(f"Order #{order_id} is in status '{order.status}', not 'PROPOSAL'. Duplicate execution rejected.")
        account = db.query(Account).filter(Account.id == order.account_id).first()
        if not account:
            raise OrderExecutionError("Simulation account not found.")

        risk_dec = db.query(RiskDecision).filter(RiskDecision.order_id == order.id).first()
        approved_qty = risk_dec.approved_qty if risk_dec else order.requested
        if approved_qty <= 0:
            raise OrderExecutionError(f"Cannot execute order #{order_id} with approved quantity 0.")

        market_open, _ = is_market_session_active()
        observed_price = executable_quote_price(order.symbol) if market_open else None
        if observed_price is None:
            raise OrderExecutionError("A fresh market quote during an open session is required to settle this order.")
        risk = risk_engine.evaluate_order(db, order.symbol, order.side, approved_qty, observed_price)
        if risk["outcome"] == "REJECTED":
            order.status = "REJECTED"
            order.reason = risk["reason"]
            db.commit()
            raise OrderExecutionError(risk["reason"])

        final_qty = risk["approved_qty"]
        order.price = risk["fill_price"]
        config = db.query(RiskConfig).first()
        fee_pct = config.fee_pct if config else 0.1
        fee = round(final_qty * order.price * fee_pct / 100.0, 2)
        order.executed = final_qty
        order.fee = fee
        target_status = "RESIZED" if final_qty < order.requested else "APPROVED"
        execution_id = self._execute_fill(db, account, order, final_qty, order.price, fee, final_status=target_status)
        db.commit()

        return {
            "order_id": order.id,
            "status": order.status,
            "executed": order.executed,
            "execution_id": execution_id,
            "cash_after": account.cash_balance,
        }


paper_broker = PaperBroker()
