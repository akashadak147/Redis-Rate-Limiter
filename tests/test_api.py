import os
import time
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, PyMongoError

from rate_limiter.app import create_app
from rate_limiter.settings import Settings


class MongoIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uri = os.environ.get("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017")
        cls.mongo = MongoClient(cls.uri, timeoutMS=2_000, tz_aware=True)
        cls.addClassCleanup(cls.mongo.close)
        try:
            cls.mongo.admin.command("ping")
        except PyMongoError:
            raise RuntimeError("Start MongoDB or set TEST_MONGODB_URI before running the tests.") from None

    def setUp(self):
        self.settings = Settings(mongodb_uri=self.uri, mongodb_database=f"rate_limit_test_{uuid4().hex}")
        self.addCleanup(self.mongo.drop_database, self.settings.mongodb_database)
        self.counters = self.mongo[self.settings.mongodb_database]["rate_limit_counters"]
        # Advance the test clock independently of MongoDB's TTL clock.
        self.start = (int(time.time()) // 60 + 1) * 60
        self.now = self.start + 30.25
        self.app = self.new_app()
        self.http = self.enterContext(TestClient(self.app))

    def new_app(self):
        return create_app(self.settings, clock=lambda: self.now)

    def request(self, client_id="client-a"):
        return self.http.get("/api/demo", headers={"X-Client-ID": client_id})

    def test_quota_responses_and_headers(self):
        results = [self.request() for _ in range(6)]
        self.assertEqual([response.status_code for response in results], [200] * 5 + [429])
        self.assertEqual(
            [response.headers["x-ratelimit-remaining"] for response in results],
            ["4", "3", "2", "1", "0", "0"],
        )
        for response in results:
            self.assertEqual(response.headers["x-ratelimit-limit"], "5")
            self.assertEqual(response.headers["x-ratelimit-reset"], str(self.start + 60))
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(results[0].json(), {"message": "Protected endpoint reached."})
        self.assertEqual(results[-1].json()["detail"]["error"], "rate_limit_exceeded")
        self.assertEqual(results[-1].headers["retry-after"], "30")
        self.assertEqual(self.counters.find_one()["count"], 6)

    def test_other_client_has_separate_quota(self):
        for _ in range(6):
            blocked = self.request("client-a")
        self.assertEqual(blocked.status_code, 429)
        allowed = self.request("Client-a")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["x-ratelimit-remaining"], "4")
        self.assertEqual(sorted(row["count"] for row in self.counters.find()), [1, 6])

    def test_exact_boundary_resets_without_waiting_for_deletion(self):
        self.assertEqual(self.request().status_code, 200)
        first = self.counters.find_one()
        self.now = self.start + 59.999
        for _ in range(5):
            blocked = self.request()
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers["retry-after"], "1")

        self.now = self.start + 60
        fresh = self.request()
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.headers["x-ratelimit-remaining"], "4")
        self.assertEqual(fresh.headers["x-ratelimit-reset"], str(self.start + 120))
        self.assertEqual(self.counters.count_documents({}), 2)
        old = self.counters.find_one({"_id": first["_id"]})
        self.assertEqual(old["count"], 6)
        self.assertEqual(old["expiresAt"], first["expiresAt"])
        self.assertEqual(old["expiresAt"], datetime.fromtimestamp(self.start + 120, UTC))

    def test_twenty_concurrent_requests(self):
        ready = Barrier(20, timeout=10)

        def make_request():
            ready.wait()
            return self.request().status_code

        with ThreadPoolExecutor(max_workers=20) as executor:
            requests = [executor.submit(make_request) for _ in range(20)]
            statuses = Counter(future.result(timeout=15) for future in requests)

        self.assertEqual(statuses, {200: 5, 429: 15})
        self.assertEqual(self.counters.count_documents({}), 1)
        self.assertEqual(self.counters.find_one()["count"], 20)

    def test_backend_restart_preserves_the_counter(self):
        with TestClient(self.new_app()) as first_backend:
            first_backend.get("/api/demo", headers={"X-Client-ID": "restart-sample"})

        with TestClient(self.new_app()) as restarted_backend:
            response = restarted_backend.get("/api/demo", headers={"X-Client-ID": "restart-sample"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-ratelimit-remaining"], "3")
        self.assertEqual(self.counters.find_one()["count"], 2)

    def test_invalid_ids_and_readiness_do_not_consume_quota(self):
        bad_headers = [
            [],
            [("X-Client-ID", "")],
            [("X-Client-ID", "x" * 65)],
            [("X-Client-ID", "client/a")],
            [("X-Client-ID", "one"), ("X-Client-ID", "two")],
        ]
        for headers in bad_headers:
            with self.subTest(headers=headers):
                response = self.http.get("/api/demo", headers=headers)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"]["error"], "invalid_client_id")

        self.assertEqual(self.http.get("/health").json(), {"status": "ready"})
        self.assertEqual(self.counters.count_documents({}), 0)

    def test_database_failure_and_recovery(self):
        self.assertEqual(self.request().status_code, 200)
        store = self.app.state.store
        with (
            patch.object(store.collection, "find_one_and_update", side_effect=AutoReconnect) as write,
            patch.object(store.database, "command", side_effect=AutoReconnect),
        ):
            refused = self.request()
            self.assertEqual(refused.status_code, 503)
            self.assertEqual(refused.json()["detail"]["error"], "quota_unavailable")
            self.assertEqual(self.http.get("/health").status_code, 503)
            write.assert_called_once()

        self.assertEqual(self.http.get("/health").status_code, 200)
        restored = self.request()
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.headers["x-ratelimit-remaining"], "3")

    def test_mongodb_removes_expired_documents(self):
        self.assertEqual(self.counters.index_information()["expiresAt_1"]["expireAfterSeconds"], 0)
        self.counters.insert_one({
            "_id": "expired-test-counter",
            "count": 1,
            "expiresAt": datetime.now(UTC) - timedelta(seconds=1),
        })

        deadline = time.monotonic() + 75
        while self.counters.find_one({"_id": "expired-test-counter"}) is not None:
            if time.monotonic() >= deadline:
                self.fail("MongoDB did not remove the expired counter before the deadline.")
            time.sleep(0.25)


class ConfigurationTests(unittest.TestCase):
    def test_invalid_settings_are_rejected_at_startup(self):
        for name, value in (
            ("RATE_LIMIT_REQUESTS", "0"),
            ("RATE_LIMIT_WINDOW_SECONDS", "1.5"),
            ("MONGODB_TIMEOUT_MS", "-1"),
            ("MONGODB_URI", "invalid"),
            ("MONGODB_URI", "mongodb://127.0.0.1:27017/?w=0"),
            ("MONGODB_DATABASE", ""),
        ):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                with self.assertRaisesRegex(ValueError, name):
                    with TestClient(create_app()):
                        self.fail("Invalid settings should prevent startup.")
