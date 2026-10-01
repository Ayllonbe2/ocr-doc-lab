"""Documentos de empresa: certificados de estar al corriente (TGSS y AEAT), póliza de
responsabilidad civil, inscripción en el registro de empresas acreditadas, apertura del centro
de trabajo y documentos libres (plan de seguridad y salud, evaluación de riesgos, CAE)."""
from __future__ import annotations

import os
import re
from datetime import date

from ..validadores import buscar_cifs, buscar_fechas, buscar_importes, buscar_nifs
from .base import NUM, Campo, Extractor, buscar, campo, tras_etiqueta
from .comunes import (fecha_documento, fecha_en, identificador_empresa, identificador_valido, meses_validez,
                      razon_social, sumar_meses)

# Si el certificado no dice su validez, se asume esta (meses). Configurable.
VALIDEZ_CERTIFICADO = int(os.getenv("OCR_VALIDEZ_CERTIFICADO_MESES", "6"))


def _vigente(desde: Campo | None, hasta: Campo | None) -> bool | None:
    if hasta is None:
        return None
    hoy = date.today()
    return (desde is None or desde.valor <= hoy) and hoy <= hasta.valor


class _CertificadoCorriente(Extractor):
    grupo = "empresa"
    campos = ("razon_social", "identificador", "fecha_emision", "al_corriente", "codigo_verificacion",
              "caduca", "validez_meses")
    obligatorios = ("identificador", "fecha_emision", "al_corriente")

    def extraer(self, doc):
        c = {"razon_social": razon_social(doc), "identificador": identificador_empresa(doc)}
        c["fecha_emision"] = fecha_en(doc, r"\b(?:FECHA\s+DE\s+(?:EMISION|EXPEDICION)|EXPEDID[OA]|EMITID[OA])\b") \
            or fecha_documento(doc)
        h = buscar(doc, r"\b(NO\s+)?(?:ESTA|SE\s+ENCUENTRA|FIGURA)\s+AL\s+CORRIENTE")
        if h:
            c["al_corriente"] = campo(h.match.group(1) is None, h.lineas)
        elif buscar(doc, r"\bTIENE\s+(?:DEUDAS|DEUDA)\s+PENDIENTE|\bNO\s+ESTA\s+AL\s+CORRIENTE"):
            c["al_corriente"] = campo(False, buscar(doc, r"DEUDA|NO\s+ESTA").lineas)
        from ..autenticidad import codigos_confirmados
        codigos, _ = codigos_confirmados(doc)       # sin dígito de control: solo si se confirma
        if codigos:
            h = buscar(doc, re.escape(codigos[0]["codigo"][:6]))
            c["codigo_verificacion"] = campo(codigos[0]["codigo"], h.lineas if h else None)
        meses, dicho = meses_validez(doc, VALIDEZ_CERTIFICADO)
        if c["fecha_emision"]:
            f = c["fecha_emision"]
            c["caduca"] = Campo(sumar_meses(f.valor, meses), "documento" if dicho else "calculado", f.confianza, f.pagina)
            c["validez_meses"] = Campo(meses, "documento" if dicho else "por_defecto", 1.0, f.pagina)
        return c

    def validar(self, campos, doc):
        return {"identificador_valido": identificador_valido(campos["identificador"].valor)
                if "identificador" in campos else None,
                "vigente": _vigente(campos.get("fecha_emision"), campos.get("caduca")),
                "al_corriente": campos["al_corriente"].valor if "al_corriente" in campos else None}


class CertificadoTgss(_CertificadoCorriente):
    tipo = "certificado_tgss"
    nombre = "Certificado de estar al corriente con la Seguridad Social (TGSS)"
    claves = {r"TESORERIA GENERAL DE LA SEGURIDAD SOCIAL": 3, r"AL CORRIENTE": 2, r"SEGURIDAD SOCIAL": 1,
              r"\bCERTIFICA\b": 1, r"CUENTA DE COTIZACION|\bC\.?C\.?C\.?\b": 0.5, r"OBLIGACIONES": 0.5}


