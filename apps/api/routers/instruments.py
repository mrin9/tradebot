from fastapi import APIRouter, HTTPException
from packages.utils.mongo import get_db
from packages.config import settings

router = APIRouter(prefix="/api/instruments", tags=["instruments"])

@router.get("")
async def get_instruments():
    """
    Fetch all active trading instruments from the registry.
    Maps the latest active date to referenceDate for dashboard compatibility.
    """
    try:
        db = get_db()
        instruments = list(db[settings.INSTRUMENT_MASTER_COLLECTION].find({}, {'_id': 0}))
        
        for inst in instruments:
            # Map the latest active date to referenceDate for dashboard compatibility
            dates = inst.get("activeDates", [])
            if dates:
                inst["referenceDate"] = sorted(dates, reverse=True)[0]
            else:
                inst["referenceDate"] = None
                
        # Sort by latest referenceDate then instrumentType
        instruments.sort(key=lambda x: (x.get("referenceDate", "") or "", x.get("instrumentType", "") or ""), reverse=True)
        return instruments
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
