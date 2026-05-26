# plates

Web‑based ALPR (Automatic License Plate Recognition) system for Brazilian plates.

## Goal

Build a web‑based ALPR system that uses the client's browser camera, detects Brazilian license plates, saves detections (with raw image) to PostgreSQL, and exposes tuneable parameters via a DB‑driven config table.

## Constraints & Preferences

- All camera enumeration and video capture must happen in the client browser (`getUserMedia` + `enumerateDevices`), not on the server.
- Only Brazilian plates matching `AAA9A99` (Mercosul) or `AAA9999` (old format) may be saved.
- Detections must be deduplicated: same plate + same camera within a configurable time window is not saved again.
- Confidence threshold must be enforced before saving; configurable via DB.
- The config table must hold parameters like `dedup_seconds`, `cleanup_interval`, and `confidence_threshold`.
- PostgreSQL database on localhost, database `plates`, user `moesio`, password `moesio`.
- The `image` column must be `bytea` storing raw JPEG bytes, not base64 text.
- Camera identifier (`camera_id`) must be a string (the browser's `deviceId`), not an integer.
- Unit tests must exist for all core logic (plate validation, config, detect endpoint, API).

## Quick Start

```bash
# install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# set up database
cp .env.example .env
# edit .env with your DATABASE_URL if needed
alembic upgrade head

# run
python webapp/webapp.py
```

Open `http://localhost:5000` in a browser. The app will request camera access and begin detecting plates automatically.

For HTTPS access from mobile devices (required for `getUserMedia` over non-localhost), use `ngrok` or a self-signed certificate:

```bash
ngrok http 5000
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the client-side HTML/JS page |
| `POST` | `/detect` | Receives a JPEG frame, returns JSON detections |
| `GET` | `/config` | Lists all config parameters (from cache) |
| `PUT` | `/config/<key>` | Updates a config parameter (immediate effect) |

### POST /detect

**Request:** `multipart/form-data` with a field `image` containing a JPEG frame.

**Response:**
```json
{
  "detections": [
    {"plate": "ABC1D23", "confidence": 0.95, "camera_id": "...", "camera_name": "..."}
  ]
}
```

Empty `detections` array when no plate is found or confidence is below threshold.

## Configuration

Stored in the `config` PostgreSQL table with an in-memory cache (10s TTL). Changes via `PUT /config/<key>` take immediate effect.

| Key | Default | Description |
|-----|---------|-------------|
| `dedup_seconds` | `60` | Deduplication window in seconds |
| `cleanup_interval` | `20` | How often stale dedup cache entries are purged (every N saves) |
| `confidence_threshold` | `0.0` | Minimum confidence to accept a detection |
| `rtsp_cameras` | `[]` | Câmeras IP (JSON array, ver seção RTSP) |

### RTSP Cameras

Além da captura pelo navegador, o sistema suporta câmeras IP via RTSP. Configure-as atualizando o parâmetro `rtsp_cameras` com um JSON array:

```bash
curl -X PUT http://localhost:5000/config/rtsp_cameras \
  -H "Content-Type: application/json" \
  -d '{"value": "[{\"host\":\"192.168.1.100\",\"port\":554,\"username\":\"admin\",\"password\":\"12345\",\"path\":\"/Streaming/Channels/101\",\"name\":\"Portaria\"}]"}'
```

Campos disponíveis por câmera:

| Campo | Obrigatório | Default | Descrição |
|-------|-------------|---------|-----------|
| `host` | Sim | — | IP ou hostname da câmera |
| `port` | Sim | `554` | Porta RTSP |
| `username` | Não | `""` | Usuário de autenticação |
| `password` | Não | `""` | Senha de autenticação |
| `path` | Não | `"/"` | Caminho do stream RTSP |
| `name` | Não | `"rtsp:<host>:<port>"` | Nome amigável (salvo no banco) |

As threads RTSP são iniciadas automaticamente na primeira requisição HTTP após a aplicação subir. Cada câmera executa em uma *daemon thread* que captura 1 frame por segundo, executa ALPR, valida a placa, deduplica e salva no banco. Se o stream cair, a thread tenta reconectar com backoff exponencial (3s–30s).

## Project Structure

```
plates/
├── webapp/
│   ├── __init__.py
│   ├── webapp.py          # Flask app, routes, core logic
│   ├── database.py        # SQLAlchemy models (Detection, Config)
│   ├── config.py          # Config cache manager
│   └── templates/
│       └── index.html     # Client-side camera + detection UI
├── tests/
│   ├── conftest.py        # Pytest fixtures
│   ├── test_plate.py      # Plate validation tests (13)
│   ├── test_config.py     # Config module tests (14)
│   ├── test_detect.py     # Detect endpoint tests (9)
│   ├── test_api.py        # Config API tests (6)
│   └── test_rtsp.py       # RTSP support tests (14)
├── alembic/               # Database migrations
├── .env.example
├── requirements.txt
└── README.md
```

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

All 56 tests should pass. Tests mock the database and ALPR model, so no external dependencies are needed.

## Key Decisions

- **Camera ID** stored as `String(200)` to accept long hex `deviceId` strings from `enumerateDevices`.
- **Images** stored as `bytea` (raw JPEG bytes) instead of base64 text to save space and avoid encoding overhead.
- **Config** stored in DB table with in-memory cache (10s TTL) so changes take effect without restart; `PUT /config/<key>` forces `reload()` for immediate effect.
- **Test architecture** uses `autouse` fixture to pre-fill the config cache with defaults, preventing real DB access during tests; ALPR predictions are fully mocked.
- **Dedup key** includes both `plate_text` and `camera_id` so the same plate from different cameras is treated independently.
- **RTSP cameras** run in daemon threads started on the first HTTP request; reconnection uses exponential backoff (3s–30s) to avoid flooding the network.
