"""Localiza la zona MRZ con morfología de OpenCV (sin modelos).

Idea: la MRZ es un bloque de texto oscuro, denso y muy ancho respecto a su alto.
Se resaltan los trazos oscuros (black-hat), se funden los caracteres en bloques y se
elige el bloque más grande con proporción de MRZ.
"""
from __future__ import annotations

import cv2
import numpy as np

Caja = tuple[int, int, int, int]
_ANCHO = 800


def localizar_mrz(img: np.ndarray) -> Caja | None:
    h0, w0 = img.shape[:2]
    escala = _ANCHO / w0
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gris = cv2.resize(gris, (_ANCHO, max(1, round(h0 * escala))), interpolation=cv2.INTER_AREA)
    gris = cv2.GaussianBlur(gris, (3, 3), 0)

    rect = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    cuadrado = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))

    blackhat = cv2.morphologyEx(gris, cv2.MORPH_BLACKHAT, rect)
    grad = np.absolute(cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=-1))
    mn, mx = float(grad.min()), float(grad.max())
    grad = ((grad - mn) / (mx - mn + 1e-6) * 255).astype(np.uint8)

    grad = cv2.morphologyEx(grad, cv2.MORPH_CLOSE, rect)
    umbral = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    umbral = cv2.morphologyEx(umbral, cv2.MORPH_CLOSE, cuadrado)
    umbral = cv2.erode(umbral, None, iterations=3)

    contornos, _ = cv2.findContours(umbral, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mejor, mejor_area = None, 0
    for c in contornos:
        x, y, w, h = cv2.boundingRect(c)
        if h == 0:
            continue
        proporcion = w / h
        # TD1: 3 líneas de 30 caracteres → bloque de proporción ~3:1 a ~8:1.
        if 2.5 <= proporcion <= 12 and w >= _ANCHO * 0.25 and w * h > mejor_area:
            mejor, mejor_area = (x, y, w, h), w * h
    if mejor is None:
        return None

    x, y, w, h = mejor
    # Margen: la erosión recorta los bordes del bloque.
    mx_, my_ = int(w * 0.06), int(h * 0.15)
    x, y = max(0, x - mx_), max(0, y - my_)
    w = min(_ANCHO - x, w + 2 * mx_)
    h = min(gris.shape[0] - y, h + 2 * my_)
    return (round(x / escala), round(y / escala), round(w / escala), round(h / escala))
