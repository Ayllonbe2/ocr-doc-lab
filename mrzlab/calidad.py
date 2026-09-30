"""Evaluación de calidad de imagen: nitidez, iluminación, contraste, reflejos y resolución.

Solo OpenCV, sin modelos. Cada métrica se calcula sobre la foto entera y, si se ha
localizado, sobre la zona de la MRZ, que es la que decide si el DNI se puede leer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

ORDEN = {"ok": 0, "dudoso": 1, "mal": 2}
_ANCHO_GLOBAL = 1000
_ANCHO_MRZ = 900

MENSAJES = {
    "nitidez": "Imagen borrosa: enfoca o acerca el móvil y mantén el pulso",
    "brillo_bajo": "Imagen muy oscura: busca más luz",
    "brillo_alto": "Imagen demasiado iluminada",
    "oscuros": "Gran parte de la foto está en sombra",
    "quemados": "Zonas quemadas por exceso de luz",
    "contraste": "Poco contraste: el texto se confunde con el fondo",
    "reflejo": "Hay un reflejo: inclina el DNI o quita el flash",
    "lado_min_px": "Resolución baja: usa la cámara trasera o acércate",
    "altura_linea_px": "La MRZ sale muy pequeña: acerca la cámara al DNI",
}

Caja = tuple[int, int, int, int]  # x, y, ancho, alto


def cargar_umbrales(ruta: str | Path) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _gris(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _redimensionar(img: np.ndarray, ancho: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w == ancho:
        return img
    interp = cv2.INTER_AREA if w > ancho else cv2.INTER_CUBIC
    return cv2.resize(img, (ancho, max(1, round(h * ancho / w))), interpolation=interp)


def nitidez(gris: np.ndarray, ancho: int) -> float:
    """Varianza del Laplaciano tras llevar la imagen a un ancho fijo.

    Sin normalizar, la misma foto da valores distintos según su resolución.
    """
    g = _redimensionar(gris, ancho)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def manchas_reflejo(img: np.ndarray) -> tuple[float, list[Caja]]:
    """Zonas blancas saturadas (brillo máximo y sin color): reflejos del plastificado o flash."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mascara = ((hsv[..., 2] >= 250) & (hsv[..., 1] <= 30)).astype(np.uint8) * 255
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mascara, connectivity=8)
    area_total = img.shape[0] * img.shape[1]
    minimo = area_total * 0.0005
    cajas, mayor = [], 0
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= minimo:
            cajas.append((int(x), int(y), int(w), int(h)))
            mayor = max(mayor, int(area))
    return mayor / area_total, cajas


def metricas(img: np.ndarray, zona: str, altura_mrz: int | None = None) -> dict[str, float]:
    gris = _gris(img)
    brillo = float(gris.mean())
    m = {
        "nitidez": nitidez(gris, _ANCHO_GLOBAL if zona == "global" else _ANCHO_MRZ),
        "brillo_bajo": brillo,
        "brillo_alto": brillo,
        "quemados": float((gris > 250).mean()),
        "contraste": float(gris.std()),
        "reflejo": manchas_reflejo(img)[0],
    }
    if zona == "global":
        m["oscuros"] = float((gris < 30).mean())
        m["lado_min_px"] = float(min(gris.shape[:2]))
    elif altura_mrz is not None:
        m["altura_linea_px"] = altura_mrz / 3
    return {k: round(v, 4) for k, v in m.items()}


def _nivel(valor: float, regla: dict) -> str:
    if regla["sentido"] == "min":
        return "mal" if valor < regla["mal"] else "dudoso" if valor < regla["dudoso"] else "ok"
    return "mal" if valor > regla["mal"] else "dudoso" if valor > regla["dudoso"] else "ok"


@dataclass
class Evaluacion:
    zonas: dict[str, dict[str, dict]]
    avisos: list[dict]
    veredicto: str
    reflejos: list[Caja]

    def a_dict(self) -> dict:
        return {"zonas": self.zonas, "avisos": self.avisos,
                "veredicto": self.veredicto, "reflejos": self.reflejos}


