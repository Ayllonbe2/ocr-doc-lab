"""¿Está firmada la ficha? Tinta manuscrita en la zona de firma, junto a su etiqueta.

Se mira un recuadro bajo (y a la derecha de) la etiqueta «Firma del trabajador», «Recibí»…,
se tapa el texto impreso que haya dentro y se mide la tinta que queda. Un PDF con firma
electrónica PAdES íntegra cuenta como firmado.
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from ..lineas import Linea
from .base import Campo, norm

ETIQUETAS = (r"\b(?:FIRMA\s+(?:DEL?\s+|DE\s+LA\s+)?(?:TRABAJADOR|TRABAJADORA|PERSONA|INTERESAD|EMPLEAD|ALUMN|"
             r"RECEPTOR|QUE\s+RECIBE)|FIRMA\s+PERSONA\s+QUE\s+SE\s+INCORPORA|RECIBI\b|RECIBE\s+Y\s+FIRMA|"
             r"ENTERADO\s+Y\s+CONFORME|CONFORME\s*:|FDO\.?\s*(?:EL|LA)\s+TRABAJADOR)")

# Fracción de píxeles con tinta en la zona (ya sin el texto impreso).
FIRMADO = 0.004
VACIO = 0.0012


def _es_texto(ln: Linea) -> bool:
    letras = sum(c.isalnum() for c in ln.texto)
    return ln.origen in ("capa_texto", "formulario") or (letras >= 4 and ln.confianza >= 0.6
                                                         and letras / max(len(ln.texto), 1) >= 0.6)


def _zona(etiqueta: Linea, lineas: list[Linea]) -> tuple[float, float, float, float]:
    """Bajo la etiqueta y a su derecha (en formularios se firma al lado), sin pasar de la siguiente
    etiqueta de la misma fila (la firma de la empresa, por ejemplo)."""
    alto = max(etiqueta.caja[3], 0.01)
    x0 = max(0.0, etiqueta.caja[0] - 0.02)
    y0 = etiqueta.caja[1] - alto * 0.2
    x1 = min(1.0, x0 + max(0.5, etiqueta.caja[2] * 2.2))
    vecinas = [o.caja[0] for o in lineas if o is not etiqueta and o.pagina == etiqueta.pagina and _es_texto(o)
               and abs(o.centro_y - etiqueta.centro_y) < alto and o.caja[0] > etiqueta.x2]
    if vecinas:
        x1 = min(x1, min(vecinas) - 0.01)
    return x0, y0, x1, min(1.0, etiqueta.y2 + 0.09)


def tinta(img: np.ndarray, zona: tuple[float, float, float, float], texto: list[Linea]) -> float:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(zona[0] * w), int(zona[1] * h), int(zona[2] * w), int(zona[3] * h))
    rec = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if rec.size == 0:
        return 0.0
    binaria = cv2.adaptiveThreshold(rec, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    # Fuera el texto impreso (con un margen) y las líneas rectas largas (renglones, marcos).
    for ln in texto:
        a = int((ln.caja[0] - 0.004) * w) - x0, int((ln.caja[1] - 0.004) * h) - y0
        b = int((ln.x2 + 0.004) * w) - x0, int((ln.y2 + 0.004) * h) - y0
        cv2.rectangle(binaria, a, b, 0, -1)
    for kernel in ((max(15, rec.shape[1] // 4), 1), (1, max(15, rec.shape[0] // 3))):
        rectas = cv2.morphologyEx(binaria, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, kernel))
        binaria = cv2.subtract(binaria, rectas)
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # Trazos que tocan el borde superior de la zona: vienen de la firma de la fila de arriba
    # (la del responsable, por ejemplo), que suele invadir el hueco de la siguiente.
    n, etiquetas, stats, _ = cv2.connectedComponentsWithStats(binaria, connectivity=8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_TOP] <= 1:
            binaria[etiquetas == i] = 0
    return float((binaria > 0).mean())


def firmado(doc) -> Campo | None:
    """True/False si se ha podido comprobar; None si no hay zona de firma reconocible."""
    if any(f.get("integra") for f in doc.firmas):
        return Campo(True, "firma_electronica", 1.0, 1)
    etiquetas = [ln for ln in doc.lineas if re.search(ETIQUETAS, norm(ln.texto))]
    if not etiquetas:
        return None
    mejor: tuple[float, Linea] | None = None
    for et in etiquetas:
        img = doc.imagen(et.pagina)
        if img is None:
            continue
        zona = _zona(et, doc.lineas)
        # Solo se tapa texto impreso de verdad: el OCR a veces «lee» un trozo de la firma («o», «J»)
        # y taparlo borraría la propia firma.
        dentro = [ln for ln in doc.lineas if ln.pagina == et.pagina and ln.x2 > zona[0] and ln.caja[0] < zona[2]
                  and ln.y2 > zona[1] and ln.caja[1] < zona[3] and _es_texto(ln)]
        t = tinta(img, zona, dentro)
        if mejor is None or t > mejor[0]:
            mejor = (t, et)
    if mejor is None:
        return None
    t, et = mejor
    if t >= FIRMADO:
        return Campo(True, "imagen", min(1.0, t / (FIRMADO * 3)), et.pagina)
    if t <= VACIO:
        return Campo(False, "imagen", 1.0 - t / VACIO * 0.5, et.pagina)
    return None      # tinta dudosa: mejor revisión manual que adivinar
