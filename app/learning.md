# Features
- reliability(retries,backoffs using jitter,timeouts,idempotency(handled race condition using lua script),circuit breaker)
- logging (json foramte) 
- observability
- prompt validation to save cost ,context window 
- multiple llm providers support through stratergy pattren
- streaming response to make user feel faster response


### LLM Gateway — Engineering Progress Record

1. **Initial implementation:** Built a FastAPI-based LLM gateway using the Strategy pattern and provider registry, with Groq integration and Server-Sent Events (SSE) for streaming responses.

2. **Before reliability improvements:** The gateway could forward model responses, but needed stronger handling for transient provider failures, repeated requests, request tracing, and operational visibility.

3. **Reliability engineering:** Added retry handling with exponential backoff and jitter, a circuit breaker, and idempotency controls to reduce the impact of transient failures and duplicate operations.

4. **Structured observability:** Implemented JSON logs with request IDs, authenticated user IDs, operation IDs, provider/model details, exception traces, and timing measurements.

5. **Streaming performance instrumentation:** Measured initialization duration, first raw chunk, first non-empty content, router-observed first content, total streaming duration, and chunk count.

6. **Redis integration:** Added Redis-backed response persistence with batched chunk writes and TTL-based caching work. The implementation must preserve streaming responsiveness while handling Redis failures and incomplete generations safely.

7. **Model benchmark — October 26, 2026:** Compared three successful Groq model requests using the same benchmark setup:
   - GPT-OSS 20B: 7.40 s router-observed first content; 9.26 s total.
   - Qwen 3.8 27B: 5.57 s router-observed first content; 6.54 s total.
   - GPT-OSS 120B: 6.96 s router-observed first content; 13.50 s total.
   These are preliminary single-request observations, not statistically reliable rankings.

8. **Streaming failure semantics:** Identified that HTTP 200 can be committed before model generation succeeds. Provider errors after SSE starts must be communicated through structured SSE error events; clients must not treat HTTP 200 alone as successful generation.

9. **Resume/LinkedIn positioning:** Present the project as an observable, reliability-focused LLM gateway that combines streaming, model-provider abstraction, retries, circuit breaking, idempotency, Redis integration, structured logging, and latency benchmarking. Add measured production-scale claims only after repeatable load tests and deployment validation.


## Latency 
# LLM Gateway — Streaming Latency Benchmark
**Date:** October 26, 2026

## 1. Benchmark Results

| Metric | GPT-OSS 20B | Qwen 3.8 27B | GPT-OSS 120B |
|---|---:|---:|---:|
| Initialization time | 0.27 s | 0.46 s | 0.26 s |
| First raw chunk (possibly empty) | 1.62 s | 0.94 s | 0.64 s |
| First non-empty content (provider timer) | 3.14 s | 0.94 s | 1.02 s |
| First non-empty content (router timer) | 7.40 s | 5.57 s | 6.96 s |
| Total streaming duration | 9.26 s | 6.54 s | 13.50 s |
| Chunks observed | 940 | 638 | 2,923 |
| Outcome | Success | Success | Success |

## 2. What the Measurements Mean

- **Initialization time:** Time taken by the gateway to prepare the streaming response.
- **First raw chunk:** The first chunk yielded by the provider stream. It can be empty, so it does not necessarily mean the user has received answer text.
- **First non-empty content — provider timer:** Time measured by the provider integration until actual text content arrives.
- **First non-empty content — router timer:** Time measured by the router until it receives its first non-empty provider chunk. This timer starts from a different point, so its values should not be directly compared with provider-timer values.
- **Total streaming duration:** Time from the router's streaming timer start until generation completes.

## 3. Key Observations

- **Qwen 3.8 27B** had the shortest observed total streaming duration: **6.54 seconds**.
- **GPT-OSS 120B** produced the first raw chunk fastest at **0.64 seconds**, but that chunk was empty. Its first non-empty content arrived at **1.02 seconds** on the provider timer.
- **GPT-OSS 20B** took **3.14 seconds** to produce its first non-empty content on the provider timer.
- A fast first chunk does not necessarily mean a fast complete response. GPT-OSS 120B had the longest total duration at **13.50 seconds**.

## 4. Drawbacks and Limitations

