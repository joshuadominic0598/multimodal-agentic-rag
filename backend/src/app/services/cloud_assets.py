"""Read only private assets pinned to a published Azure index."""

from pathlib import Path

from app.core import store as s
from app.integrations import azure_auth, azure_cloud

def read_asset(index_id: str, asset_id: str):
    # Only asset references recorded during this app's publication can be fetched.
    index = s.get("indexes", index_id, True)
    matches = [
        x for x in index.get("blob_assets", []) if s.digest(x["local_asset"])[:16] == asset_id
    ]
    if len(matches) != 1:
        raise ValueError("Cloud asset not found in this index snapshot.")
    item = matches[0]
    profile = azure_cloud.resolve(index["azure_profile"]["id"], index["azure_profile"])
    if item["endpoint"] != profile["blob_endpoint"]:
        raise ValueError("Cloud asset endpoint changed.")
    from azure.storage.blob import BlobServiceClient

    client = BlobServiceClient(
        account_url=item["endpoint"],
        credential=profile["blob_key"]
        if profile.get("auth_mode", "api-key") == "api-key"
        else azure_auth.credential(profile),
        retry_total=0,
    )
    try:
        raw = (
            client.get_blob_client(container=item["container"], blob=item["blob_name"])
            .download_blob(max_concurrency=1)
            .readall()
        )
        import mimetypes

        mime = mimetypes.guess_type(item["local_asset"])[0] or "application/octet-stream"
        inline = mime.startswith(("image/", "audio/", "video/")) or mime == "application/pdf"
        return raw, mime, Path(item["local_asset"]).name.replace(chr(34), ""), inline
    except Exception:
        raise ValueError(
            "Could not retrieve the private cloud reference. Check Blob data access."
        ) from None
    finally:
        client.close()
