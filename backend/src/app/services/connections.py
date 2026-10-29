"""Connection creation, model discovery and capability verification."""

from io import BytesIO

from PIL import Image, ImageDraw

from app.core import store
from app.ingestion.extraction import asset
from app.integrations import providers

def connection(configuration: dict, copy_from: str = ""):
    if copy_from:
        original = store.get("connections", copy_from, True)
        if original["provider"] != configuration["provider"]:
            raise ValueError("A saved key can only be reused with the same provider.")
    prepared = providers.prepare(configuration, copy_from or None)
    return providers.public(store.put("connections", store.uid(), prepared))

def _probe_vision(profile, budget):
    image = Image.new("RGB", (200, 100), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((10, 10, 90, 90), fill="red")
    drawing.rectangle((110, 10, 190, 90), fill="blue")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    visual = asset("_system", "vision-test.png", buffer.getvalue())
    response, _ = providers.generate(
        profile,
        budget,
        "You are testing vision.",
        "Name the two rectangle colors.",
        [store.asset_path(visual)],
    )
    return "red" in response.lower() and "blue" in response.lower()

def test_connection(id: str):
    profile = providers.resolve(id)
    run_id = store.uid()
    budget = providers.Budget(run_id, 2)
    response, _ = providers.generate(
        profile,
        budget,
        "You are a connection test.",
        "Reply with exactly: Connection ready.",
    )
    vision_verified = _probe_vision(profile, budget) if profile.get("vision") else False
    identity_fields = [
        "provider",
        "model",
        "endpoint",
        "auth_mode",
        "tenant_id",
        "client_id",
        "secret",
        "vision",
    ]
    with store.LOCK:
        current = store.get("connections", id, True)
        if any(current.get(field) != profile.get(field) for field in identity_fields):
            raise ValueError(
                "This connection changed during its test. Test the current model and credentials again."
            )
        store.patch(
            "connections",
            id,
            tested_text=True,
            tested_vision=vision_verified,
            tested_at=store.now(),
        )
    return {"ready": True, "text": response, "vision_verified": vision_verified, "run_id": run_id}

def discover_models(configuration: dict, connection_id: str = ""):
    profile = providers.prepare(configuration, connection_id or None)
    profile["id"] = connection_id or "model-discovery"
    profile["key"] = (
        providers.cipher().decrypt(profile["secret"].encode()).decode()
        if profile.get("secret")
        else ""
    )
    return providers.list_models(profile)
