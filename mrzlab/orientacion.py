"""Orientación del DNI en la foto: girarla (0/90/180/270°) hasta dejarlo derecho antes de leerlo.

1. Si se ven los bordes de la tarjeta, su forma dice si está en vertical (90/270) o
   apaisada (0/180).
2. Para decidir entre las posiciones posibles, se lee la foto reducida con RapidOCR **sin** su
   clasificador de ángulo (que endereza cada línea por su cuenta y ocultaría el giro) y gana
   la posición en la que se lee más texto con buena confianza. Las palabras propias del DNI
   (etiquetas del anverso, «IDESP», «<<<» de la MRZ) cuentan más.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import pagina, preproceso

LADO_PRUEBA = 960        # lado largo de la foto reducida con la que se puntúa cada posición
CONFIANZA_MIN = 0.5
MARGEN = 1.25            # para girar, la otra posición tiene que puntuar al menos esto más
_PALABRAS = re.compile(r"DNI|DOCUMENTO|NACIONAL|ESPA|APELLIDO|NOMBRE|SEXO|NACIONALIDAD|"
                       r"NACIMIENTO|VALIDEZ|SOPORTE|IDESP|<<<")


@dataclass
class Orientacion:
    giro: int                       # grados en sentido horario aplicados a la foto
    metodo: str
    puntos: dict[int, float] = field(default_factory=dict)
    ms: int = 0

    def a_dict(self) -> dict:
        return {"giro": self.giro, "metodo": self.metodo,
                "puntos": {str(k): round(v, 1) for k, v in self.puntos.items()}, "ms": self.ms}


def _candidatos(img: np.ndarray) -> tuple[list[int], str]:
    """Giros posibles según la forma de la tarjeta (o los 4 si no se ven sus bordes)."""
    esquinas = preproceso.buscar_tarjeta(img)
    if esquinas is not None:
        si, sd, id_, ii = esquinas
        ancho = max(np.linalg.norm(sd - si), np.linalg.norm(id_ - ii))
        alto = max(np.linalg.norm(ii - si), np.linalg.norm(id_ - sd))
        if min(ancho, alto) >= 100 and 1.2 < max(ancho, alto) / min(ancho, alto) < 2.0:
            if alto > ancho:
                return [90, 270], "tarjeta en vertical"
            return [0, 180], "tarjeta apaisada"
    return [0, 90, 180, 270], "sin bordes de tarjeta: se prueban las 4 posiciones"


def puntuar(img: np.ndarray) -> float:
    """Cuánto texto legible hay en la foto tal cual está (sin enderezar líneas)."""
    from .motores import RapidOCR
    h, w = img.shape[:2]
    f = min(1.0, LADO_PRUEBA / max(h, w))
    red = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
    resultado, _ = RapidOCR.cargar()(red, use_cls=False)
    puntos = 0.0
    for _, texto, conf in resultado or []:
        conf = float(conf)
        util = re.sub(r"[^A-Za-z0-9<]", "", texto)
        if conf < CONFIANZA_MIN or len(util) < 3:
            continue
        puntos += conf * len(util)
        puntos += 15 * len(_PALABRAS.findall(util.upper()))
    return puntos


def orientar(img: np.ndarray) -> tuple[np.ndarray, Orientacion]:
    """La foto con el DNI derecho y qué se hizo. Sin RapidOCR, la deja como está."""
    from .motores import RapidOCR
    if not RapidOCR().disponible()[0]:
        return img, Orientacion(0, "sin RapidOCR: no se comprueba")
    t0 = time.perf_counter()
    candidatos, metodo = _candidatos(img)
    puntos = {g: puntuar(pagina.girar(img, g)) for g in candidatos}
    mejor = max(puntos, key=puntos.get)
    if 0 in puntos and mejor != 0 and puntos[mejor] < MARGEN * puntos[0]:
        mejor = 0  # sin una diferencia clara, no se toca
    if puntos[mejor] == 0:
        mejor = 0 if 0 in puntos else mejor
        metodo += " (sin texto legible)"
    ms = round((time.perf_counter() - t0) * 1000)
    return pagina.girar(img, mejor), Orientacion(mejor, metodo, puntos, ms)
