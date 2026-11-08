"""Per-session chat rate limit acceptance. Offline; no model/API calls."""
import unittest

from fastapi.testclient import TestClient

import tests.test_answering as fixtures
from web.main import create_app
from web.ratelimit import CHAT_RATE_LIMIT, SlidingWindowLimiter


class SlidingWindowLimiterTests(unittest.TestCase):
    def test_window_allows_then_denies_then_recovers_exactly_at_expiry(self):
        clock = [100.0]
        limiter = SlidingWindowLimiter(3, 60.0, now=lambda: clock[0])
        self.assertEqual([limiter.check("session")[0] for _ in range(3)], [True, True, True])
        allowed, retry_after = limiter.check("session")
        self.assertFalse(allowed)
        self.assertAlmostEqual(retry_after, 60.0)
        # Denied attempts are not recorded, so retrying cannot extend the lockout.
        clock[0] += 10.0
        allowed, retry_after = limiter.check("session")
        self.assertFalse(allowed)
        self.assertAlmostEqual(retry_after, 50.0)
        clock[0] += 51.0  # 161 > first hit 100 + window 60
        self.assertTrue(limiter.check("session")[0])

    def test_keys_are_isolated_and_expired_buckets_are_pruned(self):
        clock = [0.0]
        limiter = SlidingWindowLimiter(1, 60.0, now=lambda: clock[0])
        self.assertTrue(limiter.check("a")[0])
        self.assertFalse(limiter.check("a")[0])
        self.assertTrue(limiter.check("b")[0])  # separate session keeps its budget
        self.assertEqual(len(limiter._hits), 2)
        clock[0] = 61.0
        self.assertTrue(limiter.check("a")[0])  # window slid for "a"
        self.assertEqual(list(limiter._hits), ["a"])  # expired "b" bucket pruned

    def test_invalid_config_and_retry_after_rounding(self):
        for max_requests, window in ((0, 60.0), (5, 0.0), (-1, 60.0)):
            with self.subTest(max_requests=max_requests, window=window):
                with self.assertRaises(ValueError):
                    SlidingWindowLimiter(max_requests, window)
        self.assertEqual(SlidingWindowLimiter.retry_after_header(0.0), "1")
        self.assertEqual(SlidingWindowLimiter.retry_after_header(0.2), "1")
        self.assertEqual(SlidingWindowLimiter.retry_after_header(45.1), "46")


class ChatRateLimitGatewayTests(unittest.TestCase):
    setUp = fixtures.AnswerGatewayTests.setUp
    ask = fixtures.AnswerGatewayTests.ask

    def test_budget_denies_with_429_retry_after_while_history_stays_readable(self):
        for number in range(CHAT_RATE_LIMIT):
            self.assertEqual(self.ask(f"Pertanyaan {number}").status_code, 200)
        blocked = self.ask()
        self.assertEqual(blocked.status_code, 429, blocked.text)
        self.assertEqual(blocked.json()["error"]["code"], "rate_limited")
        self.assertGreaterEqual(int(blocked.headers["retry-after"]), 1)
        self.assertIn("Try again in", blocked.json()["error"]["message"])
        # Blocked retries do not extend the lockout, and reads are never counted.
        self.assertEqual(self.ask().status_code, 429)
        self.assertEqual(self.client.get("/api/chat").status_code, 200)

    def test_other_sessions_keep_their_own_budget(self):
        for number in range(CHAT_RATE_LIMIT):
            self.assertEqual(self.ask(f"Pertanyaan {number}").status_code, 200)
        self.assertEqual(self.ask().status_code, 429)
        other = TestClient(self.app)
        other.__enter__()
        self.addCleanup(other.__exit__, None, None, None)
        csrf = other.get("/api/documents").json()["csrf_token"]
        # Fresh bucket: the request passes the limiter and fails later at the
        # document gate (409), which would be 429 if budgets were shared.
        response = other.post("/api/chat", json={"question": "Q"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "document_changed")

    def test_csrf_is_checked_before_the_limit_and_harness_may_disable_it(self):
        # Rejected for CSRF, not rate: no token is consumed from the budget.
        for number in range(CHAT_RATE_LIMIT):
            self.assertEqual(self.ask(f"Pertanyaan {number}").status_code, 200)
        forged = self.client.post("/api/chat", json={"question": "Q"}, headers={"X-CSRF-Token": "wrong"})
        self.assertEqual(forged.status_code, 403)
        # evals/run.py builds its own app without the limit; construction-time
        # configuration only, never an HTTP switch.
        harness_app = create_app(chat_rate_limit=None)
        self.assertIsNone(harness_app.state.chat_rate_limiter)
        self.assertIsNotNone(create_app().state.chat_rate_limiter)


if __name__ == "__main__":
    unittest.main()
