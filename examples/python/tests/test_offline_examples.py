from __future__ import annotations

import asyncio
import builtins
import contextlib
import csv
import io
import json
import runpy
import socket
import sys
import tempfile
import unittest
import types
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_EXAMPLES = REPO_ROOT / "examples" / "python"
sys.path.insert(0, str(PYTHON_EXAMPLES))
TEST_TOKEN = "offline-secret-token"
TEST_URL = "https://www.tiktok.com/@offline/video/1234567890123456789"


def block_network() -> list[mock._patch]:
    patches = [
        mock.patch("socket.socket.connect", side_effect=AssertionError("real socket connect blocked")),
        mock.patch("socket.socket.connect_ex", side_effect=AssertionError("real socket connect_ex blocked")),
        mock.patch("socket.create_connection", side_effect=AssertionError("real socket creation blocked")),
        mock.patch("socket.getaddrinfo", side_effect=AssertionError("real DNS lookup blocked")),
    ]
    for patcher in patches:
        patcher.start()
    return patches


NETWORK_GUARDS = block_network()

try:
    import apify_client  # noqa: F401
    import dotenv  # noqa: F401
except ImportError:
    # The offline suite exercises its fakes and does not need installed SDK code.
    apify_client_stub = types.ModuleType("apify_client")
    apify_client_stub.ApifyClient = object
    apify_client_stub.ApifyClientAsync = object
    apify_errors_stub = types.ModuleType("apify_client.errors")

    class ApifyApiError(Exception):
        pass

    class NotFoundError(ApifyApiError):
        pass

    apify_errors_stub.ApifyApiError = ApifyApiError
    apify_errors_stub.NotFoundError = NotFoundError
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: False
    sys.modules["apify_client"] = apify_client_stub
    sys.modules["apify_client.errors"] = apify_errors_stub
    sys.modules["dotenv"] = dotenv_stub

import apify_run
import async_run
import csv_batch
import single_url


class FakeRun:
    def __init__(self, run_id: str = "run-1", status: str = "SUCCEEDED", dataset_id: str | None = "dataset-1") -> None:
        self.id = run_id
        self.status = status
        self.default_dataset_id = dataset_id


class FakeSyncClient:
    def __init__(self, *, run: FakeRun | None = None, items: list[dict] | None = None) -> None:
        self.run_value = run or FakeRun()
        self.wait_result: FakeRun | dict | None = self.run_value
        self.refetched_run: FakeRun | dict | None = self.run_value
        self.wait_error: Exception | None = None
        self.get_error: Exception | None = None
        self.wait_durations: list[timedelta] = []
        self.refetched_run_ids: list[str] = []
        self.items = items if items is not None else [{"text": "offline transcript", "segments": [{"start": 0, "end": 1, "text": "offline"}], "errMsg": ""}]
        self.requested_run_ids: list[str] = []
        self.requested_dataset_ids: list[str] = []

    def run(self, run_id: str) -> SimpleNamespace:
        self.requested_run_ids.append(run_id)

        def wait_for_finish(*, wait_duration: timedelta | None, timeout: float | None = None) -> FakeRun | dict | None:
            if not isinstance(wait_duration, timedelta):
                raise TypeError("wait_duration must be timedelta")
            self.wait_durations.append(wait_duration)
            if self.wait_error:
                raise self.wait_error
            return self.wait_result

        def get() -> FakeRun | dict | None:
            self.refetched_run_ids.append(run_id)
            if self.get_error:
                raise self.get_error
            return self.refetched_run

        return SimpleNamespace(wait_for_finish=wait_for_finish, get=get)

    def dataset(self, dataset_id: str) -> SimpleNamespace:
        self.requested_dataset_ids.append(dataset_id)
        return SimpleNamespace(iterate_items=lambda: iter(self.items))


class FakeAsyncRunClient:
    def __init__(self, client: "FakeAsyncClient", run_id: str) -> None:
        self.client = client
        self.run_id = run_id

    async def get(self) -> FakeRun | None:
        self.client.requested_run_ids.append(self.run_id)
        if self.client.get_error:
            raise self.client.get_error
        return self.client.runs.get(self.run_id)

    async def wait_for_finish(self) -> FakeRun | None:
        self.client.active_waits += 1
        self.client.max_active_waits = max(self.client.max_active_waits, self.client.active_waits)
        try:
            if self.client.wait_delay:
                await asyncio.sleep(self.client.wait_delay)
            if self.client.wait_error:
                raise self.client.wait_error
            run = self.client.runs.get(self.run_id)
            if run is not None and run.status not in {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}:
                return FakeRun(run.id, status="SUCCEEDED", dataset_id=run.default_dataset_id)
            return run
        finally:
            self.client.active_waits -= 1


class FakeAsyncDataset:
    def __init__(self, items: list[dict]) -> None:
        self.items = items

    async def iterate_items(self):
        for item in self.items:
            yield item


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []

    def __init__(self, *, runs: dict[str, FakeRun] | None = None, items: list[dict] | None = None) -> None:
        self.runs = runs or {"run-1": FakeRun()}
        self.items = items if items is not None else [{"text": "offline transcript", "segments": [], "errMsg": ""}]
        self.requested_run_ids: list[str] = []
        self.requested_dataset_ids: list[str] = []
        self.get_error: Exception | None = None
        self.wait_error: Exception | None = None
        self.wait_delay = 0.0
        self.active_waits = 0
        self.max_active_waits = 0
        self.start_attempts = 0
        self.__class__.instances.append(self)

    def run(self, run_id: str) -> FakeAsyncRunClient:
        return FakeAsyncRunClient(self, run_id)

    def dataset(self, dataset_id: str) -> FakeAsyncDataset:
        self.requested_dataset_ids.append(dataset_id)
        return FakeAsyncDataset(self.items)

    def actor(self, actor_id: str) -> SimpleNamespace:
        raise AssertionError("waiting/retrieving a Run must not create a Run")


class OfflinePythonExamplesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp = Path(self.temp_dir.name)
        self.quiet_stdout = contextlib.redirect_stdout(io.StringIO())
        self.quiet_stdout.__enter__()
        self.addCleanup(self.quiet_stdout.__exit__, None, None, None)

    def test_start_actor_run_once_sends_one_post_and_never_puts_token_in_url(self) -> None:
        response = SimpleNamespace(status=201, read=lambda: json.dumps({"data": {"id": "run-abc", "status": "READY"}}).encode())

        class FakeConnection:
            instances: list["FakeConnection"] = []

            def __init__(self, host: str, timeout: int) -> None:
                self.host = host
                self.timeout = timeout
                self.requests: list[tuple] = []
                self.__class__.instances.append(self)

            def request(self, method: str, path: str, body: bytes, headers: dict) -> None:
                self.requests.append((method, path, body, headers))

            def getresponse(self):
                return response

            def close(self) -> None:
                pass

        with mock.patch.object(apify_run.http.client, "HTTPSConnection", FakeConnection):
            run = apify_run.start_actor_run_once(TEST_TOKEN, TEST_URL)

        self.assertEqual(run["id"], "run-abc")
        connection = FakeConnection.instances[0]
        self.assertEqual(len(connection.requests), 1)
        self.assertEqual(connection.host, "api.apify.com")
        method, path, body, headers = connection.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v2/actors/apple_yang~tiktok-transcripts-scraper/runs")
        self.assertNotIn(TEST_TOKEN, path)
        self.assertNotIn("token=", path)
        self.assertEqual(headers["Authorization"], f"Bearer {TEST_TOKEN}")
        self.assertEqual(json.loads(body), {"videoUrl": TEST_URL})

    def test_actor_and_url_environment_overrides_are_ignored_by_shared_helper(self) -> None:
        hosts: list[str] = []
        requests: list[tuple[str, str, dict]] = []

        class FakeConnection:
            def __init__(self, host: str, timeout: int) -> None:
                hosts.append(host)

            def request(self, method: str, path: str, body: bytes, headers: dict) -> None:
                requests.append((method, path, json.loads(body)))

            def getresponse(self):
                return SimpleNamespace(status=201, read=lambda: b'{"data":{"id":"run-1"}}')

            def close(self) -> None:
                pass

        with mock.patch.dict("os.environ", {
            "APIFY_ACTOR_ID": "S9A11NvceWaGorwwh",
            "TIKTOK_VIDEO_URL": "https://www.tiktok.com/@wrong/video/111",
        }), mock.patch.object(apify_run.http.client, "HTTPSConnection", FakeConnection):
            apify_run.start_actor_run_once(TEST_TOKEN, TEST_URL)
        self.assertEqual(hosts, ["api.apify.com"])
        self.assertEqual(requests, [("POST", "/v2/actors/apple_yang~tiktok-transcripts-scraper/runs", {"videoUrl": TEST_URL})])

    def test_empty_or_invalid_url_fails_before_http_connection(self) -> None:
        with mock.patch.object(apify_run.http.client, "HTTPSConnection") as connection:
            with self.assertRaisesRegex(ValueError, "Input error"):
                apify_run.start_actor_run_once(TEST_TOKEN, "")
            connection.assert_not_called()

    def test_start_actor_run_once_malformed_response_is_unknown_and_not_retried(self) -> None:
        class FakeConnection:
            request_count = 0

            def __init__(self, host: str, timeout: int) -> None:
                pass

            def request(self, *args, **kwargs) -> None:
                self.__class__.request_count += 1

            def getresponse(self):
                return SimpleNamespace(status=201, read=lambda: b"not-json")

            def close(self) -> None:
                pass

        with mock.patch.object(apify_run.http.client, "HTTPSConnection", FakeConnection):
            with self.assertRaises(apify_run.RunStartError) as raised:
                apify_run.start_actor_run_once(TEST_TOKEN, TEST_URL)
        self.assertTrue(raised.exception.outcome_unknown)
        self.assertIn("may have started", str(raised.exception))
        self.assertEqual(FakeConnection.request_count, 1)

    def test_non_object_and_invalid_run_response_shapes_are_unknown_without_retry(self) -> None:
        malformed_bodies = [b"null", b"[]", b'"ok"', b"123", b'{"data":null}', b'{"data":[]}', b'{"data":{"id":123}}']
        for response_body in malformed_bodies:
            with self.subTest(response_body=response_body):
                class FakeConnection:
                    request_count = 0
                    paths: list[str] = []

                    def __init__(self, host: str, timeout: int) -> None:
                        self.host = host

                    def request(self, method: str, path: str, body: bytes, headers: dict) -> None:
                        self.__class__.request_count += 1
                        self.__class__.paths.append(path)

                    def getresponse(self):
                        return SimpleNamespace(status=201, read=lambda: response_body)

                    def close(self) -> None:
                        pass

                with mock.patch.object(apify_run.http.client, "HTTPSConnection", FakeConnection):
                    with self.assertRaises(apify_run.RunStartError) as raised:
                        apify_run.start_actor_run_once(TEST_TOKEN, TEST_URL)
                self.assertTrue(raised.exception.outcome_unknown)
                self.assertIn("invalid Run structure", str(raised.exception))
                self.assertEqual(FakeConnection.request_count, 1)
                self.assertEqual(FakeConnection.paths, ["/v2/actors/apple_yang~tiktok-transcripts-scraper/runs"])

    def _run_single_main(
        self,
        *,
        run: FakeRun | None = None,
        items: list[dict] | None = None,
        create_side_effect=None,
        argv: list[str] | None = None,
    ) -> tuple[FakeSyncClient, str, str, Path, int]:
        client = FakeSyncClient(run=run, items=items)
        output_file = self.tmp / "single.json"
        stdout = io.StringIO()
        creator = mock.Mock(side_effect=create_side_effect or (lambda *args: {"id": "run-1"}))
        patches = [
            mock.patch.object(single_url, "load_dotenv"),
            mock.patch.object(single_url, "ApifyClient", return_value=client),
            mock.patch.object(single_url, "start_actor_run_once", creator),
            mock.patch.object(single_url, "OUTPUT_DIR", self.tmp),
            mock.patch.object(single_url, "OUTPUT_FILE", output_file),
            mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN, "APIFY_ACTOR_ID": "S9A11NvceWaGorwwh", "TIKTOK_VIDEO_URL": "https://www.tiktok.com/@wrong/video/111"}),
            mock.patch.object(sys, "argv", argv or ["single_url.py", "--video-url", TEST_URL]),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stack.enter_context(contextlib.redirect_stdout(stdout))
            single_url.main()
        return client, stdout.getvalue(), output_file.read_text(encoding="utf-8") if output_file.exists() else "", output_file, creator.call_count

    def test_single_url_success_waits_then_saves_full_dataset_without_optional_video_fields(self) -> None:
        items = [{"text": "offline text", "segments": [], "errMsg": "", "createTime": "2025-01-01", "duration": 12}]
        client, output, saved, output_file, create_count = self._run_single_main(items=items)
        self.assertEqual(create_count, 1)
        self.assertEqual(client.requested_run_ids, ["run-1"])
        self.assertEqual(client.wait_durations, [timedelta(seconds=single_url.DEFAULT_MAX_WAIT)])
        self.assertEqual(client.requested_dataset_ids, ["dataset-1"])
        self.assertEqual(json.loads(saved), items)
        self.assertIn("Actor: apple_yang/tiktok-transcripts-scraper", output)
        self.assertNotIn("audioUrl", saved)
        self.assertNotIn("videoUrl", saved)
        self.assertNotIn(TEST_TOKEN, output)
        self.assertNotIn(TEST_TOKEN, saved)
        self.assertTrue(output_file.is_relative_to(self.tmp))

    def test_single_output_preflight_fails_before_client_or_post_and_cleans_probe(self) -> None:
        blocker = self.tmp / "output-parent-is-file"
        blocker.write_text("preserve me", encoding="utf-8")
        output_directory = blocker / "generated"
        class FakeConnection:
            request_count = 0

            def __init__(self, *args, **kwargs) -> None:
                pass

            def request(self, *args, **kwargs) -> None:
                self.__class__.request_count += 1

            def getresponse(self):
                return SimpleNamespace(status=201, read=lambda: b'{"data":{"id":"must-not-exist"}}')

            def close(self) -> None:
                pass

        with mock.patch.object(single_url, "load_dotenv") as load_env, \
             mock.patch.object(single_url, "ApifyClient") as sdk_client, \
             mock.patch.object(apify_run.http.client, "HTTPSConnection", FakeConnection), \
             mock.patch.object(single_url, "OUTPUT_DIR", output_directory), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(sys, "argv", ["single_url.py"]), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as raised:
                single_url.main()
        self.assertIn("Output directory preflight failed", str(raised.exception))
        self.assertEqual(raised.exception.code, str(raised.exception))
        load_env.assert_not_called()
        sdk_client.assert_not_called()
        self.assertEqual(FakeConnection.request_count, 0)
        self.assertEqual(blocker.read_text(encoding="utf-8"), "preserve me")
        self.assertFalse(output_directory.exists())
        self.assertNotIn("offline-secret-token", str(raised.exception))

    def test_successful_output_preflight_removes_probe_and_preserves_existing_result(self) -> None:
        existing = self.tmp / "python-single-url-response.json"
        existing.write_text("keep existing output\n", encoding="utf-8")
        single_url.preflight_output_directory(self.tmp)
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep existing output\n")
        self.assertEqual(list(self.tmp.iterdir()), [existing])

    def test_single_max_wait_defaults_bounds_and_invalid_values_fail_before_sdk(self) -> None:
        self.assertEqual(single_url.DEFAULT_MAX_WAIT, 900)
        self.assertEqual(single_url.parse_max_wait("1"), 1)
        self.assertEqual(single_url.parse_max_wait("86400"), 86400)
        max_wait_client, _, _, _, _ = self._run_single_main(
            argv=["single_url.py", "--max-wait", "86400"],
        )
        self.assertEqual(max_wait_client.wait_durations, [timedelta(seconds=86400)])
        for invalid in ("0", "-1", "86401", "1.5", "abc", "9223372036854775807"):
            with self.subTest(invalid=invalid):
                with mock.patch.object(single_url, "load_dotenv") as load_env, \
                     mock.patch.object(single_url, "ApifyClient") as sdk_client, \
                     mock.patch.object(single_url, "start_actor_run_once") as create_run, \
                     mock.patch.object(sys, "argv", ["single_url.py", "--max-wait", invalid]), \
                     contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        single_url.main()
                self.assertEqual(raised.exception.code, 2)
                load_env.assert_not_called()
                sdk_client.assert_not_called()
                create_run.assert_not_called()

    def test_single_wait_limit_reports_same_run_and_never_creates_another_run(self) -> None:
        client = FakeSyncClient()
        client.wait_result = None
        client.refetched_run = FakeRun(run_id="existing-run", status="RUNNING")
        output = io.StringIO()
        error_output = io.StringIO()
        creator = mock.Mock(return_value={"id": "existing-run"})
        with mock.patch.object(single_url, "load_dotenv"), \
             mock.patch.object(single_url, "ApifyClient", return_value=client), \
             mock.patch.object(single_url, "start_actor_run_once", creator), \
             mock.patch.object(single_url, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(single_url, "OUTPUT_FILE", self.tmp / "timeout.json"), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(sys, "argv", ["single_url.py", "--max-wait", "1"]), \
             contextlib.redirect_stdout(output), \
             contextlib.redirect_stderr(error_output):
            with self.assertRaises(SystemExit) as raised:
                single_url.main()

        message = str(raised.exception)
        self.assertIn("may still be running", message)
        self.assertIn("python3 examples/python/async_run.py wait --run-id existing-run --max-wait 1", message)
        self.assertNotIn(TEST_TOKEN, message)
        self.assertNotIn(TEST_TOKEN, output.getvalue())
        self.assertNotIn(TEST_TOKEN, error_output.getvalue())
        self.assertEqual(creator.call_count, 1)
        self.assertEqual(client.requested_run_ids, ["existing-run"])
        self.assertEqual(client.wait_durations, [timedelta(seconds=1)])
        self.assertEqual(client.refetched_run_ids, ["existing-run"])
        self.assertEqual(client.requested_dataset_ids, [])
        self.assertFalse((self.tmp / "timeout.json").exists())

    def test_single_wait_refetch_distinguishes_missing_run_without_post(self) -> None:
        client = FakeSyncClient()
        client.wait_result = None
        client.refetched_run = None
        with self.assertRaisesRegex(SystemExit, "could not be found after the wait limit"):
            single_url.wait_for_existing_run(client, "missing-run", 900)
        self.assertEqual(client.requested_run_ids, ["missing-run"])
        self.assertEqual(client.refetched_run_ids, ["missing-run"])
        self.assertEqual(client.requested_dataset_ids, [])

    def test_single_nonterminal_wait_result_is_treated_as_timeout_and_reuses_run_id(self) -> None:
        client = FakeSyncClient(run=FakeRun(run_id="existing-run", status="RUNNING"))
        client.wait_result = FakeRun(run_id="existing-run", status="RUNNING")
        client.refetched_run = None
        create_run = mock.Mock()
        with mock.patch.object(single_url, "start_actor_run_once", create_run):
            with self.assertRaises(SystemExit) as raised:
                single_url.wait_for_existing_run(client, "existing-run", 15)
        self.assertIn("may still be running", str(raised.exception))
        self.assertIn("--run-id existing-run --max-wait 15", str(raised.exception))
        self.assertEqual(client.wait_durations, [timedelta(seconds=15)])
        self.assertEqual(client.requested_run_ids, ["existing-run"])
        self.assertEqual(client.refetched_run_ids, ["existing-run"])
        self.assertEqual(client.requested_dataset_ids, [])
        create_run.assert_not_called()

    def test_single_wait_sdk_none_then_get_none_is_not_reported_as_timeout(self) -> None:
        client = FakeSyncClient()
        # apify-client 3.3.0's RunClient.wait_for_finish handles 404s internally
        # and returns None; an ID-based RunClient.get() also maps 404 to None.
        client.wait_result = None
        client.refetched_run = None
        create_run = mock.Mock()
        output = io.StringIO()
        error_output = io.StringIO()
        with mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(single_url, "start_actor_run_once", create_run), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
            with self.assertRaises(SystemExit) as raised:
                single_url.wait_for_existing_run(client, "missing-run", 900)
        self.assertIn("could not be found after the wait limit", str(raised.exception))
        self.assertNotIn("may still be running", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))
        self.assertNotIn(TEST_TOKEN, output.getvalue())
        self.assertNotIn(TEST_TOKEN, error_output.getvalue())
        self.assertEqual(client.requested_run_ids, ["missing-run"])
        self.assertEqual(client.refetched_run_ids, ["missing-run"])
        self.assertEqual(client.requested_dataset_ids, [])
        create_run.assert_not_called()

    def test_single_url_creation_unknown_does_not_retry(self) -> None:
        calls = 0

        def fail_once(*args):
            nonlocal calls
            calls += 1
            raise apify_run.RunStartError("response missing; may have started", outcome_unknown=True)

        with mock.patch.object(single_url, "load_dotenv"), \
             mock.patch.object(single_url, "ApifyClient") as sdk_client, \
             mock.patch.object(single_url, "start_actor_run_once", side_effect=fail_once), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(sys, "argv", ["single_url.py", "--video-url", TEST_URL]):
            with self.assertRaises(SystemExit) as raised:
                single_url.main()
        self.assertIn("Run creation result is unknown", str(raised.exception))
        self.assertIn("check Apify Console", str(raised.exception))
        self.assertIn("Do not retry", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))
        self.assertEqual(calls, 1)
        sdk_client.assert_called_once()

    def test_single_prints_created_run_id_before_wait_begins(self) -> None:
        output = io.StringIO()
        sequence: list[str] = []
        output_file = self.tmp / "ordered.json"

        class OrderedClient(FakeSyncClient):
            def run(self, run_id: str) -> SimpleNamespace:
                sequence.append("wait_started")
                self_outer.assertIn(f"Run ID: {run_id}", output.getvalue())
                return super().run(run_id)

        self_outer = self
        client = OrderedClient()

        def create_once(token: str, video_url: str) -> dict:
            sequence.append("created")
            return {"id": "run-order"}

        with mock.patch.object(single_url, "load_dotenv"), \
             mock.patch.object(single_url, "ApifyClient", return_value=client), \
             mock.patch.object(single_url, "start_actor_run_once", side_effect=create_once), \
             mock.patch.object(single_url, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(single_url, "OUTPUT_FILE", output_file), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(sys, "argv", ["single_url.py"]), \
             contextlib.redirect_stdout(output), \
             mock.patch("builtins.print", wraps=builtins.print) as print_spy:
            single_url.main()
        sequence.insert(1, "run_id_printed")
        self.assertEqual(sequence, ["created", "run_id_printed", "wait_started"])
        run_id_print_calls = [
            call for call in print_spy.call_args_list
            if call.args and str(call.args[0]).startswith("Run ID:")
        ]
        self.assertEqual(len(run_id_print_calls), 1)
        self.assertIs(run_id_print_calls[0].kwargs.get("flush"), True)

    def test_single_url_run_failure_missing_dataset_and_empty_dataset(self) -> None:
        with self.assertRaisesRegex(SystemExit, "failure status FAILED"):
            self._run_single_main(run=FakeRun(status="FAILED"))
        with self.assertRaisesRegex(SystemExit, "no default Dataset ID"):
            self._run_single_main(run=FakeRun(dataset_id=None))
        with self.assertRaisesRegex(SystemExit, "Dataset is empty"):
            self._run_single_main(items=[])

    def test_single_url_missing_text_is_a_completed_run_not_a_run_failure(self) -> None:
        with self.assertRaisesRegex(SystemExit, "Transcript failure: transcript text is empty or missing"):
            self._run_single_main(items=[{"segments": [], "errMsg": ""}])

    def test_single_default_url_and_cli_override_ignore_url_environment(self) -> None:
        for argv, expected_url in (
            (["single_url.py"], apify_run.DEFAULT_VIDEO_URL),
            (["single_url.py", TEST_URL], TEST_URL),
            (["single_url.py", "--video-url", TEST_URL], TEST_URL),
        ):
            with self.subTest(expected_url=expected_url):
                client = FakeSyncClient()
                calls = []
                with mock.patch.object(single_url, "load_dotenv"), \
                     mock.patch.object(single_url, "ApifyClient", return_value=client), \
                     mock.patch.object(single_url, "start_actor_run_once", side_effect=lambda token, url: calls.append((token, url)) or {"id": "run-1"}), \
                     mock.patch.object(single_url, "OUTPUT_DIR", self.tmp), \
                     mock.patch.object(single_url, "OUTPUT_FILE", self.tmp / "result.json"), \
                     mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN, "APIFY_ACTOR_ID": "S9A11NvceWaGorwwh", "TIKTOK_VIDEO_URL": "https://www.tiktok.com/@wrong/video/111"}), \
                     mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    single_url.main()
                self.assertEqual(calls, [(TEST_TOKEN, expected_url)])

    def test_single_rejects_both_url_forms_and_ordinary_creation_errors_safely(self) -> None:
        error_output = io.StringIO()
        with mock.patch.object(single_url, "load_dotenv"), \
             mock.patch.object(single_url, "ApifyClient"), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(sys, "argv", ["single_url.py", TEST_URL, "--video-url", TEST_URL]), \
             contextlib.redirect_stderr(error_output):
            with self.assertRaises(SystemExit) as duplicate:
                single_url.main()
        self.assertEqual(duplicate.exception.code, 2)
        self.assertIn("not both", error_output.getvalue())

        output = io.StringIO()
        with mock.patch.object(single_url, "load_dotenv"), \
             mock.patch.object(single_url, "ApifyClient"), \
             mock.patch.object(single_url, "start_actor_run_once", side_effect=RuntimeError(f"transport failed {TEST_TOKEN}")), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(sys, "argv", ["single_url.py"]), \
             contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                single_url.main()
        self.assertIn("Run creation result is unknown", str(raised.exception))
        self.assertIn("check Apify Console", str(raised.exception))
        self.assertIn("Do not retry directly", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))
        self.assertNotIn("UnboundLocalError", str(raised.exception))

    def test_async_runstart_error_prompts_console_check_without_leaking_token(self) -> None:
        with mock.patch.object(async_run, "start_actor_run_once", side_effect=apify_run.RunStartError(TEST_TOKEN, outcome_unknown=True)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as raised:
                asyncio.run(async_run.start_run(TEST_TOKEN, TEST_URL))
        self.assertIn("Run creation result is unknown", str(raised.exception))
        self.assertIn("check Apify Console", str(raised.exception))
        self.assertIn("Do not retry", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))
        self.assertNotIn(TEST_TOKEN, output.getvalue())
        self.assertNotIn("UnboundLocalError", str(raised.exception))

    def test_async_start_ordinary_creation_error_prints_actor_first_and_redacts_token(self) -> None:
        output = io.StringIO()
        with mock.patch.object(async_run, "start_actor_run_once", side_effect=RuntimeError(f"transport failed {TEST_TOKEN}")), \
             contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                asyncio.run(async_run.start_run(TEST_TOKEN, TEST_URL))
        self.assertTrue(output.getvalue().startswith("Actor: apple_yang/tiktok-transcripts-scraper"))
        self.assertIn("Run creation result is unknown", str(raised.exception))
        self.assertIn("check Apify Console", str(raised.exception))
        self.assertIn("Do not retry directly", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))
        self.assertNotIn(TEST_TOKEN, output.getvalue())
        self.assertNotIn("UnboundLocalError", str(raised.exception))

    def test_async_start_only_creates_once_and_returns_run_id(self) -> None:
        calls = []
        output = io.StringIO()
        with mock.patch.object(async_run, "start_actor_run_once", side_effect=lambda *args: calls.append(args) or {"id": "run-abc", "status": "READY"}), \
             contextlib.redirect_stdout(output):
            asyncio.run(async_run.start_run(TEST_TOKEN, TEST_URL))
        self.assertEqual(len(calls), 1)
        self.assertIn("Actor: apple_yang/tiktok-transcripts-scraper", output.getvalue())
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1]), {"run_id": "run-abc", "status": "READY"})
        self.assertNotIn(TEST_TOKEN, output.getvalue())

    def test_async_start_cli_default_and_override_and_wait_never_starts(self) -> None:
        for argv, expected_url in (
            (["async_run.py", "start"], apify_run.DEFAULT_VIDEO_URL),
            (["async_run.py", "start", "--video-url", TEST_URL], TEST_URL),
        ):
            calls = []
            with self.subTest(expected_url=expected_url), \
                 mock.patch.object(async_run, "load_dotenv"), \
                 mock.patch.object(async_run, "ApifyClientAsync", return_value=FakeAsyncClient()), \
                 mock.patch.object(async_run, "start_actor_run_once", side_effect=lambda token, url: calls.append((token, url)) or {"id": "run-abc", "status": "READY"}), \
                 mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN, "APIFY_ACTOR_ID": "S9A11NvceWaGorwwh", "TIKTOK_VIDEO_URL": "https://www.tiktok.com/@wrong/video/111"}), \
                 mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                asyncio.run(async_run.main())
            self.assertEqual(calls, [(TEST_TOKEN, expected_url)])

        with mock.patch.object(async_run, "load_dotenv"), \
             mock.patch.object(async_run, "ApifyClientAsync", return_value=FakeAsyncClient()), \
             mock.patch.object(async_run, "start_actor_run_once", side_effect=AssertionError("wait must not create")), \
             mock.patch.object(async_run, "OUTPUT_DIR", self.tmp), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(sys, "argv", ["async_run.py", "wait", "--run-id", "run-1"]), \
             contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(async_run.main())

    def test_async_wait_reads_exact_run_and_its_dataset(self) -> None:
        client = FakeAsyncClient(runs={"existing-run": FakeRun("existing-run", dataset_id="right-dataset")})
        with mock.patch.object(async_run, "OUTPUT_DIR", self.tmp):
            asyncio.run(async_run.fetch_run_result(client, "existing-run", 1, TEST_TOKEN))
        self.assertEqual(client.requested_run_ids, ["existing-run"])
        self.assertEqual(client.requested_dataset_ids, ["right-dataset"])
        self.assertTrue((self.tmp / "python-async-run-existing-run.json").exists())
        self.assertEqual(client.start_attempts, 0)

    def test_async_wait_not_found_read_error_and_timeout_are_distinct(self) -> None:
        missing = FakeAsyncClient(runs={})
        with self.assertRaisesRegex(SystemExit, "Run not found"):
            asyncio.run(async_run.fetch_run_result(missing, "missing-run", 1, TEST_TOKEN))

        read_error = FakeAsyncClient()
        read_error.get_error = RuntimeError(f"offline read failure {TEST_TOKEN}")
        with self.assertRaises(SystemExit) as read_raised:
            asyncio.run(async_run.fetch_run_result(read_error, "run-1", 1, TEST_TOKEN))
        self.assertIn("Run read/network error", str(read_raised.exception))
        self.assertNotIn(TEST_TOKEN, str(read_raised.exception))

        failed_run = FakeAsyncClient(runs={"failed-run": FakeRun("failed-run", status="FAILED")})
        with self.assertRaisesRegex(SystemExit, "status FAILED"):
            asyncio.run(async_run.fetch_run_result(failed_run, "failed-run", 1, TEST_TOKEN))
        self.assertEqual(failed_run.requested_dataset_ids, [])

        timeout = FakeAsyncClient(runs={"slow-run": FakeRun("slow-run", status="RUNNING")})
        timeout.wait_delay = 0.1
        with self.assertRaises(SystemExit) as raised:
            asyncio.run(async_run.fetch_run_result(timeout, "slow-run", 0.001, TEST_TOKEN))
        self.assertIn("may still be running", str(raised.exception))
        self.assertIn("--run-id slow-run", str(raised.exception))
        self.assertNotEqual(raised.exception.code, 0)
        self.assertEqual(timeout.requested_dataset_ids, [])

    def test_async_empty_transcript_or_actor_error_is_reported_and_saved(self) -> None:
        for items, expected in (
            ([{"segments": [], "errMsg": ""}], "transcript text is empty or missing"),
            ([{"text": "", "errMsg": "no transcript"}], "Actor errMsg is non-empty"),
        ):
            with self.subTest(expected=expected), mock.patch.object(async_run, "OUTPUT_DIR", self.tmp):
                client = FakeAsyncClient(items=items)
                with self.assertRaisesRegex(SystemExit, "Transcript failure") as raised:
                    asyncio.run(async_run.fetch_run_result(client, "run-1", 1, TEST_TOKEN))
                self.assertIn(expected, str(raised.exception))
                self.assertTrue((self.tmp / "python-async-run-run-1.json").exists())

    def test_csv_writes_start_intent_before_post_and_unknown_is_not_reposted(self) -> None:
        csv_path = self.tmp / "input.csv"
        result_path = self.tmp / "runs.jsonl"
        csv_path.write_text(f"videoUrl\n{TEST_URL}\n", encoding="utf-8")
        observed = []

        def unknown_after_intent(token: str, video_url: str) -> dict:
            lines = result_path.read_text(encoding="utf-8").splitlines()
            observed.extend(json.loads(line)["status"] for line in lines)
            raise apify_run.RunStartError(f"{TEST_TOKEN} connection outcome unclear", outcome_unknown=True)

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", side_effect=lambda **kwargs: FakeAsyncClient()), \
             mock.patch.object(csv_batch, "start_actor_run_once", side_effect=unknown_after_intent):
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))
        self.assertIn("start_attempted", observed)
        records = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records[-1]["status"], "run_creation_unknown")
        self.assertNotIn(TEST_TOKEN, result_path.read_text(encoding="utf-8"))

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", side_effect=lambda **kwargs: FakeAsyncClient()), \
             mock.patch.object(csv_batch, "start_actor_run_once") as no_repost:
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))
            no_repost.assert_not_called()

    def test_csv_unexpected_creation_error_is_unknown_safe_and_never_reposted(self) -> None:
        csv_path = self.tmp / "unexpected_creation_error.csv"
        result_path = self.tmp / "unexpected_creation_error.jsonl"
        csv_path.write_text(f"videoUrl\n{TEST_URL}\n", encoding="utf-8")
        intent_seen = []

        def fail_after_intent(token: str, video_url: str):
            lines = result_path.read_text(encoding="utf-8").splitlines()
            intent_seen.extend(json.loads(line)["status"] for line in lines)
            raise RuntimeError(f"transport interrupted; secret={TEST_TOKEN}")

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", return_value=FakeAsyncClient()), \
             mock.patch.object(csv_batch, "start_actor_run_once", side_effect=fail_after_intent), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))

        self.assertEqual(intent_seen, ["start_attempted"])
        jsonl = result_path.read_text(encoding="utf-8")
        record = json.loads(jsonl.splitlines()[-1])
        self.assertEqual(record["status"], "run_creation_unknown")
        self.assertIn("Run may already have been created", record["error"])
        self.assertIn("Check Apify Console", record["error"])
        self.assertNotIn(TEST_TOKEN, jsonl)
        self.assertIn("Run creation unknown / reconciliation required: 1", output.getvalue())

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", return_value=FakeAsyncClient()), \
             mock.patch.object(csv_batch, "start_actor_run_once") as no_repost, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))
        no_repost.assert_not_called()

    def test_csv_interruption_after_flushed_start_attempted_requires_reconciliation(self) -> None:
        csv_path = self.tmp / "interrupted.csv"
        result_path = self.tmp / "interrupted.jsonl"
        csv_path.write_text(f"videoUrl\n{TEST_URL}\n", encoding="utf-8")
        row = {
            "record_key": f"url:{csv_batch.url_fingerprint(TEST_URL)}:1",
            "row_number": 2,
            "id": None,
            "videoUrl": TEST_URL,
        }
        fake_client = FakeAsyncClient()
        with result_path.open("a", encoding="utf-8") as output_handle:
            with mock.patch.object(csv_batch, "start_actor_run_once", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    asyncio.run(csv_batch.process_row(fake_client, row, None, output_handle, TEST_TOKEN, 0.5))

        first_record = json.loads(result_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(first_record["status"], "start_attempted")

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", return_value=FakeAsyncClient()), \
             mock.patch.object(csv_batch, "start_actor_run_once") as no_repost:
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))
        no_repost.assert_not_called()
        self.assertEqual(csv_batch.read_latest_records(result_path)[row["record_key"]]["status"], "needs_reconciliation")

    def test_csv_reconcile_is_read_only_and_lists_unknown_rows(self) -> None:
        result_path = self.tmp / "runs.jsonl"
        record = {"record_key": "key-1", "row_number": 2, "videoUrl": TEST_URL, "run_id": None, "status": "run_creation_unknown", "error": TEST_TOKEN}
        result_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        output = io.StringIO()
        with mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "load_dotenv"), \
             mock.patch.object(sys, "argv", ["csv_batch.py", "--reconcile"]), \
             mock.patch.dict("os.environ", {"APIFY_TOKEN": TEST_TOKEN}), \
             mock.patch.object(csv_batch, "ApifyClientAsync", side_effect=AssertionError("no client allowed")), \
             mock.patch.object(csv_batch, "start_actor_run_once", side_effect=AssertionError("no POST allowed")), \
             contextlib.redirect_stdout(output):
            asyncio.run(csv_batch.main())
        self.assertIn("run_creation_unknown", output.getvalue())
        self.assertNotIn(TEST_TOKEN, output.getvalue())

    def test_csv_bounded_concurrency_unique_runs_and_duplicate_url_keys(self) -> None:
        csv_path = self.tmp / "duplicate_urls.csv"
        result_path = self.tmp / "runs.jsonl"
        csv_path.write_text(f"videoUrl\n{TEST_URL}\n{TEST_URL}\n{TEST_URL}\n{TEST_URL}\n", encoding="utf-8")
        run_counter = 0
        created_inputs: list[dict] = []
        fake_clients: list[FakeAsyncClient] = []

        def new_client(**kwargs):
            client = FakeAsyncClient(items=[{"text": "has text", "segments": []}])
            fake_clients.append(client)
            return client

        def create_run(token: str, video_url: str) -> dict:
            nonlocal run_counter
            run_counter += 1
            created_inputs.append({"videoUrl": video_url})
            run_id = f"run-{run_counter}"
            fake_clients[0].runs[run_id] = FakeRun(run_id, status="RUNNING")
            return {"id": run_id, "status": "READY"}

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", side_effect=new_client), \
             mock.patch.object(csv_batch, "start_actor_run_once", side_effect=create_run):
            asyncio.run(csv_batch.process_csv(csv_path, 2, 0.5, TEST_TOKEN))

        self.assertEqual(len(created_inputs), 4)
        self.assertTrue(all(list(run_input) == ["videoUrl"] for run_input in created_inputs))
        self.assertLessEqual(fake_clients[0].max_active_waits, 2)
        records = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
        final = [record for record in records if record["status"] == "completed_with_transcript"]
        keys = {record["record_key"] for record in final}
        url_hash = csv_batch.url_fingerprint(TEST_URL)
        self.assertEqual(keys, {f"url:{url_hash}:{index}" for index in range(1, 5)})

    def test_csv_run_failure_empty_transcript_and_dataset_error_are_distinct(self) -> None:
        output = io.StringIO()
        failed_handle = io.StringIO()
        failed_client = FakeAsyncClient(runs={"failed-run": FakeRun("failed-run", status="FAILED")})
        failed_record = {"record_key": "failed", "videoUrl": TEST_URL, "run_id": "failed-run"}
        asyncio.run(csv_batch.resolve_existing_run(failed_client, "failed-run", failed_record, failed_handle, TEST_TOKEN, 0.5))
        failed_json = json.loads(failed_handle.getvalue().splitlines()[-1])
        self.assertEqual(failed_json["status"], "actor_failed")

        empty_client = FakeAsyncClient(items=[{"segments": []}])
        empty_handle = io.StringIO()
        empty_record = {"record_key": "empty", "videoUrl": TEST_URL, "run_id": "run-1"}
        asyncio.run(csv_batch.resolve_existing_run(empty_client, "run-1", empty_record, empty_handle, TEST_TOKEN, 0.5))
        empty_json = json.loads(empty_handle.getvalue().splitlines()[-1])
        self.assertEqual(empty_json["status"], "transcript_empty")

        class BrokenDatasetClient(FakeAsyncClient):
            def dataset(self, dataset_id: str):
                raise RuntimeError(f"dataset failed; token={TEST_TOKEN}")

        broken = BrokenDatasetClient()
        broken_handle = io.StringIO()
        broken_record = {"record_key": "broken", "videoUrl": TEST_URL, "run_id": "run-1"}
        asyncio.run(csv_batch.resolve_existing_run(broken, "run-1", broken_record, broken_handle, TEST_TOKEN, 0.5))
        broken_jsonl = broken_handle.getvalue()
        broken_json = json.loads(broken_jsonl)
        self.assertEqual(broken_json["status"], "dataset_error")
        self.assertNotIn(TEST_TOKEN, broken_jsonl)

        with contextlib.redirect_stdout(output):
            csv_batch.print_summary([
                failed_json,
                empty_json,
                broken_json,
            ])
        self.assertIn("Actor Run failed: 1", output.getvalue())
        self.assertIn("Empty or missing transcript: 1", output.getvalue())
        self.assertIn("Dataset read errors: 1", output.getvalue())

    def test_csv_actor_error_message_is_saved_as_transcript_failure_and_exits_nonzero(self) -> None:
        csv_path = self.tmp / "actor_error.csv"
        result_path = self.tmp / "actor_error.jsonl"
        csv_path.write_text(f"videoUrl\n{TEST_URL}\n", encoding="utf-8")
        client = FakeAsyncClient(
            runs={"run-err": FakeRun("run-err")},
            items=[{"text": "", "segments": [], "errMsg": "no transcript"}],
        )
        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", return_value=client), \
             mock.patch.object(csv_batch, "start_actor_run_once", return_value={"id": "run-err", "status": "READY"}), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))
        records = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records[-1]["status"], "transcript_failed")
        self.assertIn("no transcript", records[-1]["error"])
        self.assertNotIn(TEST_TOKEN, result_path.read_text(encoding="utf-8"))

    def test_csv_failure_and_pending_statuses_exit_nonzero_and_are_persisted(self) -> None:
        cases = ("actor_failed", "dataset_error", "dataset_empty", "run_creation_unknown", "processing_error")
        for expected_status in cases:
            with self.subTest(status=expected_status):
                csv_path = self.tmp / f"{expected_status}.csv"
                result_path = self.tmp / f"{expected_status}.jsonl"
                csv_path.write_text(f"videoUrl\n{TEST_URL}\n", encoding="utf-8")

                class DatasetErrorClient(FakeAsyncClient):
                    def dataset(self, dataset_id: str):
                        raise RuntimeError("offline dataset read failure")

                if expected_status == "actor_failed":
                    client = FakeAsyncClient(runs={"run-1": FakeRun("run-1", status="FAILED")})
                elif expected_status == "dataset_error":
                    client = DatasetErrorClient(runs={"run-1": FakeRun("run-1")})
                elif expected_status == "dataset_empty":
                    client = FakeAsyncClient(runs={"run-1": FakeRun("run-1")}, items=[])
                else:
                    client = FakeAsyncClient()

                def create_run(token: str, video_url: str):
                    if expected_status == "run_creation_unknown":
                        raise apify_run.RunStartError("unknown response", outcome_unknown=True)
                    if expected_status == "processing_error":
                        return {"status": "READY"}
                    return {"id": "run-1", "status": "READY"}

                with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
                     mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
                     mock.patch.object(csv_batch, "ApifyClientAsync", return_value=client), \
                     mock.patch.object(csv_batch, "start_actor_run_once", side_effect=create_run), \
                     contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))
                self.assertNotEqual(raised.exception.code, 0)
                records = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(records[-1]["status"], expected_status)

    def test_process_csv_rejects_out_of_range_concurrency_directly(self) -> None:
        for concurrency in (0, 17):
            with self.subTest(concurrency=concurrency), \
                 mock.patch.object(csv_batch, "ApifyClientAsync", side_effect=AssertionError("client must not be constructed")):
                with self.assertRaisesRegex(SystemExit, "concurrency must be an integer"):
                    asyncio.run(csv_batch.process_csv(self.tmp / "not-read.csv", concurrency, 1, TEST_TOKEN))

    def test_csv_with_header_only_is_an_empty_batch_and_exits_nonzero(self) -> None:
        csv_path = self.tmp / "header_only.csv"
        csv_path.write_text("videoUrl\n", encoding="utf-8")
        with mock.patch.object(csv_batch, "ApifyClientAsync", side_effect=AssertionError("empty CSV must not create a client")):
            with self.assertRaisesRegex(SystemExit, "header but no video rows") as raised:
                asyncio.run(csv_batch.process_csv(csv_path, 1, 1, TEST_TOKEN))
        self.assertNotEqual(raised.exception.code, 0)

    def test_empty_token_does_not_corrupt_csv_errors_or_jsonl(self) -> None:
        error_text = "plain error message"
        self.assertEqual(csv_batch.safe_error(RuntimeError(error_text), ""), error_text)
        output = io.StringIO()
        csv_batch.append_record(output, {"error": error_text}, "")
        self.assertEqual(json.loads(output.getvalue()), {"error": error_text})

    def test_csv_resumes_known_run_skips_completed_and_rejects_bad_ids_or_urls(self) -> None:
        csv_path = self.tmp / "with_ids.csv"
        result_path = self.tmp / "runs.jsonl"
        url2 = "https://www.tiktok.com/@offline/video/9876543210123456789"
        csv_path.write_text(
            "id,videoUrl\n"
            f"resume,{TEST_URL}\n"
            f"done,{url2}\n"
            f"dup,{TEST_URL}\n"
            f"dup,{url2}\n"
            ",\n"
            f"empty,{''}\n",
            encoding="utf-8",
        )
        resume_key = f"id:{csv_batch.url_fingerprint('resume')}"
        done_key = f"id:{csv_batch.url_fingerprint('done')}"
        existing = [
            {"record_key": resume_key, "row_number": 2, "id": "resume", "videoUrl": TEST_URL, "run_id": "old-run", "run_status": "RUNNING", "status": "run_pending"},
            {"record_key": done_key, "row_number": 3, "id": "done", "videoUrl": url2, "run_id": "finished-run", "run_status": "SUCCEEDED", "status": "completed_with_transcript"},
        ]
        result_path.write_text("".join(json.dumps(record) + "\n" for record in existing), encoding="utf-8")
        client = FakeAsyncClient(runs={"old-run": FakeRun("old-run", dataset_id="resume-dataset")})

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", return_value=client), \
             mock.patch.object(csv_batch, "start_actor_run_once") as no_create:
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 2, 0.5, TEST_TOKEN))
            no_create.assert_not_called()

        self.assertEqual(client.requested_run_ids, ["old-run"])
        self.assertEqual(client.requested_dataset_ids, ["resume-dataset"])
        latest = csv_batch.read_latest_records(result_path)
        self.assertEqual(latest[resume_key]["status"], "completed_with_transcript")
        self.assertEqual(latest[done_key]["status"], "completed_with_transcript")
        self.assertTrue(any(record["status"] == "duplicate_id" for record in latest.values()))
        self.assertTrue(any(record["status"] == "input_error" for record in latest.values()))

    def test_csv_without_id_uses_url_hash_occurrence_and_empty_url_never_posts(self) -> None:
        csv_path = self.tmp / "no_ids.csv"
        result_path = self.tmp / "runs.jsonl"
        csv_path.write_text(f'videoUrl\n{TEST_URL}\n""\n{TEST_URL}\n', encoding="utf-8")
        calls = []
        client = FakeAsyncClient()

        def create_run(*args):
            run_id = f"run-{len(calls) + 1}"
            calls.append(args)
            client.runs[run_id] = FakeRun(run_id, status="RUNNING")
            return {"id": run_id, "status": "READY"}

        with mock.patch.object(csv_batch, "OUTPUT_DIR", self.tmp), \
             mock.patch.object(csv_batch, "OUTPUT_FILE", result_path), \
             mock.patch.object(csv_batch, "ApifyClientAsync", return_value=client), \
             mock.patch.object(csv_batch, "start_actor_run_once", side_effect=create_run):
            with self.assertRaisesRegex(SystemExit, "Batch incomplete"):
                asyncio.run(csv_batch.process_csv(csv_path, 1, 0.5, TEST_TOKEN))
        self.assertEqual(len(calls), 2)
        latest = csv_batch.read_latest_records(result_path)
        self.assertIn(f"url:{csv_batch.url_fingerprint(TEST_URL)}:1", latest)
        self.assertIn(f"url:{csv_batch.url_fingerprint(TEST_URL)}:2", latest)
        self.assertEqual(sum(record["status"] == "input_error" for record in latest.values()), 1)

    def test_summary_reports_required_status_groups(self) -> None:
        records = [
            {"status": "completed_with_transcript", "run_status": "SUCCEEDED"},
            {"status": "transcript_empty", "run_status": "SUCCEEDED"},
            {"status": "actor_failed", "run_status": "FAILED"},
            {"status": "dataset_error", "run_status": "SUCCEEDED"},
            {"status": "run_creation_unknown"},
            {"status": "needs_reconciliation"},
            {"status": "run_pending", "run_status": "RUNNING"},
            {"status": "processing_error"},
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            csv_batch.print_summary(records)
        summary = output.getvalue()
        for label in ("Actor Run SUCCEEDED", "Completed with transcript text", "Empty or missing transcript", "Actor Run failed", "Dataset read errors", "Run creation unknown", "Still running"):
            self.assertIn(label, summary)
        self.assertIn("Processing errors: 1", summary)

    def test_low_python_version_fails_before_sdk_import(self) -> None:
        class VersionInfo(tuple):
            major = property(lambda value: value[0])
            minor = property(lambda value: value[1])

        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "apify_client" or name.startswith("apify_client."):
                raise AssertionError("Apify SDK import happened before Python version validation")
            return real_import(name, *args, **kwargs)

        script_path = PYTHON_EXAMPLES / "single_url.py"
        with mock.patch.object(sys, "version_info", VersionInfo((3, 10, 9))), \
             mock.patch("builtins.__import__", side_effect=guarded_import):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(script_path))
        self.assertIn("Python 3.11 or newer is required", str(raised.exception))


def tearDownModule() -> None:
    for patcher in reversed(NETWORK_GUARDS):
        patcher.stop()


if __name__ == "__main__":
    unittest.main()
