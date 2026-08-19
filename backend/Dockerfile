# Digest-pinned so a build is reproducible and a poisoned tag cannot slip in
# between two builds of the same commit; Dependabot bumps the digest. The tag
# rides along in this comment for humans: python:3.14-slim
FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The one thing this image needs that pip cannot install. Every uploaded video
# is probed with ffprobe and re-encoded with ffmpeg before it is stored, so the
# binaries are as much a dependency as Pillow is. Installed from the base
# image's own distribution rather than as a Python wrapper: the wrappers ship
# the same binaries with a package index in front of them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Requirements are copied on their own so the install layer stays cached across
# every build that changed only application code. requirements.txt pins every
# package with a hash, and --require-hashes makes pip refuse anything that does
# not match, so a compromised index cannot substitute a package.
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
COPY manage.py .

# The service parses payloads posted by a phone and decodes images uploaded
# from a browser, so it does not run as root.
RUN useradd --create-home app

# Created and owned before the volume is mounted over it. A named volume takes
# its ownership from the image's directory, so without this the mounted path
# arrives owned by root and the unprivileged process cannot write an avatar.
RUN mkdir -p /data/avatars /data/photos /data/videos /data/reports \
    && chown app:app /data/avatars /data/photos /data/videos /data/reports \
    && chmod 700 /data/reports

USER app

EXPOSE 8000

# Apply pending migrations, then serve. The upgrade is a no-op once the
# database is current, so restarts stay quick.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