1. **Only one request per model:** These results are preliminary. Network conditions, provider load, and transient variation can affect timings.
2. **Different output sizes:** Chunk counts differ significantly. Chunks are not equivalent to tokens, so they cannot establish which model has higher token throughput.
3. **Different timer start points:** Provider and router measurements include different portions of the request lifecycle. Compare the same metric across models.
4. **No controlled throughput measurement:** These tests do not establish performance under concurrent users or sustained load.
5. **No statistical confidence:** Repeat each model test 5–10 times with identical prompts and settings, then compare medians and output token counts.
6. **HTTP 200 is not generation success:** Because SSE headers are sent before generation finishes, a later provider error may occur after the HTTP status is committed. The client must handle structured SSE error events.

**Conclusion:** In this initial test, Qwen 3.8 27B completed the response fastest, while GPT-OSS 120B showed the fastest arrival of the first raw chunk. These are single-request observations, not definitive model rankings.

---
- retries : okay to retry before the first chunk we receive ,because immediatly the router recives the chumk it sends to the user if we retry after the first chunk we may get duplicate chunks
- we do retries max 3 times that too if in the first attempt if it fails after the first chunk we just terminates the loop and rise the exeption it will catched by the router and sends the error to the client,update status failed in redis
- backof retries ,instead of retring immediatly which actually increses the load to the server ,we retry after some gap .we have that function in the util file that actaully calculates the delay.
- in production multiple users sends rqst simuktaneously we need some thing to identify the http ,we can use middleware assign the rqst id ,later we can even add validation through token ,user send the token ,we validate and extract the user id .
- issue is if we use onlu user id and user sends three rqsts all 3 http shows the same id ,we need to differentiate each rqst ,so we use both userid,rqst id.
- we create a context to store the rqst id when it reaches
- for validation backen service sends jwt it has userid,expiry,who generated it ,to whome it is .

### circute breakers
- suppose llm service is experiencing an outage and every rqst fails backoff helps space out retries ,but imagine 1000 users arraving to that llm service ,if each user do three attempts ,our gate way could make up to 3000 attemps.
- this causes unnecessary rqsts to unhealty service,latency for clients,wasted resources .
- retries helps with temporary failures.
- solition is circuit breaker ,after enough qualifying failures ,it temprarily stops seng rqsts to the llm service
- CLOSED:rqst can reach llm service,failures are monitered.
- OPEN:calls are blocked,reqts fail fast instead of repeatedly callng llm.
- HALF_OPEN:requery test,limited no of rqsts are allowed to test the service

- WORKING
Requests reach Groq normally.
Five qualifying failures occur.
The breaker opens.
New requests to Groq are rejected quickly without making an upstream call.
After a cooldown, the breaker allows a limited recovery probe.
If Groq recovers, the breaker closes; otherwise, it opens again.

### IDEMPOTENCY
- we have client , backend , gateway , llm
- gateway has also connection with redis ,redis has status,operation key,chunks .
- client starts with sending rqst it has opeartion key ,backend forwords that to the gateway and gateway asks the llm service ,now gateway before sending to the backend it updates the redis for every chunk ,after the stream it updates the status to "done",if llm service is down while streaming , gateway waits untill the time is out and after that it updates the status failed,now user side time will be out and he tries again,now gateway checks if it is failed so refetches from the llm.
- if connection between the backend client is failed same client asks with same key ,backend asks gateway it asks redis if it seens done,sends that .
-what if streaming is being done from gateway to backend ,now user retried due to conection lost between backend and client he lost response so he retries ,now backend again asks gateway and gate sees the redis it decides if that to ask llm or redis is enough send all chunks from the first chunk

- so the redis store key=operationid, value=[fingerprints(shahash of prompt,model,operation key),messages,prompt,status]

```
Situation	                                                          Server action
Same user + same operation ID + same fingerprint + RUNNING	        Attach to the existing stream
Same user + same operation ID + same fingerprint + DONE	            Replay stored chunks
Same user + same operation ID + different fingerprint	              Return 409 Conflict
```

### handling race condition 
- imagine user clicked the send button twice accedentally ,due context switching they both see no key in redis ,so both goes to the llm.
```
if not await redis_client.exists(key):
    await redis_client.hset(key, mapping=data)
```
- here this is not attomic so we use lua script to make it attomic ,we added that in the  app/src/service/operation_store.py

- here we will have 2 pairs ,one for metadata ,other for chunks
```
userid:operationid:chunks - actuall chunks
userid:operationid -{status,chunkcount,fingerprints,status}
```
- we have create fingerprint function in util service ,we use this in chatrouter 
- RUNNING: TTL of 10 minutes, refreshed while streaming.
COMPLETED: TTL of 5 minutes.
FAILED: TTL of 5 minutes.

