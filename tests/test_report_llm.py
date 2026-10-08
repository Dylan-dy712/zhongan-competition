import json
import unittest
from unittest.mock import patch

import requests
from urllib3.exceptions import ReadTimeoutError

from services.api.app.llm_extractor import OpenAiCompatibleExtractor
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.report_llm import draft_report


VALID = json.dumps({"sections": [{"section_type": s, "claims": []} for s in SECTION_TYPES],
                    "actions": []})
PAYLOAD = {"choices": [{"message": {"content": VALID}}], "usage": {"total_tokens": 12}}


class ReportRequestTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.dict("os.environ", {"LLM_BASE_URL": "https://example.invalid",
                                               "LLM_API_KEY": "synthetic-test-key",
                                               "LLM_MODEL_ID": "test-model"})
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_report_waits_longer_than_old_45_second_limit(self):
        clock = [0.]
        def call(messages, *, timeout):
            self.assertEqual(timeout, (10, 180))
            clock[0] += 49.49
            return PAYLOAD, VALID
        with patch("services.api.app.report_llm.time.monotonic", side_effect=lambda: clock[0]), \
             patch.object(OpenAiCompatibleExtractor, "_call", side_effect=call):
            result = draft_report("synthetic", [], None)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage_metadata"]["request_attempts"][0]["elapsed_seconds"], 49.49)
        self.assertIsNone(result["repaired_output"])

    def test_wrapped_read_timeout_retries_without_leaking_exception_message(self):
        failure = requests.ConnectionError(ReadTimeoutError(None, "secret-url", "private-content"))
        with patch.object(OpenAiCompatibleExtractor, "_call",
                          side_effect=[failure, (PAYLOAD, VALID)]) as call, \
             patch("services.api.app.report_llm.time.sleep"):
            result = draft_report("synthetic", [], None)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(call.call_count, 2)
        attempts = result["usage_metadata"]["request_attempts"]
        self.assertEqual(attempts[0]["code"], "REPORT_MODEL_TIMEOUT")
        self.assertNotIn("private-content", json.dumps(attempts))
        self.assertNotIn("secret-url", json.dumps(attempts))
        self.assertIsNone(result["repaired_output"])

    def test_exhausted_timeouts_are_bounded_and_preserve_specific_error(self):
        clock = [0.]
        timeouts = []
        def call(messages, *, timeout):
            timeouts.append(timeout)
            clock[0] += timeout[1]
            raise requests.ReadTimeout("private")
        def sleep(seconds):
            clock[0] += seconds
        with patch.object(OpenAiCompatibleExtractor, "_call", side_effect=call), \
             patch("services.api.app.report_llm.time.monotonic", side_effect=lambda: clock[0]), \
             patch("services.api.app.report_llm.time.sleep", side_effect=sleep):
            result = draft_report("synthetic", [], None)
        self.assertEqual(timeouts, [(10, 180), (10, 49)])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "REPORT_MODEL_TIMEOUT")
        self.assertTrue(result["retryable"])
        self.assertLessEqual(clock[0], 240)

    def test_permanent_http_error_does_not_retry(self):
        response = requests.Response()
        response.status_code = 401
        with patch.object(OpenAiCompatibleExtractor, "_call",
                          side_effect=requests.HTTPError("private", response=response)) as call:
            result = draft_report("synthetic", [], None)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result["error_code"], "REPORT_MODEL_HTTP_ERROR")
        self.assertFalse(result["retryable"])
        self.assertEqual(result["usage_metadata"]["request_attempts"][0]["http_status"], 401)

    def test_transient_http_errors_retry(self):
        for status in (429, 503):
            response = requests.Response()
            response.status_code = status
            with self.subTest(status=status), \
                 patch.object(OpenAiCompatibleExtractor, "_call",
                              side_effect=[requests.HTTPError(response=response), (PAYLOAD, VALID)]) as call, \
                 patch("services.api.app.report_llm.time.sleep"):
                self.assertEqual(draft_report("synthetic", [], None)["status"], "completed")
                self.assertEqual(call.call_count, 2)

    def test_schema_repair_retains_both_outputs(self):
        invalid = {"choices": [{"message": {"content": "{}"}}]}
        with patch.object(OpenAiCompatibleExtractor, "_call",
                          side_effect=[(invalid, "{}"), (PAYLOAD, VALID)]) as call:
            result = draft_report("synthetic", [], None)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["raw_output"], invalid)
        self.assertEqual(result["repaired_output"], PAYLOAD)
        self.assertEqual(len(call.call_args.args[0]), 4)

    def test_retry_and_schema_repair_share_two_call_limit(self):
        with patch.object(OpenAiCompatibleExtractor, "_call",
                          side_effect=[requests.ReadTimeout(), (PAYLOAD, "{}")]) as call, \
             patch("services.api.app.report_llm.time.sleep"):
            result = draft_report("synthetic", [], None)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "REPORT_MODEL_SCHEMA_INVALID")

    def test_missing_response_choices_is_recorded_as_failure(self):
        with patch.object(OpenAiCompatibleExtractor, "_call", side_effect=IndexError()) as call:
            result = draft_report("synthetic", [], None)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result["error_code"], "REPORT_MODEL_RESPONSE_INVALID")

    def test_other_model_calls_keep_original_default_timeout(self):
        with patch("services.api.app.llm_extractor.requests.post") as post:
            post.return_value.json.return_value = PAYLOAD
            client = OpenAiCompatibleExtractor()
            client._call([])
            self.assertEqual(post.call_args.kwargs["timeout"], 45)
            client._call([], timeout=(10, 180))
            self.assertEqual(post.call_args.kwargs["timeout"], (10, 180))


if __name__ == "__main__":
    unittest.main()
