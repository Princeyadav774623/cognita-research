"""Fetch media a user pointed at, when the deployment permits it.

Off by default, and that is a product decision rather than a technical one.
Downloading from a third-party host generally breaches its terms of service; it
is defensible for a tool someone runs on their own machine and a real liability
for a hosted service. `ALLOW_REMOTE_FETCH` makes that an explicit choice by
whoever deploys this, rather than a default nobody noticed.

Local file upload has no such problem and is always available.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import settings

log = logging.getLogger("resolve")

YTDLP = shutil.which("yt-dlp") or "yt-dlp"


class ResolveError(RuntimeError):
    pass


@dataclass(frozen=True)
class Resolved:
    path: str
    title: str | None
    author: str | None
    duration_ms: int | None
    webpage_url: str | None


def check_url_is_fetchable(url: str) -> None:
    """Refuse URLs that point back inside our own network.

    Without this, "paste a link" is a server-side request forgery primitive: a
    user submits http://169.254.169.254/… or http://localhost:5432 and the
    service fetches it from inside the perimeter and hands back what it found.
    Resolution happens here, before yt-dlp sees the URL.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ResolveError("only http(s) URLs are accepted")
    host = parsed.hostname
    if not host:
        raise ResolveError("that URL has no host")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ResolveError(f"could not resolve {host}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ResolveError(
                f"{host} resolves to a private address; that is not fetchable"
            )


def fetch(url: str, dest_dir: str, *, timeout: int = 1800) -> Resolved:
    """Download the audio of `url` into `dest_dir`."""
    if not settings().allow_remote_fetch:
        raise ResolveError(
            "fetching from a URL is disabled on this server. Upload the file "
            "instead, or set ALLOW_REMOTE_FETCH=true if you have established "
            "that it is appropriate for your deployment."
        )
    check_url_is_fetchable(url)
    os.makedirs(dest_dir, exist_ok=True)

    template = os.path.join(dest_dir, "source.%(ext)s")
    cmd = [
        YTDLP,
        "--no-playlist",             # a playlist URL must not become 200 jobs
        "--no-warnings",
        "--print-json", "--no-simulate",
        "-f", "bestaudio/best",      # only audio is transcribed
        "--max-filesize", str(settings().max_upload_bytes),
        "-o", template,
        url,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ResolveError("yt-dlp is not installed on this server") from exc
    except subprocess.TimeoutExpired as exc:
        raise ResolveError(f"fetching timed out after {timeout}s") from exc

    if out.returncode != 0:
        tail = (out.stderr or "").strip().splitlines()
        raise ResolveError(tail[-1] if tail else "could not fetch that URL")

    meta = {}
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                meta = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    path = meta.get("_filename") or _only_file(dest_dir)
    if not path or not os.path.exists(path):
        raise ResolveError("the download produced no file")

    duration = meta.get("duration")
    return Resolved(
        path=path,
        title=meta.get("title"),
        author=meta.get("uploader") or meta.get("channel"),
        duration_ms=int(duration * 1000) if duration else None,
        webpage_url=meta.get("webpage_url") or url,
    )


def _only_file(directory: str) -> str | None:
    names = [n for n in os.listdir(directory) if n.startswith("source.")]
    return os.path.join(directory, names[0]) if names else None
