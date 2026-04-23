from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.settings import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def verify_bearer(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.api_key:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "unauthorized",
                "message": "Invalid or missing bearer token",
                "details": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    if token != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "unauthorized",
                "message": "Invalid or missing bearer token",
                "details": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
