from fastapi import APIRouter, HTTPException

from app.evaluation.results import latest_eval_results

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/results")
async def eval_results(current_user: UserPublic = Depends(get_current_user)):
    """Latest cached COVID-QA eval metrics. 404 if no run has been cached yet
    (run `uv run python -m app.evaluation.evals` on the backend first)."""
    row = latest_eval_results()
    if row is None:
        raise HTTPException(status_code=404, detail="No eval run cached yet.")
    return {"created_at": row["created_at"], "metrics": row["metrics"]}
