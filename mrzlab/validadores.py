"""Validaciones de datos españoles que se repiten en todos los documentos.

NIF, NIE y CIF con su dígito o letra de control; fechas en los formatos habituales («14/03/2025»,
«14 de marzo de 2025»…); importes («600.000,00 €»). Sin OCR: solo texto.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
_LETRA_CONTROL_CIF = "JABCDEFGHI"
# Letra inicial del CIF → tipo de control: «L» letra, «D» dígito, «A» cualquiera de los dos.
_CONTROL_CIF = {**dict.fromkeys("ABEH", "D"), **dict.fromkeys("KPQS", "L"),
                **dict.fromkeys("CDFGJNRUVW", "A")}

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
         "diciembre": 12}


def sin_acentos(texto: str) -> str:
    """Mayúsculas y sin tildes; la Ñ se conserva («ESPAÑA», no «ESPANA»)."""
    texto = texto.upper().replace("Ñ", "\0")
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return texto.replace("\0", "Ñ")


def compactar(texto: str) -> str:
    """Quita espacios, puntos y guiones: «12.345.678-z» → «12345678Z»."""
    return re.sub(r"[\s.\-]", "", texto.upper())


# ── Identificadores ──────────────────────────────────────────────────────────

def nif_valido(valor: str) -> bool:
    """DNI (8 dígitos + letra) o NIE (X/Y/Z + 7 dígitos + letra)."""
    v = compactar(valor)
    if re.fullmatch(r"\d{8}[A-Z]", v):
        return LETRAS_DNI[int(v[:8]) % 23] == v[8]
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", v):
        return LETRAS_DNI[int(str("XYZ".index(v[0])) + v[1:8]) % 23] == v[8]
    return False


def cif_valido(valor: str) -> bool:
    v = compactar(valor)
    if not re.fullmatch(r"[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J]", v):
        return False
    digitos = [int(c) for c in v[1:8]]
    pares = sum(digitos[1::2])
    impares = sum(sum(divmod(d * 2, 10)) for d in digitos[0::2])
    control = (10 - (pares + impares) % 10) % 10
    tipo = _CONTROL_CIF.get(v[0], "A")
    ok_digito, ok_letra = v[8] == str(control), v[8] == _LETRA_CONTROL_CIF[control]
    return {"D": ok_digito, "L": ok_letra}.get(tipo, ok_digito or ok_letra)


# DNI de 7 cifras (los antiguos, «1.234.567-L») se completan con un cero a la izquierda.
_P_NIF = re.compile(r"(?<![A-Z0-9.])([XYZ][\s.\-]?\d{7}|\d{1,2}[\s.]?\d{3}[\s.]?\d{3})[\s\-]?([A-Z])(?![A-Z0-9])")
_P_CIF = re.compile(r"(?<![A-Z0-9])([ABCDEFGHJKLMNPQRSUVW])[\s\-]?(\d{2}[\s.]?\d{3}[\s.]?\d{2})[\s\-]?([0-9A-J])(?![A-Z0-9])")


def buscar_nifs(texto: str, corregir: bool = False) -> list[str]:
    """NIF/NIE con letra correcta, en orden de aparición y sin repetir.

    `corregir`: prueba también las confusiones típicas del OCR en la letra final («0» por «D»,
    «8» por «B»…). Solo se acepta si la letra de control lo confirma; úsese solo con el valor que
    está junto a su etiqueta, nunca buscando por todo el texto.
    """
    vistos: list[str] = []
    for m in _P_NIF.finditer(texto.upper()):
        numero = compactar(m.group(1))
        if numero[0].isdigit():
            numero = numero.zfill(8)
        v = numero + m.group(2)
        if nif_valido(v) and v not in vistos:
            vistos.append(v)
    if corregir and not vistos:
        for m in re.finditer(r"(?<![A-Z0-9])([XYZ]\d{7}|\d{8})([0-9A-Z])(?![A-Z0-9])", compactar(texto)):
            for letra in _CONFUSION_LETRA.get(m.group(2), ""):
                if nif_valido(m.group(1) + letra):
                    vistos.append(m.group(1) + letra)
                    break
    return vistos


def buscar_cifs(texto: str, corregir: bool = False) -> list[str]:
    vistos: list[str] = []
    for m in _P_CIF.finditer(texto.upper()):
        v = compactar("".join(m.groups()))
        if cif_valido(v) and v not in vistos:
            vistos.append(v)
    if corregir and not vistos:
        # «817175365» → «B17175365»: la letra inicial leída como cifra.
        for m in re.finditer(r"(?<![A-Z0-9])([0-9A-Z])(\d{7})([0-9A-J])(?![A-Z0-9])", compactar(texto)):
            for letra in _CONFUSION_INICIAL.get(m.group(1), ""):
                v = letra + m.group(2) + m.group(3)
                if cif_valido(v):
                    vistos.append(v)
                    break
    return vistos


# Confusiones típicas del OCR entre cifras y letras (solo se prueban donde va una letra).
_CONFUSION_LETRA = {"0": "D", "8": "B", "5": "S", "2": "Z", "6": "G", "1": "T", "4": "A", "7": "T", "3": "B"}
_CONFUSION_INICIAL = {"8": "B", "6": "G", "0": "D", "5": "S", "4": "A", "3": "B", "2": "Z"}


# ── Fechas ───────────────────────────────────────────────────────────────────

_P_FECHA_NUM = re.compile(r"(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4}|\d{2})(?!\d)")
# Tolera palabras pegadas por el OCR: «3 DEMAYO DE1985», «15 DE NOVIEMBREDE2010».
_P_FECHA_LETRA = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:DE\s*)?(" + "|".join(m.upper() for m in MESES) + r")\s*(?:DEL|DE)?\s*(\d{4})(?!\d)")


def _fecha(d: int, m: int, a: int) -> date | None:
    if a < 100:
        a += 2000 if a <= date.today().year % 100 + 1 else 1900
    try:
        return date(a, m, d)
    except ValueError:
        return None


def buscar_fechas(texto: str) -> list[tuple[date, int]]:
    """Fechas del texto con su posición, en orden de aparición."""
    t = sin_acentos(texto)
    encontradas: list[tuple[date, int]] = []
    for m in _P_FECHA_NUM.finditer(t):
        f = _fecha(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if f:
            encontradas.append((f, m.start()))
    for m in _P_FECHA_LETRA.finditer(t):
        f = _fecha(int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3)))
        if f:
            encontradas.append((f, m.start()))
    return sorted(encontradas, key=lambda x: x[1])


def leer_fecha(texto: str) -> date | None:
    fechas = buscar_fechas(texto)
    return fechas[0][0] if fechas else None


# ── Importes ─────────────────────────────────────────────────────────────────

_P_IMPORTE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,(\d{1,2}))?\s*(?:€|\bEUROS?\b|\bEUR\b)")


def buscar_importes(texto: str) -> list[float]:
    """Importes en euros con formato español («600.000,00 €», «1.200.000 euros»)."""
    return [float(re.sub(r"[.\s]", "", m.group(1)) + "." + (m.group(2) or "0"))
            for m in _P_IMPORTE.finditer(texto.upper())]