class CertificadoAeat(_CertificadoCorriente):
    tipo = "certificado_aeat"
    nombre = "Certificado de estar al corriente de obligaciones tributarias (AEAT)"
    claves = {r"AGENCIA (?:ESTATAL DE ADMINISTRACION )?TRIBUTARIA": 3, r"OBLIGACIONES TRIBUTARIAS": 2,
              r"AL CORRIENTE": 2, r"\bCERTIFICA\b": 1, r"LEY GENERAL TRIBUTARIA|REGLAMENTO GENERAL[A-Z ,]{0,40}GESTION": 1}


class SeguroRc(Extractor):
    tipo = "seguro_rc"
    nombre = "Póliza de seguro de responsabilidad civil"
    grupo = "empresa"
    campos = ("tomador", "identificador", "aseguradora", "poliza", "vigencia_desde", "vigencia_hasta",
              "limite_siniestro")
    obligatorios = ("identificador", "poliza", "vigencia_desde", "vigencia_hasta")
    claves = {r"RESPONSABILIDAD CIVIL": 3, r"\bPOLIZA\b": 2, r"\bTOMADOR": 1.5, r"\bASEGURADOR": 1,
              r"\bSINIESTRO": 1, r"CONDICIONES PARTICULARES": 1, r"\bPRIMA\b": 0.5, r"SUMA ASEGURADA|LIMITE": 0.5}

    def _identificador_tomador(self, doc) -> Campo | None:
        """CIF del tomador: el primero tras la etiqueta «Tomador», no el de la aseguradora."""
        for i, (texto, _) in enumerate(doc.filas):
            m = re.search(r"\bTOMADOR", texto)
            if not m:
                continue
            for j in range(i, min(i + 4, len(doc.filas))):
                t = doc.filas[j][0][m.start():] if j == i else doc.filas[j][0]
                encontrados = buscar_cifs(t) or buscar_nifs(t)
                if encontrados:
                    return campo(encontrados[0], doc.filas[j][1])
            # Hay etiqueta pero no se lee su CIF: vacío. El de la aseguradora nunca vale.
            return None
        return identificador_empresa(doc)

    def extraer(self, doc):
        c: dict[str, Campo | None] = {"tomador": razon_social(doc, r"\bTOMADOR(?:\s+DEL\s+SEGURO)?\b\s*:?"),
                                      "identificador": self._identificador_tomador(doc)}
        r = tras_etiqueta(doc, r"\b(?:ENTIDAD\s+ASEGURADORA|ASEGURADORA|ASEGURADOR|COMPAÑIA)\b\s*:?")
        if r and not buscar_cifs(r[0]):
            c["aseguradora"] = campo(r[0], r[1])
        else:
            h = buscar(doc, r"\b([A-Z][A-Z ]{2,40}\s+SEGUROS(?:\s+Y\s+REASEGUROS)?(?:\s*,?\s*S\.?A\.?)?|SEGUROS\s+[A-Z][A-Z ]{2,40})\b")
            if h:
                c["aseguradora"] = campo(" ".join(h.match.group(1).split()), h.lineas)
        r = tras_etiqueta(doc, rf"(?:{NUM}\s*(?:DE\s+)?POLIZA|\bPOLIZA\s+{NUM})\s*:?",
                          r"\b((?=[A-Z0-9/\-.]*\d)[A-Z0-9][A-Z0-9/\-.]{4,}[0-9A-Z])\b")
        if r:
            c["poliza"] = campo(r[0], r[1])
        h = buscar(doc, r"DESDE[^\n]{0,40}?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{1,2}\s+DE\s+[A-Z]+\s+DE\s+\d{4})"
                        r"[^\n]{0,40}?HASTA[^\n]{0,40}?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{1,2}\s+DE\s+[A-Z]+\s+DE\s+\d{4})")
        if h:
            f1, f2 = buscar_fechas(h.match.group(1)), buscar_fechas(h.match.group(2))
            if f1 and f2:
                c["vigencia_desde"], c["vigencia_hasta"] = campo(f1[0][0], h.lineas), campo(f2[0][0], h.lineas)
        if "vigencia_desde" not in c:
            c["vigencia_desde"] = fecha_en(doc, r"\b(?:FECHA\s+DE\s+EFECTO|EFECTO|INICIO\s+DE\s+(?:LA\s+)?VIGENCIA|FECHA\s+DE\s+INICIO)\b", 1)
            c["vigencia_hasta"] = fecha_en(doc, r"\b(?:FECHA\s+DE\s+VENCIMIENTO|VENCIMIENTO|FIN\s+DE\s+(?:LA\s+)?VIGENCIA|FECHA\s+DE\s+FIN)\b", 1)
        for texto, lineas in doc.filas:
            if re.search(r"\bLIMITE\b[^\n]{0,30}(?:SINIESTRO|INDEMNIZACION)|SUMA\s+ASEGURADA|LIMITE\s+MAXIMO", texto):
                importes = buscar_importes(texto)
                if importes:
                    c["limite_siniestro"] = campo(max(importes), lineas)
                    break
        return c

    def validar(self, campos, doc):
        desde, hasta = campos.get("vigencia_desde"), campos.get("vigencia_hasta")
        return {"identificador_valido": identificador_valido(campos["identificador"].valor)
                if "identificador" in campos else None,
                "vigente": _vigente(desde, hasta),
                "fechas_coherentes": (desde.valor < hasta.valor) if desde and hasta else None}


