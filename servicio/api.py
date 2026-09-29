"""Endpoint de verificación del DNI. Las imágenes no se guardan ni se registran."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.formparsers import MultiPartParser

from . import lectura, verificacion

MAX_BYTES = 15 * 1024 * 1024
# Starlette escribe en un fichero temporal en disco los archivos subidos de más de 1 MB (una
# foto de móvil pesa 2-5 MB). Con este límite se quedan en memoria: la foto no toca el disco.
# El atributo se llama «spool_max_size» desde Starlette 1.x y «max_file_size» antes.
ATRIBUTO_SPOOL = "spool_max_size" if hasattr(MultiPartParser, "spool_max_size") else "max_file_size"
setattr(MultiPartParser, ATRIBUTO_SPOOL,
        max(getattr(MultiPartParser, ATRIBUTO_SPOOL), MAX_BYTES + 1024 * 1024))

router = APIRouter()


def _leer(archivo: UploadFile, cara: str) -> bytes:
    # Síncrono a propósito: el endpoint es «def» y FastAPI lo ejecuta en un hilo aparte
    # (el OCR es CPU y bloquearía el bucle de eventos).
    datos = archivo.file.read(MAX_BYTES + 1)
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, f"La foto del {cara} es demasiado grande (máx. 15 MB)")
    if not datos:
        raise HTTPException(400, f"Falta la foto del {cara}")
    return datos


@router.post("/v1/dni/verificar")
def verificar_dni(
    anverso: UploadFile = File(..., description="Foto del anverso del DNI (JPG, PNG, WEBP)"),
    reverso: UploadFile = File(..., description="Foto del reverso del DNI, con la MRZ"),
    dni_declarado: str = Form(..., description="Nº de DNI que ha indicado el usuario"),
    intento: int = Form(1, description=f"1 o {verificacion.INTENTOS_MAX}: lo lleva el backend"),
) -> dict:
    """Verifica el DNI y devuelve VERIFICADO, REPETIR o REVISION_ADMIN.

    Sin estado: el backend guarda el nº de intento y, en REVISION_ADMIN, avisa al admin con los
    datos leídos y el motivo. Las imágenes se procesan en memoria y se descartan.
    """
    if not 1 <= intento <= verificacion.INTENTOS_MAX:
        raise HTTPException(400, f"intento debe estar entre 1 y {verificacion.INTENTOS_MAX}")
    datos_a, datos_r = _leer(anverso, "anverso"), _leer(reverso, "reverso")
    try:
        return verificacion.verificar(datos_a, datos_r, dni_declarado, intento).a_dict()
    except lectura.ImagenInvalida as e:
        raise HTTPException(400, str(e))
    finally:
        del datos_a, datos_r
