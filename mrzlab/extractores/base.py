"""Interfaz común de los extractores y utilidades para buscar datos por etiqueta y posición.

Un extractor recibe un `Documento` (líneas con posición, vengan de la capa de texto, de un
formulario o del OCR) y devuelve campos. No decide si el documento vale: solo dice qué pone y
si es coherente consigo mismo. Un dato que no pasa su propia validación (un NIF con la letra
mal) no se devuelve: es mejor un campo vacío que un dato erróneo dado por bueno.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from ..lineas import Linea
from ..validadores import sin_acentos

if TYPE_CHECKING:
    from ..documentos import Documento


@dataclass
class Campo:
    valor: Any
    origen: str
    confianza: float
    pagina: int
    caja: tuple | None = None          # de la línea de donde sale (solo para el laboratorio)

    def a_dict(self) -> dict:
        valor = self.valor.isoformat() if isinstance(self.valor, date) else self.valor
        return {"valor": valor, "origen": self.origen, "confianza": round(self.confianza, 3),
                "pagina": self.pagina}


class Extractor:
    tipo = ""                                  # identificador del endpoint
    nombre = ""                                # nombre legible
    grupo = ""                                 # titulacion | empresa | trabajador
    campos: tuple[str, ...] = ()
    obligatorios: tuple[str, ...] = ()
    # Clasificador: patrón (sobre texto en mayúsculas y sin tildes) → peso.
    claves: dict[str, float] = {}
    # Algunos modelos oficiales traen muchas páginas de instrucciones (el contrato del SEPE, 20).
    max_paginas: int | None = None

    def extraer(self, doc: Documento) -> dict[str, Campo]:
        raise NotImplementedError

    def validar(self, campos: dict[str, Campo], doc: Documento) -> dict[str, bool | None]:
        return {}

    def faltan(self, campos: dict[str, Campo]) -> list[str]:
        """Campos obligatorios que no se han leído."""
        return [c for c in self.obligatorios if c not in campos]

    def describir(self) -> dict:
        return {"tipo": self.tipo, "nombre": self.nombre, "grupo": self.grupo,
                "campos": list(self.campos), "obligatorios": list(self.obligatorios)}


# ── Utilidades ───────────────────────────────────────────────────────────────

def campo(valor: Any, lineas: list[Linea] | Linea | None) -> Campo | None:
    if valor in (None, "", []):
        return None
    if isinstance(lineas, Linea):
        lineas = [lineas]
    lineas = lineas or []
    if not lineas:
        return Campo(valor, "desconocido", 0.0, 0)
    origenes = [ln.origen for ln in lineas]
    return Campo(valor, max(set(origenes), key=origenes.count), min(ln.confianza for ln in lineas),
                 lineas[0].pagina, lineas[0].caja)


def norm(texto: str) -> str:
    return " ".join(sin_acentos(texto).split())


@dataclass
class Hallazgo:
    match: re.Match
    lineas: list[Linea]


def buscar(doc: Documento, patron: str | re.Pattern, desde: int = 0) -> Hallazgo | None:
    """Primer acierto del patrón en el texto del documento (sin tildes, en mayúsculas).

    Busca fila a fila y, si no, en el texto corrido: una frase puede partirse en dos líneas.
    """
    rx = re.compile(patron) if isinstance(patron, str) else patron
    for i, (texto, lineas) in enumerate(doc.filas):
        if i < desde:
            continue
        m = rx.search(texto)
        if m:
            return Hallazgo(m, lineas)
    m = rx.search(doc.texto_norm)
    if m:
        return Hallazgo(m, doc.lineas_en(m.start(), m.end()))
    return None


def valor_tras(doc: Documento, etiqueta: str, valor: str, ventana: int = 250) -> Hallazgo | None:
    """Primer `valor` (regex con un grupo) en los `ventana` caracteres que siguen a la etiqueta,
    en el texto corrido (sirve cuando el dato está en la línea siguiente o en otra columna)."""
    for m in re.finditer(etiqueta, doc.texto_norm):
        trozo = doc.texto_norm[m.end():m.end() + ventana]
        v = re.search(valor, trozo)
        if v:
            inicio = m.end() + v.start()
            return Hallazgo(v, doc.lineas_en(inicio, inicio + len(v.group(0))))
    return None


# «Nº» tal como sale del OCR: «Nº», «N°», «NO», «N'», «N?», «N.», «NUMERO».
NUM = r"(?:NUMERO|\bN\s?[º°O'?*\"9]?\.?)"

# Un título: palabras de al menos dos letras (o «Y»/«E»); se para en el ruido del OCR.
TITULO = r"(?: (?:[A-ZÑ]{2,}|Y|E)(?= |$|[,.;:)\n]))+"


def buscar_todos(doc: Documento, patron: str | re.Pattern) -> list[Hallazgo]:
    rx = re.compile(patron) if isinstance(patron, str) else patron
    return [Hallazgo(m, doc.lineas_en(m.start(), m.end())) for m in rx.finditer(doc.texto_norm)]


# Textos que son etiquetas de formulario, no datos: en una fila de casillas, lo que hay a la
# derecha de una etiqueta suele ser la etiqueta de la casilla siguiente.
ES_ETIQUETA = re.compile(
    r"^(?:(?:C\.?I\.?F|N\.?I\.?F|N\.?I\.?E|D\.?N\.?I)\.?(?:\s*/\s*[A-Z.]{2,5})*\s*:?|"
    r"(?:FECHA|N[º°O]\.?|NUMERO|DOMICILIO|DIRECCION|RAZON\s+SOCIAL|NOMBRE|APELLIDOS|PUESTO|TOMADOR|"
    r"ENTIDAD|POLIZA|NACIONALIDAD|MUNICIPIO|CODIGO\s+POSTAL|PAIS|NIVEL\s+FORMATIVO|FIRMA|D\./DÑA\.)(?![A-Z])[^0-9]{0,45})$")


# Las mismas etiquetas sin espacios: el OCR a veces las pega («NOMBREORAZON SOCIAL»).
_ETIQUETAS_COMPACTAS = ("NOMBREORAZONSOCIAL", "RAZONSOCIAL", "NOMBREYAPELLIDOS", "APELLIDOSYNOMBRE",
                        "TOMADORDELSEGURO", "ENTIDADASEGURADORA", "DIRECCIONDELAOBRA", "FECHADE",
                        "DOMICILIOSOCIAL", "CODIGOPOSTAL", "NIVELFORMATIVO", "CIFNIF", "NIFNIE")


def es_etiqueta(texto: str) -> bool:
    t = norm(texto)
    if ES_ETIQUETA.search(t):
        return True
    compacto = re.sub(r"[^A-ZÑ]", "", t)
    return any(compacto.startswith(e) and len(compacto) <= len(e) + 12 for e in _ETIQUETAS_COMPACTAS)


def tras_etiqueta(doc: Documento, etiqueta: str, valor: str | None = None,
                  max_filas_abajo: float = 3.0, lineas: list[Linea] | None = None,
                  valida: Callable[[str], bool] | None = None) -> tuple[str, list[Linea]] | None:
    """Valor junto a una etiqueta: detrás en la misma línea, a su derecha o justo debajo.

    `valor` (regex) filtra los candidatos: el primero que lo cumpla, y se devuelve lo que casa.
    `valida` (opcional) descarta los que no pasan una comprobación (un NIF con su letra).
    Sirve para formularios (el dato en la casilla bajo el título) y para textos «Etiqueta: dato».
    `lineas` limita la búsqueda a una parte del documento (una sección).
    """
    todas = lineas if lineas is not None else doc.lineas
    rx_et = re.compile(etiqueta)
    rx_val = re.compile(valor) if valor else None

    def acepta(texto: str) -> str | None:
        texto = texto.strip(" :.-\t|[]_'`\",;!¡")   # «|», «[»: bordes de casilla leídos por el OCR
        if sum(c.isalnum() for c in texto) < 2 or es_etiqueta(texto):
            return None
        if rx_val is not None:
            m = rx_val.search(norm(texto))
            texto = (m.group(1) if m.groups() else m.group(0)) if m else None
        return texto if texto and (valida is None or valida(texto)) else None

    for ln in todas:
        t = norm(ln.texto)
        m = rx_et.search(t)
        if not m:
            continue
        # 1. En la misma línea, detrás de la etiqueta.
        resto = acepta(t[m.end():])
        if resto:
            return resto, [ln]
        # 2. A la derecha, en la misma fila; 3. debajo, solapando en horizontal.
        alto = max(ln.caja[3], 0.008)
        derecha = [o for o in todas if o is not ln and o.pagina == ln.pagina
                   and abs(o.centro_y - ln.centro_y) < alto * 0.7 and o.caja[0] >= ln.x2 - alto]
        debajo = [o for o in todas if o is not ln and o.pagina == ln.pagina
                  and 0 < o.caja[1] - ln.caja[1] <= alto * (max_filas_abajo + 1)
                  and o.caja[0] < ln.x2 + 0.15 and o.x2 > ln.caja[0] - 0.02]
        grupos = [sorted(derecha, key=lambda o: o.caja[0]),
                  sorted(debajo, key=lambda o: (o.caja[1], abs(o.caja[0] - ln.caja[0])))]
        # Casilla de formulario: etiqueta sin «:» y el dato justo debajo, alineado a la izquierda.
        # Lo que haya a su derecha suele ser la etiqueta de la casilla vecina.
        if not t.rstrip().endswith(":") and any(abs(o.caja[0] - ln.caja[0]) < 0.03
                                                and o.caja[1] - ln.y2 < alto * 2.5 for o in debajo):
            grupos.reverse()
        for grupo in grupos:
            for o in grupo:
                if rx_et.search(norm(o.texto)):
                    continue
                # Si lo que leyó un motor no encaja, se prueba lo que leyó el otro.
                v = acepta(o.texto) or (acepta(o.alternativa) if o.alternativa else None)
                if v:
                    return v, [o]
    return None


# Nombres de persona: palabras de letras (con tildes y Ñ), partículas y coma entre apellidos y nombre.
# Las palabras que suelen seguir al nombre en una frase («… con NIF», «… nacido») no cuentan.
_PALABRA = r"(?!(?:CON|NIF|DNI|NIE|CUYO|CUYA|QUE|HA|EN|MAYOR|TITULAR|PROVISTO|PROVISTA|NACIDO|NACIDA)\b)[A-ZÑ][A-ZÑ'\-]+"
NOMBRE = rf"({_PALABRA}(?:,?\s+(?:DE\s+LA\s+|DE\s+LOS\s+|DEL\s+|DE\s+|Y\s+)?{_PALABRA}){{1,6}})"


# Palabras de etiquetas y textos de formulario: si aparecen, no es un nombre de persona.
_NO_NOMBRE = {"FECHA", "NACIMIENTO", "NIF", "NIE", "DNI", "DOMICILIO", "MUNICIPIO", "NACIONALIDAD", "CODIGO",
              "POSTAL", "PAIS", "NIVEL", "FORMATIVO", "EMPRESA", "FIRMA", "DATOS", "SOCIAL", "CUENTA",
              "REGIMEN", "CALIDAD", "CONCEPTO", "ACTIVIDAD", "RAZON", "CENTRO", "TRABAJO", "SEGURIDAD",
              "CURSO", "PREVENCION", "RIESGOS", "LABORALES", "TITULO", "UNIVERSIDAD", "MASTER", "TECNICO",
              "SUPERIOR", "CERTIFICADO", "CERTIFICA", "REGISTRO", "SERVICIO", "PERSONA", "TRABAJADORA",
              "TRABAJADOR", "RESPONSABLE", "PROYECTO", "GRUPO", "NOMBRE", "APELLIDOS", "TELEFONO", "CORREO",
              "LEY", "ARTICULO", "DECRETO", "REAL", "CONVENIO", "ORDEN", "RESOLUCION", "SOCIEDAD", "SL", "SA"}
_PARTICULAS = {"DE", "LA", "DEL", "LOS", "LAS", "Y", "E", "EL"}


def limpiar_nombre(nombre: str) -> str | None:
    """«GOMEZ  RUIZ ,LUIS» → «GOMEZ RUIZ, LUIS». None si no parece un nombre."""
    n = re.sub(r"\s*,\s*", ", ", " ".join(nombre.split())).strip(" ,.")
    palabras = [p for p in re.split(r"[\s,]+", n) if p]
    if not 2 <= len(palabras) <= 7 or any(len(p) > 20 for p in palabras):
        return None
    if re.search(r"\d", n) or _NO_NOMBRE & {sin_acentos(p) for p in palabras}:
        return None
    # Al menos dos palabras que no sean partículas: «DE LA LEY» no es un nombre.
    if sum(sin_acentos(p) not in _PARTICULAS for p in palabras) < 2:
        return None
    return n
