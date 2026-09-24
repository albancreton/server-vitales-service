"""OpenAPI 3.1 description of the vitalsd HTTP API (schema v1).

Hand-maintained alongside the collectors; tests/test_openapi.py cross-checks
the declared schemas against real State payloads so the two can't silently
drift. Consumers can feed /openapi.json to Swagger/ReDoc viewers or generate
client types (e.g. via openapi-typescript).
"""
from __future__ import annotations

from . import __version__


def _null(t: str, **extra) -> dict:
    """A nullable scalar: unsupported readings are null, never absent."""
    return {"type": [t, "null"], **extra}


_TEMPS = {
    "type": "object",
    "description": "Every labeled temperature sensor, degrees C.",
    "additionalProperties": {"type": "number"},
}

_GPU_MEMORY = {
    "type": ["object", "null"],
    "description": "VRAM (dedicated) or system RAM (unified memory hosts).",
    "properties": {
        "total": {"type": "integer"},
        "used": {"type": "integer"},
        "free": {"type": "integer"},
        "used_pct": _null("number"),
    },
    "required": ["total", "used", "free", "used_pct"],
}

_SCHEMAS = {
    "Health": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "uptime_s": {"type": "number"},
        },
        "required": ["ok", "uptime_s"],
    },
    "Platform": {
        "type": "object",
        "properties": {
            "machine": {"type": "string"},
            "kernel": {"type": "string"},
            "os": {"type": "string"},
        },
        "required": ["machine", "kernel", "os"],
    },
    "CpuStatic": {
        "type": "object",
        "properties": {
            "count": _null("integer"),
            "count_physical": _null("integer"),
            "model": _null("string"),
        },
        "required": ["count", "count_physical", "model"],
    },
    "GpuStatic": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "vendor": {"type": "string", "enum": ["nvidia", "amd"]},
            "name": {"type": "string"},
            "uuid": _null("string"),
            "memory_kind": {"type": "string", "enum": ["dedicated", "unified"]},
            "vram_total": _null("integer"),
            "power_limit_w": _null("number"),
            "max_clocks_mhz": {
                "type": "object",
                "properties": {
                    "graphics": _null("integer"),
                    "memory": _null("integer"),
                },
                "required": ["graphics", "memory"],
            },
            "temp_slowdown_c": _null("number"),
            "driver_version": _null("string"),
            "vbios": _null("string"),
        },
        "required": ["index", "vendor", "name", "memory_kind", "vram_total",
                     "power_limit_w", "max_clocks_mhz", "temp_slowdown_c"],
    },
    "InfoPayload": {
        "type": "object",
        "description": "Static host description; sections appear only when "
                       "their collector probed (see capabilities).",
        "properties": {
            "schema": {"type": "integer", "const": 1},
            "host": {"type": "string"},
            "started_at": {"type": "number"},
            "version": {"type": "string"},
            "platform": {"$ref": "#/components/schemas/Platform"},
            "capabilities": {"type": "array", "items": {"type": "string"}},
            "cpu": {"$ref": "#/components/schemas/CpuStatic"},
            "memory_total": {"type": "integer"},
            "gpus": {"type": "array",
                     "items": {"$ref": "#/components/schemas/GpuStatic"}},
            "errors": {"$ref": "#/components/schemas/Errors"},
        },
        "required": ["schema", "host", "started_at", "version", "platform",
                     "capabilities"],
    },
    "GpuFan": {
        "type": "object",
        "description": "NVML reports pct, amdgpu reports rpm; the other is null.",
        "properties": {
            "pct": _null("integer"),
            "rpm": _null("integer"),
        },
        "required": ["pct", "rpm"],
    },
    "GpuProcess": {
        "type": "object",
        "properties": {
            "pid": {"type": "integer"},
            "kind": {"type": "string", "enum": ["compute", "graphics"]},
            "mem_bytes": _null("integer"),
            "name": _null("string"),
        },
        "required": ["pid", "kind", "mem_bytes", "name"],
    },
    "GpuSample": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "vendor": {"type": "string", "enum": ["nvidia", "amd"]},
            "util_gpu_pct": _null("integer"),
            "util_memory_pct": _null("integer"),
            "memory": _GPU_MEMORY,
            "temperature_c": _null("number"),
            "temperatures_c": _TEMPS,
            "power_w": _null("number"),
            "fans": {"type": "array",
                     "items": {"$ref": "#/components/schemas/GpuFan"}},
            "clocks_mhz": {
                "type": "object",
                "properties": {
                    "graphics": _null("integer"),
                    "memory": _null("integer"),
                },
                "required": ["graphics", "memory"],
            },
            "perf_state": _null("string"),
            "throttle_reasons": {"type": "array", "items": {"type": "string"},
                                 "description": "NVIDIA only; [] elsewhere."},
            "processes": {"type": "array",
                          "items": {"$ref": "#/components/schemas/GpuProcess"},
                          "description": "NVIDIA only; [] elsewhere."},
        },
        "required": ["index", "vendor", "util_gpu_pct", "util_memory_pct",
                     "memory", "temperature_c", "temperatures_c", "power_w",
                     "fans", "clocks_mhz", "perf_state", "throttle_reasons",
                     "processes"],
    },
    "CpuSample": {
        "type": "object",
        "properties": {
            "usage_pct": {"type": "number"},
            "per_core_pct": {"type": "array", "items": {"type": "number"}},
            "count": _null("integer"),
            "load_avg": {"type": "array", "items": {"type": "number"},
                         "minItems": 3, "maxItems": 3},
            "freq_mhz": _null("integer"),
            "temperature_c": _null("number"),
            "temperatures_c": _TEMPS,
        },
        "required": ["usage_pct", "per_core_pct", "count", "load_avg",
                     "freq_mhz", "temperature_c", "temperatures_c"],
    },
    "MemorySample": {
        "type": "object",
        "properties": {
            "total": {"type": "integer"},
            "used": {"type": "integer"},
            "available": {"type": "integer"},
            "used_pct": {"type": "number"},
        },
        "required": ["total", "used", "available", "used_pct"],
    },
    "SwapSample": {
        "type": "object",
        "properties": {
            "total": {"type": "integer"},
            "used": {"type": "integer"},
            "used_pct": {"type": "number"},
        },
        "required": ["total", "used", "used_pct"],
    },
    "ChassisFan": {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "rpm": {"type": "integer"},
        },
        "required": ["label", "rpm"],
    },
    "Power": {
        "type": "object",
        "description": "measured_w sums the listed sources — what the platform "
                       "can measure, not wall power.",
        "properties": {
            "measured_w": _null("number"),
            "sources": {"type": "object",
                        "additionalProperties": {"type": "number"}},
        },
        "required": ["measured_w", "sources"],
    },
    "Errors": {
        "type": "object",
        "description": "Collector name -> error message for collectors that "
                       "failed this payload; their sections are absent.",
        "additionalProperties": {"type": "string"},
    },
    "LoadedModel": {
        "type": "object",
        "description": "One model a service holds resident. Extra "
                       "adapter-specific keys (size_bytes, type) may appear.",
        "properties": {
            "id": {"type": "string", "description": "Pass as `model` to unload it."},
            "name": {"type": "string"},
            "state": {"type": "string",
                      "description": "ready | starting | stopping | ... (service-defined)"},
            "vram_bytes": _null("integer"),
            "size_bytes": _null("integer"),
            "type": _null("string"),
        },
        "required": ["id", "name", "state", "vram_bytes"],
    },
    "ModelService": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": ["llamaswap", "comfyui", "fourfold"]},
            "container": _null("string"),
            "granularity": {"type": "string", "enum": ["model", "service"],
                            "description": "model: unload accepts a model id; "
                                           "service: all-or-nothing."},
            "ok": {"type": "boolean"},
            "error": _null("string"),
            "vram_bytes": {**_null("integer"),
                           "description": "GPU memory of the service's container "
                                          "processes (NVML); null when unattributed."},
            "models": {"type": "array",
                       "items": {"$ref": "#/components/schemas/LoadedModel"}},
        },
        "required": ["id", "kind", "container", "granularity", "ok", "error",
                     "vram_bytes", "models"],
    },
    "OtherGpuProcess": {
        "type": "object",
        "description": "A GPU process no configured service claims.",
        "properties": {
            "pid": {"type": "integer"},
            "name": _null("string"),
            "container": _null("string"),
            "mem_bytes": _null("integer"),
        },
        "required": ["pid", "name", "container", "mem_bytes"],
    },
    "ModelsPayload": {
        "type": "object",
        "properties": {
            "schema": {"type": "integer", "const": 1},
            "host": {"type": "string"},
            "ts": {"type": "number"},
            "services": {"type": "array",
                         "items": {"$ref": "#/components/schemas/ModelService"}},
            "other": {"type": "array",
                      "items": {"$ref": "#/components/schemas/OtherGpuProcess"}},
        },
        "required": ["schema", "host", "ts", "services", "other"],
    },
    "UnloadRequest": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "A service id, or \"*\" for all."},
            "model": {"type": "string", "description": "Omit to unload everything the service holds."},
            "force": {"type": "boolean", "default": False,
                      "description": "comfyui: restart even with prompts running/queued."},
        },
        "required": ["service"],
    },
    "UnloadResponse": {
        "type": "object",
        "properties": {
            "results": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "action": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["service", "ok"],
            }},
        },
        "required": ["results"],
    },
    "TickPayload": {
        "type": "object",
        "description": "One metrics snapshot; sections appear only when their "
                       "collector probed.",
        "properties": {
            "schema": {"type": "integer", "const": 1},
            "ts": {"type": "number"},
            "host": {"type": "string"},
            "tick_us": {"type": "integer"},
            "gpus": {"type": "array",
                     "items": {"$ref": "#/components/schemas/GpuSample"}},
            "cpu": {"$ref": "#/components/schemas/CpuSample"},
            "memory": {"$ref": "#/components/schemas/MemorySample"},
            "swap": {"$ref": "#/components/schemas/SwapSample"},
            "fans": {"type": "array",
                     "items": {"$ref": "#/components/schemas/ChassisFan"},
                     "description": "Chassis/CPU fans from hwmon (non-GPU)."},
            "power": {"$ref": "#/components/schemas/Power"},
            "errors": {"$ref": "#/components/schemas/Errors"},
        },
        "required": ["schema", "ts", "host", "tick_us", "power"],
    },
}


