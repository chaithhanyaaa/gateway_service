# LLM Gateway

## Live Deployment

**Base URL:** https://llm-gateway-latest-1.onrender.com

### Test the API

The gateway exposes the following endpoint:

`POST https://llm-gateway-latest-1.onrender.com/chat`

Send a `POST` request with a valid JWT bearer token and JSON body.

```bash
curl -N -X POST https://llm-gateway-latest-1.onrender.com/chat \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "operation_id": "a1719b20-d100-46d3-bade-a8af3f0c2c9a",
    "provider": "groq",
    "model": "qwen/qwen3.8-27b",
    "prompt": "Explain how Redis caching works.",
    "messages": []
  }'
```

**Requirements**
- Generate a valid JWT using the configured signing secret, issuer, audience, and expiration.
- Use a new operation ID for a new operation.
- The service may take time to respond if the hosting platform has spun down an idle instance.
- Opening the base URL in a browser may return `404 Not Found` because the application does not define a root route. Test the `/chat` endpoint using a `POST` request instead.

---


A production-oriented LLM Gateway built with **FastAPI, Python, Redis, JWT authentication, and Server-Sent Events (SSE)**. It provides a unified interface for LLM providers, with reliability mechanisms including retries, exponential backoff with jitter, circuit breakers, idempotency, Redis-backed operation persistence, and structured logging.

## Features

- **Provider registry:** Uses the Strategy Pattern to select LLM providers through a common interface.
- **Streaming responses:** Delivers generated content incrementally using SSE.
- **JWT authentication:** Validates bearer tokens, including expiration, subject, issuer, and audience.
- **Request tracing:** Correlates logs with request IDs, authenticated user IDs, and operation IDs.
- **Retries and backoff:** Retries eligible provider failures with bounded attempts and exponential backoff with jitter.
- **Circuit breaker:** Limits calls to unhealthy providers and allows recovery attempts.
- **Idempotency:** Uses operation IDs and Redis-backed state to support duplicate-request handling.
- **Redis persistence:** Stores operation state and streaming results with configurable TTLs.
- **Graceful Redis fallback:** Allows LLM requests to proceed when Redis is unavailable, with reduced persistence guarantees.
- **Docker deployment:** Publishes a containerized application that can run locally or on a container hosting platform.

## Architecture

```text
Client
  |
  | POST /chat + Bearer JWT
  v
FastAPI Gateway
  |
  +--> JWT Validation
  |
  +--> Request ID / User Context
  |
  +--> Request Validation
  |
  +--> Operation ID / Idempotency
  |        |
  |        +--> Redis availability check
  |        +--> Check operation state
  |        +--> Reuse eligible stored results
  |        +--> Persist operation and chunks
  |
  +--> Provider Registry
  |        |
  |        +--> Groq Provider
  |
  +--> Retry + Exponential Backoff + Jitter
  |
  +--> Circuit Breaker
  |
  v
LLM Provider
  |
  | Generated chunks
  v
SSE Response
  |
  +--> Redis operation persistence
  |
  v
Client
```

Redis supports operation tracking and persistence. It is separate from the LLM provider. If Redis becomes unavailable, the gateway can continue without Redis-backed persistence, but the associated reliability guarantees are reduced.

## Tech Stack

- Python 3.12
- FastAPI and Uvicorn
- Redis / Render Key Value
- PyJWT
- Groq API and LangChain Groq integration
- Server-Sent Events
- Docker
- Render

## Getting Started

### Prerequisites

Install:

- Docker Desktop or Docker Engine
- A Groq API key
- A JWT signing secret
- Git, if cloning the source repository

Redis must run separately. The published gateway image does not include a Redis server, and this repository does not provide a Docker Compose YAML file.

### 1. Clone the repository

Replace the placeholder with your actual Git repository URL.

```bash
git clone https://github.com/chaithhanyaaa/gateway_service
```

### 2. Configure environment variables

Create a `.env` file in the directory from which you will run Docker:

```env
HOST=0.0.0.0
PORT=8080

# LLM provider
GROQ_API_KEY=your_groq_api_key

# JWT verification
JWT_SECRET=your_strong_random_secret
JWT_ALGORITHM=HS256
JWT_ISSUER=your-auth-service
JWT_AUDIENCE=llm-gateway

# Redis connection
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# Circuit breaker
GROQ_FAILURE_THRESHOLD=2
GROQ_RECOVERY_TIMEOUT=5.0

# Operation lifecycle
OPERATION_TTL_SECONDS=300
RUNNING_TTL_SECONDS=600
```

These are example values. Confirm the exact environment variable names against the application configuration. If the Redis client uses `Redis.from_url()`, configure `REDIS_URL` instead of separate host and port variables.

**Security:** Keep `.env` out of Git. Never publish your provider API key or JWT signing secret.

### 3. Start Redis

Because Redis is not included in the gateway image, start a separate Redis container:

```bash
docker run -d \
  --name gateway-redis \
  --restart unless-stopped \
  -p 127.0.0.1:6379:6379 \
  redis:7-alpine
```

This runs Redis on port `6379` on your local machine. The port mapping binds it to loopback, rather than exposing it to other machines on your network.

For local development, configure the gateway to connect to `host.docker.internal:6379` when it runs in Docker Desktop on Windows or macOS.

On Linux, `host.docker.internal` may require additional Docker configuration. An alternative is to run both containers on the same Docker network, as shown below.

