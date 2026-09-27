import unittest

from termux_agent.server import SlidingWindowRateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_sliding_window_limits_bursts_and_recovers(self):
        clock = [100.0]
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10, clock=lambda: clock[0])
        self.assertEqual(limiter.allow("127.0.0.1"), (True, 0))
        clock[0] += 1
        self.assertEqual(limiter.allow("127.0.0.1"), (True, 0))
        clock[0] += 1
        allowed, retry_after = limiter.allow("127.0.0.1")
        self.assertFalse(allowed)
        self.assertEqual(retry_after, 8)
        clock[0] = 110.0
        self.assertEqual(limiter.allow("127.0.0.1"), (True, 0))

    def test_client_bookkeeping_is_bounded(self):
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, max_clients=1)
        limiter.allow("client-one")
        limiter.allow("client-two")
        self.assertEqual(len(limiter._events), 1)
        self.assertIn("client-two", limiter._events)


if __name__ == "__main__":
    unittest.main()
