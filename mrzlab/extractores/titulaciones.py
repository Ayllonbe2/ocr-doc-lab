"""Titulaciones de prevención: diploma de 60 h de la construcción (FLC), Técnico Superior en
Prevención de Riesgos Profesionales (FP) y Máster Universitario en PRL."""
from __future__ import annotations

import re
from datetime import date

from .base import NUM, TITULO, Campo, Extractor, buscar, campo, tras_etiqueta, valor_tras
from .comunes import fecha_documento, nif_cerca, nif_mal_escrito, titular


def _cortar_titulo(titulo: str) -> str:
    """El título acaba antes de «por la Universidad…», «con carácter oficial…», etc."""
    titulo = " ".join(titulo.split())
    return re.split(r"\s(?:POR\s+LA|POR\s+EL|CON\s+CARACTER|CON\s+VALIDEZ|EXPIDE|QUE\s+LE|EN\s+EL\s+CENTRO)\b",
                    titulo)[0].strip(" ,")

CCAA = ("ANDALUCIA", "ARAGON", "ASTURIAS", "ILLES BALEARS", "ISLAS BALEARES", "CANARIAS", "CANTABRIA",
        "CASTILLA-LA MANCHA", "CASTILLA - LA MANCHA", "CASTILLA LA MANCHA", "CASTILLA Y LEON", "CATALUNYA",
        "CATALUÑA", "COMUNITAT VALENCIANA", "COMUNIDAD VALENCIANA", "EXTREMADURA", "GALICIA",
        "COMUNIDAD DE MADRID", "REGION DE MURCIA", "NAVARRA", "PAIS VASCO", "EUSKADI", "LA RIOJA",
        "CEUTA", "MELILLA")


def _fecha_no_futura(campos: dict[str, Campo], nombre: str = "fecha") -> bool | None:
    return campos[nombre].valor <= date.today() if nombre in campos else None


def _comunes(doc) -> tuple[dict[str, Campo], object]:
    tit, h = titular(doc)
    return {"titular": tit, "nif": nif_cerca(doc, h), "fecha": fecha_documento(doc)}, h


