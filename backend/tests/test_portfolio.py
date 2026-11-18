from app.portfolio.service import portfolio_service


def test_portfolio_valuation(db):
    summary = portfolio_service.get_portfolio_summary(db)

    assert "equity" in summary
    assert "cash" in summary
    assert "positions" in summary
    assert "metrics" in summary

    # Equity must equal cash + sum(market values)
    invested = sum(p["market_value"] for p in summary["positions"])
    assert round(summary["equity"], 1) == round(summary["cash"] + invested, 1)


def test_portfolio_record_snapshot(db):
    snap = portfolio_service.record_snapshot(db)
    assert snap.total_equity > 0
    assert snap.time_label is not None
