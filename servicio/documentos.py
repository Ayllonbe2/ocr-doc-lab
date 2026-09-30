"""Endpoints de documentos: leer un documento de un tipo o decir qué documento es.

Sin estado: el documento llega en la petición, se procesa en memoria (tampoco la subida toca el
disco, ver `api.py`) y se descarta. En los logs solo quedan el tipo, el resultado y el tiempo.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from mrzlab import documentos
from mrzlab.extractores import REGISTRO

from .api import MAX_BYTES

router = APIRouter(prefix="/v1/documentos")

_ESTADOS_ERROR = {"vacio": 400, "corrupto": 400, "cifrado": 400, "formato": 415, "demasiadas_paginas": 422,
                  "sin_motores": 503}


def _leer(archivo: UploadFile) -> bytes:
    datos = archivo.file.read(MAX_BYTES + 1)
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "El documento es demasiado grande (máx. 15 MB)")
    if not datos:
        raise HTTPException(400, "Falta el documento")
    return datos


def _error(e: documentos.DocumentoInvalido) -> HTTPException:
    return HTTPException(_ESTADOS_ERROR.get(e.motivo, 400), str(e))


@router.get("/tipos")
def tipos() -> dict:
    """Tipos admitidos, con sus campos y cuáles son obligatorios."""
    return {"tipos": [e.describir() for e in REGISTRO.values()]}


@router.post("/clasificar")
def clasificar(archivo: UploadFile = File(..., description="PDF, JPG, PNG o WEBP")) -> dict:
    """Qué tipo de documento parece (o `null` si ninguno), con los candidatos y su puntuación."""
    datos = _leer(archivo)
    try:
        return documentos.clasificar(datos)
    except documentos.DocumentoInvalido as e:
        raise _error(e)
    finally:
        del datos


@router.post("/{tipo}/extraer")
def extraer(tipo: str, archivo: UploadFile = File(..., description="PDF, JPG, PNG o WEBP")) -> dict:
    """Lee el documento y devuelve sus campos, validaciones, autenticidad y calidad.

    `lectura`: COMPLETA · INCOMPLETA (revisión manual) · ILEGIBLE (pedir otra foto o escaneo) ·
    OTRO_DOCUMENTO (se ha subido otro tipo de documento). Quien llama compara los campos con sus
    datos y decide.
    """
    if tipo not in REGISTRO:
        raise HTTPException(404, f"Tipo de documento desconocido: {tipo}")
    datos = _leer(archivo)
    try:
        return documentos.procesar(datos, tipo).a_dict()
    except documentos.DocumentoInvalido as e:
        raise _error(e)
    finally:
        del datos
