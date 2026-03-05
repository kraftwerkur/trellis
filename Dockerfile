# Stage 1: Build dashboard
FROM node:20-slim AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ .
RUN npm run build

# Stage 2: Python API + static dashboard
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY trellis/ trellis/
COPY --from=dashboard /dashboard/out /app/static
EXPOSE 8000
CMD ["uvicorn", "trellis.main:app", "--host", "0.0.0.0", "--port", "8000"]
