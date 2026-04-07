"""Application-level exception types and FastAPI exception handlers.

Register all handlers in main.py via:
    from app.core.exceptions import register_exception_handlers
    register_exception_handlers(app)
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class VerityError(Exception):
    """Base class for all application errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(VerityError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, status_code=404)


class ConflictError(VerityError):
    def __init__(self, message: str = "Resource already exists") -> None:
        super().__init__(message, status_code=409)


class ValidationError(VerityError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=422)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach exception handlers to the FastAPI app instance."""

    def _sanitize_for_json(value: Any) -> Any:
        """Ensure values returned in error payloads are JSON-serialisable.

        Some validation errors can include ``Ellipsis`` (``...``) as an input marker
        for "missing required field". FastAPI's default encoder can't serialise it.
        """
        if value is ...:
            return None
        if isinstance(value, Mapping):
            return {k: _sanitize_for_json(v) for k, v in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [_sanitize_for_json(v) for v in value]
        return value

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = _sanitize_for_json(exc.errors())
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(errors)},
        )

    @app.exception_handler(VerityError)
    async def verity_error_handler(request: Request, exc: VerityError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )
