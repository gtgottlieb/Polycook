from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import PaperTrade, TradeCreate, TradeOut
from services import paper_trading
from state import app_state

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=list[TradeOut])
async def list_trades(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PaperTrade).order_by(PaperTrade.created_at.desc()))
    trades = result.scalars().all()
    contracts_by_token = app_state.contracts_by_token
    output = []
    for t in trades:
        if t.status == "open":
            unrealized = paper_trading.compute_unrealized_pnl(t, contracts_by_token)
        else:
            unrealized = None
        output.append(TradeOut.from_db(t, unrealized_pnl=unrealized))
    return output


@router.post("", response_model=TradeOut, status_code=201)
async def create_trade(body: TradeCreate, db: AsyncSession = Depends(get_db)):
    opp = next((o for o in app_state.opportunities if o.id == body.opportunity_id), None)
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found or no longer valid")
    try:
        return await paper_trading.create_paper_trade(db, opp, body.size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{trade_id}/close", response_model=TradeOut)
async def close_trade(trade_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await paper_trading.close_paper_trade(
            db, trade_id, app_state.contracts_by_token
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
