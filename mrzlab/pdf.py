"""Lectura de PDF sin OCR: texto con posiciones, valores de formularios y render de páginas.

- Texto, imágenes, metadatos y render: pypdfium2 (PDFium, Apache-2.0/BSD). Es rápido: 20
  páginas en décimas de segundo.
- Valores de formularios sin aplanar (anotaciones): pdfplumber (MIT), solo si el PDF los tiene.
- PyMuPDF no se usa porque es AGPL.
- Todo en memoria: se abre desde los bytes, sin ficheros temporales.
"""
from __future__ import annotations

import io
import re

import numpy as np

from .lineas import CAPA_TEXTO, FORMULARIO, Linea

# Una página es «digital» si su capa de texto tiene al menos esto de texto legible.
MIN_CARACTERES = 40
MIN_PROPORCION_LEGIBLE = 0.6


class PdfInvalido(ValueError):
    def __init__(self, motivo: str, mensaje: str):
        super().__init__(mensaje)
        self.motivo = motivo            # corrupto | cifrado | demasiadas_paginas


def es_pdf(datos: bytes) -> bool:
    return datos[:1024].lstrip().startswith(b"%PDF")


def abrir(datos: bytes):
    """Documento de PDFium. Lanza PdfInvalido si está cifrado con contraseña o roto."""
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(datos)
        if len(doc) == 0:
            raise PdfInvalido("corrupto", "El PDF no tiene páginas")
        return doc
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise PdfInvalido("cifrado", "El PDF está protegido con contraseña") from e
        raise PdfInvalido("corrupto", "No se pudo abrir el PDF") from e


def _texto_legible(texto: str) -> tuple[int, float]:
    """Caracteres útiles y proporción legible (fuentes sin mapa de caracteres dan basura)."""
    visibles = [c for c in texto if not c.isspace()]
    if not visibles:
        return 0, 0.0
    buenos = sum(1 for c in visibles if c.isalnum() or c in ".,;:-/()ºª€%'\"")
    return buenos, buenos / len(visibles)


def _normalizar_caja(l: float, b: float, r: float, t: float, ancho: float, alto: float,
                     giro: int) -> tuple[float, float, float, float]:
    """Caja del espacio de la página (origen abajo a la izquierda) a fracción de la página tal
    como se ve (con su giro aplicado), origen arriba a la izquierda."""
    u0, u1 = l / ancho, r / ancho
    v0, v1 = 1 - t / alto, 1 - b / alto
    esquinas = [(u0, v0), (u1, v1)]
    if giro == 90:
        esquinas = [(1 - v, u) for u, v in esquinas]
    elif giro == 180:
        esquinas = [(1 - u, 1 - v) for u, v in esquinas]
    elif giro == 270:
        esquinas = [(v, 1 - u) for u, v in esquinas]
    (a, b_), (c, d) = esquinas
    x0, x1, y0, y1 = min(a, c), max(a, c), min(b_, d), max(b_, d)
    return x0, y0, x1 - x0, y1 - y0


def lineas_capa_texto(doc, indice: int, numero: int) -> list[Linea]:
    """Segmentos de texto de la página con su caja: PDFium los agrupa por línea y los separa
    en los huecos grandes, así que «CÓDIGO POSTAL      PAÍS» son dos segmentos."""
    pagina = doc[indice]
    ancho, alto = pagina.get_size()
    giro = pagina.get_rotation() % 360
    tp = pagina.get_textpage()
    trozos = []
    try:
        for k in range(tp.count_rects()):
            l, b, r, t = tp.get_rect(k)
            texto = " ".join(tp.get_text_bounded(l, b, r, t).split())
            if texto:
                trozos.append([texto, l, b, r, t])
    finally:
        tp.close()
    # En texto justificado PDFium parte las palabras de una misma frase («INFORMA», «Y ENTREGA»,
    # «a:»): se unen los trozos de la misma línea separados por menos de 1,5 veces su altura.
    trozos.sort(key=lambda z: (-round((z[2] + z[4]) / 2), z[1]))
    unidos: list[list] = []
    for z in trozos:
        u = unidos[-1] if unidos else None
        alto_z = max(z[4] - z[2], 1.0)
        if (u and abs((u[2] + u[4]) / 2 - (z[2] + z[4]) / 2) < 0.5 * max(alto_z, u[4] - u[2])
                and 0 <= z[1] - u[3] < 1.5 * alto_z):
            u[0] += " " + z[0]
            u[2], u[3], u[4] = min(u[2], z[2]), z[3], max(u[4], z[4])
        else:
            unidos.append(z)
    return [Linea(texto, _normalizar_caja(l, b, r, t, ancho, alto, giro), numero, CAPA_TEXTO)
            for texto, l, b, r, t in unidos]


