

def check_symbol_and_quantity(symbol: str, requested_qty: int, known_symbols: list[str]) -> tuple[bool, str]:
    if not symbol or symbol.upper() not in [s.upper() for s in known_symbols]:
        return False, f"Unknown or unsupported fictional asset symbol '{symbol}'."
    if requested_qty <= 0:
        return False, f"Order quantity must be positive. Received {requested_qty}."
    return True, "Valid symbol and positive quantity."


def check_cash_sufficiency(
    side: str,
    qty: int,
    price: float,
    fee_pct: float,
    available_cash: float
) -> tuple[bool, str]:
    if side.upper() == "SELL":
        return True, "Cash check passed (sell order provides cash inflow)."

    total_cost = qty * price * (1.0 + fee_pct / 100.0)
    if total_cost > available_cash:
        return False, f"Insufficient cash. Required: ₹{total_cost:,.2f}, Available: ₹{available_cash:,.2f}."
    return True, "Cash sufficiency verified."


def check_max_order_size(
    qty: int,
    price: float,
    equity: float,
    max_order_pct: float
) -> tuple[bool, int, str]:
    """
    Ensure order notional does not exceed configured % of total equity.
    If it exceeds, deterministic sizing resizes it down to allowed limit.
    """
    order_val = qty * price
    max_allowed_val = equity * (max_order_pct / 100.0)

    if order_val <= max_allowed_val + 1e-6:
        return True, qty, f"Order value ₹{order_val:,.2f} is within {max_order_pct}% equity limit (₹{max_allowed_val:,.2f})."

    resized_qty = max(0, int(max_allowed_val / price))
    return False, resized_qty, f"Resized to {max_order_pct}% max-order limit ({resized_qty} units)."


def check_asset_concentration(
    symbol: str,
    side: str,
    qty: int,
    price: float,
    equity: float,
    current_position_qty: int,
    max_allocation_pct: float
) -> tuple[bool, str]:
    if side.upper() == "SELL":
        return True, "Concentration check passed (sell reduces asset concentration)."

    projected_holding_val = (current_position_qty + qty) * price
    projected_pct = (projected_holding_val / equity) * 100.0

    if projected_pct > max_allocation_pct:
        return False, f"Maximum asset concentration ({max_allocation_pct}%) exceeded. Projected: {projected_pct:.1f}%."
    return True, f"Asset concentration within limit ({projected_pct:.1f}% <= {max_allocation_pct}%)."


def check_no_short_selling(
    side: str,
    qty: int,
    current_position_qty: int
) -> tuple[bool, str]:
    if side.upper() == "BUY":
        return True, "No leverage rule satisfied."

    if qty > current_position_qty:
        return False, f"Short selling prohibited. Available: {current_position_qty}, Attempted to sell: {qty}."
    return True, f"Holding available for sell order ({qty} <= {current_position_qty})."


def check_drawdown_limit(
    current_drawdown_pct: float,
    drawdown_halt_pct: float,
    side: str
) -> tuple[bool, str]:
    if side.upper() == "SELL":
        return True, "Risk-off liquidations permitted under drawdown halt."

    if current_drawdown_pct >= drawdown_halt_pct:
        return False, f"Portfolio drawdown ({current_drawdown_pct:.1f}%) exceeds safety threshold ({drawdown_halt_pct}%). New buy orders halted."
    return True, f"Drawdown ({current_drawdown_pct:.1f}%) within allowable limit."
