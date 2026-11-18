from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.db.models import Account, Asset, EquitySnapshot, Position
from app.market.dhan_adapter import dhan_live_feed
from sqlalchemy.orm import Session


class PortfolioService:
    """
    Authoritative portfolio accounting and valuation engine.
    In LIVE_ONLY mode: valuations require verified, eligible live DhanHQ quotes.
    Never falls back silently to historical prices or fabricated zeros.
    """

    def get_portfolio_summary(self, db: Session) -> dict[str, Any]:
        account = db.query(Account).first()
        if not account:
            account = Account(
                name="Primary Simulation Account",
                starting_cash=settings.INITIAL_EQUITY,
                cash_balance=settings.INITIAL_CASH,
            )
            db.add(account)
            db.commit()

        positions = db.query(Position).filter(Position.account_id == account.id).all()
        assets = {a.symbol: a for a in db.query(Asset).all()}

        # Calculate position market values and unrealized P&L
        pos_list = []
        invested_total = 0.0
        unrealized_pnl_total = 0.0
        valuation_complete = True

        for p in positions:
            live_q = dhan_live_feed.get_quote(p.symbol)
            live_price = live_q.get("price") if live_q else None
            is_eligible = live_price is not None and live_price > 0 and live_q.get("is_live", False)

            asset = assets.get(p.symbol)

            if is_eligible:
                current_price = live_price
                market_val = p.quantity * current_price
                pnl = (current_price - p.average_entry) * p.quantity
                invested_total += market_val
                unrealized_pnl_total += pnl
                val_status = "LIVE_MARKED"
            elif live_price is not None and live_price > 0:
                # Market closed or serving last available: mark to verified last session close
                current_price = live_price
                market_val = p.quantity * current_price
                pnl = (current_price - p.average_entry) * p.quantity
                invested_total += market_val
                unrealized_pnl_total += pnl
                pt = live_q.get("price_type") if live_q else "LAST_SESSION_CLOSE"
                val_status = pt if pt in ("OFFICIAL_SESSION_CLOSE", "LAST_SESSION_CLOSE", "LAST_OBSERVED_PRICE") else "LAST_SESSION_CLOSE"
            else:
                # Absolutely no verified market data available
                current_price = None
                market_val = None
                pnl = None
                valuation_complete = False
                val_status = "VALUATION_UNAVAILABLE"

            pos_list.append({
                "symbol": p.symbol,
                "name": asset.name if asset else p.symbol,
                "qty": p.quantity,
                "average": p.average_entry,
                "current_price": current_price,
                "market_value": round(market_val, 2) if market_val is not None else None,
                "unrealized_pnl": round(pnl, 2) if pnl is not None else None,
                "valuation_status": val_status,
                "allocation_pct": 0.0
            })

        if valuation_complete or not positions:
            total_equity = account.cash_balance + invested_total
            total_pnl = total_equity - account.starting_cash
            total_pnl_pct = (total_pnl / account.starting_cash) * 100.0 if account.starting_cash > 0 else 0.0
            inv_display = round(invested_total, 2)
            pnl_display = round(unrealized_pnl_total, 2)
            val_note = None
            if positions and any(p["valuation_status"] != "LIVE_MARKED" for p in pos_list):
                val_note = "Portfolio marked to verified last session close. Closing valuation, not real-time intraday equity."
        else:
            total_equity = account.cash_balance
            total_pnl = 0.0
            total_pnl_pct = 0.0
            inv_display = None
            pnl_display = None
            val_note = "Holding valuation awaiting verified market observations. Cash and cost basis remain fully verified."

        # Assign allocation percentages if total equity and position market values are available
        for pos in pos_list:
            if pos["market_value"] is not None and total_equity > 0:
                pos["allocation_pct"] = round((pos["market_value"] / total_equity) * 100.0, 1)
            else:
                pos["allocation_pct"] = None

        # Drawdown computation
        snapshots = db.query(EquitySnapshot).filter(EquitySnapshot.account_id == account.id).order_by(EquitySnapshot.timestamp.asc()).all()
        peak_equity = max([s.total_equity for s in snapshots] + [total_equity, account.starting_cash])
        current_drawdown = max(0.0, ((peak_equity - total_equity) / peak_equity) * 100.0) if peak_equity > 0 else 0.0

        # Equity history for charts
        history = []
        for s in snapshots:
            history.append({
                "time": s.time_label,
                "price": round(s.total_equity, 2),
                "equity": round(s.total_equity, 2),
            })

        # Ensure latest point is represented
        now_label = datetime.now(UTC).strftime("%H:%M")
        if not history or history[-1]["time"] != now_label:
            history.append({
                "time": now_label,
                "price": round(total_equity, 2),
                "equity": round(total_equity, 2),
            })

        return {
            "equity": round(total_equity, 2),
            "cash": round(account.cash_balance, 2),
            "invested": inv_display,
            "currency": account.currency,
            "valuation_complete": valuation_complete,
            "valuation_note": val_note,
            "positions": pos_list,
            "metrics": {
                "equity": round(total_equity, 2),
                "cash": round(account.cash_balance, 2),
                "invested": inv_display,
                "unrealized_pnl": pnl_display,
                "realized_pnl": 0.0,
                "total_pnl": round(total_pnl, 2),
                "total_pnl_pct": round(total_pnl_pct, 2),
                "current_drawdown_pct": round(current_drawdown, 2),
                "risk_status": "Guarded",
                "valuation_complete": valuation_complete,
                "valuation_note": val_note,
            },
            "history": history,
        }

    def record_snapshot(self, db: Session) -> EquitySnapshot | None:
        summary = self.get_portfolio_summary(db)
        account = db.query(Account).first()
        if not account:
            return None
        metrics = summary["metrics"]
        now = datetime.now(UTC)
        snap = EquitySnapshot(
            account_id=account.id,
            timestamp=now,
            time_label=now.strftime("%H:%M"),
            cash=metrics["cash"],
            invested=metrics["invested"] if metrics["invested"] is not None else 0.0,
            total_equity=metrics["equity"],
            pnl=metrics["total_pnl"],
            drawdown_pct=metrics["current_drawdown_pct"]
        )
        db.add(snap)
        db.commit()
        return snap


portfolio_service = PortfolioService()
