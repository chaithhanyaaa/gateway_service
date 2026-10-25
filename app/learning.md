- retries : okay to retry before the first chunk we receive ,because immediatly the router recives the chumk it sends to the user if we retry after the first chumk we may get duplicate chunks
- we do retry max 3 times that too if in the first attempt if it failes after the first chunk we just terminates the loop and rise the exeption it will catched by the router and sends the error to the client
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
