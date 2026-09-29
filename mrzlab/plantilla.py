"""Plantilla de posiciones del anverso: dónde está cada campo dentro de la tarjeta.

Las posiciones son relativas a la tarjeta vista de frente, entre 0 y 1: (x, y, ancho, alto).
La plantilla se aprende de fotos bien leídas (la caja de cada campo reconocido por su
etiqueta) y se promedia entre fotos. **Solo guarda coordenadas: ningún dato de la persona.**

Con la plantilla, en una foto nueva se sitúa la tarjeta y se recorta la zona de cada campo
para leerla por separado. Así el motor lee un recorte pequeño con un tipo de dato conocido
(solo dígitos en una fecha, solo letras en un nombre…), que es donde Tesseract mejora mucho.

Para situar la tarjeta se usan, por este orden de preferencia:
  1. sus bordes (homografía; corrige la perspectiva), comprobados con los campos reconocidos;
  2. los campos ya reconocidos por su etiqueta («anclas»), si hay plantilla: escala y
     desplazamiento, sin corregir la perspectiva;
  3. la foto entera, si tiene proporción de tarjeta (foto ya recortada al borde).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

from . import anverso, preproceso

Caja = tuple[int, int, int, int]
CajaRel = tuple[float, float, float, float]
RUTA = Path(os.getenv("PLANTILLA_ANVERSO",
                      Path(__file__).resolve().parent.parent / "plantillas" / "anverso.yaml"))
ANCHO_TARJETA = 1400  # px de la tarjeta enderezada
_bloqueo = threading.Lock()


# ── Fichero ──────────────────────────────────────────────────────────────────

def cargar(ruta: Path | None = None) -> dict[str, dict] | None:
    """{campo: {"caja": [x, y, w, h], "n": muestras}} o None si no hay plantilla."""
    try:
        datos = yaml.safe_load(Path(ruta or RUTA).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    campos = datos.get("campos") or {}
    return {c: v for c, v in campos.items() if es_clave(c)} or None


def es_clave(c: str) -> bool:
    """Un campo («dni»…) o una etiqueta impresa («etiqueta.nombre»…)."""
    return c in anverso.CAMPOS or (c.startswith("etiqueta.") and c[9:] in anverso.ETIQUETAS)


def _escribir(campos: dict[str, dict], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cabecera = ("# Posiciones de los campos en el anverso del DNI, relativas a la tarjeta (0-1):\n"
                "# [x, y, ancho, alto]. n = fotos promediadas. Solo coordenadas: sin datos personales.\n"
                "# La genera MRZ Lab («Aprender posiciones»).\n")
    cuerpo = yaml.safe_dump({"campos": campos}, sort_keys=False, allow_unicode=True)
    ruta.write_text(cabecera + cuerpo, encoding="utf-8")


def aprender(nuevas: dict[str, list[float]], ruta: Path | None = None) -> dict[str, dict]:
    """Suma unas posiciones a la plantilla (media de todas las fotos aprendidas)."""
    limpias = {}
    for c, caja in nuevas.items():
        if not es_clave(c) or len(caja) != 4:
            raise ValueError(f"Campo o caja no válidos: {c}")
        x, y, w, h = (float(v) for v in caja)
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
            raise ValueError(f"Caja fuera de la tarjeta: {c}")
        limpias[c] = [x, y, w, h]
    ruta = Path(ruta or RUTA)
    with _bloqueo:
        campos = cargar(ruta) or {}
        for c, caja in limpias.items():
            previa = campos.get(c)
            if previa:
                n = int(previa["n"])
                caja = [(p * n + v) / (n + 1) for p, v in zip(previa["caja"], caja)]
                campos[c] = {"caja": [round(v, 4) for v in caja], "n": n + 1}
            else:
                campos[c] = {"caja": [round(v, 4) for v in caja], "n": 1}
        _escribir(campos, ruta)
    return campos


def borrar(ruta: Path | None = None) -> None:
    with _bloqueo:
        Path(ruta or RUTA).unlink(missing_ok=True)


# ── Geometría: de la foto a la tarjeta ───────────────────────────────────────

def _girar(c: CajaRel) -> CajaRel:
    x, y, w, h = c
    return (1 - x - w, 1 - y - h, w, h)


def _centro(c) -> tuple[float, float]:
    return (c[0] + c[2] / 2, c[1] + c[3] / 2)


def _error(rel: dict[str, CajaRel], plant: dict[str, dict]) -> float | None:
    """Distancia media entre los centros medidos y los de la plantilla."""
    comunes = [c for c in rel if c in plant]
    if not comunes:
        return None
    return float(np.mean([np.hypot(*np.subtract(_centro(rel[c]), _centro(plant[c]["caja"])))
                          for c in comunes]))


@dataclass
class Geometria:
    metodo: str
    imagen: np.ndarray                    # de donde se recortan las zonas
    foto_a_rel: callable                  # caja en la foto -> caja relativa (tarjeta derecha)
    rel_a_px: callable                    # caja relativa -> caja en «imagen»
    girada: bool = False
    error_anclas: float | None = None
    notas: list[str] = field(default_factory=list)


def _por_homografia(img: np.ndarray, esquinas: np.ndarray, metodo: str) -> Geometria:
    w = ANCHO_TARJETA
    h = round(w / preproceso.PROPORCION_ID1)
    m = cv2.getPerspectiveTransform(esquinas, np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    tarjeta = cv2.warpPerspective(img, m, (w, h), flags=cv2.INTER_CUBIC)

    def foto_a_rel(c: Caja) -> CajaRel:
        x, y, cw, ch = c
        pts = cv2.perspectiveTransform(
            np.float32([[[x, y]], [[x + cw, y]], [[x + cw, y + ch]], [[x, y + ch]]]), m).reshape(4, 2)
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        return (float(x0 / w), float(y0 / h), float((x1 - x0) / w), float((y1 - y0) / h))

    def rel_a_px(c: CajaRel) -> Caja:
        return (round(c[0] * w), round(c[1] * h), round(c[2] * w), round(c[3] * h))

    return Geometria(metodo, tarjeta, foto_a_rel, rel_a_px)


def _por_anclas(img: np.ndarray, cajas: dict[str, Caja], plant: dict[str, dict]) -> Geometria | None:
    """Escala y desplazamiento que llevan la plantilla a los campos reconocidos en la foto.

    x_foto = s·P·x_rel + bx ;  y_foto = s·y_rel + by   (P = proporción de la tarjeta)
    """
    comunes = [c for c in cajas if c in plant]
    if len(comunes) < 3:  # con 2 puntos el ajuste siempre «encaja», esté bien o mal
        return None
    rel = np.array([_centro(plant[c]["caja"]) for c in comunes])
    foto = np.array([_centro(cajas[c]) for c in comunes])
    if np.ptp(rel[:, 0]) < 0.1 and np.ptp(rel[:, 1]) < 0.1:
        return None
    p = preproceso.PROPORCION_ID1
    # Incógnitas: s, bx, by. Filas: una ecuación por coordenada.
    a = np.zeros((2 * len(comunes), 3))
    b = np.zeros(2 * len(comunes))
    a[0::2, 0], a[0::2, 1], b[0::2] = p * rel[:, 0], 1, foto[:, 0]
    a[1::2, 0], a[1::2, 2], b[1::2] = rel[:, 1], 1, foto[:, 1]
    (s, bx, by), *_ = np.linalg.lstsq(a, b, rcond=None)
    if s <= 50:  # tarjeta de menos de 50 px de alto: el ajuste no tiene sentido
        return None

    def foto_a_rel(c: Caja) -> CajaRel:
        return tuple(float(v) for v in ((c[0] - bx) / (s * p), (c[1] - by) / s, c[2] / (s * p), c[3] / s))

    def rel_a_px(c: CajaRel) -> Caja:
        return (round(s * p * c[0] + bx), round(s * c[1] + by), round(s * p * c[2]), round(s * c[3]))

    return Geometria("campos reconocidos (anclas)", img, foto_a_rel, rel_a_px)


def _orientar(g: Geometria, cajas: dict[str, Caja], plant: dict[str, dict] | None) -> Geometria:
    """Decide si la tarjeta enderezada está boca abajo y, si lo está, la gira."""
    rel = {c: g.foto_a_rel(k) for c, k in cajas.items()}
    girar = False
    if plant and _error(rel, plant) is not None:
        girar = _error({c: _girar(v) for c, v in rel.items()}, plant) < _error(rel, plant)
    else:
        # Sin plantilla: en el anverso los apellidos y el nombre van encima de las fechas.
        nombres = [_centro(rel[c])[1] for c in ("apellidos", "nombre") if c in rel]
        fechas = [_centro(rel[c])[1] for c in rel if c.startswith("fecha_")]
        girar = bool(nombres and fechas and np.mean(nombres) > np.mean(fechas))
    if not girar:
        return g
    # La imagen girada ya está derecha: una caja relativa cae en los mismos píxeles.
    a_rel = g.foto_a_rel
    return Geometria(g.metodo, cv2.rotate(g.imagen, cv2.ROTATE_180),
                     lambda c: _girar(a_rel(c)), g.rel_a_px, girada=True, notas=g.notas)


def situar(img: np.ndarray, cajas: dict[str, Caja], plant: dict[str, dict] | None) -> Geometria | None:
    """Sitúa la tarjeta en la foto. cajas: campos ya reconocidos por su etiqueta (anclas)."""
    candidatas: list[Geometria] = []
    esquinas = preproceso.esquinas_apaisadas(img)
    if esquinas is not None:
        candidatas.append(_orientar(_por_homografia(img, esquinas, "bordes de la tarjeta"), cajas, plant))
    if plant:
        g = _por_anclas(img, cajas, plant)
        if g:
            candidatas.append(g)
    h, w = img.shape[:2]
    if not candidatas and 1.4 < max(w, h) / min(w, h) < 1.8:
        esq = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        if h > w:  # foto en vertical: la tarjeta está girada 90°
            esq = np.float32([esq[1], esq[2], esq[3], esq[0]])
        candidatas.append(_orientar(_por_homografia(img, esq, "foto entera (recortada a la tarjeta)"),
                                    cajas, plant))
    if not candidatas:
        return None
    if plant and cajas:
        for g in candidatas:
            g.error_anclas = _error({c: g.foto_a_rel(k) for c, k in cajas.items()}, plant)
    # Los bordes de la tarjeta mandan: las anclas se ajustan a los mismos campos con los que
    # se mide el desvío, así que su desvío siempre sale pequeño aunque estén mal leídas.
    # Solo se prefieren si los bordes no encajan con los campos reconocidos.
    bordes = candidatas[0] if not candidatas[0].metodo.startswith("campos") else None
    anclas = next((g for g in candidatas if g.metodo.startswith("campos")), None)
    if bordes and (anclas is None or bordes.error_anclas is None or bordes.error_anclas <= 0.06):
        mejor = bordes
    else:
        mejor = anclas or bordes
    if mejor.error_anclas is not None and mejor.error_anclas > 0.08:
        mejor.notas.append("los campos reconocidos no encajan bien con la plantilla "
                           f"(desvío medio {mejor.error_anclas:.2f})")
    return mejor


# ── Lectura por zonas ────────────────────────────────────────────────────────

# Margen alrededor de la zona aprendida (fracción de la tarjeta). Los nombres se alargan
# a la derecha: otra persona puede tener un nombre más largo que el de la foto aprendida.
_MARGEN = {"nombre": (0.015, 0.012, 0.30), "apellidos": (0.015, 0.012, 0.30)}
_MARGEN_DEFECTO = (0.015, 0.012, 0.03)  # izquierda, vertical, derecha


# Etiqueta impresa encima de cada campo de texto libre (DNI 4.0 y 3.0).
_ETIQUETA_DE = {"apellidos": ("apellidos", "primer_apellido"), "nombre": ("nombre",)}


def _zona_entre_etiquetas(campo: str, caja: CajaRel, plant: dict[str, dict]) -> CajaRel | None:
    """Nombres y apellidos: desde su etiqueta hasta la siguiente etiqueta de debajo.

    Así la zona cubre una o dos líneas, sea cual sea el número de líneas de la foto con la
    que se aprendió (las etiquetas van impresas siempre en el mismo sitio).
    """
    etq = next((plant[f"etiqueta.{e}"]["caja"] for e in _ETIQUETA_DE.get(campo, ())
                if f"etiqueta.{e}" in plant), None)
    if etq is None:
        return None
    ex, ey, ew, eh = etq
    abajo = [v["caja"] for k, v in plant.items() if k.startswith("etiqueta.")
             and v["caja"][1] > ey + eh * 1.5                      # por debajo
             and v["caja"][0] < ex + max(ew, 0.25) and v["caja"][0] + v["caja"][2] > ex - 0.02]  # misma columna
    x0 = max(0.0, min(ex, caja[0]) - 0.015)
    y0 = ey + eh * 0.9
    if abajo:
        # Hasta justo encima de la etiqueta siguiente; como mínimo, una línea de alto.
        y1 = max(min(v[1] for v in abajo) - 0.004, y0 + caja[3])
    else:
        y1 = caja[1] + caja[3] + 0.012
    x1 = min(1.0, max(caja[0] + caja[2], ex + ew) + 0.30)
    return (x0, y0, x1 - x0, min(1.0, y1) - y0)


def zona(campo: str, caja: CajaRel, plant: dict[str, dict] | None = None) -> CajaRel:
    if plant:
        z = _zona_entre_etiquetas(campo, caja, plant)
        if z:
            return z
    izq, vert, der = _MARGEN.get(campo, _MARGEN_DEFECTO)
    x, y, w, h = caja
    x0, y0 = max(0.0, x - izq), max(0.0, y - vert)
    x1, y1 = min(1.0, x + w + der), min(1.0, y + h + vert)
    return (x0, y0, x1 - x0, y1 - y0)


def _recortar(img: np.ndarray, c: Caja) -> np.ndarray | None:
    x, y, w, h = c
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return img[y0:y1, x0:x1]


def zonas_px(g: Geometria, plant: dict[str, dict]) -> dict[str, Caja]:
    return {c: g.rel_a_px(zona(c, v["caja"], plant)) for c, v in plant.items() if c in anverso.CAMPOS}


def leer(motor, g: Geometria, plant: dict[str, dict]) -> dict:
    """Lee cada zona de la plantilla con un motor y valida el valor según el tipo de campo."""
    t0 = time.perf_counter()
    campos, textos = {}, {}
    for c, caja in zonas_px(g, plant).items():
        recorte = _recortar(g.imagen, caja)
        if recorte is None:
            campos[c], textos[c] = None, "(zona fuera de la foto)"
            continue
        try:
            texto = motor.leer_zona(recorte, anverso.TIPO_CAMPO[c])
        except Exception as e:  # un motor que falla no debe tumbar la comparación
            texto = f"error: {type(e).__name__}: {e}"
        textos[c] = texto
        campos[c] = anverso.leer_campo(c, texto)
    dni = campos.get("dni")
    r = anverso.buscar_dni(dni) if dni else None
    return {
        "campos": {c: campos.get(c) for c in anverso.CAMPOS if c in plant},
        "textos": textos,
        "dni_valido": bool(r and r[1]),
        "encontrados": sum(v is not None for v in campos.values()),
        "ms": round((time.perf_counter() - t0) * 1000),
    }
