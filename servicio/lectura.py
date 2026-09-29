"""Lectura de cada cara del DNI. Todo en memoria: nada se guarda.

- Reverso: la MRZ (Tesseract y, si no da una MRZ válida, RapidOCR), sobre la foto original y,
  si hace falta, sobre la tarjeta enderezada.
- Anverso: el nº de DNI (con letra correcta) y el nº de soporte, junto a su etiqueta y, si hay
  plantilla de posiciones, también por la posición de cada campo en la tarjeta.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from mrzlab import anverso, calidad, deteccion, motores, mrz, plantilla, preproceso

UMBRALES = Path(os.getenv("UMBRALES", Path(__file__).resolve().parent.parent / "umbrales.yaml"))
# Primero el motor más rápido; el siguiente solo si el anterior no consigue una MRZ válida.
ORDEN_MRZ = ("tesseract", "rapidocr")
# Anverso: RapidOCR lee mejor el texto general; Tesseract, por posición.
ORDEN_ANVERSO = ("rapidocr", "tesseract")


class ImagenInvalida(ValueError):
    pass


def decodificar(datos: bytes) -> np.ndarray:
    """Abre la foto respetando la orientación EXIF (las fotos de móvil suelen venir giradas)."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(datos))).convert("RGB")
    except Exception as e:
        raise ImagenInvalida("No se pudo abrir la imagen (formatos: JPG, PNG, WEBP)") from e
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


@lru_cache(maxsize=1)
def _umbrales() -> dict:
    return calidad.cargar_umbrales(UMBRALES)


def _disponibles(orden: tuple[str, ...]) -> list[motores.Motor]:
    por_nombre = {m.nombre: m for m in motores.TODOS if m.disponible()[0]}
    return [por_nombre[n] for n in orden if n in por_nombre]


@dataclass
class Calidad:
    veredicto: str                       # apta | riesgo | rechazar
    avisos: list[str] = field(default_factory=list)   # qué corregir, para el usuario

    @property
    def mala(self) -> bool:
        return self.veredicto != "apta"


def _calidad(ev: calidad.Evaluacion) -> Calidad:
    mensajes = []
    for a in ev.avisos:
        if a["mensaje"] not in mensajes:
            mensajes.append(a["mensaje"])
    return Calidad(ev.veredicto, mensajes)


# ── Reverso ──────────────────────────────────────────────────────────────────

@dataclass
class LecturaReverso:
    mrz: mrz.ResultadoMRZ | None   # la mejor lectura (válida o no)
    calidad: Calidad

    @property
    def valida(self) -> bool:
        return self.mrz is not None and self.mrz.valido


def _variantes(img: np.ndarray, caja):
    yield img, caja
    tarjeta = preproceso.enderezar_tarjeta(img)
    if tarjeta is None:
        return
    caja_t = deteccion.localizar_mrz(tarjeta)
    if caja_t is not None and caja_t[1] + caja_t[3] / 2 < tarjeta.shape[0] / 2:
        # La MRZ va abajo: si ha quedado arriba, la tarjeta está boca abajo.
        tarjeta = cv2.rotate(tarjeta, cv2.ROTATE_180)
        caja_t = deteccion.localizar_mrz(tarjeta)
    yield tarjeta, caja_t


def leer_reverso(img: np.ndarray) -> LecturaReverso:
    caja = deteccion.localizar_mrz(img)
    ev = calidad.evaluar(img, _umbrales(), caja)
    es_valida = lambda i: (r := mrz.leer(i.lineas)) is not None and r.valido  # noqa: E731

    mejor, mejor_p = None, -1
    for m in _disponibles(ORDEN_MRZ):
        for img_v, caja_v in _variantes(img, caja):
            lectura = m.leer(img_v, caja_v, es_valida)
            for intento in lectura.intentos:
                r = mrz.leer(intento.lineas)
                if r is None:
                    continue
                if r.valido:
                    return LecturaReverso(r, _calidad(ev))
                p = sum(r.controles.values())
                if p > mejor_p:
                    mejor, mejor_p = r, p
    return LecturaReverso(mejor, _calidad(ev))


# ── Anverso ──────────────────────────────────────────────────────────────────

@dataclass
class LecturaAnverso:
    # Candidatos leídos, sin repetir y en orden de confianza. El DNI solo si su letra cuadra.
    dnis: list[str]
    soportes: list[str]
    calidad: Calidad
    # Todo el texto leido, sin espacios (solo en memoria; fuera del repr para que no acabe en
    # un log). Sirve para confirmar un dato de la MRZ aunque el OCR lo haya pegado a otro.
    texto: str = field(default="", repr=False)

    @property
    def completa(self) -> bool:
        return bool(self.dnis and self.soportes)


def _añadir(lista: list[str], valor: str | None) -> None:
    if valor and valor not in lista:
        lista.append(valor)


def leer_anverso(img: np.ndarray) -> LecturaAnverso:
    ev = calidad.evaluar(img, _umbrales(), None)
    dnis: list[str] = []
    soportes: list[str] = []
    textos: list[str] = []
    mejor_lectura = None

    # 1) Junto a su etiqueta, con el texto de la foto entera.
    for m in _disponibles(ORDEN_ANVERSO):
        lineas = [anverso.Linea(t, c, conf) for t, c, conf in m.texto(img)]
        textos += [anverso.normalizar(ln.texto).replace(" ", "") for ln in lineas]
        a = anverso.extraer(lineas)
        if a["dni_valido"]:
            _añadir(dnis, a["campos"]["dni"])
        _añadir(soportes, a["campos"]["num_soporte"])
        if mejor_lectura is None or (a["dni_valido"], a["encontrados"]) > (
                mejor_lectura["dni_valido"], mejor_lectura["encontrados"]):
            mejor_lectura = a
        if dnis and soportes:
            return LecturaAnverso(dnis, soportes, _calidad(ev), "|".join(textos))

    # 2) Por posición, si hay plantilla: solo las zonas del DNI y del soporte.
    plant = plantilla.cargar()
    if plant:
        zonas = {k: v for k, v in plant.items() if k in ("dni", "num_soporte") or k.startswith("etiqueta.")}
        cajas = {c: tuple(k) for c, k in (mejor_lectura or {}).get("cajas", {}).items()}
        cajas.update({f"etiqueta.{c}": tuple(k)
                      for c, k in (mejor_lectura or {}).get("cajas_etiquetas", {}).items()})
        g = plantilla.situar(img, cajas, plant)
        if g is not None:
            for m in _disponibles(ORDEN_ANVERSO):
                p = plantilla.leer(m, g, zonas)
                textos += [anverso.normalizar(t).replace(" ", "") for t in p["textos"].values()]
                if p["dni_valido"]:
                    _añadir(dnis, p["campos"].get("dni"))
                _añadir(soportes, p["campos"].get("num_soporte"))
                if dnis and soportes:
                    break
    return LecturaAnverso(dnis, soportes, _calidad(ev), "|".join(textos))
