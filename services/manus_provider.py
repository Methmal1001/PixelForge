"""Manus AI provider (Manus API v2, https://open.manus.ai/docs/v2).

Manus is an autonomous agent, not a single image endpoint, so one generation is:

1. POST /v2/task.create   - a task asking for exactly one image file
2. GET  /v2/task.listMessages - poll until the agent status is ``stopped``
   (``waiting`` is answered with "continue"; ``error`` fails the request)
3. download the newest ``assistant_message`` attachment of type ``image``

Tasks typically take one to several minutes and consume Manus credits. The API
key is only ever sent to api.manus.ai, never to attachment download hosts.
"""

from __future__ import annotations

import base64
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from PIL import Image, UnidentifiedImageError

from services.generation_service import (
    GenerationAuthError,
    GenerationCancelledError,
    GenerationError,
    GenerationQuotaError,
    GenerationRequest,
    ImageGenerationService,
    PRESET_ASPECT_RATIOS,
    compose_prompt,
)
from services.image_processor import ImageLoadError, load_image, make_thumbnail, normalize_mode
from models.presets import find_preset

API_BASE = "https://api.manus.ai/v2"
AGENT_PROFILES = {
    "lite": "Lite (fewest credits)",
    "standard": "Standard",
    "max": "Max (highest quality, most credits)",
}
DEFAULT_PROFILE = "lite"
POLL_INTERVAL = 5.0
TASK_TIMEOUT = 15 * 60
MAX_CONTINUES = 3
# "waiting" reasons from status_detail.waiting_for_event_type
BACKGROUND_WAIT_TYPES = {"cascadeJobCall"}           # agent waits for its own job: keep polling
ASK_USER_TYPES = {"messageAskUser", "cascadeAskUser"}  # agent asks a question: reply "continue"
REFERENCE_MAX_SIDE = 1536

# (method, url, headers, body, timeout) -> (status_code, content_type, body)
Transport = Callable[[str, str, dict, bytes | None, float], tuple[int, str, bytes]]
Progress = Callable[[str], None]


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None,
                     timeout: float) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise GenerationError(
            f"Could not reach Manus ({reason}). Check your internet connection and try again."
        ) from exc


