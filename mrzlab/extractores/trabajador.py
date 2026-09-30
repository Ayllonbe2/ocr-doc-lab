"""Documentos de prevención de cada trabajador: contrato, reconocimiento médico y fichas firmadas
(información del art. 18, formación del art. 19 y entrega de EPIs)."""
from __future__ import annotations

import re
from datetime import date

from ..lineas import Linea
from ..validadores import buscar_nifs
from .base import NOMBRE, Campo, Extractor, buscar, campo, limpiar_nombre, norm, tras_etiqueta
from .comunes import (VALOR_ID, es_nif, fecha_documento, fecha_en, id_de, identificador_valido, nif_cerca,
                      razon_social, titular)
from .firma import firmado


def _entre(doc, inicio: str, fin: str | None) -> list[Linea]:
    """Líneas entre dos títulos de sección (en orden de lectura)."""
    dentro, activo = [], False
    for ln in doc.lineas:
        t = norm(ln.texto)
        if not activo and re.search(inicio, t):
            activo = True
            continue
        if activo and fin and re.search(fin, t):
            break
        if activo:
            dentro.append(ln)
    return dentro


class ContratoLaboral(Extractor):
    tipo = "contrato_laboral"
    nombre = "Contrato de trabajo"
    grupo = "trabajador"
    campos = ("identificador_empresa", "razon_social", "nif_trabajador", "nombre_trabajador", "fecha_inicio",
              "tipo_contrato")
    obligatorios = ("identificador_empresa", "nif_trabajador", "fecha_inicio", "tipo_contrato")
    claves = {r"CONTRATO DE TRABAJO": 4, r"PERSONA TRABAJADORA|\bTRABAJADOR": 1, r"CUENTA DE COTIZACION": 1,
              r"CLAUSULAS": 1, r"ESTATUTO DE LOS TRABAJADORES": 1, r"\bJORNADA\b": 0.5,
              r"INDEFINID|DURACION DETERMINADA|TEMPORAL": 0.5}
    max_paginas = 25                                 # el modelo del SEPE tiene 20

    _EMPRESA = r"DATOS\s+DE\s+LA\s+EMPRESA|\bLA\s+EMPRESA\b"
    _TRABAJADOR = r"DATOS\s+DE\s+LA\s+PERSONA\s+TRABAJADORA|DATOS\s+DEL\s+TRABAJADOR|DATOS\s+DE\s+LA\s+TRABAJADORA"
    _FIN = r"DATOS\s+DE\s+LA\s+ASISTENCIA|DECLARAN|CLAUSULAS"

    def extraer(self, doc):
        empresa = _entre(doc, self._EMPRESA, self._TRABAJADOR)
        trabajador = _entre(doc, self._TRABAJADOR, self._FIN)
        c: dict[str, Campo | None] = {}
        if empresa:
            # Solo el valor de la casilla «CIF/NIF/NIE» de la empresa: en la misma sección está el
            # NIF de su representante, que nunca debe pasar por el de la empresa.
            r = tras_etiqueta(doc, r"^C\.?\s?I\.?\s?F\.?(?:\s*/\s*N\.?I\.?F\.?)?(?:\s*/\s*N\.?I\.?E\.?)?\s*:?", VALOR_ID,
                              lineas=empresa, valida=lambda t: id_de(t) is not None)
            if r:
                c["identificador_empresa"] = campo(id_de(r[0]), r[1])
            c["razon_social"] = razon_social(doc, r"\bNOMBRE\s+O\s+RAZON\s+SOCIAL(?:\s+DE\s+LA\s+EMPRESA)?\b\s*:?")
        if trabajador:
            r = tras_etiqueta(doc, r"\bN\.?\s?I\.?\s?F\.?(?:\s*/\s*N\.?I\.?E\.?)?\s*:?", VALOR_ID, lineas=trabajador,
                              valida=es_nif)
            if r:
                c["nif_trabajador"] = campo(buscar_nifs(r[0], corregir=True)[0], r[1])
            r = tras_etiqueta(doc, r"^(?:D\.?\s*/\s*D(?:Ñ|N)?A?\.?|NOMBRE(?:\s+Y\s+APELLIDOS)?)\s*:?", NOMBRE,
                              lineas=trabajador)
            if r and limpiar_nombre(r[0]):
                c["nombre_trabajador"] = campo(limpiar_nombre(r[0]), r[1])
        elif not empresa and len(buscar_nifs(doc.texto_norm)) == 1:
            # Contrato sin secciones y con un único NIF: es el del trabajador. Si hay secciones
            # pero no se ha encontrado la del trabajador, no se adivina (podría salir el NIF del
            # representante de la empresa).
            tit, h = titular(doc)
            c["nombre_trabajador"], c["nif_trabajador"] = tit, nif_cerca(doc, h)
        c["fecha_inicio"] = fecha_en(doc, r"\b(?:INICIANDOSE\s+LA\s+RELACION\s+LABORAL\s+EN\s+FECHA|FECHA\s+DE\s+INICIO|"
                                          r"FECHA\s+DE\s+ALTA|CON\s+EFECTOS?\s+(?:DESDE|DE)|A\s+PARTIR\s+DEL?\s+(?:DIA)?)", 1)
        h = buscar(doc, r"\bCONTRATO\s+DE\s+TRABAJO\s+(INDEFINIDO|TEMPORAL|DE\s+DURACION\s+DETERMINADA|FIJO[\s\-]DISCONTINUO|"
                        r"FORMATIVO|PARA\s+LA\s+FORMACION|EN\s+PRACTICAS|A\s+TIEMPO\s+PARCIAL)")
        if h:
            c["tipo_contrato"] = campo(" ".join(h.match.group(1).split()), h.lineas)
        return c

    def validar(self, campos, doc):
        return {"identificador_empresa_valido": identificador_valido(campos["identificador_empresa"].valor)
                if "identificador_empresa" in campos else None,
                "nif_trabajador_valido": True if "nif_trabajador" in campos else None}


