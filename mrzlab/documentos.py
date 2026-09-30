"""Leer un documento (PDF o imagen) y extraer los campos de un tipo. Todo en memoria.

Tres caminos, decididos por página:
- PDF con capa de texto → texto y campos de formulario, sin OCR (exacto y rápido);
- PDF escaneado → render a 300 ppp → orientación e inclinación → OCR;
- foto → buscar la hoja y enderezarla → orientación e inclinación → OCR.

El mismo extractor recibe las líneas de cualquiera de los tres.
"""
from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import os

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import autenticidad, calidad, clasificador, ocr_documento, pagina as prep, pdf
from .extractores import REGISTRO
from .extractores.base import Campo, norm
from .lineas import Linea, Pagina, orden_lectura

logger = logging.getLogger(__name__)
# pdfminer, en DEBUG, vuelca en el log el texto del PDF que va leyendo: datos personales. Nunca
# por debajo de WARNING, aunque la aplicación suba el nivel general.
for _ruidoso in ("pdfminer", "pdfplumber", "pyhanko", "PIL"):
    logging.getLogger(_ruidoso).setLevel(logging.WARNING)

MAX_PAGINAS = int(os.getenv("OCR_MAX_PAGINAS", "5"))
# Páginas escaneadas que se pasan por OCR como mucho (cada una cuesta segundos de CPU). Las
# digitales no cuentan: leer su texto es inmediato.
MAX_PAGINAS_OCR = int(os.getenv("OCR_MAX_PAGINAS_OCR", "5"))
PPP_OCR = 300
PPP_VISTA = 150        # para QR y firmas en páginas digitales
UMBRALES = Path(os.getenv("UMBRALES", Path(__file__).resolve().parent.parent / "umbrales.yaml"))

# Estados de la lectura
COMPLETA = "COMPLETA"                 # están todos los campos obligatorios
INCOMPLETA = "INCOMPLETA"             # faltan campos y la calidad es buena → revisión manual
ILEGIBLE = "ILEGIBLE"                 # faltan campos y la calidad es mala → pedir otra foto/escaneo
OTRO_DOCUMENTO = "OTRO_DOCUMENTO"     # parece claramente otro tipo de documento


class DocumentoInvalido(ValueError):
    def __init__(self, motivo: str, mensaje: str):
        super().__init__(mensaje)
        self.motivo = motivo      # vacio | formato | corrupto | cifrado | demasiadas_paginas


@lru_cache(maxsize=1)
def _umbrales() -> dict:
    return calidad.cargar_umbrales(UMBRALES)


@dataclass
class Documento:
    origen: str                                   # pdf_digital | pdf_escaneado | pdf_mixto | imagen
    paginas: list[Pagina]
    metadatos: dict = field(default_factory=dict)
    firmas: list[dict] = field(default_factory=list)
    datos_pdf: bytes | None = field(default=None, repr=False)

    def __post_init__(self):
        self.lineas: list[Linea] = orden_lectura([ln for p in self.paginas for ln in p.lineas])
        # Filas (líneas a la misma altura) con su texto normalizado, y posición en el texto corrido.
        self.filas: list[tuple[str, list[Linea]]] = []
        for ln in self.lineas:
            ultima = self.filas[-1][1] if self.filas else None
            if (ultima and ultima[0].pagina == ln.pagina
                    and abs(ultima[0].centro_y - ln.centro_y) < max(ultima[0].caja[3], ln.caja[3]) * 0.5):
                ultima.append(ln)
            else:
                self.filas.append(("", [ln]))
        self.filas = [(norm("  ".join(ln.texto for ln in ls)), ls) for _, ls in self.filas]
        self._inicios: list[int] = []
        partes, pos = [], 0
        for texto, _ in self.filas:
            self._inicios.append(pos)
            partes.append(texto)
            pos += len(texto) + 1
        self.texto_norm = "\n".join(partes)
        self.texto = "\n".join("  ".join(ln.texto for ln in ls) for _, ls in self.filas)

    def lineas_en(self, inicio: int, fin: int) -> list[Linea]:
        salida: list[Linea] = []
        for i, pos in enumerate(self._inicios):
            if pos > fin:
                break
            if pos + len(self.filas[i][0]) >= inicio:
                salida.extend(self.filas[i][1])
        return salida

    def imagen(self, numero: int) -> np.ndarray | None:
        """Imagen de la página (la del OCR o, en las digitales, un render a 150 ppp)."""
        p = self.paginas[numero - 1]
        if p.imagen is None and self.datos_pdf is not None:
            p.imagen = pdf.renderizar(self.datos_pdf, numero - 1, PPP_VISTA)
        return p.imagen


