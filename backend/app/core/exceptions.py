"""Application-level exception types and FastAPI exception handlers.

Register all handlers in main.py via:
    from app.core.exceptions import register_exception_handlers
    register_exception_handlers(app)
"""
from fastapi import FastAPI, Request
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

    @app.exception_handler(VerityError)
    async def verity_error_handler(request: Request, exc: VerityError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )
