from app.market.dhan_adapter import dhan_live_feed
from sqlalchemy import text

"""
SYNQ — Risk-Gated Paper-Trade Proposal Service
Manages the lifecycle of paper-trade proposals generated from evidence-backed AI analysis.
Enforces deterministic risk limits, proposal expiration, explicit human confirmation,
and confirmation-time revalidation before paper execution.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.logging import logger
from app.db.models import Account, PaperTradeProposal, Position, RiskConfig
from app.db.session import SessionLocal
from app.execution.paper_broker import paper_broker


def _dt_expired(dt: datetime | None, now: datetime) -> bool:
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return dt < now


class PaperProposalService:
    """
    Manages proposal creation, deterministic risk pre-checking, expiry,
    confirmation-time revalidation, and paper broker execution.
    """

    def create_proposal_from_analysis(
        self,
        run_id: str,
        symbol: str,
        side: str,
        price: float,
        reason: str,
        event_id: str | None = None,
        snapshot_id: str | None = None,
        target_allocation_pct: float = 8.0,
        expiry_minutes: int = 15
    ) -> dict[str, Any]:
        """
        Calculates maximum allowed quantity under the 10% single-order limit
        and creates a PENDING_CONFIRMATION proposal.
        """
        sym = symbol.upper()
        now_utc = datetime.now(UTC)
        proposal_id = f"PROP_{now_utc.strftime('%Y%m%d_%H%M%S')}_{sym}_{uuid.uuid4().hex[:4]}"
        expires_at = now_utc + timedelta(minutes=expiry_minutes)

        with SessionLocal() as db:
            account = db.query(Account).first()
            risk_cfg = db.query(RiskConfig).first()

            cash = float(account.cash_balance) if account else 1000000.0
            positions = db.query(Position).all()
            invested_val = sum(float(p.quantity) * float(p.average_entry) for p in positions)
            total_equity = cash + invested_val

            max_order_pct = float(risk_cfg.max_order_pct) if risk_cfg else getattr(settings, "MAX_ORDER_PCT", 10.0)
            max_order_val = total_equity * (max_order_pct / 100.0)

            # Execution price convention including configured slippage
            slippage_pct = getattr(settings, "SLIPPAGE_PCT", 0.05)
            estimated_fill_price = round(price * (1.0 + (slippage_pct / 100.0 if side == "BUY" else -slippage_pct / 100.0)), 2)

            # Size proposal to comply with 10% limit
            target_val = min(max_order_val, total_equity * (target_allocation_pct / 100.0))
            calculated_qty = max(1, int(target_val / estimated_fill_price)) if estimated_fill_price > 0 else 0
            estimated_notional = round(calculated_qty * estimated_fill_price, 2)

            # Pre-evaluate deterministic risk
            risk_passed = True
            risk_notes = []

            if estimated_notional > max_order_val:
                risk_passed = False
                risk_notes.append(f"Notional ₹{estimated_notional:,.2f} exceeds 10% single order limit of ₹{max_order_val:,.2f}")

            if side == "BUY":
                fee_pct = getattr(settings, "COMMISSION_PCT", 0.1)
                est_fee = round(estimated_notional * (fee_pct / 100.0), 2)
                total_outflow = estimated_notional + est_fee
                if total_outflow > cash:
                    risk_passed = False
                    risk_notes.append(f"Insufficient cash (Requires ₹{total_outflow:,.2f}, Available ₹{cash:,.2f})")
            elif side == "SELL":
                cur_pos = db.query(Position).filter(Position.symbol == sym).first()
                cur_qty = cur_pos.quantity if cur_pos else 0
                if calculated_qty > cur_qty:
                    risk_passed = False
                    risk_notes.append(f"Prohibited: Short selling not permitted (Holdings: {cur_qty}, Proposed: {calculated_qty})")

            status = "PENDING_CONFIRMATION" if risk_passed else "REJECTED_BY_RISK"

            rec = PaperTradeProposal(
                proposal_id=proposal_id,
                run_id=run_id,
                event_id=event_id,
                snapshot_id=snapshot_id,
                symbol=sym,
                side=side.upper(),
                requested_qty=calculated_qty,
                estimated_price=estimated_fill_price,
                estimated_notional=estimated_notional,
                reason=reason,
                risk_check_passed=risk_passed,
                risk_notes="; ".join(risk_notes) if risk_notes else "Passed 10% limit and cash sufficiency pre-checks.",
                status=status,
                created_at=now_utc,
                expires_at=expires_at
            )
            db.add(rec)
            db.commit()

        logger.info(f"Created Paper Trade Proposal {proposal_id}: {side} {calculated_qty} {sym} @ ₹{estimated_fill_price} (Status: {status})")
        return {
            "proposal_id": proposal_id,
            "run_id": run_id,
            "symbol": sym,
            "side": side,
            "requested_qty": calculated_qty,
            "estimated_price": estimated_fill_price,
            "estimated_notional": estimated_notional,
            "risk_check_passed": risk_passed,
            "risk_notes": "; ".join(risk_notes) if risk_notes else "Risk pre-checks passed.",
            "status": status,
            "expires_at": expires_at.isoformat()
        }

    def list_proposals(self, status: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        """List proposals with expiration awareness."""
        now_utc = datetime.now(UTC)
        with SessionLocal() as db:
            q = db.query(PaperTradeProposal)
            if status:
                q = q.filter(PaperTradeProposal.status == status.upper())
            records = q.order_by(PaperTradeProposal.created_at.desc()).limit(limit).all()

            results = []
            for r in records:
                # Check expiration in real time
                is_expired = r.status == "PENDING_CONFIRMATION" and _dt_expired(r.expires_at, now_utc)
                current_status = "EXPIRED" if is_expired else r.status

                if is_expired and r.status != "EXPIRED":
                    r.status = "EXPIRED"
                    db.commit()

                results.append({
                    "proposal_id": r.proposal_id,
                    "run_id": r.run_id,
                    "event_id": r.event_id,
                    "snapshot_id": r.snapshot_id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "requested_qty": r.requested_qty,
                    "estimated_price": r.estimated_price,
                    "estimated_notional": r.estimated_notional,
                    "reason": r.reason,
                    "risk_check_passed": r.risk_check_passed,
                    "risk_notes": r.risk_notes,
                    "status": current_status,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    "expires_at": r.expires_at.isoformat() if r.expires_at else "",
                    "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                    "execution_order_id": r.execution_order_id
                })
            return results

    def confirm_and_execute_proposal(self, proposal_id: str) -> dict[str, Any]:
        """
        Explicit user confirmation action.
        Performs confirmation-time revalidation (expiration, duplicate fill prevention,
        cash sufficiency, 10% limit) and submits to paper broker.
        """
        now_utc = datetime.now(UTC)
        with SessionLocal() as db:
            if db.get_bind().dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            prop = db.query(PaperTradeProposal).filter_by(proposal_id=proposal_id).first()
            if not prop:
                return {"success": False, "error": "Paper proposal not found."}
            if prop.status in ("CONFIRMED", "EXECUTED"):
                return {"success": False, "error": "Paper proposal was already executed."}
            if prop.status not in ("PENDING", "PENDING_CONFIRMATION"):
                return {"success": False, "error": f"Paper proposal is {prop.status}; it cannot be executed."}
            if _dt_expired(prop.expires_at, now_utc):
                prop.status = "EXPIRED"
                db.commit()
                return {"success": False, "error": "Paper proposal has expired."}
            quote = dhan_live_feed.get_quote(prop.symbol)
            if not quote or not quote.get("price") or quote.get("freshness_status") != "LIVE":
                return {"success": False, "error": "A fresh market quote is required."}

            # Submit to local simulated paper broker
            broker_res = paper_broker.submit_and_process_order(
                db=db,
                symbol=prop.symbol,
                side=prop.side,
                requested_qty=prop.requested_qty,
                price=quote["price"],
                auto_execute=True,
                commit=False
            )

            if broker_res.get("status") in ("APPROVED", "RESIZED", "FILLED") and broker_res.get("executed", 0) > 0:
                prop.status = "EXECUTED"
                prop.confirmed_at = now_utc
                prop.execution_order_id = broker_res.get("order_id")
                db.commit()
                return {
                    "success": True,
                    "proposal_id": proposal_id,
                    "status": "EXECUTED",
                    "executed_qty": broker_res.get("executed"),
                    "fill_price": broker_res.get("price"),
                    "fee": broker_res.get("fee"),
                    "order_id": broker_res.get("order_id"),
                    "message": f"Successfully confirmed and executed {broker_res.get('executed')} shares of {prop.symbol}."
                }
            else:
                prop.status = "EXECUTION_FAILED"
                prop.rejection_reason = broker_res.get("reason", "Paper broker rejected order.")
                db.commit()
                return {
                    "success": False,
                    "proposal_id": proposal_id,
                    "status": "EXECUTION_FAILED",
                    "error": broker_res.get("reason")
                }

    def reject_proposal(self, proposal_id: str, reason: str = "Operator dismissed proposal") -> dict[str, Any]:
        """Explicit operator rejection."""
        with SessionLocal() as db:
            prop = db.query(PaperTradeProposal).filter(PaperTradeProposal.proposal_id == proposal_id).first()
            if not prop:
                return {"success": False, "error": f"Proposal '{proposal_id}' not found."}
            if prop.status not in ("PENDING", "PENDING_CONFIRMATION"):
                return {"success": False, "error": f"Paper proposal is {prop.status}; it cannot be rejected."}
            prop.status = "REJECTED_BY_OPERATOR"
            prop.rejection_reason = reason
            db.commit()
            return {"success": True, "proposal_id": proposal_id, "status": "REJECTED_BY_OPERATOR"}


paper_proposal_service = PaperProposalService()