# ── Lectura ──────────────────────────────────────────────────────────────────

def _decodificar_imagen(datos: bytes) -> np.ndarray:
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(datos))).convert("RGB")
    except Exception as e:
        raise DocumentoInvalido("formato", "Formato no admitido (PDF, JPG, PNG o WEBP)") from e
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _pagina_ocr(img: np.ndarray, numero: int, tipo: str) -> Pagina:
    if not ocr_documento.disponibles():
        raise DocumentoInvalido("sin_motores", "No hay ningún motor OCR disponible para leer páginas escaneadas")
    img, info = prep.preparar(img, es_foto=(tipo == "foto"))
    lineas, motor = ocr_documento.leer(img, numero, es_foto=(tipo == "foto") or None)
    altura = ocr_documento.altura_letra_px(lineas, img.shape[0])
    ev = calidad.evaluar_documento(img, _umbrales(), altura)
    cal = {"veredicto": ev.veredicto, "avisos": [a["mensaje"] for a in ev.avisos],
           "metricas": ev.zonas["documento"], "preparacion": info}
    if not lineas:
        cal["veredicto"] = "rechazar"
        cal["avisos"].append("No se ha podido leer texto en la página")
    return Pagina(numero, tipo, lineas, img, cal, motor)


def leer(datos: bytes, max_paginas: int = MAX_PAGINAS) -> Documento:
    if not datos:
        raise DocumentoInvalido("vacio", "El fichero está vacío")
    if not pdf.es_pdf(datos):
        return Documento("imagen", [_pagina_ocr(_decodificar_imagen(datos), 1, "foto")])
    try:
        documento_pdf = pdf.abrir(datos)
    except pdf.PdfInvalido as e:
        raise DocumentoInvalido(e.motivo, str(e)) from e
    try:
        n = len(documento_pdf)
        if n > max_paginas:
            raise DocumentoInvalido("demasiadas_paginas", f"El PDF tiene {n} páginas (máximo {max_paginas})")
        formularios = pdf.lineas_formularios(datos)
        paginas: list[Pagina] = []
        con_ocr = 0
        for i in range(n):
            texto = pdf.lineas_capa_texto(documento_pdf, i, i + 1)
            formulario = formularios.get(i + 1, [])
            digital = pdf.es_digital(texto + formulario)
            # Plantilla digital con el contenido escaneado encima: se lee también la imagen.
            mixta = (digital and sum(len(ln.texto) for ln in texto) < 300
                     and pdf.area_imagenes(documento_pdf, i) >= 0.6)
            if (not digital or mixta) and con_ocr >= MAX_PAGINAS_OCR:
                paginas.append(Pagina(i + 1, "sin_leer", texto + formulario))
                continue
            if digital and not mixta:
                paginas.append(Pagina(i + 1, "digital", texto + formulario))
                continue
            con_ocr += 1
            ocr = _pagina_ocr(pdf.renderizar(documento_pdf, i, PPP_OCR), i + 1, "escaneada")
            # Los campos de formulario también cuentan; la capa de texto de una página escaneada,
            # solo si es mixta (en una escaneada suele ser basura).
            ocr.lineas = (texto if mixta else []) + formulario + ocr.lineas
            ocr.tipo = "mixta" if mixta else "escaneada"
            paginas.append(ocr)
        meta = pdf.metadatos(documento_pdf, datos)
    finally:
        documento_pdf.close()
    tipos = {p.tipo for p in paginas} - {"sin_leer"}
    origen = ("pdf_digital" if tipos == {"digital"} else
              "pdf_escaneado" if tipos == {"escaneada"} else "pdf_mixto")
    return Documento(origen, paginas, meta, autenticidad.firmas(datos), datos)


# ── Proceso completo ─────────────────────────────────────────────────────────

@dataclass
class Resultado:
    tipo: str
    lectura: str
    origen: str
    paginas: int
    campos: dict[str, Campo]
    validaciones: dict[str, bool | None]
    clasificacion: dict
    autenticidad: dict
    calidad: dict
    avisos: list[str]
    tiempo_ms: int

    def a_dict(self) -> dict:
        return {"tipo": self.tipo, "lectura": self.lectura, "origen": self.origen,
                "paginas": self.paginas, "campos": {k: c.a_dict() for k, c in self.campos.items()},
                "validaciones": self.validaciones, "clasificacion": self.clasificacion,
                "autenticidad": self.autenticidad, "calidad": self.calidad, "avisos": self.avisos,
                "tiempo_ms": self.tiempo_ms}


