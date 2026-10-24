import uuid

from app.src.core.request_context import request_id_var,user_id_var


class RequestIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Only process HTTP requests.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Generate a unique ID for this request.
        request_id = uuid.uuid4().hex

        # Store it in this execution context.
        token = request_id_var.set(request_id)

        async def send_with_request_id(message):
            # Add the ID to the response headers.
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-request-id", request_id.encode("ascii"))
                )
                message = {**message, "headers": headers}

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)