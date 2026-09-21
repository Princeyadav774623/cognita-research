"""Where media files live.

The API receives an upload and a worker processes it, and until now both had to
see the same filesystem — so they had to be the same machine. Workers already
scale (jobs are claimed with SKIP LOCKED); the disk was what stopped machines
scaling with them.

Two backends behind one interface. Local is the default and is right for a
single-node deployment or development: no credentials, no service to run. S3 is
what makes the API and worker independent, and works against anything
S3-compatible — AWS, MinIO, R2, Spaces.

The interface is deliberately file-oriented rather than stream-oriented.
Everything downstream is ffmpeg, which wants a path it can seek in, not a
stream; pretending otherwise would mean writing a temp file at every call site
instead of one place.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import BinaryIO, Iterator, Protocol

from app.config import settings

log = logging.getLogger("storage")


class StorageError(RuntimeError):
    pass


class Storage(Protocol):
    name: str

    def put(self, key: str, source: BinaryIO | str) -> str: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def exists(self, key: str) -> bool: ...

    @contextmanager
    def local_path(self, key: str) -> Iterator[str]: ...


class LocalStorage:
    """Files on this machine's disk. The default."""

    name = "local"

    def __init__(self, root: str | None = None):
        self.root = root or settings().media_root
        os.makedirs(self.root, exist_ok=True)

    def _abs(self, key: str) -> str:
        # A key arriving with "../" in it would otherwise write anywhere the
        # process can reach. Keys are generated internally today; this stops
        # that being load-bearing.
        path = os.path.normpath(os.path.join(self.root, key.lstrip("/")))
        if not path.startswith(os.path.abspath(self.root)):
            raise StorageError(f"refusing a key that escapes the root: {key!r}")
        return path

    def put(self, key: str, source: BinaryIO | str) -> str:
        dest = self._abs(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if isinstance(source, str):
            if os.path.abspath(source) != dest:
                shutil.copyfile(source, dest)
        else:
            with open(dest, "wb") as out:
                shutil.copyfileobj(source, out)
        return key

    @contextmanager
    def local_path(self, key: str) -> Iterator[str]:
        path = self._abs(key)
        if not os.path.exists(path):
            raise StorageError(f"{key} is not in storage")
        yield path          # already local; nothing to clean up

    def delete_prefix(self, prefix: str) -> None:
        target = self._abs(prefix)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.exists(target):
            os.remove(target)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._abs(key))


class S3Storage:
    """An S3-compatible bucket. What lets the API and worker be separate hosts."""

    name = "s3"

    def __init__(self):
        cfg = settings()
        if not cfg.s3_bucket:
            raise StorageError("STORAGE_BACKEND=s3 but S3_BUCKET is not set")
        try:
            import boto3
        except ImportError as exc:
            raise StorageError(
                "STORAGE_BACKEND=s3 but boto3 is not installed. "
                "pip install boto3"
            ) from exc
        self.bucket = cfg.s3_bucket
        self.prefix = cfg.s3_prefix.strip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=cfg.s3_endpoint_url or None,
            region_name=cfg.s3_region or None,
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}".lstrip("/") if self.prefix else key

    def put(self, key: str, source: BinaryIO | str) -> str:
        if isinstance(source, str):
            self._client.upload_file(source, self.bucket, self._key(key))
        else:
            self._client.upload_fileobj(source, self.bucket, self._key(key))
        return key

    @contextmanager
    def local_path(self, key: str) -> Iterator[str]:
        """Download to a temp file for the duration of the block.

        Media is large and this is the expensive half of the abstraction, which
        is why callers take a path once and do all their work inside one block
        rather than reaching for the file repeatedly.
        """
        suffix = os.path.splitext(key)[1]
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="veracity-")
        os.close(fd)
        try:
            self._client.download_file(self.bucket, self._key(key), path)
            yield path
        finally:
            try:
                os.remove(path)
            except OSError:         # pragma: no cover
                pass

    def delete_prefix(self, prefix: str) -> None:
        full = self._key(prefix).rstrip("/") + "/"
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self._client.delete_objects(Bucket=self.bucket,
                                            Delete={"Objects": keys})

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError:
            return False


_storage: Storage | None = None


def storage() -> Storage:
    global _storage
    if _storage is None:
        backend = settings().storage_backend.lower()
        if backend == "s3":
            _storage = S3Storage()
        elif backend == "local":
            _storage = LocalStorage()
        else:
            raise StorageError(f"unknown STORAGE_BACKEND {backend!r}")
        log.info("[storage] using %s backend", _storage.name)
    return _storage


def source_key(media_id: str, filename: str) -> str:
    """Where a media item's original file lives.

    The extension is kept only so ffmpeg has something familiar to look at;
    ffprobe decides what the file actually is.
    """
    ext = os.path.splitext(filename or "")[1].lower()
    ext = ext if len(ext) <= 8 and ext.isascii() else ""
    return f"{media_id}/source{ext}"
