"""Ground-truth evaluation and independent review endpoints."""

from fastapi import APIRouter, File, Form, UploadFile

from app.agents.evaluation import parse_dataset, run_evaluation
from app.core import store as s
from app.core.schemas import Evaluation, Review
from app.services.jobs import submit

router = APIRouter()

@router.post("/api/reviews/{id}")
def review(id: str, body: Review):
    return s.put("reviews", id, {**body.model_dump(), "updated": s.now()})

@router.get("/api/reviews/{id}")
def get_review(id: str):
    return s.get("reviews", id)

@router.post("/api/datasets")
async def dataset(
    file: UploadFile = File(...), document_id: str = Form(...), index_id: str = Form(...)
):
    return parse_dataset(
        await file.read(3 * 1024 * 1024 + 1), file.filename or "dataset.json", document_id, index_id
    )

@router.get("/api/datasets/{id}")
def dataset_get(id: str):
    return s.get("datasets", id, True)

@router.post("/api/evaluations")
def evaluation(body: Evaluation):
    def run(id):
        return run_evaluation(
            body.dataset_id, body.connection_ids, id, body.max_calls, body.judge_id, body.max_passes
        )

    return submit("evaluation", run)

@router.get("/api/evaluations/{id}")
def get_evaluation(id: str):
    obj = s.get("evaluations", id, True)
    obj["reviews"] = {x["run_id"]: s.get("reviews", x["run_id"]) for x in obj.get("results", [])}
    return obj
