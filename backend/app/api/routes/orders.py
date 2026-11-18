from hashlib import sha256

from app.api.dependencies import get_db
from app.core.errors import OrderExecutionError
from app.db.models import Execution, LedgerEntry, Order
from app.db.models.order import OrderSubmission
from app.execution.paper_broker import executable_quote_price, paper_broker
from app.schemas.orders import ExecutionResponse, LedgerEntryResponse, OrderCreate, OrderResponse
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/orders", response_model=list[OrderResponse])
def get_orders(db: Session = Depends(get_db)):
    records = db.query(Order).order_by(Order.created_at.desc()).limit(50).all()
    return [order_response(order) for order in records]


def order_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id, symbol=order.symbol, side=order.side, requested=order.requested,
        executed=order.executed, price=order.price, fee=order.fee, status=order.status,
        reason=order.reason, time=order.created_at.strftime("%H:%M"), created_at=order.created_at,
    )


@router.post("/orders", response_model=OrderResponse)
def create_order(
    payload: OrderCreate,
    idempotency_key: str = Header(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    """Submit a paper order once for a client-supplied idempotency key."""
    digest = sha256(payload.model_dump_json().encode()).hexdigest()
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    prior = db.get(OrderSubmission, idempotency_key)
    if prior:
        if prior.request_sha256 != digest:
            raise HTTPException(409, "Idempotency key already belongs to a different order request.")
        return order_response(db.get(Order, prior.order_id))

    symbol = payload.symbol.upper()
    price = executable_quote_price(symbol) if payload.auto_execute else payload.price
    if price is None:
        raise HTTPException(409, "A fresh market quote is required for immediate paper execution.")
    result = paper_broker.submit_and_process_order(
        db=db, symbol=symbol, side=payload.side, requested_qty=payload.requested, price=price,
        auto_execute=payload.auto_execute, reason=payload.reason, commit=False,
    )
    db.add(OrderSubmission(key=idempotency_key, request_sha256=digest, order_id=result["order_id"]))
    db.commit()
    return order_response(db.get(Order, result["order_id"]))


@router.post("/orders/{order_id}/confirm", response_model=OrderResponse)
def confirm_and_execute_order(order_id: int, db: Session = Depends(get_db)):
    """Confirm and execute a proposal order staged by the decision pipeline."""
    try:
        paper_broker.execute_staged_proposal(db, order_id)
    except OrderExecutionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return order_response(db.get(Order, order_id))


@router.get("/executions", response_model=list[ExecutionResponse])
def get_executions(db: Session = Depends(get_db)):
    records = db.query(Execution).order_by(Execution.timestamp.desc()).limit(50).all()
    return records


@router.get("/ledger", response_model=list[LedgerEntryResponse])
def get_ledger(db: Session = Depends(get_db)):
    records = db.query(LedgerEntry).order_by(LedgerEntry.created_at.desc()).limit(50).all()
    return records
