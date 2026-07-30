"""The FastAPI application: configuration guard, error shape, and routes."""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import APP_NAME, APP_VERSION, check_deploy_config
from app.routers import auth, ingest, settings, workouts

# Run before anything else imports an engine. Failing during import stops
# uvicorn before it binds a port, so a misconfigured install never serves a
# single request rather than serving them insecurely.
check_deploy_config()

app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Answer a malformed body with the same error shape as everything else.

    The framework default is a 422 whose detail is a list of field objects.
    Every other error here is {"detail": "<sentence>"}, and one endpoint
    answering in a different shape means the client needs two ways to read an
    error. The specifics are dropped deliberately: field paths from a body the
    caller sent them are of no help to the caller and of some help to anyone
    probing the API.
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Request body is missing or malformed."},
    )


@app.get("/api/status")
def read_status() -> dict:
    """Public, unauthenticated, and deliberately dull: enough for a health check
    and a version banner, nothing an unauthenticated caller should not know."""
    return {"name": APP_NAME, "version": APP_VERSION}


app.include_router(auth.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(workouts.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