def evaluar(img: np.ndarray, umbrales: dict, caja_mrz: Caja | None = None) -> Evaluacion:
    zonas: dict[str, dict[str, dict]] = {}
    avisos: list[dict] = []
    peor = "ok"

    recortes = {"global": (img, None)}
    if caja_mrz is not None:
        x, y, w, h = caja_mrz
        recorte = img[y:y + h, x:x + w]
        if recorte.size:
            recortes["mrz"] = (recorte, h)

    for zona, (imagen, altura) in recortes.items():
        valores = metricas(imagen, zona, altura)
        zonas[zona] = {}
        for nombre, valor in valores.items():
            regla = umbrales[zona].get(nombre)
            if regla is None:
                continue
            nivel = _nivel(valor, regla)
            if regla.get("solo_aviso") and nivel == "mal":
                nivel = "dudoso"
            zonas[zona][nombre] = {"valor": valor, "nivel": nivel}
            if nivel != "ok":
                avisos.append({"zona": zona, "metrica": nombre, "nivel": nivel,
                               "mensaje": MENSAJES[nombre]})
                if ORDEN[nivel] > ORDEN[peor]:
                    peor = nivel

    # Brillo bajo y alto comparten valor: dejar solo el que aplica.
    for z in zonas.values():
        if "brillo_bajo" in z and "brillo_alto" in z:
            z["brillo"] = z.pop("brillo_bajo") if z["brillo_bajo"]["nivel"] != "ok" \
                else z.pop("brillo_alto")
            z.pop("brillo_bajo", None)
            z.pop("brillo_alto", None)

    veredicto = {"ok": "apta", "dudoso": "riesgo", "mal": "rechazar"}[peor]
    _, reflejos = manchas_reflejo(img)
    return Evaluacion(zonas, avisos, veredicto, reflejos)


# ── Documentos A4 (escaneados o fotografiados) ───────────────────────────────

MENSAJES_DOCUMENTO = {
    **MENSAJES,
    "reflejo": "Hay un reflejo sobre el papel: evita el flash y la luz directa",
    "lado_min_px": "Resolución baja: escanea a 300 ppp o acerca el móvil",
    "altura_letra_px": "El texto sale muy pequeño: acerca el móvil o escanea a más resolución",
    "oscuros": "Parte de la hoja está en sombra",
}


def reflejo_papel(img: np.ndarray) -> float:
    """Mayor mancha de brillo quemado MÁS CLARA que el papel que la rodea (fracción del área).

    En un documento el papel blanco ya está cerca de 255: la medida del DNI (zonas blancas sin
    color) lo tomaría todo por reflejo. Aquí solo cuenta un brillo que destaca sobre el papel,
    como el de un flash o una lámpara en una foto.
    """
    gris = _redimensionar(_gris(img), 800)
    papel = cv2.medianBlur(gris, 31).astype(np.int16)
    quemado = ((gris >= 250) & (gris.astype(np.int16) - papel >= 12)).astype(np.uint8)
    # Además, un papel que en la foto no es blanco (<230) con zonas saturadas: reflejo.
    if float(np.median(gris)) < 230:
        quemado |= (gris >= 252).astype(np.uint8)
    quemado = cv2.morphologyEx(quemado, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(quemado, connectivity=8)
    mayor = max((int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n)), default=0)
    return mayor / gris.size


def evaluar_documento(img: np.ndarray, umbrales: dict, altura_letra: float | None = None) -> Evaluacion:
    """Calidad de una página: las métricas de la foto entera más el alto de la letra leída.

    El alto de la letra decide mejor que el tamaño de la imagen: un A4 entero en una foto de
    12 MP tiene letra suficiente; un recorte pequeño, no.
    """
    reglas = umbrales["documento"]
    valores = metricas(img, "global")
    valores["reflejo"] = round(reflejo_papel(img), 4)
    if altura_letra is not None:
        valores["altura_letra_px"] = round(float(altura_letra), 1)
    zona: dict[str, dict] = {}
    avisos: list[dict] = []
    peor = "ok"
    for nombre, valor in valores.items():
        regla = reglas.get(nombre)
        if regla is None:
            continue
        nivel = _nivel(valor, regla)
        if regla.get("solo_aviso") and nivel == "mal":
            nivel = "dudoso"
        zona[nombre] = {"valor": valor, "nivel": nivel}
        if nivel != "ok":
            avisos.append({"zona": "documento", "metrica": nombre, "nivel": nivel,
                           "mensaje": MENSAJES_DOCUMENTO[nombre]})
            peor = max(peor, nivel, key=ORDEN.get)
    if "brillo_bajo" in zona and "brillo_alto" in zona:
        zona["brillo"] = zona["brillo_bajo"] if zona["brillo_bajo"]["nivel"] != "ok" else zona["brillo_alto"]
        del zona["brillo_bajo"], zona["brillo_alto"]
    veredicto = {"ok": "apta", "dudoso": "riesgo", "mal": "rechazar"}[peor]
    _, reflejos = manchas_reflejo(img)
    return Evaluacion({"documento": zona}, avisos, veredicto, reflejos)
