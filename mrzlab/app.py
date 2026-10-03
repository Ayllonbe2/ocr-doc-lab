"""OCR Doc Lab (laboratorio): API local para comparar motores OCR sobre la MRZ del DNI.

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

from . import analisis, calidad, cotejo, motores, plantilla, sintetico

RAIZ = Path(__file__).resolve().parent
UMBRALES_RUTA = Path(os.getenv("UMBRALES", RAIZ.parent / "umbrales.yaml"))
MAX_BYTES = 25 * 1024 * 1024

app = FastAPI(title="OCR Doc Lab", docs_url=None, redoc_url=None)


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
        lista.append({"nombre": m.nombre, "licencia": m.licencia, "disponible": ok, "nota": nota,
                      "dni": m.nombre in analisis.MOTORES_DNI})
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
    img = imagenes.get("orientada", img)  # las cajas van sobre la foto ya girada
    tarjeta = imagenes.get("tarjeta")
    return {
        "archivo": archivo.filename,
        **resultado,
        "imagen_anotada": _jpeg_b64(_anotar(img, caja, evaluacion.reflejos), 1200),
        "recorte_mrz": _jpeg_b64(img[caja[1]:caja[1] + caja[3], caja[0]:caja[0] + caja[2]], 900)
        if caja else None,
        "tarjeta_zonas": _jpeg_b64(_dibujar_zonas(*tarjeta), 900) if tarjeta else None,
    }


@app.post("/api/cotejo")
def cotejar(cuerpo: dict = Body(...)):
    """Compara los campos leídos en el anverso con los de la MRZ (no recibe imágenes)."""
    anv, rev = cuerpo.get("anverso"), cuerpo.get("reverso")
    if not isinstance(anv, dict) or not isinstance(rev, dict):
        raise HTTPException(400, "Hacen falta «anverso» (candidatos por campo) y «reverso» (campos de la MRZ)")
    try:
        decl = cuerpo.get("declarado")
        return cotejo.cotejar(anv, rev, mrz_valida=bool(cuerpo.get("mrz_valida", True)),
                              declarado=decl if isinstance(decl, dict) else None)
    except (AttributeError, TypeError) as e:
        raise HTTPException(400, f"Formato no válido: {e}")


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


# ── Documentos (títulos, certificados, pólizas, contratos, fichas…) ──────────

@app.get("/documentos")
def pagina_documentos():
    return FileResponse(RAIZ / "static" / "documentos.html")


@app.get("/api/documentos/tipos")
def tipos_documento():
    from .extractores import REGISTRO
    return [e.describir() for e in REGISTRO.values()]


@app.get("/api/documentos/muestra/{tipo}")
def muestra_documento(tipo: str, origen: str = "digital", semilla: int = 0, firmada: bool = True):
    """Documento sintético (datos ficticios): PDF digital, PDF escaneado o foto JPG."""
    from . import sintetico_docs as sd
    if tipo not in sd.PLANTILLAS:
        raise HTTPException(404, "Tipo desconocido")
    rng = np.random.default_rng(semilla)
    opciones = {"firmada": firmada} if tipo in ("informacion_art18", "formacion_art19", "entrega_epis") else {}
    pdf, _ = sd.generar(tipo, rng, **opciones)
    if origen == "escaneado":
        return Response(sd.escanear(pdf, rng), media_type="application/pdf")
    if origen == "foto":
        return Response(sd.a_jpeg(sd.foto(sd.a_imagen(pdf, 200), rng)), media_type="image/jpeg")
    return Response(pdf, media_type="application/pdf")


def _pagina_anotada(img: np.ndarray, lineas, cajas_campos: set) -> str:
    """Página con las líneas leídas (azul) y las que dan un campo (verde)."""
    out = img.copy()
    h, w = img.shape[:2]
    grosor = max(1, round(w / 800))
    for ln in lineas:
        x, y, cw, ch = ln.caja
        color = (60, 180, 60) if ln.caja in cajas_campos else (255, 140, 40)
        cv2.rectangle(out, (int(x * w), int(y * h)), (int((x + cw) * w), int((y + ch) * h)), color, grosor)
    return _jpeg_b64(out, 1100)


@app.post("/api/documentos/analizar")
async def analizar_documento(archivo: UploadFile = File(...), tipo: str = Form(...)):
    from . import documentos
    from .extractores import REGISTRO
    if tipo not in REGISTRO:
        raise HTTPException(404, "Tipo desconocido")
    datos = await archivo.read()
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "Documento demasiado grande (máx. 25 MB)")
    try:
        resultado, doc = documentos.procesar_con_documento(datos, tipo)
    except documentos.DocumentoInvalido as e:
        raise HTTPException(415 if e.motivo == "formato" else 400, str(e))
    finally:
        del datos
    salida = resultado.a_dict()
    cajas_campos = {c.caja for c in resultado.campos.values() if c.caja}
    for nombre, c in resultado.campos.items():
        salida["campos"][nombre]["caja"] = c.caja
    paginas = []
    for p in doc.paginas:
        try:
            img = doc.imagen(p.numero)
        except Exception:
            img = None
        paginas.append({
            "numero": p.numero, "tipo": p.tipo, "motor": p.motor, "calidad": p.calidad,
            "imagen": _pagina_anotada(img, [ln for ln in doc.lineas if ln.pagina == p.numero], cajas_campos)
            if img is not None else None,
        })
    salida["lab"] = {
        "archivo": archivo.filename,
        "paginas": paginas,
        # Solo en el laboratorio (local): lo que ha leído cada línea, para depurar extractores.
        "lineas": [{"texto": ln.texto, "alternativa": ln.alternativa, "origen": ln.origen,
                    "confianza": ln.confianza, "pagina": ln.pagina, "caja": [round(v, 4) for v in ln.caja]}
                   for ln in doc.lineas],
    }
    return salida


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
