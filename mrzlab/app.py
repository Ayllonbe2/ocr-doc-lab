"""MRZ Lab: API local para comparar motores OCR sobre la MRZ del DNI.

Las imágenes se procesan en memoria y no se guardan en disco ni se registran en logs.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import cv2
import numpy as np
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from . import analisis, calidad, motores, plantilla, sintetico

RAIZ = Path(__file__).resolve().parent
UMBRALES_RUTA = Path(os.getenv("UMBRALES", RAIZ.parent / "umbrales.yaml"))
MAX_BYTES = 25 * 1024 * 1024

app = FastAPI(title="MRZ Lab", docs_url=None, redoc_url=None)


def _jpeg_b64(img: np.ndarray, ancho_max: int) -> str:
    h, w = img.shape[:2]
    if w > ancho_max:
        img = cv2.resize(img, (ancho_max, round(h * ancho_max / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _anotar(img: np.ndarray, caja_mrz, reflejos) -> np.ndarray:
    out = img.copy()
    grosor = max(2, round(max(img.shape[:2]) / 400))
    for x, y, w, h in reflejos:
        cv2.rectangle(out, (x, y), (x + w, y + h), (40, 40, 230), grosor)
    if caja_mrz:
        x, y, w, h = caja_mrz
        cv2.rectangle(out, (x, y), (x + w, y + h), (60, 180, 60), grosor)
    return out


@app.get("/")
def index():
    return FileResponse(RAIZ / "static" / "index.html")


@app.get("/api/estado")
def estado():
    lista = []
    for m in motores.TODOS:
        ok, nota = m.disponible()
        lista.append({"nombre": m.nombre, "licencia": m.licencia, "disponible": ok, "nota": nota})
    return {"motores": lista, "umbrales": calidad.cargar_umbrales(UMBRALES_RUTA)}


@app.get("/api/muestras")
def muestras():
    return list(sintetico.MUESTRAS)


@app.get("/api/muestras/{nombre}.jpg")
def muestra(nombre: str):
    generar = sintetico.MUESTRAS.get(nombre)
    if generar is None:
        raise HTTPException(404, "Muestra desconocida")
    ok, buf = cv2.imencode(".jpg", generar(), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return Response(buf.tobytes(), media_type="image/jpeg")


@app.post("/api/analizar")
async def analizar(archivo: UploadFile = File(...), motores_sel: str = Form(""),
                   lado: str = Form("auto")):
    datos = await archivo.read()
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "Imagen demasiado grande (máx. 25 MB)")
    try:
        img = analisis.decodificar(datos)
    except analisis.ImagenInvalida as e:
        raise HTTPException(400, str(e))
    del datos

    umbrales = calidad.cargar_umbrales(UMBRALES_RUTA)  # se relee: puedes ajustar sin reiniciar
    pedidos = {n for n in motores_sel.split(",") if n}
    if lado not in analisis.LADOS:
        raise HTTPException(400, f"lado debe ser uno de {', '.join(analisis.LADOS)}")
    imagenes: dict = {}
    resultado, evaluacion = analisis.analizar(img, umbrales, pedidos, lado, imagenes=imagenes)
    caja = resultado["caja_mrz"]
    tarjeta = imagenes.get("tarjeta")
    return {
        "archivo": archivo.filename,
        **resultado,
        "imagen_anotada": _jpeg_b64(_anotar(img, caja, evaluacion.reflejos), 1200),
        "recorte_mrz": _jpeg_b64(img[caja[1]:caja[1] + caja[3], caja[0]:caja[0] + caja[2]], 900)
        if caja else None,
        "tarjeta_zonas": _jpeg_b64(_dibujar_zonas(*tarjeta), 900) if tarjeta else None,
    }


def _dibujar_zonas(tarjeta: np.ndarray, zonas: dict, propuesta: dict) -> np.ndarray:
    """Tarjeta enderezada: zonas de la plantilla (morado), campos (verde) y etiquetas (naranja)."""
    out = tarjeta.copy()
    grosor = max(2, round(tarjeta.shape[1] / 500))
    for c, (x, y, w, h) in propuesta.items():
        color = (0, 150, 255) if c.startswith("etiqueta.") else (60, 180, 60)  # naranja / verde
        cv2.rectangle(out, (x, y), (x + w, y + h), color, grosor)
    for c, (x, y, w, h) in zonas.items():
        cv2.rectangle(out, (x, y), (x + w, y + h), (200, 60, 160), grosor)
        cv2.putText(out, c, (x + 2, max(12, y - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                    tarjeta.shape[1] / 2200, (200, 60, 160), max(1, grosor // 2), cv2.LINE_AA)
    return out


@app.get("/api/plantilla")
def ver_plantilla():
    return {"campos": plantilla.cargar(), "ruta": str(plantilla.RUTA)}


@app.post("/api/plantilla")
def aprender_plantilla(cuerpo: dict = Body(...)):
    """Suma a la plantilla las posiciones de una foto. Solo coordenadas (0-1), sin datos."""
    try:
        campos = plantilla.aprender(cuerpo.get("campos") or {})
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(500, f"No se pudo guardar la plantilla: {e}")
    return {"campos": campos}


@app.delete("/api/plantilla")
def borrar_plantilla():
    plantilla.borrar()
    return {"campos": None}
