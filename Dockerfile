# ============================================================
# Dockerfile for the FastAPI QC Inspection API
# ============================================================
#
# A Dockerfile is a recipe that tells Docker how to build a container image.
# Each instruction (FROM, WORKDIR, COPY, RUN, etc.) adds a "layer" to the image.
# Docker caches layers, so if requirements.txt hasn't changed, it won't
# reinstall packages — making subsequent builds much faster.
# ============================================================

# -- Base image --
# We use the official Python 3.12 slim image.
# "slim" means it's a smaller variant without build tools, which is fine
# because psycopg2-binary bundles its own native libraries.
FROM python:3.12-slim

# -- Working directory --
# All subsequent commands run inside /app inside the container.
# This is the root of our project inside the container filesystem.
WORKDIR /app

# -- Install dependencies --
# We copy requirements.txt FIRST (before the rest of the code) so Docker
# can cache the pip install step. If only your code changes (not requirements),
# Docker reuses the cached layer and the build is much faster.
COPY requirements.txt .

# --no-cache-dir   = don't store the pip download cache (saves image space)
# --upgrade pip    = make sure pip itself is up to date
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# -- Copy application source code --
# After installing deps, copy all the app source files into the container.
COPY ./app ./app

# -- Expose the port --
# Documents that the container listens on port 8000.
# This doesn't actually publish the port — that's done in docker-compose.yml.
EXPOSE 8000

# -- Start the application --
# uvicorn is the ASGI server that runs FastAPI.
#
#   app.main:app  = Python module path: the 'app' object in 'app/main.py'
#   --host 0.0.0.0  = listen on all network interfaces (required in Docker;
#                      without this the container is unreachable from outside)
#   --port 8000   = match the EXPOSE above
#   --reload      = auto-restart when code changes (great for development;
#                   remove this flag for a production deployment)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
