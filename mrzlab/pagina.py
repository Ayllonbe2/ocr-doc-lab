"""Preparar la imagen de una página antes del OCR: la hoja en una foto, su orientación y su
inclinación.

- Foto de móvil: se busca la hoja (el cuadrilátero claro más grande) y se endereza la
  perspectiva. Si no se encuentra, se sigue con la foto entera.
- Orientación 0/90/180/270: Tesseract OSD.
- Inclinación fina (±8°): la que maximiza el contraste entre filas de texto y huecos.
"""
from __future__ import annotations

import cv2
import numpy as np


def _ordenar_esquinas(pts: np.ndarray) -> np.ndarray:
    """Arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.float32([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])


def buscar_hoja(img: np.ndarray, area_min: float = 0.2) -> np.ndarray | None:
    """Esquinas de la hoja en la foto (4×2), o None si no hay un cuadrilátero claro."""
    h, w = img.shape[:2]
    f = 1000 / max(h, w)
    peq = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
    f = min(f, 1.0)
    gris = cv2.GaussianBlur(cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    # Dos pistas: bordes (Canny) y papel claro sobre fondo más oscuro (Otsu).
    bordes = cv2.dilate(cv2.Canny(gris, 40, 120), np.ones((5, 5), np.uint8))
    claro = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    claro = cv2.morphologyEx(claro, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    area_img = peq.shape[0] * peq.shape[1]
    mejor, mejor_area = None, 0.0
    for mascara in (claro, bordes):
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contornos, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c)
            if area < area_min * area_img or area > 0.98 * area_img:
                continue
            aprox = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
            if len(aprox) == 4 and cv2.isContourConvex(aprox) and area > mejor_area:
                mejor, mejor_area = aprox, area
    return None if mejor is None else _ordenar_esquinas(mejor) / f


def enderezar_hoja(img: np.ndarray, esquinas: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = esquinas
    ancho = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    alto = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    destino = np.float32([[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]])
    m = cv2.getPerspectiveTransform(esquinas.astype(np.float32), destino)
    return cv2.warpPerspective(img, m, (ancho, alto), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)


def girar(img: np.ndarray, grados: int) -> np.ndarray:
    return {0: img, 90: cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
            180: cv2.rotate(img, cv2.ROTATE_180),
            270: cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)}[grados % 360]


def orientacion(img: np.ndarray) -> int:
    """Grados (0/90/180/270, en sentido horario) que hay que girar para leer la página.

    Tesseract OSD; si no está o no hay texto suficiente, 0.
    """
    try:
        import pytesseract
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        f = min(1.0, 2000 / max(gris.shape[:2]))
        gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else gris
        osd = pytesseract.image_to_osd(gris, config="--psm 0 -c min_characters_to_try=20",
                                       output_type=pytesseract.Output.DICT)
        if float(osd.get("orientation_conf", 0)) < 1.5:
            return 0
        return int(osd.get("rotate", 0)) % 360
    except Exception:
        return 0


def inclinacion(img: np.ndarray, maximo: float = 8.0, paso: float = 0.25) -> float:
    """Ángulo (grados) que endereza las filas de texto: el que da el perfil más «a rayas»."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    f = 1000 / max(gris.shape[:2])
    gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    tinta = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    if tinta.mean() < 1:
        return 0.0
    h, w = tinta.shape
    centro = (w / 2, h / 2)

    def puntuacion(angulo: float) -> float:
        m = cv2.getRotationMatrix2D(centro, angulo, 1.0)
        perfil = cv2.warpAffine(tinta, m, (w, h), flags=cv2.INTER_NEAREST).sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(perfil) ** 2))

    # Búsqueda gruesa y luego fina alrededor del mejor.
    gruesa = max(np.arange(-maximo, maximo + 1e-6, 1.0), key=puntuacion)
    fina = max(np.arange(gruesa - 1, gruesa + 1 + 1e-6, paso), key=puntuacion)
    return float(round(fina, 2))


def rotar(img: np.ndarray, angulo: float) -> np.ndarray:
    if abs(angulo) < 0.1:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angulo, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preparar(img: np.ndarray, es_foto: bool) -> tuple[np.ndarray, dict]:
    """Hoja enderezada, orientada y sin inclinación. Devuelve también qué se hizo."""
    info: dict = {"hoja_detectada": None, "giro": 0, "inclinacion": 0.0}
    if es_foto:
        esquinas = buscar_hoja(img)
        info["hoja_detectada"] = esquinas is not None
        if esquinas is not None:
            img = enderezar_hoja(img, esquinas)
    giro = orientacion(img)
    if giro:
        img = girar(img, giro)
        info["giro"] = giro
    angulo = inclinacion(img)
    if angulo:
        img = rotar(img, angulo)
        info["inclinacion"] = angulo
    return img, info
