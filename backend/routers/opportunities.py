from fastapi import APIRouter
from models import OpportunityOut
from state import app_state

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityOut])
async def list_opportunities():
    """Return all current arbitrage opportunities."""
    return [OpportunityOut.from_opportunity(o) for o in app_state.opportunities]


@router.get("/{opportunity_id}", response_model=OpportunityOut)
async def get_opportunity(opportunity_id: str):
    from fastapi import HTTPException
    for opp in app_state.opportunities:
        if opp.id == opportunity_id:
            return OpportunityOut.from_opportunity(opp)
    raise HTTPException(status_code=404, detail="Opportunity not found")
