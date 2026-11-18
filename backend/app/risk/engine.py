import math
from typing import Any

from app.core.config import settings
from app.db.models import Account, Asset, Position, Quote, RiskConfig
from app.market.scenarios import resolve_scenario_type
from app.risk.rules import (
    check_asset_concentration,
    check_cash_sufficiency,
    check_drawdown_limit,
    check_max_order_size,
    check_no_short_selling,
    check_symbol_and_quantity,
)
from sqlalchemy.orm import Session


class RiskEngine:
    """
    Independent deterministic risk gate service.
    Enforces absolute compliance invariants prior to simulated order execution.
    """

    def evaluate_order(
        self,
        db: Session,
        symbol: str,
        side: str,
        requested_qty: int,
        price: float,
        scenario_type: str | None = None
    ) -> dict[str, Any]:
        """
        Validate order proposal against all active deterministic risk constraints.
        """
        symbol = symbol.upper()
        side = side.upper()

        account = db.query(Account).first()
        risk_cfg = db.query(RiskConfig).first()
        if not risk_cfg:
            risk_cfg = RiskConfig()

        if (
            account is None or account.starting_cash <= 0
            or side not in ("BUY", "SELL")
            or type(requested_qty) is not int or requested_qty <= 0
            or not math.isfinite(price) or price < 0.01
        ):
            return {
                "outcome": "REJECTED", "reason": "Invalid account or order inputs.",
                "evaluated_qty": requested_qty, "approved_qty": 0, "rule_results": [],
            }

        # Compute authoritative equity and current position
        positions = db.query(Position).filter(Position.account_id == account.id).all()
        quotes = {q.symbol: q.price for q in db.query(Quote).all()}
        invested = sum(p.quantity * quotes.get(p.symbol, p.average_entry) for p in positions)
        total_equity = account.cash_balance + invested

        if not math.isfinite(total_equity) or total_equity <= 0:
            return {
                "outcome": "REJECTED", "reason": "Portfolio equity must be positive.",
                "evaluated_qty": requested_qty, "approved_qty": 0, "rule_results": [],
            }

        curr_pos = next((p.quantity for p in positions if p.symbol == symbol), 0)
        known_assets = [a.symbol for a in db.query(Asset).all()]

        # Compute drawdown from initial starting capital
        drawdown_pct = max(0.0, ((account.starting_cash - total_equity) / account.starting_cash) * 100.0)

        rule_results = []
        approved_qty = requested_qty

        # Scenario check: Unverified rumor or misleading news headline fails risk gate deterministically
        resolved_scenario = resolve_scenario_type(scenario_type) if scenario_type else None
        if resolved_scenario == "UNVERIFIED_RUMOR":
            rule_results.append({
                "rule_name": "Source verification & news sentiment gate",
                "passed": False,
                "description": "Blocked: unverified market rumor triggered strict source verification rule.",
                "measured_value": "Unverified",
                "limit_value": "Verified Source Only"
            })
            return {
                "outcome": "REJECTED",
                "reason": "Unverified headline failed the deterministic risk gate.",
                "evaluated_qty": requested_qty,
                "approved_qty": 0,
                "rule_results": rule_results,
            }

        # Rule 1: Valid symbol & positive quantity
        p1, d1 = check_symbol_and_quantity(symbol, requested_qty, known_assets)
        rule_results.append({
            "rule_name": "Valid symbol and positive quantity",
            "passed": p1,
            "description": d1,
            "measured_value": f"{requested_qty} {symbol}",
            "limit_value": "> 0"
        })
        if not p1:
            return {
                "outcome": "REJECTED",
                "reason": d1,
                "evaluated_qty": requested_qty,
                "approved_qty": 0,
                "rule_results": rule_results,
            }

        # Rule 2: Short selling check (for SELL)
        p2, d2 = check_no_short_selling(side, requested_qty, curr_pos)
        rule_results.append({
            "rule_name": "No leverage and no short selling",
            "passed": p2,
            "description": d2,
            "measured_value": f"Holdings: {curr_pos}",
            "limit_value": "No shorting"
        })
        if not p2:
            return {
                "outcome": "REJECTED",
                "reason": d2,
                "evaluated_qty": requested_qty,
                "approved_qty": 0,
                "rule_results": rule_results,
            }

        # Compute applicable simulated fill price including slippage convention
        slippage_pct = getattr(settings, "SLIPPAGE_PCT", 0.05)
        fill_price = round(price * (1.0 + slippage_pct / 100.0), 2) if side == "BUY" else round(price * (1.0 - slippage_pct / 100.0), 2)

        max_order_pct = min(risk_cfg.max_order_pct, 10.0)
        allocation_pct = min(risk_cfg.max_allocation_pct, 25.0)
        drawdown_limit = min(risk_cfg.drawdown_halt_pct, 10.0)

        # Rule 3: Max order size check (10% limit evaluated at actual fill price)
        p3, resized_qty, d3 = check_max_order_size(requested_qty, fill_price, total_equity, max_order_pct)
        rule_results.append({
            "rule_name": f"Maximum new order is {max_order_pct}% of equity",
            "passed": p3,
            "description": d3,
            "measured_value": f"₹{(requested_qty * fill_price):,.2f}",
            "limit_value": f"₹{(total_equity * max_order_pct / 100):,.2f}"
        })

        is_resized = False
        if not p3 and resized_qty == 0:
            return {
                "outcome": "REJECTED",
                "reason": "Insufficient cash to buy one share." if side == "BUY" and account.cash_balance < fill_price
                else "One share exceeds the order value limit.",
                "evaluated_qty": requested_qty, "approved_qty": 0, "rule_results": rule_results,
            }
        if not p3:
            approved_qty = resized_qty
            is_resized = True

        # Rule 4: Cash sufficiency check evaluated at fill price plus transaction fee
        p4, d4 = check_cash_sufficiency(side, approved_qty, fill_price, risk_cfg.fee_pct, account.cash_balance)
        rule_results.append({
            "rule_name": "Cash sufficiency",
            "passed": p4,
            "description": d4,
            "measured_value": f"Cash: ₹{account.cash_balance:,.2f}",
            "limit_value": f"Cost: ₹{(approved_qty * fill_price * (1 + risk_cfg.fee_pct/100)):,.2f}"
        })
        if not p4:
            return {
                "outcome": "REJECTED",
                "reason": d4,
                "evaluated_qty": requested_qty,
                "approved_qty": 0,
                "fill_price": fill_price,
                "slippage_pct": slippage_pct,
                "rule_results": rule_results,
            }

        # Rule 5: Asset concentration check (25% limit) evaluated at fill price
        p5, d5 = check_asset_concentration(symbol, side, approved_qty, fill_price, total_equity, curr_pos, allocation_pct)
        rule_results.append({
            "rule_name": f"Maximum asset concentration is {allocation_pct}%",
            "passed": p5,
            "description": d5,
            "measured_value": f"{((curr_pos + (approved_qty if side == 'BUY' else -approved_qty)) * fill_price / total_equity * 100):.1f}%",
            "limit_value": f"{allocation_pct}%"
        })
        if not p5:
            return {
                "outcome": "REJECTED",
                "reason": d5,
                "evaluated_qty": requested_qty,
                "approved_qty": 0,
                "fill_price": fill_price,
                "slippage_pct": slippage_pct,
                "rule_results": rule_results,
            }

        # Rule 6: Drawdown limit check
        p6, d6 = check_drawdown_limit(drawdown_pct, drawdown_limit, side)
        rule_results.append({
            "rule_name": f"Maximum portfolio drawdown halt at {drawdown_limit}%",
            "passed": p6,
            "description": d6,
            "measured_value": f"{drawdown_pct:.1f}%",
            "limit_value": f"{drawdown_limit}%"
        })
        if not p6:
            return {
                "outcome": "REJECTED",
                "reason": d6,
                "evaluated_qty": requested_qty,
                "approved_qty": 0,
                "fill_price": fill_price,
                "slippage_pct": slippage_pct,
                "rule_results": rule_results,
            }

        outcome = "RESIZED" if is_resized else "APPROVED"
        reason = f"Resized to {max_order_pct}% max-order limit." if is_resized else "Risk gate approved simulated order."

        return {
            "outcome": outcome,
            "reason": reason,
            "evaluated_qty": requested_qty,
            "approved_qty": approved_qty,
            "fill_price": fill_price,
            "slippage_pct": slippage_pct,
            "rule_results": rule_results,
        }


risk_engine = RiskEngine()
