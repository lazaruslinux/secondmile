# Digest-pinned so a build is reproducible and a poisoned tag cannot slip in
# between two builds of the same commit; Dependabot bumps the digest. The tag
# rides along in this comment for humans: python:3.14-slim
FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

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

# The service parses payloads posted by a phone, so it does not run as root.
RUN useradd --create-home app
USER app

EXPOSE 8000

# Apply pending migrations, then serve. The upgrade is a no-op once the
# database is current, so restarts stay quick.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
