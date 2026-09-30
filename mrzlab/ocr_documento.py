"""OCR de una página de documento (A4 escaneado o fotografiado) a líneas con posición.

Dos motores que se complementan, combinados línea a línea:
- Tesseract (`spa`): respeta espacios, tildes y la Ñ, pero en fotos con reflejos o fondos
  decorativos se deja trozos de página.
- RapidOCR (PP-OCR): encuentra casi todas las líneas, pero a veces junta palabras
  («conDNI1.234.567-L») y no conoce la Ñ.
Por cada línea de RapidOCR: si Tesseract la cubre entera, vale la de Tesseract; si no, la de
RapidOCR (con los espacios reparados). Las que solo lee un motor se conservan.
"""
from __future__ import annotations

import os
import re

import cv2
import numpy as np

from . import motores
from .lineas import Linea

# Lado largo de trabajo: ~300 ppp en un A4.
LADO_TESSERACT = 3300
LADO_RAPIDOCR = int(os.getenv("OCR_LADO_DETECCION", "1400"))   # medido: 1800 no lee más y tarda más
ORDEN = tuple(os.getenv("OCR_MOTORES_DOCUMENTO", "tesseract,rapidocr").split(","))
COBERTURA_MIN = 0.9


def _escalar(img: np.ndarray, lado: int) -> tuple[np.ndarray, float]:
    f = lado / max(img.shape[:2])
    f = min(max(f, 0.3), 3.0)
    if abs(f - 1) < 0.05:
        return img, 1.0
    interp = cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, None, fx=f, fy=f, interpolation=interp), f


def _tesseract(img: np.ndarray, pagina: int) -> list[Linea]:
    import pytesseract
    h, w = img.shape[:2]
    red, f = _escalar(img, LADO_TESSERACT)
    gris = cv2.cvtColor(red, cv2.COLOR_BGR2GRAY)
    idioma = motores.Tesseract.idioma_texto()
    datos = pytesseract.image_to_data(gris, lang=idioma, config="--oem 1 --psm 3",
                                      output_type=pytesseract.Output.DICT)
    grupos: dict[tuple, list[int]] = {}
    for i, t in enumerate(datos["text"]):
        if t.strip() and float(datos["conf"][i]) >= 0:
            grupos.setdefault((datos["block_num"][i], datos["par_num"][i], datos["line_num"][i]), []).append(i)
    lineas = []
    for idx in grupos.values():
        # (en el orden de salida de Tesseract, no por la caja: ver _tesseract_lineas)
        # Dentro de una línea de Tesseract puede haber columnas: se parte por huecos grandes.
        trozo: list[int] = []
        for i in idx + [None]:
            if trozo and (i is None or datos["left"][i] - (datos["left"][trozo[-1]] + datos["width"][trozo[-1]])
                          > 2.5 * max(datos["height"][trozo[-1]], 1)):
                x0 = min(datos["left"][j] for j in trozo)
                y0 = min(datos["top"][j] for j in trozo)
                x1 = max(datos["left"][j] + datos["width"][j] for j in trozo)
                y1 = max(datos["top"][j] + datos["height"][j] for j in trozo)
                conf = sum(float(datos["conf"][j]) for j in trozo) / len(trozo) / 100
                lineas.append(Linea(" ".join(datos["text"][j].strip() for j in trozo),
                                    (x0 / f / w, y0 / f / h, (x1 - x0) / f / w, (y1 - y0) / f / h),
                                    pagina, "ocr:tesseract", round(conf, 3)))
                trozo = []
            if i is not None:
                trozo.append(i)
    return lineas


def espaciar(texto: str) -> str:
    """Repara palabras pegadas: «conDNI1.234» → «con DNI 1.234», «de1985» → «de 1985»."""
    texto = re.sub(r"(?<=[a-záéíóúñ])(?=[A-ZÁÉÍÓÚÑ]{2})", " ", texto)
    texto = re.sub(r"(?<=[A-Za-zÁÉÍÓÚÑáéíóúñ])(?=\d)|(?<=\d)(?=[A-Za-zÁÉÍÓÚÑáéíóúñ]{2})", " ", texto)
    texto = re.sub(r",(?=[A-Za-zÁÉÍÓÚÑáéíóúñ])", ", ", texto)
    return texto


def _rapidocr(img: np.ndarray, pagina: int) -> list[Linea]:
    h, w = img.shape[:2]
    red, f = _escalar(img, LADO_RAPIDOCR)
    filas = motores.RapidOCR()._detalle(red)
    return [Linea(espaciar(t), (x / f / w, y / f / h, cw / f / w, ch / f / h), pagina, "ocr:rapidocr",
                  round(c, 3)) for t, (x, y, cw, ch), c in filas]


