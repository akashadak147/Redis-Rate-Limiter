# Question 2 | Rate limiter requirements

## Assignment requirement

Implement a simple backend rate limiter using the data model selected in Question 1 and a suitable programming language. This backend uses Python with FastAPI and the MongoDB document model selected for Question 1.

## API contract

| Request | Condition | Expected response |
|---|---|---|
| GET /api/demo | Valid client ID and quota available | 200 with a JSON success body and the quota headers. |
| GET /api/demo | Valid client ID and quota exceeded | 429 with a JSON error, quota headers, and `Retry-After`. |
| GET /api/demo | Missing, duplicated, or invalid client ID | 400 with a JSON error. No quota write. |
| GET /api/demo | Quota store unavailable or decision uncertain | 503 with a JSON error. The protected handler does not run. |
| GET /health | Database reachable and counter index ready | 200 with a JSON readiness status. |
| GET /health | Database or counter index unavailable | 503 with a JSON readiness status. |

The client supplies one `X-Client-ID` header, with 1 to 64 ASCII letters, digits, hyphens or underscores. IDs are case-sensitive. The backend uses a default limit of **five attempts per client per 60-second fixed UTC window**. Every valid attempt that reaches the successful counter update is counted, including rejected attempts. Health checks and invalid inputs consume no quota.

Quota headers are `X-RateLimit-Limit` (configured limit), `X-RateLimit-Remaining` (remaining requests clamped to zero), and `X-RateLimit-Reset` (window end as Unix seconds). On 429, `Retry-After` is a positive integer delay in seconds, calculated by rounding up the time to the window end at response generation and clamping to at least one second. Quota-bearing responses should use `Cache-Control: no-store`.

## Operational requirements

- Read the database URI, quota, window duration, and database timeout from configuration. Reject invalid settings at startup. Quota, window duration, and timeout must be integers between 1 and 2,147,483,647. Require acknowledged MongoDB writes.
- Store counters in the database so restarting the backend alone does not reset the current quota.
- Keep at most one document for each policy, client, and window. Remove expired counters automatically.
- Reuse the database client across requests. Use a synchronous route or worker thread with synchronous PyMongo to keep database I/O off the async event loop.
- Log refused requests and dependency errors without recording credentials or raw client IDs. Keep the demonstration local.

## Acceptance criteria

| Case | Pass condition |
|---|---|
| Sequential limit | Six valid requests from one new client inside one window yield five 200 responses followed by one 429. Remaining quota reaches zero on the fifth response. |
| Client isolation | A different client receives 200 and has four requests left even after the first client is blocked. |
| Rollover | A blocked client receives 200 exactly at the next boundary under controlled time, while its old document still exists. |
| Concurrent use | Twenty requests from one new client in a single window yield exactly five 200 and fifteen 429 responses with a final stored count of twenty. |
| Restart | Restarting only the backend during a window preserves a previously used quota. |
| Validation | Missing, duplicated, and malformed identifiers each receive 400 without creating a counter. |
| Failure and recovery | An unavailable database yields 503 for the protected route and health check. After restoring connectivity, health gives 200 and quota decisions resume for the current window. |
| Cleanup | Expired documents disappear eventually through the TTL index. |
