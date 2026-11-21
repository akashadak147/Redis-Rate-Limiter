# Question 2 | Rate limiter project plan

## Objective

Build a small HTTP backend that enforces a request quota. Question 1 selected **Redis’s key-value model** and a **fixed-window rate limiter**. Question 2 demonstrates those choices in a running application.

## Proposed scope

Use Python with FastAPI and redis-py. Protect one demonstration endpoint and expose one readiness endpoint. Demonstrate quota enforcement, isolation between clients, reset at a time boundary, and the behavior when the database is unavailable. Use a local deployment for the assignment.

## Work sequence

| Stage | Work | Completion check |
|---|---|---|
| 1. Confirm design | Use the key-value model with a default quota of five requests per 60-second fixed UTC window. Protect the demo route using a client identifier. | The database design matches Question 1 and the API contract is agreed. |
| 2. Set up the backend | Prepare an isolated Python environment, pin dependencies, configure a local database, and validate settings on startup. | The service starts with valid settings and reports database readiness. |
| 3. Build the counter store | Define the key format and expiration. Add the atomic update and validate it against a real database. | One counter is shared by concurrent requests for the same client and window. |
| 4. Connect HTTP behavior | Validate the demo client identifier, evaluate the quota, and map decisions to HTTP responses. | Requests return the statuses and headers in the requirements. |
| 5. Verify and demonstrate | Run the acceptance tests with isolated test data, including concurrent requests and a simulated outage. | Every acceptance case has an expected and recorded actual result. |
| 6. Prepare submission | Document installation, settings, demo steps, expected responses, and limitations. | A reviewer can reproduce the demonstration from a clean local setup. |

## Verification and evidence

Use a controllable clock for window-boundary tests and an actual Redis instance for database integration checks. Exercise concurrency within a single window and collect status totals. For cleanup, check the configured key expiration and its removal with a bounded timeout. Capture anonymized request results and a sample counter key. The final demonstration should show five successes, a rejection, a second client succeeding independently, and the first client succeeding in the next window.

## Main project risks

| Risk | Design response |
|---|---|
| A client changes its identifier | Use the supplied ID for a local demonstration. Take the ID from authenticated identity in a public deployment. |
| Parallel requests over-admit | Make the database increment atomic and decide using the count returned for that operation. |
| Expiry timing appears to control reset | Use a separate counter identity per time window. Expiry handles storage cleanup. |
| Database outage makes quota unknown | Return HTTP 503 and prevent access to the protected handler. |

See [architecture.md](architecture.md), [requirements.md](requirements.md), and [implementation.md](implementation.md).