class ReconocimientoMedico(Extractor):
    """Solo NIF, fecha y el resultado (apto / no apto / con restricciones).

    Es un dato de salud (art. 9 RGPD): no se devuelve ningún otro texto del documento.
    """
    tipo = "reconocimiento_medico"
    nombre = "Certificado de aptitud del reconocimiento médico"
    grupo = "trabajador"
    campos = ("nif", "fecha", "apto")
    obligatorios = ("nif", "fecha", "apto")
    claves = {r"RECONOCIMIENTO MEDICO": 3, r"VIGILANCIA DE LA SALUD": 2, r"\bAPTITUD\b": 2,
              r"CERTIFICADO DE APTITUD": 2, r"MEDIC[OA] DEL TRABAJO|MEDICINA DEL TRABAJO": 1.5,
              r"\bAPTO\b": 1.5, r"ARTICULO 22|ART\. 22": 1}

    _OPCION = r"\b(NO\s+APTO|APTO\s+CON\s+(?:RESTRICCIONES|LIMITACIONES|ADAPTACIONES)|APTO|PENDIENTE\s+DE\s+CALIFICACION)\b"

    def extraer(self, doc):
        _, h = titular(doc)
        c = {"nif": nif_cerca(doc, h),
             "fecha": fecha_en(doc, r"\bFECHA\s+(?:DEL\s+)?(?:RECONOCIMIENTO|EXAMEN|REVISION)\b", 1) or fecha_documento(doc)}
        # El resultado va tras su etiqueta; si el modelo lista todas las opciones sin marcar,
        # no se puede saber cuál es y se deja vacío.
        r = tras_etiqueta(doc, r"\b(?:RESULTADO|CALIFICACION|DICTAMEN|CONCLUSION)(?:\s+DE\s+(?:LA\s+)?APTITUD)?\b\s*:?",
                          self._OPCION)
        if r:
            c["apto"] = campo(" ".join(r[0].split()), r[1])
        else:
            opciones = {" ".join(m.group(1).split()) for m in re.finditer(self._OPCION, doc.texto_norm)}
            if len(opciones) == 1:
                valor = opciones.pop()
                c["apto"] = campo(valor, buscar(doc, valor.replace(" ", r"\s+")).lineas)
        return c

    def validar(self, campos, doc):
        return {"apto": (campos["apto"].valor.startswith("APTO")) if "apto" in campos else None,
                "fecha_no_futura": campos["fecha"].valor <= date.today() if "fecha" in campos else None}


