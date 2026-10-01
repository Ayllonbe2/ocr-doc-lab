"""Datos que aparecen en casi todos los documentos: titular, su NIF, empresa y fechas."""
from __future__ import annotations

import re
from datetime import date

from ..lineas import Linea
from ..validadores import buscar_cifs, buscar_fechas, buscar_nifs, cif_valido, nif_valido
from .base import NOMBRE, Campo, Hallazgo, buscar, campo, es_etiqueta, limpiar_nombre, norm, tras_etiqueta

# «D./DÑA.», «DON», «DOÑA», «D.», «DÑA.», «D/DÑA», «D./Dª.»
_TRATAMIENTO = r"(?:\bD\.?\s*/\s*D(?:Ñ|N)?A?\.?|\bD\.?\s*/\s*Dª\.?|\bDON(?:A|ÑA)?\b|\bDOÑA\b|\bD(?:Ñ|N)A\.|\bD\.)"
# Lo que suele ir justo detrás del nombre en una frase.
_TRAS_NOMBRE = (r"(?=\s*,?\s*(?:CON\b|PROVIST|TITULAR|MAYOR\b|NACID|DE\s+NACIONALIDAD|CUYO|"
                r"N\.?I\.?F|D\.?N\.?I|N\.?I\.?E|HA\s|QUE\s|EN\s+CALIDAD|$))")

# Al principio de la línea: «… riesgos al trabajador» en una frase no es una etiqueta.
_ETIQUETAS_NOMBRE = (r"^(?:NOMBRE\s+Y\s+APELLIDOS|APELLIDOS\s+Y\s+NOMBRE|APELLIDOS,\s*NOMBRE|"
                     r"TITULAR|ALUMNO/?A?|TRABAJADOR/?A?|PERSONA\s+TRABAJADORA|INTERESADO/?A?)\b\s*:?")


def titular(doc, desde: int = 0, unico: bool = False) -> tuple[Campo | None, Hallazgo | None]:
    """Nombre de la persona a la que se refiere el documento.

    `unico`: solo si hay un único «D./Dña. NOMBRE» (si hay varios, no se sabe cuál es).
    """
    patron = _TRATAMIENTO + r"\s*" + NOMBRE + _TRAS_NOMBRE
    if unico:
        # Fila a fila: el «$» del patrón es el final de la fila.
        nombres = {limpiar_nombre(m.group(1)) for texto, _ in doc.filas for m in re.finditer(patron, texto)} - {None}
        if len(nombres) > 1:
            return None, None
    h = buscar(doc, patron, desde)
    if h:
        nombre = limpiar_nombre(h.match.group(1))
        if nombre:
            return campo(nombre, h.lineas), h
    r = tras_etiqueta(doc, _ETIQUETAS_NOMBRE, NOMBRE)
    if r:
        nombre = limpiar_nombre(r[0])
        if nombre:
            return campo(nombre, r[1]), None
    return None, None


_ETIQ_NIF = r"(?:N\.?\s?I\.?\s?F\.?|D\.?\s?N\.?\s?I\.?|N\.?\s?I\.?\s?E\.?|DOCUMENTO\s+NACIONAL\s+DE\s+IDENTIDAD)"


def nif_cerca(doc, hallazgo: Hallazgo | None) -> Campo | None:
    """NIF/NIE del titular: el que va tras «NIF/DNI» junto a su nombre; si no, el único del texto."""
    if hallazgo is not None:
        pos = doc.texto_norm.find(hallazgo.match.group(0))
        if pos >= 0:
            ventana = doc.texto_norm[pos:pos + len(hallazgo.match.group(0)) + 160]
            m = re.search(_ETIQ_NIF + r"[^A-Z0-9]{0,12}([XYZ0-9][0-9.\s\-]{6,12}[A-Z])", ventana)
            if m:
                nifs = buscar_nifs(m.group(1))
                if nifs:
                    return campo(nifs[0], doc.lineas_en(pos, pos + m.end()))
    # Junto a su etiqueta se admite la letra final mal leída («971871300» → «97187130D»),
    # siempre que la letra de control lo confirme.
    r = tras_etiqueta(doc, r"\b" + _ETIQ_NIF + r"(?:\s*/\s*N\.?I\.?E\.?)?\s*:?",
                      r"([XYZ]?[0-9][0-9.\s\-]{6,11}[0-9A-Z])", valida=es_nif)
    if r:
        return campo(buscar_nifs(r[0], corregir=True)[0], r[1])
    todos = buscar_nifs(doc.texto_norm)
    if len(todos) == 1:
        h = buscar(doc, re.escape(todos[0][:4]))
        return campo(todos[0], h.lineas if h else None)
    return None      # ninguno o varios sin forma de saber cuál es: mejor vacío


