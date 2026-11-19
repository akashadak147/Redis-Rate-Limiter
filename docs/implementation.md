# Question 2 | Implementation, logic and working principle

## Project goals

Protect a sample API from excess requests, demonstrate a real use of a NoSQL data model, and show that the backend makes consistent quota decisions when several requests arrive together. The first version uses a fixed window because a client and a window map directly to one counter document, and the behavior is easy to demonstrate.

## Implementation design

1. Validate settings and initialize a database client for the application. Try to set up the expiry index at startup. If MongoDB is unavailable, retry setup on database-dependent requests and return HTTP 503 while setup fails.
2. At the protected route, validate the single client ID header. Reject invalid input with HTTP 400.
3. Capture the server's current Unix time once for window selection. Divide it by the configured window duration and round down. Multiply the result by the duration to obtain the window start. Add the duration to obtain the end. The start is included and the end belongs to the next window.
4. Identify the counter using the policy identifier, client ID, and window start. In one atomic database write, insert the document if needed, increment its count by one, and read back the post-write count. Set expiry to the window end plus 60 seconds only on insertion.
5. If the returned count is at or below the limit, let the protected route return its success response. Otherwise, return HTTP 429 and calculate the retry delay. For either outcome, remaining quota is the larger of zero and the limit minus the returned count.
6. If the database operation fails and the count is uncertain, respond with HTTP 503. A timed-out write may already have consumed quota. Preserve the attempt's original window during any specifically allowed duplicate-key recovery.
7. At the next boundary, the new window produces a new document identity. The old counter remains harmless until MongoDB removes it.

## Worked example

Assume a one-minute window beginning at 12:00:00 UTC and ending at 12:01:00 UTC.

| Client | Time | Stored count in its current window | Status | Remaining |
|---|---|---:|---|---:|
| Alice | 12:00:10 | 1 | 200 | 4 |
| Alice | 12:00:25 | 5 after three intervening attempts | 200 | 0 |
| Alice | 12:00:30 | 6 | 429 | 0 |
| Bob | 12:00:31 | 1 | 200 | 4 |
| Alice | 12:01:00 | 1 in the new window | 200 | 4 |

Alice's rejection at 12:00:30 gives a retry delay of 30 seconds if the response is generated then.

## Design limits

A fixed window permits up to ten successful requests in a short burst spanning the boundary under the five-per-minute default. Five can fall just before the boundary and another five just after. A rolling-window policy would be needed if the specification were five requests in every consecutive 60-second interval. The caller-supplied client ID supports a local assignment demo. A deployed service would derive the identity from a trusted source.

See [architecture.md](architecture.md) for storage behavior and [requirements.md](requirements.md) for expected results.
