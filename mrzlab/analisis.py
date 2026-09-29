"""Análisis de una imagen: localización, calidad y lectura con cada motor.

Lo comparten la página (app.py) y el modo por lotes (lote.py).
"""
from __future__ import annotations

import io
import time

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import anverso, calidad, deteccion, motores, mrz, plantilla, preproceso


class ImagenInvalida(ValueError):
    pass


def decodificar(datos: bytes) -> np.ndarray:
    """Abre la foto respetando la orientación EXIF (las fotos de móvil suelen venir giradas)."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(datos))).convert("RGB")
    except Exception as e:
        raise ImagenInvalida("No se pudo abrir la imagen (formatos: JPG, PNG, WEBP)") from e
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# Orden del resultado «combinado»: primero el motor más rápido; el siguiente solo si el
# anterior no consigue una MRZ válida.
ORDEN_COMBINADO = ["tesseract", "rapidocr"]


def _es_valida(intento: motores.Intento) -> bool:
    r = mrz.leer(intento.lineas)
    return r is not None and r.valido


def _mejor_lectura(intentos: list[motores.Intento]) -> tuple[dict | None, str | None]:
    mejor, mejor_desc, mejor_p = None, None, -1
    for intento in intentos:
        r = mrz.leer(intento.lineas)
        if r is None:
            continue
        p = sum(r.controles.values()) + (100 if r.valido else 0)
        if p > mejor_p:
            mejor, mejor_desc, mejor_p = r, intento.descripcion, p
    return (mejor.a_dict() if mejor else None), mejor_desc


class _Variantes:
    """Versiones de la foto a probar: la original y, si hace falta, la tarjeta enderezada.

    La enderezada se calcula una sola vez y solo si algún motor la necesita.
    """

    def __init__(self, img: np.ndarray, caja):
        self._original = ("foto original", img, caja)
        self._enderezada = None
        self._calculada = False

    def _calcular(self):
        self._calculada = True
        tarjeta = preproceso.enderezar_tarjeta(self._original[1])
        if tarjeta is None:
            return
        caja = deteccion.localizar_mrz(tarjeta)
        if caja is not None and caja[1] + caja[3] / 2 < tarjeta.shape[0] / 2:
            # La MRZ va abajo: si ha quedado arriba, la tarjeta está boca abajo.
            tarjeta = cv2.rotate(tarjeta, cv2.ROTATE_180)
            caja = deteccion.localizar_mrz(tarjeta)
        self._enderezada = ("tarjeta enderezada", tarjeta, caja)

    def __iter__(self):
        yield self._original
        if not self._calculada:
            self._calcular()
        if self._enderezada is not None:
            yield self._enderezada


def _leer_con_motor(m: motores.Motor, variantes: _Variantes) -> dict:
    intentos: list[motores.Intento] = []
    ms, errores = 0.0, []
    for nombre_var, img_var, caja_var in variantes:
        lectura = m.leer(img_var, caja_var, _es_valida)
        ms += lectura.ms
        if lectura.error:
            errores.append(f"{nombre_var}: {lectura.error}")
        intentos += [motores.Intento(f"{nombre_var} · {i.descripcion}", i.lineas, i.cajas)
                     for i in lectura.intentos]
        if any(_es_valida(i) for i in lectura.intentos):
            break
    mejor, desc = _mejor_lectura(intentos)
    return {
        "motor": m.nombre,
        "disponible": True,
        "ms": round(ms),
        "error": None if mejor else ("; ".join(errores) or None),
        "intento": desc,
        "texto_bruto": [{"descripcion": i.descripcion, "lineas": i.lineas} for i in intentos],
        "mrz": mejor,
    }


def _combinado(resultados: list[dict]) -> dict | None:
    """Tesseract y, si no valida, RapidOCR: lo que costaría en producción usarlos en cadena."""
    por_motor = {r["motor"]: r for r in resultados if r.get("disponible")}
    if not all(n in por_motor for n in ORDEN_COMBINADO):
        return None
    ms, elegido = 0, None
    for n in ORDEN_COMBINADO:
        r = por_motor[n]
        ms += r["ms"]
        if r["mrz"] and r["mrz"]["valido"]:
            elegido = r
            break
    if elegido is None:  # ninguno valida: se muestra la lectura con más controles correctos
        elegido = max((por_motor[n] for n in ORDEN_COMBINADO),
                      key=lambda r: sum(r["mrz"]["controles"].values()) if r["mrz"] else -1)
    return {
        "motor": "combinado",
        "disponible": True,
        "ms": ms,
        "error": None,
        "intento": f"{elegido['motor']} · {elegido['intento']}",
        "texto_bruto": elegido["texto_bruto"],
        "mrz": elegido["mrz"],
    }


LADOS = ("auto", "anverso", "reverso")


def _texto_y_anverso(m: motores.Motor, img: np.ndarray, con_anverso: bool) -> dict:
    """Todo el texto que ve el motor en la foto entera y, si toca, los campos del anverso."""
    t0 = time.perf_counter()
    try:
        filas = m.texto(img)
    except Exception as e:  # un motor que falla no debe tumbar la comparación
        return {"lineas": [], "ms": round((time.perf_counter() - t0) * 1000),
                "error": f"{type(e).__name__}: {e}", "anverso": None}
    ms = round((time.perf_counter() - t0) * 1000)
    lineas = [anverso.Linea(t, c, conf) for t, c, conf in filas]
    return {
        "lineas": [{"texto": ln.texto, "caja": ln.caja,
                    "confianza": None if ln.confianza is None else round(ln.confianza, 2)}
                   for ln in lineas],
        "ms": ms,
        "error": None,
        "anverso": anverso.extraer(lineas) if con_anverso else None,
    }


def _decidir_lado(resultados: list[dict]) -> str:
    disponibles = [r for r in resultados if r.get("disponible")]
    if any(r.get("mrz") and r["mrz"]["valido"] for r in disponibles):
        return "reverso"
    if any((r.get("texto") or {}).get("anverso") and anverso.parece_anverso(r["texto"]["anverso"])
           for r in disponibles):
        return "anverso"
    # Sin MRZ válida ni etiquetas del anverso: se mira si al menos hay algo con forma de MRZ.
    if any(r.get("mrz") for r in disponibles):
        return "reverso"
    return "desconocido"


def analizar(img: np.ndarray, umbrales: dict, pedidos: set[str] | None = None,
             lado: str = "auto", con_texto: bool = True,
             imagenes: dict | None = None) -> tuple[dict, calidad.Evaluacion]:
    """lado: «reverso» solo lee la MRZ, «anverso» solo los campos impresos, «auto» ambos.

    con_texto: además lee todo el texto de la foto entera con cada motor (lo que se enseña
    en la página y de donde salen los campos del anverso).
    imagenes: si se pasa, se rellena con imágenes intermedias para la página (la tarjeta
    enderezada con las zonas de la plantilla).
    """
    if lado not in LADOS:
        raise ValueError(f"lado debe ser uno de {LADOS}")
    buscar_mrz = lado != "anverso"
    con_texto = con_texto or lado != "reverso"

    caja = deteccion.localizar_mrz(img) if buscar_mrz else None
    evaluacion = calidad.evaluar(img, umbrales, caja)
    variantes = _Variantes(img, caja)

    resultados = []
    for m in motores.TODOS:
        if pedidos and m.nombre not in pedidos:
            continue
        ok, nota = m.disponible()
        if not ok:
            resultados.append({"motor": m.nombre, "disponible": False, "error": nota})
            continue
        r = _leer_con_motor(m, variantes) if buscar_mrz else {
            "motor": m.nombre, "disponible": True, "ms": 0, "error": None, "intento": None,
            "texto_bruto": [], "mrz": None}
        if con_texto:
            r["texto"] = _texto_y_anverso(m, img, con_anverso=lado != "reverso")
        resultados.append(r)

    combinado = _combinado(resultados) if buscar_mrz else None
    if combinado:
        resultados.append(combinado)

    lado_final = lado if lado != "auto" else _decidir_lado(resultados)
    salida = {
        "lado": lado_final,
        "lado_pedido": lado,
        "dimensiones": {"ancho": img.shape[1], "alto": img.shape[0]},
        "caja_mrz": caja,
        "calidad": evaluacion.a_dict(),
        "motores": resultados,
    }
    if lado_final == "anverso" and con_texto:
        salida.update(_por_posicion(img, resultados, imagenes))
    return salida, evaluacion


def _por_posicion(img: np.ndarray, resultados: list[dict], imagenes: dict | None) -> dict:
    """Plantilla de posiciones: propone posiciones para aprender y lee cada zona por motor."""
    plant = plantilla.cargar()
    # Anclas: los campos que mejor ha reconocido algún motor por su etiqueta.
    lecturas = [r["texto"]["anverso"] for r in resultados
                if r.get("disponible") and (r.get("texto") or {}).get("anverso")]
    mejor = max(lecturas, key=lambda a: (a["dni_valido"], a["encontrados"]), default=None)
    cajas = {c: tuple(k) for c, k in (mejor or {}).get("cajas", {}).items()}
    cajas.update({f"etiqueta.{c}": tuple(k) for c, k in (mejor or {}).get("cajas_etiquetas", {}).items()})

    g = plantilla.situar(img, cajas, plant)
    if g is None:
        return {"plantilla": {"hay": plant is not None, "geometria": None,
                              "aviso": "No se ha podido situar la tarjeta en la foto (sin bordes "
                                       "claros ni campos reconocidos suficientes)."}}
    info = {
        "hay": plant is not None,
        "geometria": {"metodo": g.metodo, "girada": g.girada, "notas": g.notas,
                      "error_anclas": None if g.error_anclas is None else round(g.error_anclas, 3)},
        # Para aprender: posición relativa de cada campo reconocido. Solo con los bordes de
        # la tarjeta (con anclas se deduciría de la propia plantilla).
        "propuesta": {c: [round(v, 4) for v in g.foto_a_rel(k)] for c, k in cajas.items()}
        if not g.metodo.startswith("campos") else None,
    }
    if plant:
        por_nombre = {m.nombre: m for m in motores.TODOS}
        for r in resultados:
            if r.get("disponible") and (r.get("texto") or {}).get("anverso"):
                r["texto"]["anverso"]["posicion"] = plantilla.leer(por_nombre[r["motor"]], g, plant)
    if imagenes is not None:
        imagenes["tarjeta"] = (g.imagen, plantilla.zonas_px(g, plant) if plant else {},
                               {c: g.rel_a_px(v) for c, v in (info["propuesta"] or {}).items()})
    return {"plantilla": info}
