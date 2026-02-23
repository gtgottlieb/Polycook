from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import PortfolioOut
from services import paper_trading
from state import app_state

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
async def get_portfolio(db: AsyncSession = Depends(get_db)):
    summary = await paper_trading.get_portfolio_summary(db, app_state.contracts_by_token)
    return PortfolioOut(**summary)


@router.post("/reset", response_model=PortfolioOut)
async def reset_portfolio(db: AsyncSession = Depends(get_db)):
    await paper_trading.reset_portfolio(db)
    summary = await paper_trading.get_portfolio_summary(db, app_state.contracts_by_token)
    return PortfolioOut(**summary)
