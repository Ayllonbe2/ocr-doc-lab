"""Preprocesado de imagen antes del OCR: enderezar la tarjeta y mejorar el contraste local.

Solo OpenCV, sin modelos.
"""
from __future__ import annotations

import cv2
import numpy as np

PROPORCION_ID1 = 85.6 / 54.0   # tarjeta tamaño ID-1 (DNI)
_ANCHO_TRABAJO = 900


def clahe(gris: np.ndarray) -> np.ndarray:
    """Ecualización local del contraste: compensa sombras y luz desigual."""
    return cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gris)


def umbral_adaptativo(gris: np.ndarray, altura_linea: int) -> np.ndarray:
    """Binarización por zonas: no depende de que toda la MRZ tenga la misma luz."""
    bloque = max(15, int(altura_linea * 1.2) | 1)
    return cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, bloque, 15)


def _ordenar_esquinas(pts: np.ndarray) -> np.ndarray:
    """Devuelve las esquinas como sup-izq, sup-der, inf-der, inf-izq."""
    pts = pts.reshape(4, 2).astype(np.float32)
    suma, resta = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.float32([pts[np.argmin(suma)], pts[np.argmin(resta)],
                       pts[np.argmax(suma)], pts[np.argmax(resta)]])


def buscar_tarjeta(img: np.ndarray) -> np.ndarray | None:
    """Cuatro esquinas de la tarjeta en la foto (coordenadas originales) o None."""
    h0, w0 = img.shape[:2]
    escala = _ANCHO_TRABAJO / w0
    peque = cv2.resize(img, (_ANCHO_TRABAJO, max(1, round(h0 * escala))), interpolation=cv2.INTER_AREA)
    gris = cv2.GaussianBlur(cv2.cvtColor(peque, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    bordes = cv2.dilate(cv2.Canny(gris, 30, 100), np.ones((3, 3), np.uint8), iterations=2)
    contornos, _ = cv2.findContours(bordes, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_img = peque.shape[0] * peque.shape[1]
    for c in sorted(contornos, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(c)
        if area < 0.2 * area_img:
            break
        peri = cv2.arcLength(c, True)
        for eps in (0.02, 0.04):  # las esquinas redondeadas a veces necesitan más tolerancia
            aprox = cv2.approxPolyDP(c, eps * peri, True)
            if len(aprox) == 4 and cv2.isContourConvex(aprox):
                return _ordenar_esquinas(aprox) / escala
        # Sin cuadrilátero limpio: rectángulo mínimo del contorno (tolera bordes rotos).
        caja = cv2.boxPoints(cv2.minAreaRect(c))
        if cv2.contourArea(caja) < 1.3 * area:
            return _ordenar_esquinas(caja) / escala
    return None


def esquinas_apaisadas(img: np.ndarray) -> np.ndarray | None:
    """Esquinas de la tarjeta (sup-izq, sup-der, inf-der, inf-izq) con la tarjeta apaisada.

    Ojo: «apaisada» no dice si está boca abajo; eso lo decide quien la usa.
    """
    esquinas = buscar_tarjeta(img)
    if esquinas is None:
        return None
    si, sd, id_, ii = esquinas
    ancho = max(np.linalg.norm(sd - si), np.linalg.norm(id_ - ii))
    alto = max(np.linalg.norm(ii - si), np.linalg.norm(id_ - sd))
    if min(ancho, alto) < 100:
        return None
    if alto > ancho:  # tarjeta en vertical: rotar las esquinas para dejarla apaisada
        si, sd, id_, ii = sd, id_, ii, si
        ancho, alto = alto, ancho
    if not 1.2 < ancho / alto < 2.0:  # no parece una tarjeta ID-1
        return None
    return np.float32([si, sd, id_, ii])


def enderezar_tarjeta(img: np.ndarray) -> np.ndarray | None:
    """Corrige la perspectiva: devuelve la tarjeta vista de frente, apaisada, o None."""
    esquinas = esquinas_apaisadas(img)
    if esquinas is None:
        return None
    si, sd, id_, ii = esquinas
    ancho = max(np.linalg.norm(sd - si), np.linalg.norm(id_ - ii))
    w = int(min(max(ancho, 800), 1800))
    h = round(w / PROPORCION_ID1)
    m = cv2.getPerspectiveTransform(esquinas, np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    return cv2.warpPerspective(img, m, (w, h), flags=cv2.INTER_CUBIC)
