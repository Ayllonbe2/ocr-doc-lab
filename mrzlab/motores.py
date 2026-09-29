"""Motores OCR detrás de una interfaz común.

Cada motor devuelve uno o varios «intentos» (listas de líneas leídas, en orden de
lectura). El parser de la MRZ elige después el mejor intento.

- rapidocr:  modelos PP-OCR de PaddleOCR ejecutados con ONNX Runtime (Apache 2.0).
- tesseract: Tesseract 5 sobre el recorte de la MRZ, con el modelo «mrz» si está
             (ojo: ese modelo sale del repositorio de FastMRZ, AGPL-3.0; ver «Licencias» en el README).
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from collections.abc import Callable, Iterator

import cv2
import numpy as np

from . import preproceso

Caja = tuple[int, int, int, int]
CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
TESSDATA_MRZ = os.getenv("TESSDATA_MRZ", str(Path(__file__).resolve().parent.parent / "tessdata"))
# Hilos por motor. En el modo por lotes con varios procesos se fija a 1 para no saturar la CPU.
HILOS: int | None = None


def limitar_hilos(n: int) -> None:
    global HILOS
    HILOS = n
    os.environ["OMP_THREAD_LIMIT"] = str(n)  # Tesseract
    cv2.setNumThreads(n)


@dataclass
class Intento:
    descripcion: str
    lineas: list[str]
    cajas: list[Caja | None] = field(default_factory=list)


@dataclass
class Lectura:
    intentos: list[Intento]
    ms: float
    error: str | None = None


def _recorte(img: np.ndarray, caja: Caja) -> np.ndarray:
    x, y, w, h = caja
    return img[y:y + h, x:x + w]


def _escalar_altura_linea(img: np.ndarray, objetivo: int = 48) -> tuple[np.ndarray, float]:
    """Escala el recorte de la MRZ para que cada línea mida ~objetivo px."""
    h = img.shape[0]
    f = objetivo * 3 / max(h, 1)
    f = min(max(f, 0.5), 4.0)
    return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC), f


def _con_borde(img: np.ndarray, px: int = 12) -> np.ndarray:
    """Margen alrededor del recorte: los OCR leen mal el texto pegado al borde."""
    return cv2.copyMakeBorder(img, px, px, px, px, cv2.BORDER_REPLICATE)


class Motor:
    nombre = ""
    licencia = ""

    def disponible(self) -> tuple[bool, str | None]:
        raise NotImplementedError

    def _leer(self, img: np.ndarray, caja: Caja | None) -> Iterator[Intento]:
        """Genera intentos de lectura, del más barato/probable al más costoso."""
        raise NotImplementedError

    def texto(self, img: np.ndarray) -> list[tuple[str, Caja, float | None]]:
        """Todo el texto de la foto entera: (línea, caja, confianza 0–1), en orden de lectura."""
        raise NotImplementedError

    def leer_zona(self, recorte: np.ndarray, tipo: str) -> str:
        """Texto de un recorte pequeño (la zona de un campo); tipo: ver anverso.TIPO_CAMPO."""
        raise NotImplementedError


    def leer(self, img: np.ndarray, caja: Caja | None,
             es_valida: Callable[[Intento], bool] | None = None) -> Lectura:
        """Ejecuta los intentos; si se pasa es_valida, para en el primero que la cumpla."""
        t0 = time.perf_counter()
        intentos: list[Intento] = []
        try:
            for intento in self._leer(img, caja):
                intentos.append(intento)
                if es_valida and es_valida(intento):
                    break
            return Lectura(intentos, (time.perf_counter() - t0) * 1000)
        except Exception as e:  # un motor que falla no debe tumbar la comparación
            return Lectura(intentos, (time.perf_counter() - t0) * 1000,
                           f"{type(e).__name__}: {e}")


class RapidOCR(Motor):
    nombre = "rapidocr"
    licencia = "Apache-2.0 (modelos PP-OCR de PaddleOCR)"
    _motor = None

    def disponible(self):
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True, None
        except ImportError as e:
            return False, str(e)

    def _detalle(self, img: np.ndarray) -> list[tuple[str, Caja, float]]:
        """(texto, caja, confianza) de cada línea, en orden de lectura."""
        if RapidOCR._motor is None:
            import onnxruntime
            from rapidocr_onnxruntime import RapidOCR as _R
            onnxruntime.disable_telemetry_events()  # además de ORT_DISABLE_TELEMETRY
            hilos = {"intra_op_num_threads": HILOS, "inter_op_num_threads": HILOS} if HILOS else {}
            RapidOCR._motor = _R(**hilos)
        resultado, _ = RapidOCR._motor(img)
        if not resultado:
            return []
        filas = []
        for puntos, texto, conf in resultado:
            pts = np.array(puntos, dtype=np.float32)
            x, y = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            filas.append(((y + y2) / 2, x, texto, (int(x), int(y), int(x2 - x), int(y2 - y)),
                          float(conf)))
        filas.sort(key=lambda f: (round(f[0] / 10), f[1]))
        return [(f[2], f[3], f[4]) for f in filas]

    def _ocr(self, img: np.ndarray) -> tuple[list[str], list[Caja]]:
        filas = self._detalle(img)
        return [f[0] for f in filas], [f[1] for f in filas]

    def leer_zona(self, recorte, tipo):
        img = _con_borde(recorte)
        # Los nombres pueden ocupar dos líneas: ahí hace falta el detector.
        filas = self._detalle(img) if tipo == "nombre" else []
        if filas:
            return " ".join(f[0] for f in filas)
        # Una sola línea: solo reconocimiento. El detector, en recortes tan pequeños, a veces
        # parte el texto en trozos que se solapan («123456 5678Z»).
        if RapidOCR._motor is None:
            self._detalle(img)  # carga el motor
        res, _ = RapidOCR._motor(img, use_det=False, use_cls=False)
        return " ".join(r[0] for r in res or [] if r and r[0])

    def texto(self, img):
        h, w = img.shape[:2]
        f = min(1.0, 1600 / max(h, w))
        red = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
        return [(t, (round(cx / f), round(cy / f), round(cw / f), round(ch / f)), conf)
                for t, (cx, cy, cw, ch), conf in self._detalle(red)]

    def _leer(self, img, caja):
        if caja is not None:
            rec, f = _escalar_altura_linea(_recorte(img, caja))
            lineas, cajas = self._ocr(rec)
            x0, y0 = caja[0], caja[1]
            cajas = [(x0 + round(cx / f), y0 + round(cy / f), round(cw / f), round(ch / f))
                     for cx, cy, cw, ch in cajas]
            yield Intento("recorte MRZ", lineas, cajas)
        # Foto entera (reducida): no depende de que el localizador acierte.
        h, w = img.shape[:2]
        f = min(1.0, 1600 / max(h, w))
        red = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
        lineas, cajas = self._ocr(red)
        cajas = [(round(cx / f), round(cy / f), round(cw / f), round(ch / f))
                 for cx, cy, cw, ch in cajas]
        yield Intento("foto entera", lineas, cajas)
        if caja is not None:
            # Contraste local (sombras, luz desigual) sobre el recorte.
            gris = preproceso.clahe(cv2.cvtColor(rec, cv2.COLOR_BGR2GRAY))
            lineas, _ = self._ocr(cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR))
            yield Intento("recorte MRZ con CLAHE", lineas)


class Tesseract(Motor):
    nombre = "tesseract"
    licencia = "Apache-2.0"

    def _idioma(self) -> tuple[str, str | None]:
        if (Path(TESSDATA_MRZ) / "mrz.traineddata").is_file():
            return "mrz", TESSDATA_MRZ
        return "eng", None

    def disponible(self):
        try:
            import pytesseract  # noqa: F401
        except ImportError as e:
            return False, str(e)
        if shutil.which("tesseract") is None:
            return False, "binario tesseract no instalado"
        idioma, _ = self._idioma()
        return True, None if idioma == "mrz" else "sin mrz.traineddata: se usa «eng»"

    def _leer(self, img, caja):
        import pytesseract
        if caja is None:
            raise RuntimeError("no se localizó la MRZ (Tesseract necesita el recorte)")
        objetivo = 48
        rec, _ = _escalar_altura_linea(_recorte(img, caja), objetivo)
        gris = cv2.cvtColor(rec, cv2.COLOR_BGR2GRAY)
        idioma, tessdata = self._idioma()
        config = f"--oem 1 --psm 6 -c tessedit_char_whitelist={CHARSET}"
        if tessdata:
            config += f' --tessdata-dir "{tessdata}"'
        otsu = lambda g: cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        con_clahe = preproceso.clahe(gris)
        variantes = (
            ("recorte binarizado", lambda: otsu(gris)),
            ("umbral adaptativo", lambda: preproceso.umbral_adaptativo(gris, objetivo)),
            ("CLAHE + binarizado", lambda: otsu(con_clahe)),
            ("recorte en gris", lambda: gris),
        )
        for desc, preparar in variantes:
            texto = pytesseract.image_to_string(preparar(), lang=idioma, config=config)
            yield Intento(f"{desc} ({idioma})", [t for t in texto.splitlines() if t.strip()])

    @staticmethod
    def idioma_texto() -> str:
        """Modelo para el texto general (anverso): castellano si está instalado."""
        import pytesseract
        try:
            return "spa" if "spa" in pytesseract.get_languages(config="") else "eng"
        except Exception:
            return "eng"

    # Por tipo de campo: caracteres permitidos y modo de página (7 = una línea, 6 = bloque).
    _ZONAS = {
        "fecha": ("0123456789 ", 7),
        "digitos": ("0123456789", 7),
        "dni": ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ", 7),
        "alfanumerico": ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ", 7),
        "sexo": ("MF", 8),
        "letras": ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 7),
        "nombre": ("ABCDEFGHIJKLMNOPQRSTUVWXYZÑÁÉÍÓÚÜ -", 6),
    }

    def leer_zona(self, recorte, tipo):
        import pytesseract
        permitidos, psm = self._ZONAS[tipo]
        gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
        # Letras de ~40 px de alto: el recorte de una línea se lleva a ~70 px.
        lineas = 2 if tipo == "nombre" else 1
        f = min(max(70 * lineas / max(gris.shape[0], 1), 0.5), 4.0)
        gris = _con_borde(cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC), 20)
        # En nombres se vetan los dígitos en vez de limitar las letras: con una lista de
        # permitidos, Tesseract se come los espacios («MARIADELCARMEN»).
        filtro = ("tessedit_char_blacklist=0123456789" if tipo == "nombre"
                  else f"tessedit_char_whitelist={permitidos.replace(' ', '')}")
        config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1 -c {filtro}"
        leido = ""
        for preparar in (lambda g: g, lambda g: cv2.threshold(
                g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]):
            leido = " ".join(pytesseract.image_to_string(
                preparar(gris), lang=self.idioma_texto(), config=config).split())
            if leido:
                break
        return leido

    def texto(self, img):
        import pytesseract
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Tesseract lee mejor con letras de ~30 px: se lleva el lado largo a ~2000 px.
        f = min(max(2000 / max(gris.shape[:2]), 0.5), 3.0)
        gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        datos = pytesseract.image_to_data(gris, lang=self.idioma_texto(), config="--oem 1 --psm 11",
                                          output_type=pytesseract.Output.DICT)
        # Con psm 11 cada palabra va suelta: se agrupan en líneas por cercanía.
        palabras = []
        for i, t in enumerate(datos["text"]):
            conf = float(datos["conf"][i])
            if not t.strip() or conf < 0:
                continue
            x, y, w, h = (round(datos[k][i] / f) for k in ("left", "top", "width", "height"))
            palabras.append([t.strip(), (x, y, w, h), conf / 100])
        palabras.sort(key=lambda p: (p[1][1] + p[1][3] / 2, p[1][0]))
        lineas: list[list] = []
        for p in palabras:
            x, y, w, h = p[1]
            for ln in lineas:
                lx, ly, lw, lh = ln[1]
                misma_fila = abs((y + h / 2) - (ly + lh / 2)) < max(h, lh) * 0.5
                if misma_fila and 0 <= x - (lx + lw) < max(h, lh) * 1.5:
                    ln[0] += " " + p[0]
                    x2, y2 = max(lx + lw, x + w), max(ly + lh, y + h)
                    ln[1] = (lx, min(ly, y), x2 - lx, y2 - min(ly, y))
                    ln[2].append(p[2])
                    break
            else:
                lineas.append([p[0], p[1], [p[2]]])
        lineas.sort(key=lambda ln: (round((ln[1][1] + ln[1][3] / 2) / 15), ln[1][0]))
        return [(t, c, sum(cs) / len(cs)) for t, c, cs in lineas]


TODOS: list[Motor] = [RapidOCR(), Tesseract()]
