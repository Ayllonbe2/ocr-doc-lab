"""Pruebas de autenticidad de un documento, antes y además de leerlo.

- Firma electrónica PAdES (pyHanko, MIT): si la firma es íntegra y cubre todo el PDF, el
  contenido no se ha tocado desde que se firmó. Sin conexión: no se descargan CRL/OCSP ni se
  comprueba la cadena de confianza (se dice en la respuesta).
- Código Seguro de Verificación (CSV) o Código Electrónico de Autenticidad (CEA): se devuelve para
  comprobarlo en la sede electrónica del organismo emisor.
- QR: se decodifica con OpenCV (ya es dependencia).
- Metadatos: editores de imagen o de PDF en línea, y guardados posteriores sin firma.
"""
from __future__ import annotations

import io
import logging
import re

import cv2
import numpy as np

from .validadores import sin_acentos

_P_CSV = re.compile(
    r"(?:\bCODIGO\s+SEGURO\s+DE\s+VERIFICACION|\bC\.?\s?S\.?\s?V(?![A-Z]))\.?\s*(?:\(CSV\))?\s*[:.]?\s*"
    r"([A-Z0-9]{4,}(?:[ \-][A-Z0-9]{4,}){0,5})")
_P_CEA = re.compile(
    r"(?:\bCODIGO\s+ELECTRONICO\s+DE\s+AUTENTICIDAD|\bC\.?E\.?A(?![A-Z]))\.?\s*(?:\(CEA\))?\s*[:.]?\s*"
    r"([A-Z0-9]{4,}(?:[ \-][A-Z0-9]{3,}){0,6})")

# Programas con los que se retoca un documento. Solo avisan: no prueban nada por sí solos.
_EDITORES = ("photoshop", "gimp", "paint", "canva", "ilovepdf", "smallpdf", "sejda", "pdfescape",
             "pdffiller", "sodapdf", "foxit phantompdf", "pdf-xchange editor", "inkscape")


def codigos_verificacion(texto: str) -> list[dict]:
    t = sin_acentos(texto)
    salida = []
    for tipo, patron in (("CSV", _P_CSV), ("CEA", _P_CEA)):
        for m in patron.finditer(t):
            codigo = re.sub(r"[\s\-]", "", m.group(1))
            # Un código real es largo y lleva números; evita «CSV: VERIFICAR EN LA SEDE».
            if len(codigo) >= 8 and re.search(r"\d", codigo) and all(c["codigo"] != codigo for c in salida):
                salida.append({"tipo": tipo, "codigo": codigo})
    return salida


def codigos_confirmados(doc) -> tuple[list[dict], int]:
    """Códigos de verificación de un documento leído, solo los seguros, y cuántos se descartan.

    Un CSV no tiene dígito de control: si sale del OCR, un «5» leído como «S» daría un código
    erróneo. Por eso, en las líneas de OCR, se relee la línea con los dos motores y solo vale si
    todas las lecturas contienen el mismo código.
    """
    from . import ocr_documento
    buenos, descartados = [], 0
    for c in codigos_verificacion(doc.texto):
        codigo = c["codigo"]
        linea = next((ln for ln in doc.lineas if codigo[:6] in re.sub(r"[\s\-]", "", sin_acentos(ln.texto))), None)
        if linea is None or not linea.origen.startswith("ocr:"):
            buenos.append({**c, "origen": linea.origen if linea else "desconocido"})
            continue
        img = doc.imagen(linea.pagina)
        lecturas = ([linea.texto] + ([linea.alternativa] if linea.alternativa else [])
                    + (ocr_documento.releer(img, linea.caja) if img is not None else []))
        compactas = [re.sub(r"[\s\-]", "", sin_acentos(t)) for t in lecturas if t]
        if len(compactas) >= 2 and all(codigo in t for t in compactas):
            buenos.append({**c, "origen": linea.origen})
        else:
            descartados += 1
    return buenos, descartados


def qrs(imagenes: list[np.ndarray]) -> list[str]:
    detector = cv2.QRCodeDetector()
    leidos: list[str] = []
    for img in imagenes:
        try:
            ok, textos, _, _ = detector.detectAndDecodeMulti(img)
        except cv2.error:
            continue
        for t in textos if ok else []:
            if t and t not in leidos:
                leidos.append(t)
    return leidos


def firmas(datos: bytes) -> list[dict]:
    """Firmas PAdES del PDF. Lista vacía si no tiene o no se pueden leer."""
    if b"/ByteRange" not in datos:          # sin firma: no hace falta analizar el PDF
        return []
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError:
        return []
    # Sin raíces de confianza, pyHanko registra como error que el certificado no es de confianza:
    # es lo esperado aquí (no se comprueba la cadena), así que no se muestra.
    logging.getLogger("pyhanko").setLevel(logging.CRITICAL)
    try:
        lector = PdfFileReader(io.BytesIO(datos), strict=False)
        if lector.encrypted:
            lector.decrypt("")
        firmadas = list(lector.embedded_signatures)
    except Exception:
        return []
    salida = []
    for sig in firmadas:
        try:
            # Sin raíces de confianza y sin descargas: solo integridad criptográfica y cobertura.
            estado = validate_pdf_signature(sig, ValidationContext(allow_fetching=False, trust_roots=[]))
            cubre_todo = getattr(estado.coverage, "name", "") == "ENTIRE_FILE"
            cambios = getattr(estado, "modification_level", None)
            nivel_cambios = getattr(cambios, "name", None)
            salida.append({
                "integra": bool(estado.intact and estado.valid),
                "cubre_todo": cubre_todo,
                # Tras firmar solo se admiten sellos de tiempo o firmas nuevas (LTA_UPDATES).
                "modificado_tras_firmar": not cubre_todo and nivel_cambios not in ("NONE", "LTA_UPDATES"),
                "firmante": estado.signing_cert.subject.human_friendly if estado.signing_cert else None,
                "fecha": estado.signer_reported_dt.isoformat() if estado.signer_reported_dt else None,
                "confianza_comprobada": False,
            })
        except Exception as e:
            salida.append({"integra": False, "cubre_todo": False, "modificado_tras_firmar": None,
                           "firmante": None, "fecha": None, "confianza_comprobada": False,
                           "error": type(e).__name__})
    return salida


def avisos_metadatos(meta: dict, firmas_pdf: list[dict]) -> list[str]:
    avisos = []
    programas = f"{meta.get('producer', '')} {meta.get('creator', '')}".lower()
    for editor in _EDITORES:
        if editor in programas:
            avisos.append(f"El PDF se ha generado o editado con «{editor}»")
            break
    if meta.get("revisiones", 1) > 1 and not firmas_pdf:
        avisos.append("El PDF se ha modificado después de crearse (guardados posteriores sin firma)")
    for f in firmas_pdf:
        if not f["integra"]:
            avisos.append("La firma electrónica no es válida: el documento puede estar alterado")
        elif f["modificado_tras_firmar"]:
            avisos.append("El PDF se ha modificado después de firmarse")
    return avisos
