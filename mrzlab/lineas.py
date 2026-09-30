"""Formato común de lo leído en un documento, venga de la capa de texto de un PDF, de un campo de
formulario o del OCR. Los extractores solo ven esto: no saben de dónde sale cada línea.

Las cajas van en fracción de la página (0–1), para que una misma plantilla valga para un PDF
(puntos) y para una foto (píxeles).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

Caja = tuple[float, float, float, float]   # x, y, ancho, alto (fracción de la página)

CAPA_TEXTO = "capa_texto"
FORMULARIO = "formulario"


@dataclass
class Linea:
    texto: str
    caja: Caja
    pagina: int                  # 1, 2…
    origen: str                  # capa_texto | formulario | ocr:<motor>
    confianza: float = 1.0
    alternativa: str | None = None   # lo que leyó el otro motor OCR, si difiere

    @property
    def x2(self) -> float:
        return self.caja[0] + self.caja[2]

    @property
    def y2(self) -> float:
        return self.caja[1] + self.caja[3]

    @property
    def centro_y(self) -> float:
        return self.caja[1] + self.caja[3] / 2


@dataclass
class Pagina:
    numero: int
    tipo: str                               # digital | escaneada | foto
    lineas: list[Linea] = field(default_factory=list)
    imagen: np.ndarray | None = None        # BGR; en las digitales solo si hace falta (QR, firmas)
    calidad: dict | None = None             # solo en las que pasan por OCR
    motor: str | None = None


def orden_lectura(lineas: list[Linea]) -> list[Linea]:
    """Por página, de arriba abajo y, en la misma fila, de izquierda a derecha."""
    # Filas: dos líneas son de la misma fila si sus centros distan menos de media altura.
    ordenadas = sorted(lineas, key=lambda ln: (ln.pagina, ln.centro_y, ln.caja[0]))
    filas: list[list[Linea]] = []
    for ln in ordenadas:
        ultima = filas[-1] if filas else None
        if (ultima and ultima[0].pagina == ln.pagina
                and abs(ultima[0].centro_y - ln.centro_y) < max(ultima[0].caja[3], ln.caja[3]) * 0.5):
            ultima.append(ln)
        else:
            filas.append([ln])
    return [ln for fila in filas for ln in sorted(fila, key=lambda x: x.caja[0])]


def texto(lineas: list[Linea]) -> str:
    """Texto en orden de lectura: una línea por fila, con dos espacios entre columnas."""
    salida: list[str] = []
    previa: Linea | None = None
    for ln in orden_lectura(lineas):
        misma_fila = (previa is not None and previa.pagina == ln.pagina
                      and abs(previa.centro_y - ln.centro_y) < max(previa.caja[3], ln.caja[3]) * 0.5)
        if misma_fila:
            salida[-1] += "  " + ln.texto
        else:
            salida.append(ln.texto)
        previa = ln
    return "\n".join(salida)