class ManusImageService(ImageGenerationService):
    name = "Manus AI"
    short_name = "Manus"
    supports_reference = True

    def __init__(self, api_key: str, agent_profile: str = DEFAULT_PROFILE, *,
                 transport: Transport | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, timeout: float = TASK_TIMEOUT) -> None:
        self.api_key = (api_key or "").strip()
        self.model = agent_profile if agent_profile in AGENT_PROFILES else DEFAULT_PROFILE
        self.progress: Progress | None = None
        self.last_task_url: str | None = None
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def ready_detail(self) -> str:
        return (f"Agent profile: {self.model}. Each Generate runs one Manus task (uses credits, usually "
                "1–5 minutes). Reference images are sent with the task.")

    # ------------------------------------------------------------------ HTTP helpers

    def _report(self, text: str) -> None:
        if self.progress:
            self.progress(text)

    def _api(self, method: str, endpoint: str, *, params: dict | None = None, body: dict | None = None) -> dict:
        if not self.api_key:
            raise GenerationAuthError("No Manus API key is configured. Add it in Settings → AI provider.")
        url = f"{API_BASE}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"x-manus-api-key": self.api_key, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        status, _ctype, raw = self._transport(method, url, headers, data, 60)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if status != 200 or payload.get("ok") is False:
            raise self._error_for(status, payload)
        return payload

    @staticmethod
    def _error_for(status: int, payload: dict) -> GenerationError:
        error = payload.get("error") or {}
        code = str(error.get("code", "")).lower()
        message = str(error.get("message", "")).strip()
        if status == 401 or code == "unauthenticated":
            return GenerationAuthError("Manus rejected the API key. Check it in Settings → AI provider.")
        if status == 403 or code == "permission_denied":
            return GenerationAuthError(f"This Manus API key is not allowed to do that. {message[:200]}".strip())
        if status == 429 or code == "rate_limited":
            return GenerationQuotaError("Manus rate limit reached. Wait a minute and try again.")
        if "credit" in message.lower():
            return GenerationQuotaError(f"Manus reports a credit problem: {message[:240]}")
        if status >= 500 or code == "internal":
            return GenerationError(f"Manus had a temporary problem ({status}). Try again shortly.")
        return GenerationError(f"Manus request failed ({status}). {message[:300]}".strip())

    # ------------------------------------------------------------------ request building

    def build_instruction(self, request: GenerationRequest) -> str:
        preset = find_preset(request.preset_key)
        size = f"{preset.width}×{preset.height} px" if preset else "1080×1080 px"
        ratio = PRESET_ASPECT_RATIOS.get(request.preset_key, "1:1")
        return (
            compose_prompt(request, with_reference=bool(request.reference_image))
            + "\n\nDeliverable: generate exactly ONE finished image file (PNG or JPEG), "
            f"{size} ({ratio}). Attach the image file itself to your final reply. "
            "Do not ask clarifying questions, do not build a website or slides, and do not return "
            "only a description or a link — the image file is the only required output."
        )

    def _reference_part(self, request: GenerationRequest) -> dict | None:
        if not request.reference_image:
            return None
        try:
            image = make_thumbnail(load_image(request.reference_image), REFERENCE_MAX_SIDE)
        except ImageLoadError as exc:
            raise GenerationError(f"The reference image could not be used: {exc}") from exc
        buffer = io.BytesIO()
        mime, fmt, ext = ("image/png", "PNG", "png") if image.mode == "RGBA" else ("image/jpeg", "JPEG", "jpg")
        image.save(buffer, fmt, **({"quality": 90} if fmt == "JPEG" else {}))
        data = base64.b64encode(buffer.getvalue()).decode()
        return {"type": "file", "file_data": f"data:{mime};base64,{data}",
                "filename": f"reference.{ext}", "mime_type": mime}

    def build_task_body(self, request: GenerationRequest) -> dict:
        content: list[dict] = [{"type": "text", "text": self.build_instruction(request)}]
        reference = self._reference_part(request)
        if reference:
            content.append(reference)
        return {
            "message": {"content": content},
            "agent_profile": self.model,
            "interactive_mode": False,
            "share_visibility": "private",
            "title": f"PixelForge: {request.prompt.strip()[:60]}",
        }

    # ------------------------------------------------------------------ generation

    def generate(self, request: GenerationRequest) -> Image.Image:
        request.validate()
        cancel = self.begin_generation()
        self._report("Creating Manus task…")
        created = self._api("POST", "task.create", body=self.build_task_body(request))
        task_id = created.get("task_id")
        if not task_id:
            raise GenerationError("Manus did not return a task id.")
        self.last_task_url = created.get("task_url")
        attachment = self._wait_for_image(task_id, cancel)
        self._check_cancel(task_id, cancel)
        self._report("Downloading image from Manus…")
        return self._download(attachment)

    def stop_task(self, task_id: str) -> bool:
        """Stop a Manus task so it stops using credits. Returns True on success."""
        try:
            self._api("POST", "task.stop", body={"task_id": task_id})
            return True
        except GenerationError:
            return False

    def _check_cancel(self, task_id: str, cancel) -> None:
        if cancel is not None and cancel.is_set():
            stopped = self.stop_task(task_id)
            raise GenerationCancelledError(
                "Generation stopped. " + ("The Manus task was stopped too." if stopped else
                                          f"The Manus task could not be stopped automatically: {self.last_task_url}"))

    def _latest_events(self, task_id: str) -> list[dict]:
        payload = self._api("GET", "task.listMessages",
                            params={"task_id": task_id, "order": "desc", "limit": 50})
        return payload.get("messages") or []

    @staticmethod
    def _latest_status(events: list[dict]) -> dict | None:
        for event in events:  # newest first
            if event.get("type") == "status_update":
                return event.get("status_update") or {}
        return None

    @staticmethod
    def find_image_attachment(events: list[dict]) -> dict | None:
        for event in events:  # newest first
            if event.get("type") != "assistant_message":
                continue
            for attachment in (event.get("assistant_message") or {}).get("attachments") or []:
                content_type = str(attachment.get("content_type", ""))
                if attachment.get("url") and (attachment.get("type") == "image" or content_type.startswith("image/")):
                    return attachment
        return None

    @staticmethod
    def _assistant_text(events: list[dict]) -> str:
        for event in events:
            if event.get("type") == "assistant_message":
                text = (event.get("assistant_message") or {}).get("content") or ""
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    def _wait_for_image(self, task_id: str, cancel=None) -> dict:
        start = self._clock()
        continues = 0
        answered: set[str] = set()
        while True:
            self._check_cancel(task_id, cancel)
            elapsed = self._clock() - start
            if elapsed > self._timeout:
                raise GenerationError(
                    f"Manus did not finish within {int(self._timeout // 60)} minutes. "
                    f"You can check the task in Manus: {self.last_task_url or task_id}")
            events = self._latest_events(task_id)
            status = self._latest_status(events) or {}
            agent_status = status.get("agent_status", "running")
            minutes, seconds = divmod(int(elapsed), 60)
            self._report(f"Manus is working… {minutes}:{seconds:02d} elapsed ({agent_status})")

            if agent_status == "error":
                detail = ""
                for event in events:
                    if event.get("type") == "error_message":
                        detail = str((event.get("error_message") or {}).get("message", "")
                                     or event.get("error_message") or "")
                        break
                raise GenerationError(f"Manus reported an error. {detail[:300]}".strip())

            if agent_status == "waiting":
                detail = status.get("status_detail") or {}
                kind = detail.get("waiting_for_event_type") or ""
                event_id = detail.get("waiting_for_event_id") or ""
                if kind in BACKGROUND_WAIT_TYPES:
                    # Manus is waiting for its own job (e.g. the image generator) to finish.
                    # This is normal: keep polling and do not interrupt it.
                    self._report(f"Manus is generating the image… {minutes}:{seconds:02d} elapsed")
                elif kind in ASK_USER_TYPES or not kind:
                    if event_id and event_id in answered:
                        pass  # already replied to this question; give Manus time to resume
                    elif continues >= MAX_CONTINUES:
                        raise GenerationError("Manus keeps asking for input. Open the task in Manus to "
                                              f"continue: {self.last_task_url or task_id}")
                    else:
                        continues += 1
                        answered.add(event_id)
                        self._api("POST", "task.sendMessage", body={
                            "task_id": task_id,
                            "message": {"content": "Continue and use your best judgment. Do not ask "
                                                   "questions. Generate the image now and attach the image file."},
                        })
                else:
                    # An action needing approval (e.g. sending an email). Never auto-approve.
                    raise GenerationError(
                        f"Manus is waiting for you to approve an action ({kind}). "
                        f"Review it in Manus: {self.last_task_url or task_id}")

            elif agent_status == "stopped":
                attachment = self.find_image_attachment(events)
                if attachment:
                    return attachment
                detail = self._task_detail(task_id)
                if not detail.get("has_running_background_jobs"):
                    reply = self._assistant_text(events)
                    raise GenerationError(
                        "Manus finished without attaching an image"
                        + (f": “{reply[:220]}”" if reply else ".")
                        + " Try rephrasing the prompt.")
            for _ in range(int(POLL_INTERVAL / 0.25)):  # short slices so Stop reacts quickly
                if cancel is not None and cancel.is_set():
                    break
                self._sleep(0.25)

    def _task_detail(self, task_id: str) -> dict:
        try:
            return self._api("GET", "task.detail", params={"task_id": task_id})
        except GenerationError:
            return {}

    def _download(self, attachment: dict) -> Image.Image:
        url = attachment["url"]
        # The attachment URL is a download link; the API key is deliberately NOT sent to it.
        status, _ctype, body = self._transport("GET", url, {"User-Agent": "PixelForgeAIStudio/0.2"}, None, 120)
        if status != 200:
            raise GenerationError(f"Downloading the image from Manus failed ({status}).")
        try:
            with Image.open(io.BytesIO(body)) as image:
                image.load()
                return normalize_mode(image)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise GenerationError("Manus returned a file that is not a readable image.") from exc

    # ------------------------------------------------------------------ connection test

    def check_connection(self) -> str:
        """Verify the key without creating a task. Returns a short credit summary."""
        payload = self._api("GET", "usage.availableCredits")
        data = payload.get("data") or {}
        total = data.get("total_credits")
        if total is None:
            return "key accepted"
        refresh = data.get("refresh_interval")
        return f"{total} credits available" + (f" (refreshes {refresh})" if refresh else "")
