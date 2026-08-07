"""The FastAPI application: configuration guard, error shape, and routes."""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import config
from app.config import (
    APP_NAME,
    APP_VERSION,
    MAX_BODY_BYTES,
    MAX_INGEST_BODY_BYTES,
    check_deploy_config,
)
from app.routers import auth, chests, fellowship, grove, ingest, profile, settings, workouts

# Run before anything else imports an engine. Failing during import stops
# uvicorn before it binds a port, so a misconfigured install never serves a
# single request rather than serving them insecurely.
check_deploy_config()

app = FastAPI(title=APP_NAME, version=APP_VERSION)

_BODY_CAPS = {"/api/ingest": MAX_INGEST_BODY_BYTES}


async def _send_too_large(send) -> None:
    body = b'{"detail":"Request body is too large."}'
    await send(
        {
            "type": "http.response.start",
            "status": status.HTTP_413_CONTENT_TOO_LARGE,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Refuses an oversized request body before anything tries to hold it.

    Pure ASGI rather than a FastAPI dependency so it runs outside body parsing
    entirely: an honest Content-Length is answered before a byte is read, and a
    body that arrives without one is counted as it streams.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        cap = _BODY_CAPS.get(scope.get("path", ""), MAX_BODY_BYTES)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > cap:
                    await _send_too_large(send)
                    return
            except ValueError:
                # A header that is not a number proves nothing either way; the
                # streamed count below is the real guard.
                pass

        received = 0
        too_large = False

        async def counting_receive():
            nonlocal received, too_large
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > cap:
                    # Ending the stream rather than raising: an exception here
                    # would surface as a 500 from inside the handler, while a
                    # truncated body fails to parse and produces a 400 that the
                    # sender below corrects to the honest status.
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def correcting_send(message):
            if (
                too_large
                and message["type"] == "http.response.start"
                and message["status"] == status.HTTP_400_BAD_REQUEST
            ):
                message = {**message, "status": status.HTTP_413_CONTENT_TOO_LARGE}
            await send(message)

        await self.app(scope, counting_receive, correcting_send)


app.add_middleware(BodySizeLimitMiddleware)


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
    and a version banner, nothing an unauthenticated caller should not know.

    The registration mode is in here because the sign-in screen has to know
    whether to ask for an invite code before anyone has signed in, and it is
    not a secret: anyone can learn it by sending the form once.

    The timezone is here because the app has to render times in it. A browser
    that reports a zone of its own is not to be trusted with this: privacy
    settings that pin the browser to UTC are common, and a workout started at
    05:44 would read as 12:44.
    """
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        # Read through the module rather than bound at import, so the settings
        # object is the one source of the answer.
        "registration_open": config.settings.registration_open,
        # The zone that actually loaded rather than the raw setting, so a name
        # this server could not resolve is never handed to a client that then
        # has to resolve it too.
        "timezone": str(config.SERVER_TZ),
    }


app.include_router(auth.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(workouts.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(chests.router, prefix="/api")
app.include_router(grove.router, prefix="/api")
app.include_router(fellowship.router, prefix="/api")
