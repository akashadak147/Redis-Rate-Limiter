# MongoDB Rate Limiter

This is the backend for Question 2 of the unstructured databases assignment. It uses Python, FastAPI, and PyMongo to enforce a fixed-window quota using the MongoDB document model selected for Question 1.

By default, each client can make **five requests in a fixed 60-second UTC window**. The sixth request returns **HTTP 429 Too Many Requests** with a `Retry-After` header. The next window starts with a fresh quota for each client.

## Run locally

1. Install Python 3.11 or newer. Start MongoDB locally on port 27017. If you use Docker Compose, run this from the project directory.

   ```sh
   docker compose up -d mongodb
   ```

2. Create a virtual environment and activate it.

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell, run `py -m venv .venv` and `.\.venv\Scripts\Activate.ps1`.

3. Install the backend dependencies and start the API.

   ```sh
   python -m pip install -r requirements.txt
   python -m uvicorn rate_limiter.app:app --host 127.0.0.1 --port 8000
   ```

4. Open [Swagger UI](http://127.0.0.1:8000/docs) or call the API from a second terminal.

   ```sh
   curl -i http://127.0.0.1:8000/health
   curl -i -H 'X-Client-ID: client-a' http://127.0.0.1:8000/api/demo
   ```

   In Windows PowerShell, use `curl.exe` for these examples.

## Demonstrate the quota

Send six requests with the same fresh client ID within one 60-second window. Start a few seconds after a UTC minute boundary so the requests are in the same window.

```sh
client_id="demo-$(date +%s)"
for attempt in 1 2 3 4 5 6; do
  curl -sS -o /dev/null -w "$attempt: %{http_code}\n" \
    -H "X-Client-ID: $client_id" http://127.0.0.1:8000/api/demo
done
```

The expected sequence is `200, 200, 200, 200, 200, 429`. Use a different client ID to receive `200` while the first client is blocked. Wait until the epoch timestamp in `X-RateLimit-Reset`, or wait the number of seconds in `Retry-After`, then try the original ID again.

While the counter exists, you can inspect its MongoDB document.

```sh
docker compose exec mongodb mongosh rate_limiter --quiet \
  --eval 'db.rate_limit_counters.find().toArray()'
```

## Endpoints and configuration

| Endpoint | Response |
|---|---|
| `GET /health` | `200` when the MongoDB connection and counter index are ready. `503` when the readiness check fails. |
| `GET /api/demo` | `200` within quota, `429` above quota, `400` for an invalid `X-Client-ID`, and `503` when the quota cannot be checked. |

The client ID is case-sensitive. Send exactly one `X-Client-ID` with 1 to 64 ASCII letters, digits, hyphens, or underscores. Responses for successful and rate-limited requests include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`. `Retry-After` on a `429` is given in seconds.

| Environment variable | Default |
|---|---|
| `MONGODB_URI` | `mongodb://127.0.0.1:27017` |
| `MONGODB_DATABASE` | `rate_limiter` |
| `MONGODB_TIMEOUT_MS` | `2000` |
| `RATE_LIMIT_REQUESTS` | `5` |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` |

Set variables before starting Uvicorn to override the defaults. Integer settings must be between 1 and 2,147,483,647. Use acknowledged MongoDB writes and keep credentials out of source control. The supplied MongoDB configuration binds to localhost for the assignment demo.

## How it works

MongoDB stores one document per policy, client, and window in `rate_limit_counters`. A single update increments the count and returns the new value. Using that value gives each concurrent request its own position in the quota. The key changes at the next window boundary, while a TTL index removes expired documents in the background.

At a window boundary, five requests can succeed immediately before it and five immediately after it. The demo’s client ID is supplied by the caller. An authenticated deployment would derive the ID from the verified account.

## Run the tests

Start MongoDB, then run the integration suite.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v -b
```

Use `TEST_MONGODB_URI` if the test server uses a different address. The tests create and remove isolated databases on that server. Use a local test instance. The TTL test polls for background deletion and can take about a minute with default MongoDB settings.

The suite checks the quota and headers, client isolation, exact rollover, persistence across app restarts, invalid IDs, outage handling, TTL cleanup, and concurrent requests.

All nine tests passed locally with MongoDB 7.0.30. The concurrent request test recorded 5 responses with `200` and 15 with `429`. A live HTTP check also returned `503` while MongoDB was down and resumed quota checks after it restarted.

## Design documents

- [Project plan](docs/plan.md)
- [Architecture and MongoDB document model](docs/architecture.md)
- [Requirements and acceptance criteria](docs/requirements.md)
- [Project goals and rate limiter logic](docs/implementation.md)
