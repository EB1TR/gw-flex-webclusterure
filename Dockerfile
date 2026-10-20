FROM python:3.14-alpine AS dependencies

WORKDIR /build
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --no-compile --only-binary=:all: \
    --target /dependencies -r requirements.txt

FROM python:3.14-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/dependencies

WORKDIR /app
COPY --from=dependencies /dependencies /opt/dependencies
COPY app.py .

USER 10001:10001
EXPOSE 12063

ENTRYPOINT ["python", "app.py", "--config", "/config/config.toml", "--ws-host", "0.0.0.0"]