def _calidad_documento(doc: Documento) -> dict:
    con_ocr = [p for p in doc.paginas if p.calidad]
    if not con_ocr:
        return {"veredicto": "apta", "avisos": []}
    orden = {"apta": 0, "riesgo": 1, "rechazar": 2}
    peor = max(con_ocr, key=lambda p: orden[p.calidad["veredicto"]])
    avisos: list[str] = []
    for p in con_ocr:
        avisos += [a for a in p.calidad["avisos"] if a not in avisos]
    return {"veredicto": peor.calidad["veredicto"], "avisos": avisos,
            "motores": sorted({p.motor for p in con_ocr if p.motor})}


def _autenticidad(doc: Documento) -> dict:
    imagenes = []
    for p in doc.paginas:
        try:
            img = doc.imagen(p.numero)
        except Exception:
            img = None
        if img is not None:
            imagenes.append(img)
    codigos, descartados = autenticidad.codigos_confirmados(doc)
    avisos = autenticidad.avisos_metadatos(doc.metadatos, doc.firmas)
    if descartados:
        avisos.append("Hay un código de verificación que no se ha podido leer con seguridad: compruébalo a mano")
    return {"firmas": doc.firmas,
            "codigos_verificacion": [{"tipo": c["tipo"], "codigo": c["codigo"]} for c in codigos],
            "qr": autenticidad.qrs(imagenes),
            "avisos": avisos}


def decidir_lectura(ext, campos: dict[str, Campo], clas: dict, cal: dict) -> str:
    if not clas["coincide"] and clas["tipo_detectado"] not in (None, ext.tipo):
        return OTRO_DOCUMENTO
    # Sin campos obligatorios (documentos libres) lo único que confirma el tipo es la clasificación.
    confirmado = clas["coincide"] or bool(ext.obligatorios)
    if confirmado and not ext.faltan(campos):
        return COMPLETA
    return ILEGIBLE if cal["veredicto"] != "apta" else INCOMPLETA


def procesar(datos: bytes, tipo: str, max_paginas: int | None = None) -> Resultado:
    """Lee el documento y extrae los campos del tipo indicado. Lanza KeyError si el tipo no existe."""
    return procesar_con_documento(datos, tipo, max_paginas)[0]


def procesar_con_documento(datos: bytes, tipo: str, max_paginas: int | None = None) -> tuple[Resultado, Documento]:
    """Como `procesar`, devolviendo también lo leído (líneas e imágenes): para el laboratorio."""
    ext = REGISTRO[tipo]
    t0 = time.perf_counter()
    doc = leer(datos, max_paginas or ext.max_paginas or MAX_PAGINAS)
    clas = clasificador.clasificar(doc.texto_norm, solicitado=tipo)
    campos = {k: v for k, v in ext.extraer(doc).items() if v is not None and k in ext.campos}
    validaciones = ext.validar(campos, doc)
    cal = _calidad_documento(doc)
    aut = _autenticidad(doc)
    lectura = decidir_lectura(ext, campos, clas, cal)
    avisos = list(aut["avisos"])
    if lectura == OTRO_DOCUMENTO:
        avisos.append(f"Parece otro documento ({clas['tipo_detectado']}), no {tipo}")
    faltan = ext.faltan(campos)
    if faltan and lectura != OTRO_DOCUMENTO:
        avisos.append("No se han encontrado: " + ", ".join(faltan))
    sin_leer = sum(p.tipo == "sin_leer" for p in doc.paginas)
    if sin_leer:
        avisos.append(f"{sin_leer} página(s) escaneada(s) sin leer: se ha alcanzado el límite de OCR")
    ms = round((time.perf_counter() - t0) * 1000)
    # Solo tipo, resultado y tiempo: nunca datos del documento.
    logger.info("documento tipo=%s lectura=%s origen=%s paginas=%d ms=%d",
                tipo, lectura, doc.origen, len(doc.paginas), ms)
    return Resultado(tipo, lectura, doc.origen, len(doc.paginas), campos, validaciones, clas,
                     aut, cal, avisos, ms), doc


def max_paginas_admitidas() -> int:
    return max([MAX_PAGINAS] + [e.max_paginas or 0 for e in REGISTRO.values()])


def clasificar(datos: bytes, max_paginas: int | None = None) -> dict:
    t0 = time.perf_counter()
    doc = leer(datos, max_paginas or max_paginas_admitidas())
    clas = clasificador.clasificar(doc.texto_norm)
    clas.update(origen=doc.origen, paginas=len(doc.paginas),
                tiempo_ms=round((time.perf_counter() - t0) * 1000))
    logger.info("clasificar tipo=%s origen=%s ms=%d", clas["tipo_detectado"], doc.origen, clas["tiempo_ms"])
    return clas
