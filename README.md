# vitalsd

One self-contained vitals daemon for heterogeneous Linux servers. Exposes
GPU, CPU, memory, fan, and power metrics as JSON + SSE on port 9877.
Collectors self-select at startup (NVML, amdgpu sysfs, psutil, hwmon, RAPL),
so the same code runs on any host — NVIDIA or AMD GPUs, x86 or aarch64,
dedicated or unified GPU memory. `/info.capabilities` says what a host
supports, and unsupported readings are `null`.

## Endpoints

- `GET /health` — liveness
- `GET /info` — static host + GPU description (schema v1)
- `GET /metrics` — one snapshot
- `GET /stream?hz=1` — SSE stream (`info` event, then `tick` events, 0.1-10 Hz)
- `GET /models` — models loaded across configured services (llama-swap,
  ComfyUI, Fourfold), per-service VRAM, and unclaimed GPU processes. Only
  when `/etc/vitalsd/models.toml` exists (`models` in `/info.capabilities`)
- `POST /models/unload` — `{"service": "<id>" | "*", "model"?: "<id>", "force"?: bool}`
- `GET /openapi.json` — OpenAPI 3.1 description of this API (feed it to a
  Swagger/ReDoc viewer, or `openapi-typescript` for client types)

## Loaded models (optional, per host)

Copy `deploy/models.example.toml` to `/etc/vitalsd/models.toml`, keep the
services the host runs, and restart vitalsd. Adapters:

| kind | lists | unloads |
|---|---|---|
| `llamaswap` | `/running` | one model or all, via `/api/models/unload` |
| `comfyui` | the comfy-vitals custom node's `/vitals/models` (without it: VRAM only) | restarts the container; `409` while prompts run unless `force` |
| `fourfold` | `/api/health` | `POST /api/unload` |

`POST /models/unload` is the daemon's only mutating route. It sends no CORS
header and requires `Content-Type: application/json`, so a web page can't
trigger it from a browser. Set `token` in the config to also require
`Authorization: Bearer <token>`.

## Development

    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest -q
    .venv/bin/python -m vitalsd --port 9999

## Host install (once, as root)

    sudo deploy/setup.sh        # clones to /opt/server-stats, installs systemd units

Hosts self-update daily from `origin/main` (`vitalsd-update.timer`), with
automatic rollback if `/health` fails after a restart. Immediate deploy:
push to main, then `sudo /opt/server-stats/deploy/update.sh` on the host.

The daemon runs as a root systemd service: RAPL `energy_uj` and some hwmon
nodes are root-only. Apart from `POST /models/unload` it is read-only, and
it is unauthenticated unless a models `token` is set — intended for trusted
LANs, not the open internet.
