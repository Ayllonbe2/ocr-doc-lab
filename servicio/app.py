"""App del servicio OCR: `uvicorn servicio.app:app --port 8001`.

Autenticación con una clave compartida en la cabecera `X-Api-Key` (variable `OCR_API_KEY`).
Sin clave el servicio se niega a arrancar, salvo que se pida a propósito con
`OCR_ALLOW_ANONYMOUS=true` (solo para local).
"""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mrzlab import motores

from .api import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OCR_API_KEY = os.getenv("OCR_API_KEY", "")
OCR_ALLOW_ANONYMOUS = os.getenv("OCR_ALLOW_ANONYMOUS", "").lower() == "true"

if not OCR_API_KEY and not OCR_ALLOW_ANONYMOUS:
    raise RuntimeError("Falta OCR_API_KEY. Define la clave compartida con quien llama, o pon "
                       "OCR_ALLOW_ANONYMOUS=true si de verdad quieres arrancar sin autenticación (solo en local).")
if not OCR_API_KEY:
    logger.warning("OCR sin autenticación (OCR_ALLOW_ANONYMOUS=true). No usar fuera de local.")

app = FastAPI(title="OCR Doc Lab · servicio", docs_url=None, redoc_url=None)


@app.middleware("http")
async def exigir_api_key(request: Request, call_next):
    if OCR_API_KEY and request.url.path != "/health":
        # compare_digest: una comparación normal corta en el primer carácter distinto y deja
        # adivinar la clave por el tiempo de respuesta.
        if not secrets.compare_digest(request.headers.get("X-Api-Key") or "", OCR_API_KEY):
            return JSONResponse(status_code=401, content={"detail": "API key inválida"})
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok",
            "motores": {m.nombre: m.disponible()[0] for m in motores.TODOS}}


app.include_router(router)