#### Recommended: use a Docker network

Create a network:

```bash
docker network create gateway-network
```

Start Redis on that network:

```bash
docker run -d \
  --name gateway-redis \
  --network gateway-network \
  --restart unless-stopped \
  redis:7-alpine
```

When the gateway and Redis share this network, Docker's internal DNS resolves `gateway-redis` to the Redis container.

For this configuration, set:

```env
REDIS_HOST=gateway-redis
REDIS_PORT=6379
REDIS_DB=0
```

Redis is not published to the host in this configuration; only containers on the Docker network can reach it.

**Persistence note:** The command above does not configure a persistent data volume. Redis data can be lost when the container is removed. Add a Docker volume if local persistence is needed.

### 4. Run the gateway container

Pull the published image:

```bash
docker pull chaithhanyaaa/llm-gateway:latest
```

Run it on the same network as Redis:

```bash
docker run -d \
  --name gateway-app \
  --network gateway-network \
  --restart unless-stopped \
  --env-file .env \
  -p 8080:8080 \
  chaithhanyaaa/llm-gateway:latest
```

The gateway is now available at:

`http://localhost:8080`

The main endpoint is:

`POST http://localhost:8080/chat`

Check the container logs:

```bash
docker logs -f gateway-app
```

If your Docker image or environment uses a different port, update the mapping and the `PORT` setting accordingly.

## API Reference

### `POST /chat`

Accepts an authenticated chat request and streams generated content using SSE.

#### Headers

| Header | Value |
|---|---|
| `Authorization` | `Bearer <JWT_TOKEN>` |
| `Content-Type` | `application/json` |
| `Accept` | `text/event-stream` |

#### Request body

```json
{
  "operation_id": "a1719b20-d100-46d3-bade-a8af3f0c2c9a",
  "provider": "groq",
  "model": "qwen/qwen3.8-27b",
  "prompt": "Explain how Redis caching works.",
  "messages": []
}
```

| Field | Purpose |
|---|---|
| `operation_id` | Identifies the operation for tracking and idempotency handling. |
| `provider` | Selects the registered provider, such as `groq`. |
| `model` | Exact model ID accepted by the selected provider. |
| `prompt` | Current user prompt. |
| `messages` | Previous conversation messages in the schema expected by the application. |

The operation ID shown above is an example UUID. Follow the application's validation and operation-ID generation rules.

The precise request schema is defined by the application's Pydantic model. Check that model for required fields, types, and defaults.

### Example request with cURL

Replace the token and operation ID with valid values:

```bash
curl -N -X POST http://localhost:8080/chat \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "operation_id": "a1719b20-d100-46d3-bade-a8af3f0c2c9a",
    "provider": "groq",
    "model": "qwen/qwen3.8-27b",
    "prompt": "Explain how Redis caching works.",
    "messages": []
  }'
```

The `-N` option disables cURL's output buffering so streamed events can be displayed as they arrive.

### Streaming response

The endpoint returns an SSE response using `text/event-stream`.

Illustrative events:

```text
data: {"text": "Redis"}

data: {"text": " stores data"}

data: {"text": " in memory"}
```

The exact event format, completion marker, and error-event structure depend on the implementation.

An HTTP `200 OK` means the stream has started. The upstream LLM can still fail after the response begins, so clients should handle stream errors and unexpected termination.

## JWT Authentication

The endpoint requires a valid bearer token:

```http
Authorization: Bearer <JWT_TOKEN>
```

The gateway decodes and verifies the JWT using the configured secret, algorithm, issuer, and audience. The implementation requires these four claims:

- `sub`
- `iss`
- `aud`
- `exp`

### JWT payload

A typical decoded payload is:

```json
{
  "sub": "user_123",
  "iss": "your-auth-service",
  "aud": "llm-gateway",
  "exp": 1793003600
}
```

| Claim | Purpose |
|---|---|
| `sub` | Identifies the authenticated user. The gateway reads this as the user ID. |
| `iss` | Issuer of the token; must match `JWT_ISSUER`. |
| `aud` | Intended audience; must match `JWT_AUDIENCE`. |
| `exp` | Expiration time; the token is rejected after expiry. |

JWT timestamps use NumericDate values, represented as seconds since the Unix epoch. The example timestamps are illustrative.

###  To Generate a test JWT if you need

Install PyJWT if needed:

```bash
pip install PyJWT
```

Set `JWT_SECRET` to the same secret used by the gateway. Generate a token with:

```python
import os
import datetime
import jwt

now = datetime.datetime.now(datetime.timezone.utc)

payload = {
    "sub": "user_123",
    "iss": "your-auth-service",
    "aud": "llm-gateway",
    "exp": now + datetime.timedelta(hours=1),
}

token = jwt.encode(
    payload,
    os.environ["JWT_SECRET"],
    algorithm="HS256",
)

print(token)
```

The token generator and gateway must use the same signing secret and compatible configuration. Never hardcode the secret into the script or commit it to the repository.

## Reliability Design

### 1. Provider registry and Strategy Pattern

The router selects an LLM provider through a registry. Each provider implements a shared contract, keeping provider-specific request handling separate from the API router.

This reduces coupling, simplifies testing, and makes additional providers easier to integrate.

### 2. Retries and exponential backoff with jitter

The gateway retries eligible transient provider failures using