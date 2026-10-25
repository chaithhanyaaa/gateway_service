import logging
import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.src.core.config import Settings
from app.src.core.request_context import request_id_var,user_id_var

logger = logging.getLogger(__name__)

JWT_SECRET = Settings().JWT_SECRET
JWT_ALGORITHM = Settings().JWT_ALGORITHM
JWT_ISSUER = Settings().JWT_ISSUER
JWT_AUDIENCE = Settings().JWT_AUDIENCE

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
) -> str:
    request_id = request_id_var.get()

    if credentials is None:
        logger.warning("Authentication failed: missing bearer token")
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Missing bearer token",
                "request_id": request_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )

        user_id = payload["sub"]
        logger.info(f"Authenticated user: {user_id} with request ID: {request_id}")

        if not isinstance(user_id, str) or not user_id.strip():
            raise jwt.InvalidTokenError("Invalid subject")
    except jwt.ExpiredSignatureError:
      logger.warning("Authentication failed: expired bearer token")
      raise HTTPException(
          status_code=401,
          detail={
              "message": "Bearer token expired",
              "request_id": request_id,
          },
          headers={"WWW-Authenticate": "Bearer"},
      )

    except jwt.InvalidTokenError:
        logger.warning("Authentication failed: invalid bearer token")
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Invalid or expired bearer token",
                "request_id": request_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id_var.set(user_id)

    return user_id