def nif_mal_escrito(doc) -> bool:
    """¿Hay algo con forma de NIF junto a su etiqueta pero con la letra incorrecta?"""
    for m in re.finditer(_ETIQ_NIF + r"[^A-Z0-9]{0,12}((?:[XYZ]\d{7}|\d{8})[A-Z])\b", doc.texto_norm):
        if not nif_valido(m.group(1)):
            return True
    return False


ETIQ_ID_EMPRESA = (r"\b(?:C\.?\s?I\.?\s?F\.?|N\.?\s?I\.?\s?F\.?)(?:\s*/\s*N\.?I\.?F\.?)?(?:\s*/\s*N\.?I\.?E\.?)?"
                   r"(?:\s+(?:DE\s+LA\s+EMPRESA|EMPRESA))?\s*:?")
VALOR_ID = r"([A-Z]?[0-9][0-9.\s\-]{6,10}[0-9A-Z])"


def id_de(texto: str) -> str | None:
    """CIF o NIF de un valor leído junto a su etiqueta (con las confusiones típicas corregidas
    solo si el control lo confirma)."""
    return (buscar_cifs(texto) or buscar_nifs(texto) or buscar_cifs(texto, corregir=True)
            or buscar_nifs(texto, corregir=True) or [None])[0]


def es_nif(texto: str) -> bool:
    return bool(buscar_nifs(texto, corregir=True))


def identificador_empresa(doc, lineas: list[Linea] | None = None) -> Campo | None:
    """CIF (o NIF de un autónomo) de la empresa: tras su etiqueta o, si no hay etiqueta, el único
    CIF del texto. Si hay etiqueta pero su valor no es un identificador válido, vacío."""
    r = tras_etiqueta(doc, ETIQ_ID_EMPRESA, VALOR_ID, lineas=lineas, valida=lambda t: id_de(t) is not None)
    if r:
        return campo(id_de(r[0]), r[1])
    if lineas is not None or any(re.search(ETIQ_ID_EMPRESA, norm(ln.texto)) for ln in doc.lineas):
        return None
    cifs = buscar_cifs(doc.texto_norm)
    if len(cifs) == 1:
        h = buscar(doc, re.escape(cifs[0][:4]))
        return campo(cifs[0], h.lineas if h else None)
    return None


def identificador_valido(valor: str | None) -> bool | None:
    if not valor:
        return None
    return cif_valido(valor) or nif_valido(valor)


_ETIQ_RAZON = (r"\b(?:RAZON\s+SOCIAL|NOMBRE\s+O\s+RAZON\s+SOCIAL(?:\s+DE\s+LA\s+EMPRESA)?|DENOMINACION(?:\s+SOCIAL)?|"
               r"EMPRESA|TOMADOR(?:\s+DEL\s+SEGURO)?|APELLIDOS\s+Y\s+NOMBRE\s+O\s+RAZON\s+SOCIAL)\b\s*:?")
_SOCIEDAD = r"([A-Z0-9Ñ][A-Z0-9Ñ&.,'\- ]{2,70}?\b(?:S\.?\s?L\.?\s?U?\.?|S\.?\s?A\.?\s?U?\.?|S\.?\s?COOP\.?|S\.?\s?L\.?\s?L\.?|C\.?\s?B\.?)(?=[\s,.;]|$))"


def razon_social(doc, etiqueta: str = _ETIQ_RAZON, lineas: list[Linea] | None = None) -> Campo | None:
    """Como `identificador_empresa`: con `lineas`, solo en esa sección y sin buscar fuera de ella."""
    r = tras_etiqueta(doc, etiqueta, lineas=lineas)
    if r and parece_razon_social(r[0]):
        return campo(" ".join(r[0].split()).strip(" ,.:"), r[1])
    # Si la etiqueta está pero su dato no se lee bien, vacío: cualquier otra sociedad del texto
    # (la aseguradora, el servicio de prevención…) sería un dato erróneo.
    if lineas is not None or any(re.search(etiqueta, norm(ln.texto)) for ln in doc.lineas):
        return None
    h = buscar(doc, _SOCIEDAD)
    return campo(" ".join(h.match.group(1).split()), h.lineas) if h else None


# Formas jurídicas con las que puede acabar una razón social.
_FORMA_JURIDICA = r"(?:S\.?\s?L\.?\s?(?:U|L|N\.?E)?|S\.?\s?A\.?\s?U?|S\.?\s?COOP\.?(?:\s?AND|\s?V)?|C\.?\s?B|S\.?\s?C|A\.?\s?I\.?\s?E)\.?"