def _json_response(desc: str, ref: str) -> dict:
    return {
        "200": {
            "description": desc,
            "content": {"application/json": {
                "schema": {"$ref": f"#/components/schemas/{ref}"}}},
        }
    }


DOCUMENT = {
    "openapi": "3.1.0",
    "info": {
        "title": "vitalsd",
        "version": __version__,
        "description": "Server vitals daemon: GPU, CPU, memory, fan, and "
                       "power metrics as JSON + SSE (schema v1).",
    },
    "paths": {
        "/health": {"get": {
            "summary": "Liveness probe",
            "responses": _json_response("Daemon is alive.", "Health"),
        }},
        "/info": {"get": {
            "summary": "Static host and GPU description",
            "responses": _json_response("Static description.", "InfoPayload"),
        }},
        "/metrics": {"get": {
            "summary": "One metrics snapshot",
            "responses": _json_response("Current snapshot.", "TickPayload"),
        }},
        "/stream": {"get": {
            "summary": "Server-Sent Events stream",
            "description": "Emits one `info` event (InfoPayload), then `tick` "
                           "events (TickPayload) at the requested rate.",
            "parameters": [{
                "name": "hz",
                "in": "query",
                "required": False,
                "schema": {"type": "number", "minimum": 0.1, "maximum": 10,
                           "default": 1},
                "description": "Tick rate; clamped to 0.1-10.",
            }],
            "responses": {"200": {
                "description": "SSE stream of info + tick events.",
                "content": {"text/event-stream": {
                    "schema": {"type": "string"}}},
            }},
        }},
        "/models": {"get": {
            "summary": "Models loaded across configured services",
            "description": "Only when /etc/vitalsd/models.toml exists (see "
                           "`models` in /info capabilities); 404 otherwise.",
            "responses": _json_response("Loaded-model inventory.", "ModelsPayload"),
        }},
        "/models/unload": {"post": {
            "summary": "Unload a model, a service, or everything",
            "description": "Requires Content-Type: application/json, and "
                           "`Authorization: Bearer <token>` when the config sets "
                           "a token. No CORS: meant for server-side callers. "
                           "200 all ok; 400 bad request; 401 bad token; 404 "
                           "unknown service; 409 service busy; 502 upstream failure.",
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/UnloadRequest"}}}},
            "responses": _json_response("Per-service results.", "UnloadResponse"),
        }},
        "/openapi.json": {"get": {
            "summary": "This document",
            "responses": {"200": {
                "description": "OpenAPI 3.1 description of the API.",
                "content": {"application/json": {
                    "schema": {"type": "object"}}},
            }},
        }},
    },
    "components": {"schemas": _SCHEMAS},
}
