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