"""¿Qué documento es? Puntuación por palabras clave de cada tipo.

Cada extractor declara sus claves (patrón → peso) sobre el texto en mayúsculas y sin tildes.
Gana el tipo con más puntos si supera un mínimo; si no, «desconocido». Sencillo, explicable y
sin modelos: basta para detectar el caso típico, un documento subido en la casilla equivocada.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .extractores import REGISTRO

MINIMO = 3.0          # puntos para reconocer un tipo
# El tipo pedido «coincide» si alcanza el mínimo y no queda muy por debajo del mejor.
PROPORCION_COINCIDE = 0.6


@lru_cache(maxsize=1)
def _patrones() -> dict[str, list[tuple[re.Pattern, float]]]:
    return {t: [(re.compile(p), w) for p, w in e.claves.items()] for t, e in REGISTRO.items()}


def puntuar(texto_norm: str) -> dict[str, float]:
    return {t: round(sum(w for rx, w in pats if rx.search(texto_norm)), 2)
            for t, pats in _patrones().items()}


def clasificar(texto_norm: str, solicitado: str | None = None) -> dict:
    puntos = puntuar(texto_norm)
    orden = sorted(puntos.items(), key=lambda kv: kv[1], reverse=True)
    (mejor, p1), p2 = orden[0], orden[1][1] if len(orden) > 1 else 0.0
    detectado = mejor if p1 >= MINIMO else None
    confianza = round(p1 / (p1 + p2 + 1.0), 2) if detectado else 0.0
    candidatos = [{"tipo": t, "puntos": p} for t, p in orden[:3] if p > 0]
    salida = {"tipo_detectado": detectado, "confianza": confianza, "candidatos": candidatos}
    if solicitado is not None:
        ps = puntos.get(solicitado, 0.0)
        salida["coincide"] = ps >= MINIMO and ps >= PROPORCION_COINCIDE * p1
    return salida