# Bloque de quien pide el certificado (modelo estatal) y frase que da paso a la empresa inscrita.
# Varias formas de cada uno: en una foto el OCR puede perder alguna línea.
_SOLICITANTE = r"DATOS\s+DE(?:L|\s+LA)\s+SOLICI(?:TUD|TANTE)|FECHA\s+DE\s+LA\s+SOLICITUD|EN\s+REPRESENTACION\s+DE"
_EMPRESA_INSCRITA = r"\bCERTIFICA\b|CUYOS\s+DATOS|FIGURA\s+INSCRITA"


def _tras_certifica(doc) -> list | None:
    """Líneas posteriores a «CERTIFICA» si el documento trae un bloque con los datos del solicitante;
    si no lo trae, None (se busca en todo el documento)."""
    if not buscar(doc, _SOLICITANTE):
        return None
    h = buscar(doc, _EMPRESA_INSCRITA)
    if not h:
        return []          # se ve al solicitante pero no dónde empieza la empresa: no se adivina
    ancla = h.lineas[0]
    return [ln for ln in doc.lineas if (ln.pagina, ln.caja[1]) > (ancla.pagina, ancla.caja[1])]


class RegistroEmpresa(Extractor):
    tipo = "registro_empresa"
    nombre = "Inscripción en el Registro de Empresas Acreditadas (construcción)"
    grupo = "empresa"
    campos = ("razon_social", "identificador", "numero_inscripcion", "fecha")
    obligatorios = ("identificador", "numero_inscripcion")
    claves = {r"REGISTRO DE EMPRESAS ACREDITADAS": 4, r"LEY 32/2006": 2, r"\bINSCRIPCION\b": 1.5,
              r"SECTOR DE LA CONSTRUCCION": 1, r"\bR\.?E\.?A\.?\b": 1}

    def extraer(self, doc):
        # El certificado estatal empieza por «DATOS DE LA SOLICITUD»: nombre y NIF de quien lo pide
        # (una persona o una gestoría). Los de la empresa inscrita van después de «CERTIFICA».
        empresa = _tras_certifica(doc)
        # Sin la etiqueta «empresa» sola, que casa con «la empresa cuyos datos se indican…».
        razon = razon_social(doc, r"\b(?:(?:NOMBRE\s+O\s+)?RAZON\s+SOCIAL|DENOMINACION(?:\s+SOCIAL)?)\b\s*:?",
                             lineas=empresa)
        # Fecha de inscripción («figura inscrita … desde el 22/11/2016»). Con el bloque del solicitante,
        # la primera fecha del documento es la de la solicitud: sin la de inscripción, vacía.
        inscripcion = fecha_en(doc, r"FECHA\s+DE\s+INSCRIPCION|\bDESDE\s+EL\b")
        ident = identificador_empresa(doc, empresa)
        # Sin saber dónde empieza la empresa, si el texto trae más de un identificador (el del
        # solicitante, el del representante…) no se puede asegurar cuál es: vacío.
        if empresa is None and ident is not None and \
                len(set(buscar_cifs(doc.texto_norm)) | set(buscar_nifs(doc.texto_norm))) > 1:
            ident = None
        c = {"razon_social": razon, "identificador": ident,
             "fecha": inscripcion or (fecha_documento(doc) if empresa is None else None)}
        # Nº de inscripción «NN/NN/NNNNNNN» (no una fecha: el último bloque tiene 5+ cifras). En el
        # modelo de Madrid va como «Núm. REA: 12 28 0098249».
        r = tras_etiqueta(doc, rf"(?:{NUM}\s*(?:DE\s+)?(?:INSCRIPCION|REGISTRO)(?:\s+REA)?|\bNUM\.?\s*REA)\b\s*:?",
                          r"\b(\d{2}[/ ]\d{2}[/ ]\d{5,}|\d{6,})\b")
        if r:
            c["numero_inscripcion"] = campo(r[0].replace(" ", "/"), r[1])
        return c

    def validar(self, campos, doc):
        return {"identificador_valido": identificador_valido(campos["identificador"].valor)
                if "identificador" in campos else None}