class Flc60h(Extractor):
    tipo = "flc_60h"
    nombre = "Curso de 60 horas de prevención en construcción (nivel básico)"
    grupo = "titulacion"
    campos = ("titular", "nif", "horas", "numero_registro", "numero_curso", "entidad", "fecha")
    obligatorios = ("titular", "nif", "horas", "fecha")
    claves = {r"FUNDACION LABORAL DE LA CONSTRUCCION": 3, r"CONVENIO (?:GENERAL|COLECTIVO)[A-Z ]{0,20}CONSTRUCCION": 2,
              r"\b60\s*(?:,00\s*)?H(?:ORAS)?\b": 1.5, r"NIVEL BASICO": 1.5, r"PLENO APROVECHAMIENTO": 1,
              r"PREVENCION": 0.5, r"TARJETA PROFESIONAL DE LA CONSTRUCCION": 1, r"\bDIPLOMA\b": 0.5}

    # Horas: solo en su contexto (duración del curso o su título), nunca el primer número suelto.
    _HORAS = (r"DURACION(?:\s+TOTAL)?\s+DE\s+(\d{2,3})(?:[,.]0+)?\s*HORAS",
              r"CURSO\s+DE\s+(\d{2,3})\s*H(?:ORAS)?\b",
              r"\b(\d{2,3})\s*H(?:ORAS)?\.?\s+(?:DE\s+)?NIVEL\s+BASICO",
              r"NIVEL\s+BASICO[^\n]{0,60}?\b(\d{2,3})\s*HORAS")

    def extraer(self, doc):
        c, _ = _comunes(doc)
        for patron in self._HORAS:
            h = buscar(doc, patron)
            if h:
                c["horas"] = campo(int(h.match.group(1)), h.lineas)
                break
        # Nº de registro del alumno (NNNNNN/NNNNNN/NNNNNNN). Ojo: el «número de registro» de la
        # entidad homologada no lleva barras y el «número de curso» es de todo el grupo.
        h = buscar(doc, NUM + r"\s*(?:DE\s+)?REGISTRO\s*:?\s*(\d{3,}(?:\s*/\s*\d{3,}){1,3})")
        if h:
            c["numero_registro"] = campo(re.sub(r"\s", "", h.match.group(1)), h.lineas)
        # El OCR puede separar las letras finales («97628895558 MAD»).
        h = buscar(doc, NUM + r"\s*DE\s+CURSO\s*:?\s*(\d{6,})\s?([A-Z]{2,4})?\b")
        if h:
            c["numero_curso"] = campo(h.match.group(1) + (h.match.group(2) or ""), h.lineas)
        h = buscar(doc, r"POR\s+PARTE\s+DE\s+([A-Z0-9Ñ][A-Z0-9Ñ.,&\-\s]{2,60}?)\s*,?\s*LA\s+(?:JORNADA|ACCION|ACTIVIDAD)")
        if h:
            c["entidad"] = campo(" ".join(h.match.group(1).split()).strip(" ,"), h.lineas)
        else:
            r = tras_etiqueta(doc, r"^(?:ENTIDAD\s+(?:FORMADORA|IMPARTIDORA|ORGANIZADORA)|CENTRO\s+FORMADOR|IMPARTIDO\s+POR)\b\s*:?")
            if r:
                c["entidad"] = campo(r[0], r[1])
        return c

    def validar(self, campos, doc):
        return {"nif_letra_valida": True if "nif" in campos else (False if nif_mal_escrito(doc) else None),
                "horas_minimo_60": campos["horas"].valor >= 60 if "horas" in campos else None,
                "menciona_convenio_construccion": bool(buscar(doc, r"FUNDACION LABORAL|CONVENIO[A-Z ]{0,30}CONSTRUCCION")),
                "fecha_no_futura": _fecha_no_futura(campos)}


class TsRiesgos(Extractor):
    tipo = "ts_riesgos"
    nombre = "Técnico Superior en Prevención de Riesgos Profesionales (FP)"
    grupo = "titulacion"
    campos = ("titular", "nif", "titulo", "comunidad_autonoma", "numero_registro", "fecha")
    obligatorios = ("titular", "nif", "titulo", "fecha")
    claves = {r"TECNICO SUPERIOR EN PREVENCION DE RIESGOS PROFESIONALES": 4, r"TITULO DE TECNICO SUPERIOR": 1.5,
              r"FORMACION PROFESIONAL": 1, r"CICLO FORMATIVO": 1, r"REY DE ESPAÑA": 0.5,
              r"\b(?:MINISTR[OA]|CONSEJER[OA])\b": 0.5}

    def extraer(self, doc):
        c, _ = _comunes(doc)
        # El título se LEE del documento (nunca se rellena por defecto).
        h = buscar(doc, r"\b(TECNICO SUPERIOR EN" + TITULO + ")")
        if h:
            c["titulo"] = campo(_cortar_titulo(h.match.group(1)), h.lineas)
        for nombre in CCAA:
            h = buscar(doc, r"\b" + nombre.replace(" ", r"\s+") + r"\b")
            if h:
                c["comunidad_autonoma"] = campo(nombre, h.lineas)
                break
        h = (valor_tras(doc, r"REGISTRO\s+(?:AUTONOMICO|NACIONAL|NAL\.?)\s+DE\s+TITUL(?:OS|ADOS)", r"\b(\d{8,14})\b")
             or buscar(doc, r"\b([A-Z]{2}-[A-Z]-\d{5,8})\b"))
        if h:
            c["numero_registro"] = campo(h.match.group(1), h.lineas)
        return c

    def validar(self, campos, doc):
        titulo = campos["titulo"].valor if "titulo" in campos else ""
        return {"nif_letra_valida": True if "nif" in campos else (False if nif_mal_escrito(doc) else None),
                "titulo_prevencion_riesgos": (all(p in titulo for p in ("TECNICO SUPERIOR", "PREVENCION", "RIESGOS"))
                                              if titulo else None),
                "fecha_no_futura": _fecha_no_futura(campos)}


