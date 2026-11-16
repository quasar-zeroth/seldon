"""Online transcript services. This is the only transcript module that uses the network.

`youtube`: the video's own caption tracks (creator-uploaded or YouTube's automatic
speech recognition), read through youtube-transcript-api. No key.
`supadata`: hosted transcript API (YouTube, TikTok, Instagram, X, Facebook and
media file URLs) that can AI-transcribe videos without captions. Needs
SUPADATA_API_KEY. Neither service is a model provider for Seldon's reasoning.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

SUPADATA_URL = "https://api.supadata.ai/v1"
SUPADATA_KEY_ENV = "SUPADATA_API_KEY"
TIMEOUT_SECONDS = 30.0
JOB_TIMEOUT_SECONDS = 600.0
JOB_POLL_SECONDS = 3.0
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "youtu.be"}
_TRACKING = {"si", "fbclid", "igshid", "feature", "ref", "ref_src"}
_PLATFORMS = {"tiktok.com": "tiktok", "instagram.com": "instagram", "x.com": "x", "twitter.com": "x", "facebook.com": "facebook", "fb.watch": "facebook", "vimeo.com": "vimeo"}


class TranscriptUnavailable(Exception):
    """The service answered, but no transcript exists for this media/language."""


class ServiceError(Exception):
    """The service could not be reached, refused the request or is not configured."""


@dataclass(frozen=True)
class MediaRef:
    platform: str
    media_id: str
    url: str

    def at(self, start: float) -> str:
        """Deep link to a moment in the video."""
        if self.platform == "youtube":
            return f"https://www.youtube.com/watch?v={self.media_id}&t={int(start)}s"
        return f"{self.url}#t={int(start)}"


def parse_media_url(url: str) -> MediaRef:
    text = url.strip()
    if _YOUTUBE_ID.match(text):
        return MediaRef("youtube", text, f"https://www.youtube.com/watch?v={text}")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Media URL must be HTTP(S)")
    host = parsed.hostname.lower().removeprefix("www.")
    if host in _YOUTUBE_HOSTS or host.endswith(".youtube.com"):
        parts = [p for p in parsed.path.split("/") if p]
        candidate = None
        if host == "youtu.be" and parts:
            candidate = parts[0]
        elif parts[:1] == ["watch"] or not parts:
            candidate = (parse_qs(parsed.query).get("v") or [None])[0]
        elif len(parts) >= 2 and parts[0] in {"shorts", "live", "embed", "v", "e"}:
            candidate = parts[1]
        if not candidate or not _YOUTUBE_ID.match(candidate):
            raise ValueError("Could not find an 11-character YouTube video ID in the URL")
        return MediaRef("youtube", candidate, f"https://www.youtube.com/watch?v={candidate}")
    platform = next((name for suffix, name in _PLATFORMS.items() if host == suffix or host.endswith("." + suffix)), "web")
    query = urlencode([(k, v) for k, v in parse_qs(parsed.query).items() if not (k.lower().startswith("utm_") or k.lower() in _TRACKING)], doseq=True)
    netloc = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    canonical = urlunparse((parsed.scheme, netloc, parsed.path, "", query, ""))
    return MediaRef(platform, hashlib.sha256(canonical.encode()).hexdigest()[:16], canonical)


def _http() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})


def _timestamp(text: str | None) -> str | None:
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


# ----------------------------------------------------------------------------- YouTube


def youtube_captions(video_id: str, languages: list[str]) -> dict:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api import _errors as errors
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ServiceError("youtube-transcript-api is not installed; run uv sync") from exc
    unavailable = tuple(getattr(errors, name) for name in ("TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable", "VideoUnplayable", "AgeRestricted", "InvalidVideoId") if hasattr(errors, name))
    try:
        tracks = list(YouTubeTranscriptApi().list(video_id))
    except unavailable as exc:
        raise TranscriptUnavailable(_first_line(exc)) from exc
    except Exception as exc:  # blocked IPs, network failures, page changes
        raise ServiceError(f"YouTube captions request failed: {_first_line(exc)}") from exc
    available = [{"language": t.language_code, "name": t.language, "kind": "auto-generated" if t.is_generated else "manual"} for t in tracks]
    spoken = [t.language_code for t in tracks if t.is_generated]
    wanted = languages or spoken[:1] or [t.language_code for t in tracks[:1]]
    track = None
    for generated in (False, True):  # creator captions before automatic speech recognition
        for code in wanted:
            track = next((t for t in tracks if t.is_generated == generated and _same_language(t.language_code, code)), None)
            if track:
                break
        if track:
            break
    if track is None:
        raise TranscriptUnavailable(f"No captions in {', '.join(wanted)}; available: {', '.join(sorted({a['language'] for a in available})) or 'none'}")
    try:
        fetched = track.fetch()
    except Exception as exc:
        raise ServiceError(f"YouTube caption download failed: {_first_line(exc)}") from exc
    segments = [{"start": float(s.start), "duration": float(s.duration), "text": html.unescape(s.text)} for s in fetched.snippets if s.text.strip()]
    if not segments:
        raise TranscriptUnavailable("The caption track is empty")
    return {"service": "youtube", "segments": segments, "language": track.language_code, "caption_kind": "auto-generated" if track.is_generated else "manual", "available": available, "detail": "YouTube caption track"}


def _same_language(code: str, wanted: str) -> bool:
    code, wanted = code.lower(), wanted.lower()
    return code == wanted or code.split("-")[0] == wanted


def _first_line(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return next((line.strip() for line in text if line.strip() and not line.startswith("http")), exc.__class__.__name__)[:300]


def youtube_metadata(video_id: str) -> tuple[dict, list[str]]:
    """Best-effort title/channel/upload date. Missing fields stay unknown."""
    meta: dict = {}
    warnings: list[str] = []
    watch = f"https://www.youtube.com/watch?v={video_id}"
    with _http() as client:
        try:
            response = client.get("https://www.youtube.com/oembed", params={"url": watch, "format": "json"})
            if response.status_code == 200:
                data = response.json()
                meta.update(title=data.get("title"), channel=data.get("author_name"), channel_url=data.get("author_url"))
            else:
                warnings.append(f"oEmbed metadata unavailable (HTTP {response.status_code})")
        except (httpx.HTTPError, ValueError) as exc:
            warnings.append(f"oEmbed metadata failed: {_first_line(exc)}")
        try:
            page = client.get(watch, cookies={"CONSENT": "YES+1"}).text
            meta.update(_watch_page(page))
        except httpx.HTTPError as exc:
            warnings.append(f"Watch-page metadata failed: {_first_line(exc)}")
    if not meta.get("published_at"):
        warnings.append("Upload date unknown; supply it before citing excerpts in a dated forecast")
    return {k: v for k, v in meta.items() if v not in (None, "")}, warnings


def _watch_page(page: str) -> dict:
    def find(pattern):
        match = re.search(pattern, page)
        return match.group(1) if match else None

    published = find(r'"publishDate":"([^"]+)"') or find(r'itemprop="datePublished" content="([^"]+)"') or find(r'"uploadDate":"([^"]+)"')
    length = find(r'"lengthSeconds":"(\d+)"')
    channel_id = find(r'"channelId":"(UC[\w-]{22})"')
    title = find(r'<meta name="title" content="([^"]*)"')
    channel = find(r'"ownerChannelName":"((?:[^"\\]|\\.)*)"')
    out = {
        "published_at": _timestamp(published),
        "duration_seconds": float(length) if length else None,
        "channel_id": channel_id,
        "channel_url": f"https://www.youtube.com/channel/{channel_id}" if channel_id else None,
    }
    if title:
        out["title"] = html.unescape(title)
    if channel:
        try:
            out["channel"] = json.loads(f'"{channel}"')
        except ValueError:
            out["channel"] = channel
    return out


# ----------------------------------------------------------------------------- Supadata


def supadata_key() -> str | None:
    return os.environ.get(SUPADATA_KEY_ENV) or None


def _supadata_get(client, path: str, key: str, params: dict | None = None) -> tuple[int, dict]:
    try:
        response = client.get(f"{SUPADATA_URL}{path}", params=params or {}, headers={"x-api-key": key})
    except httpx.HTTPError as exc:
        raise ServiceError(f"Supadata request failed: {_first_line(exc)}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text[:300]}
    return response.status_code, body if isinstance(body, dict) else {"content": body}


def _supadata_error(status: int, body: dict) -> Exception:
    message = f"Supadata {body.get('error') or status}: {body.get('message') or body.get('details') or 'request failed'}"
    if status in (206, 404) or body.get("error") in {"transcript-unavailable", "not-found"}:
        return TranscriptUnavailable(message)
    return ServiceError(message)


def supadata_transcript(url: str, languages: list[str], mode: str, *, key: str | None = None, client=None) -> dict:
    key = key or supadata_key()
    if not key:
        raise ServiceError(f"Supadata needs {SUPADATA_KEY_ENV}; set it, or supply a transcript with `research transcripts import`")
    params = {"url": url, "mode": mode, "text": "false"}
    if languages:
        params["lang"] = languages[0]
    own = client is None
    client = client or _http()
    try:
        status, body = _supadata_get(client, "/transcript", key, params)
        job = body.get("jobId") if status in (200, 202) else None
        if job:
            deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
            while True:
                status, body = _supadata_get(client, f"/transcript/{job}", key)
                if status != 200:
                    raise _supadata_error(status, body)
                if body.get("status") == "completed":
                    break
                if body.get("status") == "failed":
                    error = body.get("error") or {}
                    raise TranscriptUnavailable(f"Supadata transcription job failed: {error.get('message') if isinstance(error, dict) else error}")
                if time.monotonic() > deadline:
                    raise ServiceError(f"Supadata job {job} did not finish within {JOB_TIMEOUT_SECONDS:.0f} seconds; retry later")
                time.sleep(JOB_POLL_SECONDS)
        elif status != 200:
            raise _supadata_error(status, body)
        content = body.get("content")
        if not isinstance(content, list):
            raise ServiceError("Supadata returned no timed segments")
        segments = [
            {"start": float(item.get("offset") or 0) / 1000, "duration": float(item.get("duration") or 0) / 1000, "text": html.unescape(str(item.get("text", "")))}
            for item in content
            if str(item.get("text", "")).strip()
        ]
        if not segments:
            raise TranscriptUnavailable("Supadata returned an empty transcript")
        # Only a forced generation or an async job tells us the text is machine transcription.
        kind = "ai-generated" if mode == "generate" or job else "unknown"
        detail = {"native": "Platform captions via Supadata", "generate": "AI transcription via Supadata"}.get(mode, "Platform captions or AI transcription via Supadata (not reported)")
        return {"service": "supadata", "segments": segments, "language": body.get("lang"), "caption_kind": kind, "available": [{"language": code} for code in body.get("availableLangs") or []], "detail": detail}
    finally:
        if own:
            client.close()


def supadata_metadata(url: str, *, key: str | None = None, client=None) -> tuple[dict, list[str]]:
    key = key or supadata_key()
    if not key:
        return {}, ["Title, channel and upload date unknown; supply them with research transcripts import if needed"]
    own = client is None
    client = client or _http()
    try:
        status, body = _supadata_get(client, "/metadata", key, {"url": url})
    except ServiceError as exc:
        return {}, [str(exc)]
    finally:
        if own:
            client.close()
    if status != 200:
        return {}, [f"Supadata metadata unavailable (HTTP {status})"]
    author = body.get("author") or {}
    media = body.get("media") or {}
    meta = {"title": body.get("title"), "channel": author.get("displayName") or author.get("username"), "published_at": _timestamp(body.get("createdAt")), "duration_seconds": media.get("duration")}
    warnings = [] if meta["published_at"] else ["Upload date unknown; supply it before citing excerpts in a dated forecast"]
    return {k: v for k, v in meta.items() if v not in (None, "")}, warnings


# ----------------------------------------------------------------------------- orchestration


def retrieve(url: str, languages: list[str], service: str, mode: str) -> dict:
    """Fetch timed segments plus metadata, trying free captions before the keyed service."""
    ref = parse_media_url(url)
    attempts: list[str] = []
    result = None
    if service in {"auto", "youtube"} and mode != "generate":
        if ref.platform == "youtube":
            try:
                result = youtube_captions(ref.media_id, languages)
            except (TranscriptUnavailable, ServiceError) as exc:
                attempts.append(f"youtube: {exc}")
                if service == "youtube" or (isinstance(exc, ServiceError) and not supadata_key()):
                    raise
        elif service == "youtube":
            raise ValueError("The youtube service only reads YouTube videos; use supadata or auto")
    elif service == "youtube":
        raise ValueError("YouTube captions cannot generate transcripts; use --service supadata --mode generate")
    if result is None:
        if service == "auto" and not supadata_key():
            raise TranscriptUnavailable("; ".join(attempts + [f"supadata: not configured ({SUPADATA_KEY_ENV} unset)"]) + ". Set the key for AI transcription, or supply a transcript with `research transcripts import`.")
        try:
            result = supadata_transcript(ref.url, languages, mode)
        except (TranscriptUnavailable, ServiceError) as exc:
            raise type(exc)("; ".join(attempts + [f"supadata: {exc}"])) from exc
    if ref.platform == "youtube":
        meta, warnings = youtube_metadata(ref.media_id)
    else:
        meta, warnings = supadata_metadata(ref.url)
    result.update(media={"platform": ref.platform, "media_id": ref.media_id, "url": ref.url, **meta}, warnings=warnings, attempts=attempts)
    return result