class AperturaCentro(Extractor):
    tipo = "apertura_centro_trabajo"
    nombre = "Comunicación de apertura del centro de trabajo"
    grupo = "empresa"
    campos = ("razon_social", "identificador", "direccion_obra", "fecha")
    obligatorios = ("identificador", "fecha")
    claves = {r"\bAPERTURA\b": 2, r"CENTRO DE TRABAJO": 2, r"REANUDACION": 1.5, r"\bCOMUNICACION\b": 1,
              r"AUTORIDAD LABORAL": 1, r"ORDEN TIN/1071/2010": 2, r"\bOBRAS?\b": 0.5, r"\bPROMOTOR": 0.5}

    def extraer(self, doc):
        c = {"razon_social": razon_social(doc), "identificador": identificador_empresa(doc)}
        r = tras_etiqueta(doc, r"\b(?:DOMICILIO\s+DEL\s+CENTRO(?:\s+DE\s+TRABAJO)?|DIRECCION\s+DE\s+LA\s+OBRA|"
                               r"EMPLAZAMIENTO(?:\s+DE\s+LA\s+OBRA)?|SITUACION\s+DE\s+LA\s+OBRA)\b\s*:?")
        if r:
            c["direccion_obra"] = campo(r[0], r[1])
        c["fecha"] = fecha_en(doc, r"\bFECHA\s+DE\s+(?:INICIO|COMIENZO|APERTURA)\b", 1) or fecha_documento(doc)
        return c

    def validar(self, campos, doc):
        return {"identificador_valido": identificador_valido(campos["identificador"].valor)
                if "identificador" in campos else None}


class _DocumentoLibre(Extractor):
    """Documentos largos y de texto libre: se clasifican y se sacan empresa y fecha si están."""
    grupo = "empresa"
    campos = ("razon_social", "identificador", "fecha")
    obligatorios = ()
    max_paginas = 60

    def extraer(self, doc):
        return {"razon_social": razon_social(doc), "identificador": identificador_empresa(doc),
                "fecha": fecha_documento(doc)}

    def faltan(self, campos):
        return []


class PlanSeguridadSalud(_DocumentoLibre):
    tipo = "plan_seguridad_salud"
    nombre = "Plan de seguridad y salud en el trabajo (obra)"
    claves = {r"PLAN DE SEGURIDAD Y SALUD": 4, r"(?:REAL DECRETO|R\.?D\.?) 1627/1997": 1.5,
              r"ESTUDIO (?:BASICO )?DE SEGURIDAD": 1, r"\bCONTRATISTA": 1, r"\bOBRA\b": 0.5, r"\bCOORDINADOR": 0.5}


class EvaluacionRiesgos(_DocumentoLibre):
    tipo = "evaluacion_riesgos"
    nombre = "Evaluación de riesgos laborales"
    claves = {r"EVALUACION DE (?:LOS )?RIESGOS": 4, r"PUESTOS? DE TRABAJO": 1, r"PROBABILIDAD": 1,
              r"SEVERIDAD|CONSECUENCIAS": 1, r"MEDIDAS PREVENTIVAS": 1, r"ARTICULO 16|ART\. 16": 0.5}


class DocumentacionCae(_DocumentoLibre):
    tipo = "cae_documentacion"
    nombre = "Documentación de coordinación de actividades empresariales (CAE)"
    claves = {r"COORDINACION DE ACTIVIDADES EMPRESARIALES": 4, r"(?:REAL DECRETO|R\.?D\.?) 171/2004": 2,
              r"CONCURRENCIA": 1, r"EMPRESA(?:RIO)? (?:TITULAR|PRINCIPAL)": 1, r"\bCAE\b": 0.5}