class _FichaFirmada(Extractor):
    grupo = "trabajador"
    campos = ("nif_trabajador", "nombre_trabajador", "fecha", "firmado")
    obligatorios = ("fecha", "firmado")

    # Etiquetas del trabajador. Un «D./Dª.» suelto no basta: en muchas fichas el primero es el de
    # quien entrega o informa (el responsable), no el de quien recibe.
    _ETIQ_TRABAJADOR = (r"(?:\bENTREGA\s+A|\bINFORMA\s+Y\s+ENTREGA\s+A|^TRABAJADOR/?A?|^PERSONA\s+QUE\s+SE\s+INCORPORA|"
                        r"^NOMBRE\s+Y\s+APELLIDOS|^APELLIDOS\s+Y\s+NOMBRE|^NOMBRE\s+DEL\s+TRABAJADOR)\b\s*:?")
    # Fechas que no son la de la ficha.
    # (por prefijo: el OCR puede leer «aprobaci6n»)
    _FECHA = r"\bFECHA\b(?!\s+(?:DE\s+)?(?:APROB|REVIS|VERSI|EDICI|NACIM|IMPRES|ACTUALIZ))\s*:?"

    def extraer(self, doc):
        r = tras_etiqueta(doc, self._ETIQ_TRABAJADOR, NOMBRE, valida=lambda t: limpiar_nombre(t) is not None)
        if r:
            tit, h = campo(limpiar_nombre(r[0]), r[1]), None
        else:
            tit, h = titular(doc, unico=True)
        return {"nombre_trabajador": tit, "nif_trabajador": nif_cerca(doc, h),
                "fecha": self._fecha(doc), "firmado": firmado(doc)}

    def _fecha(self, doc):
        """La de la fila de la firma del trabajador; si no, la de la etiqueta «Fecha»."""
        from ..validadores import buscar_fechas
        from .firma import ETIQUETAS
        for texto, lineas in doc.filas:
            if re.search(ETIQUETAS, texto):
                fechas = buscar_fechas(texto)
                if fechas:
                    return campo(fechas[0][0], lineas)
        return fecha_en(doc, self._FECHA, 1) or fecha_documento(doc)

    def faltan(self, campos):
        faltan = super().faltan(campos)
        if "nif_trabajador" not in campos and "nombre_trabajador" not in campos:
            faltan.append("nif_trabajador")
        return faltan

    def validar(self, campos, doc):
        return {"firmado": campos["firmado"].valor if "firmado" in campos else None}


class InformacionArt18(_FichaFirmada):
    tipo = "informacion_art18"
    nombre = "Registro de información de riesgos al trabajador (art. 18 LPRL)"
    claves = {r"ARTICULO 18|ART\.? 18": 3, r"\bINFORMACION\b": 1, r"RIESGOS (?:DEL|DE SU) PUESTO": 1.5,
              r"MEDIDAS (?:DE PROTECCION|PREVENTIVAS)": 0.5, r"\bRECIBI\b|HE RECIBIDO": 1, r"EMERGENCIA": 0.5}


class FormacionArt19(_FichaFirmada):
    tipo = "formacion_art19"
    nombre = "Registro de formación en prevención (art. 19 LPRL)"
    claves = {r"ARTICULO 19|ART\.? 19": 3, r"\bFORMACION\b": 1.5, r"\bHORAS\b": 0.5, r"CONTENIDO|TEMARIO": 0.5,
              r"ASISTENCIA|APROVECHAMIENTO": 0.5, r"\bRECIBI\b|HE RECIBIDO": 0.5}


class EntregaEpis(_FichaFirmada):
    tipo = "entrega_epis"
    nombre = "Registro de entrega de equipos de protección individual (EPI)"
    claves = {r"EQUIPOS? DE PROTECCION INDIVIDUAL": 3, r"\bEPIS?\b": 2, r"\bENTREGA": 1.5,
              r"(?:REAL DECRETO|R\.?D\.?) 773/1997": 1.5, r"\bTALLA\b|\bMARCA\b|\bMODELO\b": 0.5, r"\bRECIBI\b": 1}