_LECTORES = {"tesseract": _tesseract, "rapidocr": _rapidocr}


# ── Híbrido: RapidOCR encuentra las líneas; cada una la reconocen los dos motores ──

def _cuadrilatero(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Recorte de una línea (cuadrilátero de la detección) enderezado a rectángulo."""
    tl, tr, br, bl = quad.astype(np.float32)
    ancho = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    alto = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if ancho < 4 or alto < 4:
        return np.zeros((1, 1, 3), np.uint8)
    margen = max(2, alto // 6)
    destino = np.float32([[margen, margen], [ancho + margen, margen], [ancho + margen, alto + margen],
                          [margen, alto + margen]])
    m = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), destino)
    return cv2.warpPerspective(img, m, (ancho + 2 * margen, alto + 2 * margen), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)


ALTO_LINEA = 48        # alto al que se lleva cada recorte (letras de ~35 px)
HUECO = 24


def _tesseract_lineas(recortes: list[np.ndarray]) -> list[tuple[str, float]]:
    """Texto de muchos recortes de línea con UNA sola llamada a Tesseract: se apilan en una
    imagen, uno bajo otro, y cada palabra leída vuelve a su recorte por su altura. Una llamada
    por línea costaría ~1 s cada una (arranque del proceso y carga del modelo)."""
    import pytesseract
    if not recortes:
        return []
    grises = []
    for r in recortes:
        g = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
        f = min(max(ALTO_LINEA / max(g.shape[0], 1), 0.3), 4.0)
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        # Contraste propio de cada línea: en una foto el fondo de cada recorte es de un gris
        # distinto y, pegados en un lienzo blanco, Tesseract los toma por imágenes y no lee nada.
        bajo, alto_ = np.percentile(g, (2, 98))
        if alto_ - bajo > 10:
            g = np.clip((g.astype(np.float32) - bajo) * 255 / (alto_ - bajo), 0, 255).astype(np.uint8)
        grises.append(g)
    ancho = max(g.shape[1] for g in grises) + 2 * HUECO
    alto = sum(g.shape[0] + HUECO for g in grises) + HUECO
    lienzo = np.full((alto, ancho), 255, np.uint8)
    tramos, y = [], HUECO
    for g in grises:
        lienzo[y:y + g.shape[0], HUECO:HUECO + g.shape[1]] = g
        tramos.append((y, y + g.shape[0]))
        y += g.shape[0] + HUECO
    datos = pytesseract.image_to_data(lienzo, lang=motores.Tesseract.idioma_texto(), config="--oem 1 --psm 6",
                                      output_type=pytesseract.Output.DICT)
    palabras: list[list[tuple[int, str, float]]] = [[] for _ in recortes]
    for i, t in enumerate(datos["text"]):
        c = float(datos["conf"][i])
        if not t.strip() or c < 0:
            continue
        centro = datos["top"][i] + datos["height"][i] / 2
        for k, (a, b) in enumerate(tramos):
            if a - HUECO / 2 <= centro < b + HUECO / 2:
                palabras[k].append((datos["left"][i], t.strip(), c))
                break
    # Sin reordenar por la caja: con letra grande en negrita Tesseract a veces da a una palabra
    # una caja desplazada («Doña Castro Pablo» por «Doña Pablo Castro»); su orden de salida
    # (bloque → línea → palabra) es el de lectura.
    return [(" ".join(p for _, p, _ in ps), sum(c for *_, c in ps) / len(ps) / 100) if ps else ("", 0.0)
            for ps in palabras]


def releer(img: np.ndarray, caja: tuple[float, float, float, float]) -> list[str]:
    """Vuelve a leer una línea con los dos motores (para confirmar un código sin dígito de control)."""
    h, w = img.shape[:2]
    x, y, cw, ch = caja
    m = ch * 0.3
    x0, y0 = max(0, int((x - m) * w)), max(0, int((y - m) * h))
    x1, y1 = min(w, int((x + cw + m) * w)), min(h, int((y + ch + m) * h))
    recorte = img[y0:y1, x0:x1]
    if recorte.size == 0:
        return []
    lecturas = []
    if "tesseract" in disponibles():
        try:
            lecturas.append(_tesseract_lineas([recorte])[0][0])
        except Exception:
            pass
    if "rapidocr" in disponibles():
        try:
            lecturas.append(_rapidocr_lineas([recorte])[0][0])
        except Exception:
            pass
    return lecturas


# Por debajo de esta confianza de Tesseract, la línea se lee también con RapidOCR.
CONFIANZA_SIN_SEGUNDA_LECTURA = float(os.getenv("OCR_CONFIANZA_SEGUNDA_LECTURA", "0.8"))
# Líneas de la lectura de página completa que se reutilizan tal cual en el híbrido.
CONFIANZA_REUTILIZAR = 0.9
MAX_RELECTURAS = int(os.getenv("OCR_MAX_RELECTURAS", "40"))


def _rapidocr_lineas(recortes: list[np.ndarray]) -> list[tuple[str, float]]:
    """Solo reconocimiento (sin detección) de muchos recortes, en lote."""
    if not recortes:
        return []
    eng = motores.RapidOCR.cargar()
    try:
        res, _ = eng.text_rec(recortes)
        return [(espaciar(t), float(c)) for t, c in res]
    except Exception:          # otra versión de rapidocr: uno a uno
        salida = []
        for r in recortes:
            rr, _ = eng(r, use_det=False, use_cls=False, use_rec=True)
            salida.append((espaciar(rr[0][0]), float(rr[0][1])) if rr and rr[0] and rr[0][0] else ("", 0.0))
        return salida


def _parecidos(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    a, b = re.sub(r"\W", "", a.upper()), re.sub(r"\W", "", b.upper())
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _ya_leida(caja: tuple[float, float, float, float], previas: list[Linea]) -> list[Linea] | None:
    """Líneas de la lectura de página completa que ya cubren esta caja con buena confianza."""
    x, y, w, h = caja
    cy = y + h / 2
    tapan = [p for p in previas if abs(p.centro_y - cy) < max(p.caja[3], h) * 0.6 and p.x2 > x and p.caja[0] < x + w]
    if not tapan or min(p.confianza for p in tapan) < CONFIANZA_REUTILIZAR:
        return None
    cubierto = sum(min(p.x2, x + w) - max(p.caja[0], x) for p in tapan)
    return sorted(tapan, key=lambda p: p.caja[0]) if cubierto >= COBERTURA_MIN * w else None


def _hibrido(img: np.ndarray, pagina: int, previas: list[Linea] | None = None) -> list[Linea]:
    """Detección de RapidOCR (encuentra casi todas las líneas, también en fotos) y, por línea, el
    texto de Tesseract si coincide con el de RapidOCR (conserva espacios, tildes y Ñ); si no,
    el del motor más seguro. Las líneas que la lectura de página completa (`previas`) ya leyó
    bien se reutilizan sin volver a leerlas."""
    eng = motores.RapidOCR.cargar()
    h, w = img.shape[:2]
    red, f = _escalar(img, LADO_RAPIDOCR)
    cajas, _ = eng(red, use_det=True, use_cls=False, use_rec=False)
    lineas: list[Linea] = []
    quads, recortes = [], []
    for quad in cajas or []:
        quad = np.array(quad, dtype=np.float32) / f
        x0, y0 = quad.min(axis=0)
        x1, y1 = quad.max(axis=0)
        caja = (max(0.0, x0 / w), max(0.0, y0 / h), (x1 - x0) / w, (y1 - y0) / h)
        reutilizables = _ya_leida(caja, previas or [])
        if reutilizables:
            lineas.extend(ln for ln in reutilizables if ln not in lineas)
            continue
        recorte = _cuadrilatero(img, quad)
        if recorte.shape[0] >= 6:
            quads.append(quad)
            recortes.append(recorte)
    try:
        de_tesseract = _tesseract_lineas(recortes)
    except Exception:
        de_tesseract = [("", 0.0)] * len(recortes)
    # RapidOCR solo donde Tesseract duda, en lote y con un tope (cada línea cuesta ~0,15 s):
    # primero las que llevan cifras (NIF, fechas, números de registro), luego las menos seguras.
    dudosas = [i for i, (t, c) in enumerate(de_tesseract) if c < CONFIANZA_SIN_SEGUNDA_LECTURA or len(t) < 2]
    dudosas.sort(key=lambda i: (not re.search(r"\d", de_tesseract[i][0]), de_tesseract[i][1]))
    dudosas = dudosas[:MAX_RELECTURAS]
    de_rapid: dict[int, tuple[str, float]] = dict(zip(dudosas, _rapidocr_lineas([recortes[i] for i in dudosas])))
    for i, (quad, (t_tes, c_tes)) in enumerate(zip(quads, de_tesseract)):
        t_rap, c_rap = de_rapid.get(i, ("", 0.0))
        if t_tes and (i not in de_rapid or _parecidos(t_tes, t_rap) >= 0.8 or c_tes >= c_rap):
            texto, conf, motor, otra = t_tes, max(c_tes, c_rap if _parecidos(t_tes, t_rap) >= 0.8 else 0), "tesseract", t_rap
        else:
            texto, conf, motor, otra = t_rap, c_rap, "rapidocr", t_tes
        if not texto.strip():
            continue
        x0, y0 = quad.min(axis=0)
        x1, y1 = quad.max(axis=0)
        lineas.append(Linea(texto, (max(0.0, x0 / w), max(0.0, y0 / h), (x1 - x0) / w, (y1 - y0) / h), pagina,
                            f"ocr:{motor}", round(conf, 3), otra if otra and otra != texto else None))
    return lineas


def disponibles() -> list[str]:
    por_nombre = {m.nombre: m.disponible()[0] for m in motores.TODOS}
    return [n for n in ORDEN if por_nombre.get(n)]


def _misma_fila(a: Linea, b: Linea) -> bool:
    return abs(a.centro_y - b.centro_y) < max(a.caja[3], b.caja[3]) * 0.6


def combinar(tess: list[Linea], rapid: list[Linea]) -> list[Linea]:
    """Une las lecturas de los dos motores sin duplicar líneas (ver el docstring del módulo)."""
    salida: list[Linea] = []
    usadas: set[int] = set()
    for r in rapid:
        solapan = [i for i, t in enumerate(tess) if _misma_fila(r, t) and t.x2 > r.caja[0] and t.caja[0] < r.x2]
        cubierto = sum(min(tess[i].x2, r.x2) - max(tess[i].caja[0], r.caja[0]) for i in solapan)
        if solapan and cubierto >= COBERTURA_MIN * r.caja[2]:
            for i in solapan:
                if i not in usadas:
                    salida.append(tess[i])
                    usadas.add(i)
        else:
            salida.append(r)
            usadas.update(solapan)
    salida += [t for i, t in enumerate(tess) if i not in usadas]
    return salida


def escaneo_limpio(img: np.ndarray) -> bool:
    """¿Parece un escaneo de escáner (papel blanco uniforme hasta el borde)? Si no, es una foto."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gris.shape
    b = max(4, min(h, w) // 40)
    borde = np.concatenate([gris[:b].ravel(), gris[-b:].ravel(), gris[:, :b].ravel(), gris[:, -b:].ravel()])
    return float(np.median(borde)) >= 215 and float(np.percentile(borde, 10)) >= 170


def _suficiente(lineas: list[Linea]) -> bool:
    """¿La lectura de Tesseract de un escaneo limpio basta por sí sola? Solo se descarta si apenas
    lee nada o casi todo con muy poca confianza (el análisis de página ha fallado): el híbrido
    cuesta varios segundos más por página."""
    utiles = [ln for ln in lineas if len(ln.texto) >= 4]
    if len(utiles) < 5:
        return False
    return sum(ln.confianza for ln in utiles) / len(utiles) >= 0.6


def leer(img: np.ndarray, pagina: int, orden: tuple[str, ...] | None = None,
         es_foto: bool | None = None) -> tuple[list[Linea], str | None]:
    """Líneas de la página y qué motor(es) las leyeron.

    Tesseract (página completa) primero. En fotos, o si Tesseract lee poco o con poca
    confianza, se añade el híbrido (detección de RapidOCR + reconocimiento por línea).
    """
    usar = [n for n in (orden or ORDEN) if n in disponibles()]
    if not usar:
        return [], None
    if "tesseract" not in usar:
        return _LECTORES[usar[0]](img, pagina), usar[0]
    try:
        tess = _tesseract(img, pagina)
    except Exception:
        tess = []
    foto = es_foto if es_foto is not None else not escaneo_limpio(img)
    if "rapidocr" not in usar or (not foto and _suficiente(tess)):
        return tess, "tesseract"
    try:
        hibrido = _hibrido(img, pagina, tess)
    except Exception:
        return tess, "tesseract"
    return anadir_sueltas(hibrido, tess), "tesseract+rapidocr"


def anadir_sueltas(principal: list[Linea], extra: list[Linea]) -> list[Linea]:
    """Todas las líneas de `principal` y las de `extra` que no solapan con ninguna de ellas."""
    sueltas = [e for e in extra
               if not any(_misma_fila(e, p) and e.x2 > p.caja[0] and e.caja[0] < p.x2 for p in principal)]
    return principal + sueltas


def altura_letra_px(lineas: list[Linea], alto_img: int) -> float | None:
    """Mediana del alto de las líneas leídas, en píxeles de la imagen original."""
    altos = sorted(ln.caja[3] * alto_img for ln in lineas if len(ln.texto) >= 4)
    return altos[len(altos) // 2] if altos else None
