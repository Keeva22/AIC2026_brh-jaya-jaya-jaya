# Hardware QC Inspection API

A FastAPI + PostgreSQL backend for a hardware quality-control inspection dashboard.
The device/inference script sends scan results to this API; the dashboard frontend
polls it for live and historical data.

---

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes both `docker` and `docker compose`)
- That's it — no Python installation needed on your host machine.

---

## Quick Start

### 1. Configure environment variables

A `.env` file is already provided with default development credentials.
You can edit it if you want to change the database password:

```
POSTGRES_USER=qc_user
POSTGRES_PASSWORD=change_me_in_production
POSTGRES_DB=qc_db
```

> **Security note:** Never use these default credentials in production.

---

### 2. Start the services

```bash
docker compose up --build
```

- `--build` rebuilds the FastAPI image (needed on first run or after code changes).
- Docker Compose starts PostgreSQL first and waits for it to be healthy before
  starting the API.

You should see log output from both `db` and `api` services. The API is ready
when you see a line like:

```
api-1  | INFO:     Application startup complete.
```

---

### 3. Access the API

| Resource | URL |
|---|---|
| Interactive API docs (Swagger UI) | http://localhost:8000/docs |
| Clean reference docs (ReDoc) | http://localhost:8000/redoc |
| Base URL for all API calls | http://localhost:8000 |
| PostgreSQL (for GUI tools) | `localhost:5432` |

---

### 4. Stop the services

```bash
# Stop containers (data is preserved in the Docker volume):
docker compose down

# Stop AND delete all data (wipes the database volume):
docker compose down --volumes
```

---

## API Endpoints

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns `{"status": "ok", "database": "connected"}` if everything is healthy. |

---

### Scans

#### `POST /scans` — Submit a scan result

Called by the hardware device or inference script after each scan.

**Request body (JSON):**

```json
{
  "object_type": "PCB",
  "verdict": "worthy",
  "confidence": 0.97,
  "image_url": "https://storage.example.com/scans/abc123.jpg"
}
```

- `object_type` — string, required, e.g. `"PCB"`
- `verdict` — string, required, must be `"worthy"` or `"not_worthy"`
- `confidence` — float, required, between `0.0` and `1.0`
- `image_url` — string, optional

**Example (curl):**

```bash
curl -X POST http://localhost:8000/scans/ \
  -H "Content-Type: application/json" \
  -d '{"object_type": "PCB", "verdict": "worthy", "confidence": 0.95}'
```

**Response (201 Created):**

```json
{
  "id": 1,
  "object_type": "PCB",
  "verdict": "worthy",
  "confidence": 0.95,
  "image_url": null,
  "created_at": "2025-07-15T09:00:00.000Z"
}
```

---

#### `GET /scans` — List scans (paginated + filterable)

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `verdict` | string | — | Filter by `worthy` or `not_worthy` |
| `date_from` | date | — | Start of date range (`YYYY-MM-DD`) |
| `date_to` | date | — | End of date range (`YYYY-MM-DD`) |
| `page` | int | `1` | Page number (starts at 1) |
| `page_size` | int | `20` | Items per page (max 200) |

**Example:**

```bash
# All failing scans on a specific date
curl "http://localhost:8000/scans/?verdict=not_worthy&date_from=2025-07-01&date_to=2025-07-01"

# Page 2 of all scans, 50 per page
curl "http://localhost:8000/scans/?page=2&page_size=50"
```

**Response:**

```json
{
  "total": 142,
  "page": 1,
  "page_size": 20,
  "items": [ ... ]
}
```

---

#### `GET /scans/latest` — Most recent N scans (for polling)

The frontend calls this endpoint every few seconds to show a live feed.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | `10` | How many recent scans to return (max 100) |

**Example:**

```bash
curl "http://localhost:8000/scans/latest?limit=5"
```

**Response:** Array of scan objects, newest first.

---

### Statistics

#### `GET /stats/summary` — Aggregate statistics

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `date_from` | date | — | Start of date range (`YYYY-MM-DD`) |
| `date_to` | date | — | End of date range (`YYYY-MM-DD`) |
| `group_by_day` | bool | `false` | Include per-day breakdown |

**Example:**

```bash
# Overall stats for July
curl "http://localhost:8000/stats/summary?date_from=2025-07-01&date_to=2025-07-31"

# With daily breakdown
curl "http://localhost:8000/stats/summary?group_by_day=true"
```

**Response:**

```json
{
  "total_scans": 500,
  "worthy_count": 463,
  "not_worthy_count": 37,
  "pass_rate": 0.926,
  "daily_breakdown": [
    {
      "date": "2025-07-01",
      "total": 120,
      "worthy": 112,
      "not_worthy": 8,
      "pass_rate": 0.9333
    }
  ]
}
```

---

## Project Structure

```
backend-service/
├── app/
│   ├── __init__.py         # Marks 'app' as a Python package
│   ├── main.py             # FastAPI app: middleware, routers, health check
│   ├── database.py         # SQLAlchemy engine + session setup
│   ├── models.py           # ORM model: the 'scans' table definition
│   ├── schemas.py          # Pydantic schemas: request/response validation
│   └── routers/
│       ├── __init__.py
│       ├── scans.py        # /scans endpoints
│       └── stats.py        # /stats endpoints
├── .env                    # Local secrets (not committed to git)
├── .env.example            # Template — copy this to .env
├── .gitignore
├── docker-compose.yml      # Orchestrates FastAPI + PostgreSQL
├── Dockerfile              # Recipe to build the FastAPI container image
├── requirements.txt        # Pinned Python dependencies
└── README.md               # This file
```

---

## Development Tips

### Rebuilding after code changes

If you change `requirements.txt` or the `Dockerfile`, rebuild the image:

```bash
docker compose up --build
```

If you only change Python files under `app/`, the `--reload` flag in the
Dockerfile will pick up changes automatically (no rebuild needed).

### Viewing logs

```bash
# All services
docker compose logs -f

# Just the API
docker compose logs -f api

# Just the database
docker compose logs -f db
```

### Connecting to the database directly

You can use any PostgreSQL GUI (pgAdmin, DBeaver, TablePlus) with:

- **Host:** `localhost`
- **Port:** `5432`
- **Database:** value of `POSTGRES_DB` in your `.env`
- **User / Password:** values of `POSTGRES_USER` / `POSTGRES_PASSWORD`

Or via the CLI:

```bash
docker compose exec db psql -U qc_user -d qc_db
```

### Running a quick test with sample data

```bash
# Submit 3 scans
curl -s -X POST http://localhost:8000/scans/ -H "Content-Type: application/json" \
  -d '{"object_type":"PCB","verdict":"worthy","confidence":0.98}' | python -m json.tool

curl -s -X POST http://localhost:8000/scans/ -H "Content-Type: application/json" \
  -d '{"object_type":"PCB","verdict":"not_worthy","confidence":0.91}' | python -m json.tool

curl -s -X POST http://localhost:8000/scans/ -H "Content-Type: application/json" \
  -d '{"object_type":"resistor","verdict":"worthy","confidence":0.75}' | python -m json.tool

# Check the live feed
curl -s "http://localhost:8000/scans/latest" | python -m json.tool

# Check overall stats
curl -s "http://localhost:8000/stats/summary" | python -m json.tool
```