class TsPrl(Extractor):
    tipo = "ts_prl"
    nombre = "Máster Universitario en Prevención de Riesgos Laborales"
    grupo = "titulacion"
    campos = ("titular", "nif", "titulo", "universidad", "titulo_oficial", "numero_registro", "fecha")
    obligatorios = ("titular", "titulo", "universidad", "fecha")
    claves = {r"MASTER UNIVERSITARIO": 3, r"PREVENCION DE RIESGOS LABORALES": 2, r"\bUNIVERSI(?:DAD|TAT)\b": 1,
              r"\bRECTOR": 1, r"REGISTRO NACIONAL DE TITULADOS": 1, r"TITULO (?:OFICIAL|PROPIO)": 1, r"\bMASTER\b": 1}

    def extraer(self, doc):
        c, _ = _comunes(doc)
        h = buscar(doc, r"\b(MASTER(?: UNIVERSITARIO)? EN" + TITULO + ")")
        if h:
            c["titulo"] = campo(_cortar_titulo(h.match.group(1)), h.lineas)
        h = (buscar(doc, r"POR\s+LA\s+(UNIVERSI(?:DAD|TAT)\s+[A-ZÑ .'\-]{3,80}?)(?=\s*(?:,|\.|\n|\s+Y\s|\s+EXPIDE|\s+CON\s|$))")
             or buscar(doc, r"\b(UNIVERSI(?:DAD|TAT)\s+(?:DE\s+|DEL\s+|POLITECNICA\s+|NACIONAL\s+|COMPLUTENSE\s+|AUTONOMA\s+)"
                            r"[A-ZÑ .'\-]{2,70}?)(?=\s*(?:,|\.|\n|$))"))
        if h:
            c["universidad"] = campo(" ".join(h.match.group(1).split()), h.lineas)
        oficial = self._oficial(doc)
        if oficial is not None:
            c["titulo_oficial"] = campo(oficial, (buscar(doc, r"MASTER") or buscar(doc, r".")).lineas)
        # Nº del Registro Nacional de Títulos/Titulados: «AAAA/NNNNNN».
        h = valor_tras(doc, r"REGISTRO\s+(?:NACIONAL|NAL\.?)\s+DE\s+TITUL(?:OS|ADOS)", r"\b((?:19|20)\d{2}/\d{5,7})\b", 400)
        if h:
            c["numero_registro"] = campo(h.match.group(1), h.lineas)
        return c

    @staticmethod
    def _oficial(doc) -> bool | None:
        if buscar(doc, r"TITULO\s+PROPIO|ESTUDIOS?\s+PROPIOS?|TITULACION\s+PROPIA"):
            return False
        if buscar(doc, r"MASTER\s+UNIVERSITARIO") and buscar(
                doc, r"REGISTRO\s+NACIONAL\s+DE\s+TITULADOS|TITULO\s+OFICIAL|VALIDEZ\s+EN\s+TODO\s+EL\s+TERRITORIO|REY\s+DE\s+ESPAÑA"):
            return True
        if buscar(doc, r"\bMASTER\b") and not buscar(doc, r"MASTER\s+UNIVERSITARIO"):
            return False
        return None

    def validar(self, campos, doc):
        titulo = campos["titulo"].valor if "titulo" in campos else ""
        return {"titulo_prevencion_riesgos_laborales": (all(p in titulo for p in ("PREVENCION", "RIESGOS", "LABORALES"))
                                                         if titulo else None),
                "titulo_oficial": campos["titulo_oficial"].valor if "titulo_oficial" in campos else None,
                "fecha_no_futura": _fecha_no_futura(campos)}
