import hashlib
import json
import posixpath
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .config import get_settings


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if re.match(r"^[A-Za-z]:", value) or chr(0) in value:
        raise ValueError("Unsafe skill resource path")
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in value:
        raise ValueError("Unsafe skill resource path")
    return path.as_posix()


@lru_cache(maxsize=1)
def _s3_client():
    import boto3

    settings = get_settings()
    options = {"region_name": settings.s3_region or "us-east-1"}
    if settings.s3_endpoint_url:
        options["endpoint_url"] = settings.s3_endpoint_url
    if settings.s3_access_key_id and settings.s3_secret_access_key:
        options["aws_access_key_id"] = settings.s3_access_key_id
        options["aws_secret_access_key"] = settings.s3_secret_access_key
    return boto3.client("s3", **options)


def _s3_root(skill_id: str, version: str) -> tuple[str, str]:
    settings = get_settings()
    prefix = settings.s3_prefix.strip("/")
    parts = PurePosixPath(prefix) if prefix else PurePosixPath(".")
    if ".." in parts.parts or "\\" in prefix or chr(0) in prefix:
        raise ValueError("Unsafe object storage prefix")
    key = posixpath.join(prefix, skill_id, version) if prefix else posixpath.join(skill_id, version)
    return settings.s3_bucket, key


def save_snapshot(skill_id: str, version: str, files: dict[str, bytes]) -> tuple[str, str, list[dict]]:
    settings = get_settings()
    aggregate = hashlib.sha256()
    manifest = []
    if settings.s3_bucket:
        bucket, key_root = _s3_root(skill_id, version)
        target_uri = f"s3://{bucket}/{key_root}"
        client = _s3_client()
        for path, data in sorted(files.items()):
            safe = safe_relative_path(path)
            digest = hashlib.sha256(data).hexdigest()
            client.put_object(Bucket=bucket, Key=posixpath.join(key_root, safe), Body=data,
                              Metadata={"sha256": digest})
            manifest.append({"path": safe, "sha256": digest, "bytes": len(data)})
            aggregate.update(safe.encode() + b"\0" + bytes.fromhex(digest))
        client.put_object(Bucket=bucket, Key=posixpath.join(key_root, "manifest.json"),
                          Body=json.dumps(manifest, indent=2).encode("utf-8"),
                          ContentType="application/json")
        return target_uri, aggregate.hexdigest(), manifest

    root = settings.storage_path.resolve()
    target = (root / skill_id / version).resolve()
    if root not in target.parents:
        raise ValueError("Snapshot path escaped storage root")
    target.mkdir(parents=True, exist_ok=True)
    for path, data in sorted(files.items()):
        safe = safe_relative_path(path)
        output = (target / safe).resolve()
        if target not in output.parents:
            raise ValueError("Resource path escaped snapshot")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        manifest.append({"path": safe, "sha256": digest, "bytes": len(data)})
        aggregate.update(safe.encode() + b"\0" + bytes.fromhex(digest))
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return str(target), aggregate.hexdigest(), manifest


def read_resource(snapshot_path: str, resource_path: str) -> bytes:
    safe = safe_relative_path(resource_path)
    if snapshot_path.startswith("s3://"):
        parsed = urlsplit(snapshot_path)
        bucket = parsed.netloc
        key_root = parsed.path.lstrip("/")
        if not bucket or ".." in PurePosixPath(key_root).parts or "\\" in key_root:
            raise ValueError("Unsafe snapshot object key")
        key = posixpath.join(key_root, safe)
        try:
            return _s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:
            from botocore.exceptions import ClientError
            if isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(resource_path) from exc
            raise
    root = Path(snapshot_path).resolve()
    target = (root / safe).resolve()
    if root not in target.parents or not target.is_file():
        raise FileNotFoundError(resource_path)
    return target.read_bytes()


def make_version(commit_sha: str, files: dict[str, bytes]) -> str:
    base = commit_sha[:12] if commit_sha else hashlib.sha256(b"".join(files.values())).hexdigest()[:12]
    return f"git-{base}"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:150] or "community-skill"
