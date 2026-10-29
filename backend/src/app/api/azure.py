"""Existing-resource Azure workspace endpoints."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.schemas import AzurePlanRequest, AzureProfile, AzureSignIn
from app.integrations import azure_auth, azure_cloud
from app.services.cloud_assets import read_asset
from app.services.jobs import submit

router = APIRouter()

@router.post("/api/azure/profiles")
def azure_save(body: AzureProfile):
    return azure_cloud.save(body.model_dump())

@router.put("/api/azure/profiles/{id}")
def azure_update(id: str, body: AzureProfile):
    return azure_cloud.save(body.model_dump(), id)

@router.post("/api/azure/profiles/{id}/test")
def azure_test(id: str):
    return submit("Azure connection check", azure_cloud.test_profile, id)

@router.post("/api/azure/sign-in")
def azure_sign_in(body: AzureSignIn):
    return azure_auth.start(body.model_dump())

@router.get("/api/azure/sign-in/{id}")
def azure_sign_in_status(id: str):
    return azure_auth.status(id)

@router.post("/api/azure/plan")
def azure_plan(body: AzurePlanRequest):
    return azure_cloud.plan(body.document_id, body.stage, body.config.model_dump())

@router.get("/api/azure/assets/{index_id}/{asset_id}")
def azure_asset(index_id: str, asset_id: str):
    raw, mime, filename, inline = read_asset(index_id, asset_id)
    disposition = "inline" if inline else "attachment"
    return Response(
        raw,
        media_type=mime,
        headers={"Content-Disposition": disposition + '; filename="' + filename + '"'},
    )