def parece_razon_social(valor: str) -> bool:
    """Dos palabras de letras al menos, o una forma jurídica: descarta basura y etiquetas sueltas.

    Un final de una o dos letras que no es una forma jurídica («… PRUEBA S», «… PRUEBA SI») es
    casi siempre «SL» o «SA» mal leído: sin saber cuál, el valor no se da por bueno.
    """
    t = norm(valor)
    if not 4 <= len(t) <= 90 or es_etiqueta(t):
        return False
    palabras = t.replace(",", " ").split()
    ultima = re.sub(r"[^A-Z0-9Ñ]", "", palabras[-1]) if palabras else ""
    if len(palabras) >= 3 and len(ultima) <= 2 and not re.search(rf"\b{_FORMA_JURIDICA}$", t):
        return False
    letras = re.findall(r"[A-ZÑ]{2,}", t)
    return len(letras) >= 2 or bool(re.search(rf"\b{_FORMA_JURIDICA}$", t))


def fecha_en(doc, patron: str, filas: int = 2) -> Campo | None:
    """Primera fecha tras el patrón, en esa fila o en las `filas` siguientes.

    En las filas de debajo, solo en la columna de la etiqueta: con «Entrada en vigor» y
    «Vencimiento» lado a lado y sus fechas debajo, la primera fecha de la fila es la de la otra.
    """
    for i, (texto, lineas) in enumerate(doc.filas):
        m = re.search(patron, texto)
        if not m:
            continue
        fechas = buscar_fechas(texto[m.end():])
        if fechas:
            return campo(fechas[0][0], lineas)
        etiqueta = next((ln for ln in lineas if re.search(patron, norm(ln.texto))), None)
        for j in range(i + 1, min(i + 1 + filas, len(doc.filas))):
            debajo = doc.filas[j][1]
            if etiqueta is not None:
                debajo = [ln for ln in debajo if ln.caja[0] < etiqueta.x2 and ln.x2 > etiqueta.caja[0]]
            fechas = buscar_fechas(" ".join(ln.texto for ln in debajo))
            if fechas:
                return campo(fechas[0][0], debajo)
    return None


_EXPEDICION = (r"\b(?:FECHA\s+DE\s+(?:EXPEDICION|EMISION)|EXPEDID[OA]\s+(?:EN|EL)|EMITID[OA]\s+(?:EN|EL)|"
               r"DADO\s+EN|EXPIDE|FIRMADO\s+EN|FECHA\s*:)")


def _fechas_ajenas(texto: str) -> set[int]:
    """Posiciones donde empiezan fechas que no son la del documento: la de nacimiento («nacido el
    día …») y las del propio modelo de formulario («Fecha aprobación», «Revisión», «Versión»)."""
    patron = (r"(?:NACID[OA]\s+(?:EL\s+)?(?:DIA\s+)?|FECHA\s+(?:DE\s+)?(?:APROB|REVIS|VERSI|EDICI|ACTUALIZ)\w*\W{0,4}|"
              r"\b(?:REVISION|VERSION|EDICION)\s*:?\s*\w{0,3}\W{0,4})")
    return {m.end() for m in re.finditer(patron, texto)}


def fecha_documento(doc, hoy: date | None = None) -> Campo | None:
    """Fecha de expedición: tras su etiqueta; si no hay etiqueta, la más reciente que no sea
    futura ni de nacimiento. Si hay etiqueta pero su fecha no se lee, vacío: cualquier otra
    fecha del documento sería un dato erróneo."""
    hoy = hoy or date.today()
    f = fecha_en(doc, _EXPEDICION)
    if f and f.valor <= hoy:
        return f
    if re.search(r"\b(?:DADO\s+EN|FECHA\s+DE\s+(?:EXPEDICION|EMISION)|EXPEDID[OA]\s+(?:EN|EL))", doc.texto_norm):
        return None
    ajenas = _fechas_ajenas(doc.texto_norm)
    candidatas = [(d, pos) for d, pos in buscar_fechas(doc.texto_norm)
                  if date(1950, 1, 1) <= d <= hoy and not any(0 <= pos - n <= 3 for n in ajenas)]
    if not candidatas:
        return None
    d, pos = max(candidatas, key=lambda x: x[0])
    return campo(d, doc.lineas_en(pos, pos + 10))


def meses_validez(doc, por_defecto: int) -> tuple[int, bool]:
    """Meses de validez que dice el propio documento; si no lo dice, el valor por defecto."""
    numeros = {"UNO": 1, "UN": 1, "TRES": 3, "SEIS": 6, "DOCE": 12, "DIECIOCHO": 18, "VEINTICUATRO": 24}
    h = buscar(doc, r"VALIDEZ\s+(?:DE|POR|DURANTE)\s+(?:UN\s+PERIODO\s+DE\s+)?(\d{1,2}|UNO|UN|TRES|SEIS|DOCE|DIECIOCHO|VEINTICUATRO)\s+MES")
    if h:
        v = h.match.group(1)
        return (int(v) if v.isdigit() else numeros[v]), True
    return por_defecto, False


def sumar_meses(d: date, meses: int) -> date:
    m = d.month - 1 + meses
    a, m = d.year + m // 12, m % 12 + 1
    dias = [31, 29 if a % 4 == 0 and (a % 100 or a % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(a, m, min(d.day, dias[m - 1]))
