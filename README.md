# Redis Rate Limiter

This is the backend for Question 2 of the unstructured databases assignment. It uses Python, FastAPI, and redis-py to enforce a fixed-window quota using the Redis key-value model selected for Question 1.

By default, each client can make **five requests in a fixed 60-second UTC window**. The sixth request returns **HTTP 429 Too Many Requests** with a `Retry-After` header. The next window starts with a fresh quota for each client.

## Run locally

1. Install Python 3.11 or newer. Start Redis locally on port 6379. If you use Docker Compose, run this from the project directory.

   ```sh
   docker compose up -d redis
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

While the counters exist, list their keys and inspect one with Redis CLI.

```sh
docker compose exec redis redis-cli --scan --pattern 'rate-limit:demo-v1:*'
docker compose exec redis redis-cli GET 'key-from-the-scan'
docker compose exec redis redis-cli TTL 'key-from-the-scan'
```

## Endpoints and configuration

| Endpoint | Response |
|---|---|
| `GET /health` | `200` when Redis responds to `PING`. `503` when the readiness check fails. |
| `GET /api/demo` | `200` within quota, `429` above quota, `400` for an invalid `X-Client-ID`, and `503` when the quota cannot be checked. |

The client ID is case-sensitive. Send exactly one `X-Client-ID` with 1 to 64 ASCII letters, digits, hyphens, or underscores. Responses for successful and rate-limited requests include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`. `Retry-After` on a `429` is given in seconds.

| Environment variable | Default |
|---|---|
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `REDIS_KEY_PREFIX` | `rate-limit` |
| `REDIS_TIMEOUT_MS` | `2000` |
| `RATE_LIMIT_REQUESTS` | `5` |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` |

Set variables before starting Uvicorn to override the defaults. Integer settings must be between 1 and 2,147,483,647. Keep credentials out of source control. The supplied Redis configuration binds the published port to localhost.

## How it works

Redis stores one integer counter per policy, client, and window as a string value. A Lua script runs `INCR` and sets `EXPIREAT` on the first attempt. It returns the updated count, so concurrent requests each get a distinct position in the quota. The window start is part of the key, so the next window begins with a fresh quota. Redis removes the old key after its window ends plus 60 seconds of cleanup grace.

At a window boundary, five requests can succeed immediately before it and five immediately after it. The demo’s client ID is supplied by the caller. An authenticated deployment would derive the ID from the verified account.

## Run the tests

Start Redis, then run the integration suite.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v -b
```

Use `TEST_REDIS_URL` if the server uses a different address. Run against a local test Redis instance. Each test creates and removes keys under a unique prefix.

The suite covers quota responses and headers, client isolation, exact rollover, state across application restarts, invalid IDs, outage handling, expiration, concurrent requests, and invalid settings.

## Design documents

- [Project plan](docs/plan.md)
- [Architecture and Redis key-value model](docs/architecture.md)
- [Requirements and acceptance criteria](docs/requirements.md)
- [Project goals and rate limiter logic](docs/implementation.md)