def _decodificar(valor) -> str:
    from pdfminer.psparser import PSLiteral
    from pdfminer.utils import decode_text
    if isinstance(valor, bytes):
        return decode_text(valor)
    if isinstance(valor, PSLiteral):
        return str(valor.name)
    return str(valor) if valor is not None else ""


def lineas_formularios(datos: bytes) -> dict[int, list[Linea]]:
    """Valores de los campos de texto de un formulario PDF sin aplanar, por página.

    Esos valores viven en las anotaciones, no en la capa de texto: sin esto, un contrato
    rellenado en el propio PDF parecería vacío. Solo se abre con pdfplumber si hay formulario.
    """
    if b"/AcroForm" not in datos:
        return {}
    import pdfplumber
    salida: dict[int, list[Linea]] = {}
    try:
        with pdfplumber.open(io.BytesIO(datos)) as pdf:
            for i, pagina in enumerate(pdf.pages):
                ancho, alto = float(pagina.width), float(pagina.height)
                for a in pagina.annots or []:
                    d = a.get("data") or {}
                    valor = _decodificar(d.get("V")).strip()
                    if _decodificar(d.get("FT")) != "Tx" or not valor:
                        continue
                    salida.setdefault(i + 1, []).append(Linea(
                        " ".join(valor.split()), (a["x0"] / ancho, a["top"] / alto, (a["x1"] - a["x0"]) / ancho,
                                                  (a["bottom"] - a["top"]) / alto), i + 1, FORMULARIO))
    except Exception:
        return {}
    return salida


def es_digital(lineas: list[Linea]) -> bool:
    utiles, proporcion = _texto_legible(" ".join(ln.texto for ln in lineas))
    return utiles >= MIN_CARACTERES and proporcion >= MIN_PROPORCION_LEGIBLE


def area_imagenes(doc, indice: int) -> float:
    """Fracción de la página cubierta por la mayor imagen (un escaneo ocupa casi toda)."""
    import pypdfium2.raw as pdfium_c
    pagina = doc[indice]
    ancho, alto = pagina.get_size()
    mayor = 0.0
    for obj in pagina.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=2):
        l, b, r, t = obj.get_pos()
        mayor = max(mayor, max(0.0, r - l) * max(0.0, t - b))
    return mayor / (ancho * alto) if ancho * alto else 0.0


def renderizar(datos_o_doc, indice: int, ppp: int = 300) -> np.ndarray:
    """Página `indice` (desde 0) como imagen BGR. Acepta los bytes o un documento ya abierto."""
    import cv2
    import pypdfium2 as pdfium
    propio = not isinstance(datos_o_doc, pdfium.PdfDocument)
    doc = pdfium.PdfDocument(datos_o_doc) if propio else datos_o_doc
    try:
        img = doc[indice].render(scale=ppp / 72).to_pil().convert("RGB")
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    finally:
        if propio:
            doc.close()


def metadatos(doc, datos: bytes) -> dict:
    info = {}
    try:
        meta = doc.get_metadata_dict(skip_empty=True)
    except Exception:
        meta = {}
    for k in ("Producer", "Creator", "CreationDate", "ModDate"):
        if meta.get(k):
            info[k.lower()] = meta[k]
    # Cada guardado incremental añade un «%%EOF»: más de uno = el PDF se modificó tras crearse.
    # Un PDF «linealizado» (optimizado para la web) ya trae dos de fábrica.
    eofs = len(re.findall(rb"%%EOF", datos))
    linealizado = b"/Linearized" in datos[:2048]
    info["revisiones"] = max(1, eofs - (1 if linealizado else 0))
    return info
