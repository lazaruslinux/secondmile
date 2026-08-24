"""The two messages this app sends, and the log line it writes instead when no
mail server is configured.

Both are a link and nothing else, both links land on the same page of the
frontend, and both carry their token in the fragment so no proxy log along the
way ever holds a working credential.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import APP_NAME, settings
from app.security import VERIFY_TOKEN_HOURS

log = logging.getLogger("secondmile.mail")

_SUBJECT = f"Verify your {APP_NAME} account"

_BODY = """Someone created a {app} account with this address.

Open this link to finish signing up:

{url}

The link works once and stops working after {hours} hours. If this was not you,
nothing happens: ignore this message and no account is created.
"""

_CHANGE_SUBJECT = f"Confirm this address for your {APP_NAME} account"

_CHANGE_BODY = """Someone asked to use this address for their {app} account.

Open this link to confirm it:

{url}

The link works once and stops working after {hours} hours. If this was not you,
nothing happens: ignore this message and the account keeps the address it has.
"""


def verification_url(token: str) -> str:
    """The link that lands on the frontend, which reads the token and calls the API.

    The token rides in the URL fragment, not the query string, because fragments
    never leave the browser: a query token would be written to the access log of
    every proxy the request crosses, and a log line must not be a working
    credential for the account.
    """
    return f"{settings.site_url.rstrip('/')}/verify#token={token}"


def send_verification(address: str, token: str) -> None:
    """Mail a link that finishes a signup."""
    _send(address, token, _SUBJECT, _BODY)


def send_email_change(address: str, token: str) -> None:
    """Mail a link that confirms an address somebody has asked to move to.

    Sent to the new address and never to the old one, because the new address is
    the only thing this proves anything about: whoever answers it is the person
    holding that inbox.
    """
    _send(address, token, _CHANGE_SUBJECT, _CHANGE_BODY)


def _send(address: str, token: str, subject: str, body: str) -> None:
    """Mail one link, or log it when there is nowhere to mail it.

    Called from a background task, so it runs after the response has already
    been sent and a slow or unreachable mail server never becomes a slow
    request. Nothing here raises: the caller is gone by this point, and the
    person waiting can always ask for another link.
    """
    url = verification_url(token)
    if not settings.smtp_host:
        # The documented no-mail setup. Warning level rather than info so it
        # survives whatever log filtering the container is run with, because on
        # such an install this line is the only copy of the link.
        log.warning("No SMTP configured. Verification link for %s: %s", address, url)
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = address
    message.set_content(body.format(app=APP_NAME, url=url, hours=VERIFY_TOKEN_HOURS))

    try:
        # Port 465 speaks TLS from the first byte and 587 negotiates it with
        # STARTTLS. Sending a STARTTLS handshake into an implicit-TLS port does
        # not fail cleanly, it hangs until the timeout, so the port decides
        # which one is used rather than leaving the admin to find that out.
        # Typed as the base class because SMTP_SSL is one: the branch picks
        # which is built, and everything below talks to either.
        server: smtplib.SMTP
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if settings.smtp_port != 465:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(message)
    except (smtplib.SMTPException, OSError):
        # The link is not repeated here. It is a working credential for the
        # account, and a log kept for troubleshooting is read by more people
        # than the inbox it was meant for.
        log.exception("Could not send the verification mail for %s", address)
