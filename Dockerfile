# ---- Stage 1: Build Dependencies ----
# Use a slim Python image to install our packages.
FROM python:3.11-slim as builder

WORKDIR /app

# Create a virtual environment to isolate our dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the requirements file and install dependencies into the virtual environment
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: Final Runtime Image ----
# Use a fresh slim image for the final, smaller application image
FROM python:3.11-slim

WORKDIR /code

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy the application code
COPY ./app /code/app
COPY ./alembic /code/alembic
COPY ./alembic.ini /code/alembic.ini

# Set the PATH to use the virtual environment's executables
ENV PATH="/opt/venv/bin:$PATH"

# Expose the port the app will run on
EXPOSE 80

# The command to run the application:
# 1. Run database migrations to ensure the schema is up-to-date.
# 2. Start the Uvicorn server, binding to all interfaces on port 80.
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 80