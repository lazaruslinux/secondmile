# Security policy

## Reporting

Use GitHub's private vulnerability reporting on this repository. I read
reports and will respond as quickly as I can; this is a personal project, not
a company with an on-call rotation.

Please do not open a public issue for anything exploitable.

## What counts

Anything that lets one user read or change another user's data, lets an
unauthenticated visitor do more than view the login page, bypasses the rate
limits or the invite requirement, forges workout data past the ingest
authentication, or escalates from the app to the host.

Flagging logic being wrong about a workout (a false positive on a fast run,
say) is a bug, not a vulnerability; open a normal issue for those.

## Deployment note

The compose file binds to localhost only. The intended deployment is behind
your own HTTPS reverse proxy, and nothing here terminates TLS or manages
certificates for you. If you exposed the raw ports to the internet, that is
outside what this project defends against.
