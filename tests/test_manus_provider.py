"""Tests for the Manus provider using a simulated Manus API (no network, no credits)."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from services.generation_service import (
    GenerationAuthError,
    GenerationCancelledError,
    GenerationError,
    GenerationQuotaError,
    GenerationRequest,
    get_generation_service,
)
from services.manus_provider import ManusImageService

DOWNLOAD_URL = "https://files.manus.example/output/latte.png"


def png_bytes(size=(1080, 1080)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (90, 60, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def status(agent_status, **detail):
    event = {"id": f"s-{agent_status}", "type": "status_update",
             "status_update": {"agent_status": agent_status}}
    if detail:
        event["status_update"]["status_detail"] = detail
    return event


def assistant(text="", attachments=()):
    return {"id": "a1", "type": "assistant_message",
            "assistant_message": {"content": text, "attachments": list(attachments)}}


IMAGE_ATTACHMENT = {"type": "image", "filename": "latte.png", "url": DOWNLOAD_URL, "content_type": "image/png"}


class FakeManus:
    """Simulates api.manus.ai: each listMessages call returns the next scripted page."""

    def __init__(self, pages, create_status=200, create_payload=None, detail=None):
        self.pages = list(pages)
        self.create_status = create_status
        self.create_payload = create_payload or {"ok": True, "task_id": "TASK123",
                                                 "task_url": "https://manus.im/app/TASK123"}
        self.detail = detail or {"ok": True, "has_running_background_jobs": False}
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers),
                           "body": json.loads(body) if body else None})
        if url == DOWNLOAD_URL:
            return 200, "image/png", png_bytes()
        endpoint = url.split("/v2/")[-1].split("?")[0]
        if endpoint == "task.create":
            return self.create_status, "application/json", json.dumps(self.create_payload).encode()
        if endpoint == "task.listMessages":
            page = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
            return 200, "application/json", json.dumps({"ok": True, "messages": page}).encode()
        if endpoint in ("task.sendMessage", "task.stop"):
            return 200, "application/json", b'{"ok": true}'
        if endpoint == "task.detail":
            return 200, "application/json", json.dumps(self.detail).encode()
        if endpoint == "usage.availableCredits":
            return 200, "application/json", json.dumps(
                {"ok": True, "data": {"total_credits": 300, "refresh_interval": "daily"}}).encode()
        return 404, "application/json", b'{"ok": false, "error": {"code": "not_found"}}'


def request(**overrides):
    values = dict(prompt="A cozy coffee shop social media post with a latte", design_type="Social Media Post",
                  art_style="Photorealistic", aspect_ratio="1:1 · Square Post")
    values.update(overrides)
    return GenerationRequest(**values)


def service(fake, **kwargs):
    clock = iter(range(0, 10_000, 5))
    return ManusImageService("manus-test-key", "lite", transport=fake, sleep=lambda s: None,
                             clock=lambda: next(clock), **kwargs)


class ManusLifecycleTests(unittest.TestCase):
    def test_full_lifecycle_returns_image(self) -> None:
        fake = FakeManus([[status("running")],
                          [status("running")],
                          [status("stopped"), assistant("Here is your image", [IMAGE_ATTACHMENT])]])
        progress = []
        svc = service(fake)
        svc.progress = progress.append
        image = svc.generate(request())
        self.assertEqual(image.size, (1080, 1080))

        create = fake.calls[0]
        self.assertEqual((create["method"], create["url"]), ("POST", "https://api.manus.ai/v2/task.create"))
        self.assertEqual(create["headers"]["x-manus-api-key"], "manus-test-key")
        body = create["body"]
        self.assertEqual(body["agent_profile"], "lite")
        self.assertFalse(body["interactive_mode"])
        self.assertEqual(body["share_visibility"], "private")
        text = body["message"]["content"][0]["text"]
        self.assertIn("latte", text)
        self.assertIn("exactly ONE", text)
        self.assertIn("1080×1080", text)
        self.assertEqual(svc.last_task_url, "https://manus.im/app/TASK123")
        self.assertTrue(any("working" in p for p in progress))

    def test_api_key_is_never_sent_to_download_host(self) -> None:
        fake = FakeManus([[status("stopped"), assistant("", [IMAGE_ATTACHMENT])]])
        service(fake).generate(request())
        download = [c for c in fake.calls if c["url"] == DOWNLOAD_URL][0]
        self.assertNotIn("x-manus-api-key", download["headers"])
        for call in fake.calls:
            if call["url"] != DOWNLOAD_URL:
                self.assertTrue(call["url"].startswith("https://api.manus.ai/v2/"))

    def test_waiting_state_is_answered_with_continue(self) -> None:
        fake = FakeManus([[status("waiting", waiting_for_event_type="messageAskUser")],
                          [status("running")],
                          [status("stopped"), assistant("", [IMAGE_ATTACHMENT])]])
        service(fake).generate(request())
        sends = [c for c in fake.calls if c["url"].endswith("task.sendMessage")]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["body"]["task_id"], "TASK123")
        self.assertIn("Continue", sends[0]["body"]["message"]["content"])

    def test_waiting_for_own_background_job_is_not_interrupted(self) -> None:
        # Reproduces a real Manus run: the agent waits on its image job several times, then delivers.
        job_wait = status("waiting", waiting_for_event_type="cascadeJobCall", waiting_for_event_id="JOB1")
        fake = FakeManus([[job_wait], [job_wait], [job_wait], [job_wait], [status("running")],
                          [status("stopped"), assistant("Done", [IMAGE_ATTACHMENT])]])
        progress = []
        svc = service(fake)
        svc.progress = progress.append
        self.assertEqual(svc.generate(request()).size, (1080, 1080))
        self.assertFalse([c for c in fake.calls if c["url"].endswith("task.sendMessage")],
                         "must not send 'continue' while Manus waits for its own job")
        self.assertTrue(any("generating the image" in p for p in progress))

    def test_same_question_is_answered_only_once(self) -> None:
        ask = status("waiting", waiting_for_event_type="messageAskUser", waiting_for_event_id="Q1")
        fake = FakeManus([[ask], [ask], [ask], [status("stopped"), assistant("", [IMAGE_ATTACHMENT])]])
        service(fake).generate(request())
        self.assertEqual(len([c for c in fake.calls if c["url"].endswith("task.sendMessage")]), 1)

    def test_action_approval_is_never_auto_confirmed(self) -> None:
        fake = FakeManus([[status("waiting", waiting_for_event_type="gmailSendAction",
                                  waiting_for_event_id="A1")]])
        with self.assertRaises(GenerationError) as ctx:
            service(fake).generate(request())
        self.assertIn("approve", str(ctx.exception))
        self.assertFalse([c for c in fake.calls if "confirmAction" in c["url"] or "sendMessage" in c["url"]])

    def test_stop_calls_task_stop_and_raises_cancelled(self) -> None:
        fake = FakeManus([[status("running")]])
        svc = service(fake)
        polls = {"n": 0}
        original = svc._latest_events

        def latest(task_id):
            polls["n"] += 1
            if polls["n"] == 2:
                svc.cancel()  # user clicks Stop while Manus is working
            return original(task_id)

        svc._latest_events = latest
        with self.assertRaises(GenerationCancelledError) as ctx:
            svc.generate(request())
        self.assertIn("stopped too", str(ctx.exception))
        stops = [c for c in fake.calls if c["url"].endswith("task.stop")]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["body"], {"task_id": "TASK123"})
        self.assertFalse([c for c in fake.calls if c["url"] == DOWNLOAD_URL], "no download after Stop")

    def test_a_stopped_run_does_not_affect_the_next_run(self) -> None:
        svc = service(FakeManus([[status("stopped"), assistant("", [IMAGE_ATTACHMENT])]]))
        svc.cancel()  # cancelling with nothing running is harmless
        self.assertEqual(svc.generate(request()).size, (1080, 1080))

    def test_endless_waiting_gives_up_with_task_link(self) -> None:
        fake = FakeManus([[status("waiting", waiting_for_event_type="messageAskUser")]])
        with self.assertRaises(GenerationError) as ctx:
            service(fake).generate(request())
        self.assertIn("manus.im/app/TASK123", str(ctx.exception))

    def test_stopped_without_image_reports_reply(self) -> None:
        fake = FakeManus([[status("stopped"), assistant("I created a website instead.")]])
        with self.assertRaises(GenerationError) as ctx:
            service(fake).generate(request())
        self.assertIn("without attaching an image", str(ctx.exception))
        self.assertIn("website", str(ctx.exception))

    def test_background_jobs_keep_polling_until_image(self) -> None:
        fake = FakeManus([[status("stopped"), assistant("Working on it")],
                          [status("stopped"), assistant("", [IMAGE_ATTACHMENT])]],
                         detail={"ok": True, "has_running_background_jobs": True})
        self.assertEqual(service(fake).generate(request()).size, (1080, 1080))

    def test_agent_error_and_timeout(self) -> None:
        fake = FakeManus([[status("error"), {"id": "e", "type": "error_message",
                                             "error_message": {"message": "Out of credits"}}]])
        with self.assertRaises(GenerationError) as ctx:
            service(fake).generate(request())
        self.assertIn("Out of credits", str(ctx.exception))
        with self.assertRaises(GenerationError) as ctx:
            service(FakeManus([[status("running")]]), timeout=60).generate(request())
        self.assertIn("did not finish", str(ctx.exception))

    def test_http_errors_are_mapped(self) -> None:
        cases = [(401, {"ok": False, "error": {"code": "unauthenticated", "message": "bad key"}}, GenerationAuthError),
                 (429, {"ok": False, "error": {"code": "rate_limited", "message": "slow down"}}, GenerationQuotaError),
                 (400, {"ok": False, "error": {"code": "invalid_argument", "message": "Insufficient credits"}},
                  GenerationQuotaError)]
        for code, payload, error_type in cases:
            with self.subTest(code=code), self.assertRaises(error_type):
                service(FakeManus([[]], create_status=code, create_payload=payload)).generate(request())

    def test_reference_image_is_attached_as_data_uri(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "shop.jpg"
            Image.new("RGB", (2400, 1600), (20, 40, 60)).save(ref)
            fake = FakeManus([[status("stopped"), assistant("", [IMAGE_ATTACHMENT])]])
            service(fake).generate(request(reference_image=ref))
        part = fake.calls[0]["body"]["message"]["content"][1]
        self.assertEqual(part["type"], "file")
        self.assertTrue(part["file_data"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(part["filename"], "reference.jpg")

    def test_invalid_prompt_creates_no_task(self) -> None:
        fake = FakeManus([[]])
        with self.assertRaises(ValueError):
            service(fake).generate(request(prompt="hi"))
        self.assertEqual(fake.calls, [])

    def test_check_connection_and_selection(self) -> None:
        self.assertEqual(service(FakeManus([[]])).check_connection(), "300 credits available (refreshes daily)")
        settings = {"AI_PROVIDER": "manus", "MANUS_API_KEY": "k", "MANUS_AGENT_PROFILE": "standard"}
        with mock.patch("services.config.get_setting", side_effect=lambda name, *a, **k: settings.get(name)):
            svc = get_generation_service()
        self.assertIsInstance(svc, ManusImageService)
        self.assertEqual(svc.model, "standard")
        settings.pop("MANUS_API_KEY")
        with mock.patch("services.config.get_setting", side_effect=lambda name, *a, **k: settings.get(name)):
            self.assertFalse(get_generation_service().is_configured)


if __name__ == "__main__":
    unittest.main()
