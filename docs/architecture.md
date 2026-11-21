# Question 2 | Rate limiter architecture

## Stack and boundaries

The backend uses Python with FastAPI and redis-py and applies the Redis key-value model selected for Question 1. FastAPI handles the HTTP interface. The limiter determines the client and time window and evaluates quota. The Redis store owns counter updates and expiry. One application process and one local Redis instance are enough for the demonstration. Multiple application processes can share counters when they use the same database, policy settings, and synchronized system clocks.

```mermaid
flowchart TD
    A["Protected request"] --> B{"Valid client ID?"}
    B -->|No| H["Return 400"]
    B -->|Yes| C["Increment window counter in Redis"]
    C --> D{"Counter result"}
    D -->|Within quota| E["Run handler and return 200"]
    D -->|Above quota| F["Return 429 with retry delay"]
    D -->|Database failure| G["Return 503"]
```

Invalid client identifiers return HTTP 400. The readiness route checks Redis with `PING`. The application can start while Redis is down and return HTTP 503 on database-dependent requests until Redis is reachable again.

## Key-value model

Redis stores one expiring string key per policy, client, and fixed window.

| Element | Example | Purpose |
|---|---|---|
| Key | `rate-limit:demo-v1:5:60:client-a:1770000000` | Identifies the policy, client, and window start. |
| Value | `6` | Integer count of valid attempts, including denied attempts. |
| Expiration | Window end plus 60 seconds | Automatically removes the old key after a cleanup grace period. |

A Lua script calls `INCR`, sets the absolute expiration with `EXPIREAT` when the counter first becomes one, and returns the new count. Redis executes the script atomically, so simultaneous requests receive different counter values. The next window creates a different key. An ambiguous connection failure can occur after Redis applied an increment, so the application returns 503 and avoids replaying the write.

## Trust and failure decisions

The local demonstration accepts a client-supplied identifier for reproducible tests. It can be changed by the caller, so public deployment would require a trusted identity taken from authentication. Bind the demo to localhost and keep the database URI out of source control and logs. Return 503 when the database cannot provide a quota decision. Use a finite database deadline. The quota and window duration are part of the policy identifier so different configurations use separate counters.

## Redis references

- [INCR and rate limiter patterns](https://redis.io/docs/latest/commands/incr/)
- [EXPIREAT](https://redis.io/docs/latest/commands/expireat/)
- [Redis Lua scripting](https://redis.io/docs/latest/develop/programmability/eval-intro/)