---


## 1. Timeout Strategy

### First Chunk Timeout
- The first chunk may take longer because the provider needs to process the prompt and begin generation.
- Use a configurable **30-second first-chunk timeout** initially.
- If the first chunk does not arrive within 30 seconds, treat it as a retryable failure.
- The gateway retries the LLM request using the existing manual retry mechanism.
- Retries use exponential backoff with jitter.
- The retry limit is configurable.
- If all retries fail before the first chunk, mark the operation as `FAILED` in Redis.
- Return a safe error response to the backend.

### Subsequent Chunk Timeout
- Use a configurable **10-second per-chunk idle timeout**.
- After receiving the first chunk, wait at most 10 seconds for each subsequent chunk.
- If the next chunk does not arrive within 10 seconds:
  - Stop consuming the LLM stream.
  - Do not retry the LLM generation.
  - Mark the operation as `FAILED` in Redis.
  - Store a safe error message.
  - Send an SSE error event to the backend if the connection is still active.
- The 10-second timeout is an idle timeout, not a total generation timeout.
- If chunks continue arriving within 10 seconds, the stream may continue for longer than 10 seconds overall.

### Why the Retry Policy Changes After the First Chunk
- Before the first chunk, the client has not received generated content.
- The gateway can retry without creating a partial response that must be reconciled.
- After the first chunk, the client may already have received part of the response.
- Retrying the entire generation could produce a different answer.
- Mixing the old and new generations would create an invalid response.
- Therefore, retry only before the first chunk.

---

## 2. Gateway Operation State

Redis stores two keys for each authenticated user and operation.

### Metadata Key

`operation:{user_id}:{operation_id}`

Fields:
- `status`
- `user_id`
- `fingerprint`
- `chunk_count`
- `error` (safe error information, when applicable)

### Chunks Key

`operation:{user_id}:{operation_id}:chunks`

- Stores the actual generated response chunks.
- Chunks are persisted before being sent to the backend.
- The metadata and chunks keys must have consistent TTL handling.
- TTL and cleanup will be implemented separately.

### Operation Statuses

- `RUNNING`
- `COMPLETED`
- `FAILED`

### Retry Rules

| Operation state | Gateway behavior |
|---|---|
| `RUNNING` | Attach to the existing stream |
| `COMPLETED` | Replay stored chunks |
| `FAILED`, `chunk_count = 0` | Retry may be allowed |
| `FAILED`, `chunk_count > 0` | Do not retry the same operation |
| Same operation ID, different fingerprint | Return `409 Conflict` |

- Operation claiming must be atomic.
- Use Redis Lua scripts to prevent concurrent requests from independently claiming the same operation.
- A fingerprint is generated from canonical request parameters, including authenticated user ID, prompt, messages, provider, model, and generation settings.
- The operation ID itself is excluded from the fingerprint.
- A new logical generation receives a new operation ID.
- A retry or reconnection for the same logical generation reuses the original operation ID.

---

## 3. Backend Retry and Reconnection Behavior

The backend forwards the operation ID to the gateway and must preserve it across retries for the same logical generation.

### Backend Responsibilities
- Generate an operation ID for each new logical generation.
- Reuse the same operation ID when retrying the same operation.
- Avoid automatically creating a new operation ID after a partial response failure.
- Forward SSE chunks and terminal events to the client.
- Distinguish between a completed response and a failed response.
- Avoid blindly retrying a failed operation after the first chunk.

### Backend Reconnection Flow

When the client loses its connection to the backend:

1. The client retries using the same operation ID.
2. The backend forwards the request to the gateway.
3. The gateway checks Redis.
4. If the operation is `RUNNING`, the gateway attaches the backend to the existing stream.
5. If the operation is `COMPLETED`, the gateway replays the stored chunks.
6. If the operation is `FAILED`, the gateway returns the failure without automatically starting a new generation.

### Important Distinction
- A network disconnect does not necessarily mean the LLM operation should be cancelled.
- The gateway may continue generation so that a reconnecting backend can attach to it.
- Explicit cancellation is a separate operation.
- The gateway must not confuse a disconnected client with a failed LLM generation.

---

# Latency:for the first non empty chunk form the llm is 2.8sec 

##  Metrics learning
- 

