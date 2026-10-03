"""Extractores sin OCR: documentos montados a mano con líneas y posiciones (nivel U).

Cada caso raro que ha aparecido con documentos reales o fotos tiene aquí su prueba. Todos los
nombres, NIF y CIF son inventados.
"""
from datetime import date

import pytest

from mrzlab.documentos import Documento
from mrzlab.extractores import REGISTRO
from mrzlab.lineas import Linea, Pagina


def doc(*lineas, origen="capa_texto") -> Documento:
    """Líneas como (texto, x, y) o (texto, x, y, ancho, alto, [alternativa]), en fracción de página."""
    ls = []
    for ln in lineas:
        texto, x, y, *resto = ln
        w = resto[0] if resto else 0.4
        h = resto[1] if len(resto) > 1 else 0.012
        alternativa = resto[2] if len(resto) > 2 else None
        ls.append(Linea(texto, (x, y, w, h), 1, origen, 1.0, alternativa))
    return Documento("pdf_digital", [Pagina(1, "digital", ls)])


def extraer(tipo, d):
    ext = REGISTRO[tipo]
    campos = {k: v for k, v in ext.extraer(d).items() if v is not None}
    return {k: v.valor for k, v in campos.items()}, ext.validar(campos, d)


# ── FLC 60 h ─────────────────────────────────────────────────────────────────

def _flc(*extra):
    return doc(("D./Dña. GOMEZ RUIZ, LUIS con NIF 12345678Z y nº de registro 123456/234567/3456789", 0.1, 0.20, 0.8),
               ("Ha asistido con pleno aprovechamiento al curso de", 0.2, 0.25),
               ("60H NIVEL BÁSICO DE PREVENCIÓN EN CONSTRUCCIÓN", 0.2, 0.30),
               ("Según Convenio General del sector de la Construcción, se ha celebrado por parte de", 0.1, 0.35, 0.8),
               ("FORMACION EJEMPLO SL, la jornada formativa de duración de 60,00 horas", 0.1, 0.38, 0.8),
               ("Del 1 de marzo de 2025 al 14 de marzo de 2025", 0.1, 0.42, 0.8),
               ("Entidad homologada por la Fundación Laboral de la Construcción con el número de registro "
                "0123456789 y número de curso 12345678901MAD", 0.1, 0.9, 0.8), *extra)


def test_flc_completo():
    c, v = extraer("flc_60h", _flc())
    assert c["titular"] == "GOMEZ RUIZ, LUIS"          # sin tragarse el «con» de «con NIF»
    assert c["nif"] == "12345678Z" and c["horas"] == 60 and c["fecha"] == date(2025, 3, 14)
    assert c["entidad"] == "FORMACION EJEMPLO SL"      # la frase está partida en dos líneas
    assert v == {"nif_letra_valida": True, "horas_minimo_60": True, "menciona_convenio_construccion": True,
                 "fecha_no_futura": True, "titular_tras_don_dona": False}   # «D./Dña.» no dice cuál


def test_flc_numero_registro_formato_con_barras():
    """El nº de registro de la persona lleva barras; el de la entidad, no; el de curso es del grupo."""
    c, _ = extraer("flc_60h", _flc())
    assert c["numero_registro"] == "123456/234567/3456789"
    assert c["numero_curso"] == "12345678901MAD"


def test_flc_numero_de_curso_con_letras_separadas_por_el_ocr():
    d = doc(("D./Dña. GOMEZ RUIZ, LUIS con NIF 12345678Z", 0.1, 0.2), ("número de curso 12345678901 MAD", 0.1, 0.9))
    assert extraer("flc_60h", d)[0]["numero_curso"] == "12345678901MAD"


def test_flc_horas_solo_del_titulo_del_curso():
    """«20 horas de prácticas» antes no es la duración del curso."""
    d = doc(("Incluye 20 horas de prácticas en obra", 0.1, 0.1),
            ("D./Dña. GOMEZ RUIZ, LUIS con NIF 12345678Z", 0.1, 0.2),
            ("ha superado el curso de 60 horas de nivel básico", 0.1, 0.3))
    assert extraer("flc_60h", d)[0]["horas"] == 60


def test_flc_curso_de_20_horas_no_cumple():
    d = doc(("D./Dña. GOMEZ RUIZ, LUIS con NIF 12345678Z", 0.1, 0.2), ("curso de 20 horas de nivel básico", 0.1, 0.3))
    c, v = extraer("flc_60h", d)
    assert c["horas"] == 20 and v["horas_minimo_60"] is False


def test_nif_con_letra_mal_no_se_devuelve():
    d = doc(("D./Dña. GOMEZ RUIZ, LUIS con NIF 12345678A", 0.1, 0.2), ("curso de 60 horas", 0.1, 0.3))
    c, v = extraer("flc_60h", d)
    assert "nif" not in c and v["nif_letra_valida"] is False


def test_varios_nif_sin_etiqueta_no_se_adivina():
    d = doc(("Alumno GOMEZ RUIZ LUIS", 0.1, 0.2), ("12345678Z", 0.1, 0.3), ("87654321X", 0.1, 0.4))
    assert "nif" not in extraer("flc_60h", d)[0]


# ── Técnico Superior (FP) ────────────────────────────────────────────────────

def test_ts_riesgos_titulo_leido_del_documento():
    d = doc(("Don Luis Gómez Ruiz", 0.3, 0.3), ("nacido el día 3 de mayo de 1985, con DNI 1.234.567-L,", 0.2, 0.35, 0.6),
            ("expide a su favor el presente", 0.3, 0.4),
            ("Título de Técnico Superior en Prevención de Riesgos Profesionales", 0.2, 0.45, 0.6),
            ("Madrid, a 15 de noviembre de 2010", 0.4, 0.55), ("Registro Autonómico de Títulos", 0.4, 0.8),
            ("123456789012", 0.42, 0.82))
    c, v = extraer("ts_riesgos", d)
    assert c["titulo"] == "TECNICO SUPERIOR EN PREVENCION DE RIESGOS PROFESIONALES"
    assert c["nif"] == "01234567L" and c["titular"] == "LUIS GOMEZ RUIZ"
    assert c["fecha"] == date(2010, 11, 15)             # nunca la de nacimiento
    assert c["numero_registro"] == "123456789012" and v["titulo_prevencion_riesgos"] is True


def test_ts_riesgos_documento_cualquiera_no_da_titulo():
    """Antes el título se rellenaba con un valor fijo y la comprobación nunca fallaba."""
    d = doc(("Don Luis Gómez Ruiz", 0.3, 0.3), ("Título de Técnico Superior en Administración y Finanzas", 0.2, 0.45, 0.6))
    c, v = extraer("ts_riesgos", d)
    assert c["titulo"] == "TECNICO SUPERIOR EN ADMINISTRACION Y FINANZAS"
    assert v["titulo_prevencion_riesgos"] is False
    c, v = extraer("ts_riesgos", doc(("Un documento cualquiera sin título", 0.1, 0.1)))
    assert "titulo" not in c and v["titulo_prevencion_riesgos"] is None


# ── Máster ───────────────────────────────────────────────────────────────────

def _master(titulo="Máster Universitario en Prevención de Riesgos Laborales", fecha="5 de julio de 2021"):
    return doc(("Felipe VI, Rey de España", 0.3, 0.1), ("Rector de la Universidad de Ejemplo", 0.3, 0.15),
               ("Doña Lucía Ortega Peña", 0.3, 0.3), ("nacida el día 7 de febrero de 1981 en Madrid,", 0.25, 0.35, 0.5),
               ("ha superado los estudios conducentes al título oficial de", 0.25, 0.4, 0.5),
               (titulo + "  r  .  .", 0.2, 0.45, 0.6), ("por la Universidad de Ejemplo", 0.3, 0.5),
               ("expide el presente título oficial con validez en todo el territorio nacional", 0.2, 0.55, 0.6),
               (f"Dado en Madrid, a {fecha}", 0.35, 0.6), ("Registro Nacional de Títulos", 0.1, 0.85),
               ("2021/123456", 0.1, 0.87))


def test_master_oficial():
    c, v = extraer("ts_prl", _master())
    assert c["titulo"] == "MASTER UNIVERSITARIO EN PREVENCION DE RIESGOS LABORALES"   # sin el ruido «r . .»
    assert c["universidad"] == "UNIVERSIDAD DE EJEMPLO" and c["titular"] == "LUCIA ORTEGA PEÑA"
    assert c["titulo_oficial"] is True and c["numero_registro"] == "2021/123456" and c["fecha"] == date(2021, 7, 5)
    assert v["titulo_prevencion_riesgos_laborales"] is True


def test_master_titular_con_ruido_del_borde():
    # El borde decorativo del título deja restos del OCR en la fila del nombre («… . 2»).
    d = doc(("Considerando que, conforme a las disposiciones vigentes,", 0.2, 0.3, 0.6),
            ("Don Miguel Ángel Pérez Cuadro . 2", 0.25, 0.35, 0.5),
            ("nacido el día 27 de abril de 1979 en Córdoba, de nacionalidad española,", 0.25, 0.38, 0.5),
            ("Máster Universitario en Prevención de Riesgos Laborales", 0.2, 0.45, 0.6),
            ("por la Universidad de Ejemplo", 0.3, 0.5), ("Dado en Madrid, a 3 de octubre de 2017", 0.35, 0.6))
    c, _ = extraer("ts_prl", d)
    assert c["titular"] == "MIGUEL ANGEL PEREZ CUADRO"


def test_master_propio_no_es_oficial():
    d = doc(("Universidad de Ejemplo", 0.3, 0.1), ("Doña Lucía Ortega Peña", 0.3, 0.3),
            ("Máster en Prevención de Riesgos Laborales (Título Propio)", 0.2, 0.45, 0.6))
    c, v = extraer("ts_prl", d)
    assert c["titulo_oficial"] is False and v["titulo_oficial"] is False


def test_fecha_de_expedicion_ilegible_no_se_sustituye_por_otra():
    """«a $ de mayo»: con la etiqueta «Dado en» presente, cualquier otra fecha sería un error."""
    c, _ = extraer("ts_prl", _master(fecha="$ de mayo de 2024"))
    assert "fecha" not in c


# ── Empresa ──────────────────────────────────────────────────────────────────

def test_certificado_tgss_y_caducidad():
    d = doc(("TESORERÍA GENERAL DE LA SEGURIDAD SOCIAL", 0.1, 0.05), ("Razón social: EJEMPLO OBRAS SL", 0.1, 0.2),
            ("CIF: B12345674", 0.1, 0.25), ("CERTIFICA: que la empresa está al corriente en el pago", 0.1, 0.3),
            ("Fecha de emisión: 10/01/2025", 0.1, 0.4), ("Código Seguro de Verificación (CSV): ABCD1234EFGH5678", 0.1, 0.9))
    c, v = extraer("certificado_tgss", d)
    assert c["razon_social"] == "EJEMPLO OBRAS SL" and c["identificador"] == "B12345674"
    assert c["al_corriente"] is True and c["fecha_emision"] == date(2025, 1, 10)
    assert c["caduca"] == date(2025, 7, 10) and c["validez_meses"] == 6       # por defecto
    assert c["codigo_verificacion"] == "ABCD1234EFGH5678" and v["vigente"] is False


def test_certificado_con_validez_propia_y_no_al_corriente():
    d = doc(("CIF: B12345674", 0.1, 0.25), ("CERTIFICA: que NO está al corriente de sus obligaciones", 0.1, 0.3),
            ("El presente certificado tiene una validez de doce meses", 0.1, 0.35, 0.8), ("Fecha de emisión: 10/01/2025", 0.1, 0.4))
    c, v = extraer("certificado_aeat", d)
    assert c["al_corriente"] is False and c["caduca"] == date(2026, 1, 10) and v["al_corriente"] is False


def test_poliza_cif_del_tomador_y_no_de_la_aseguradora():
    d = doc(("SEGUROS EJEMPLO, S.A.  CIF B87654325", 0.1, 0.05, 0.6), ("Nº DE PÓLIZA", 0.1, 0.2, 0.2),
            ("RC-1234567", 0.1, 0.215, 0.2), ("TOMADOR DEL SEGURO", 0.1, 0.3, 0.3), ("CIF", 0.7, 0.3, 0.05),
            ("OBRAS EJEMPLO SL", 0.1, 0.315, 0.3), ("B12345674", 0.7, 0.315, 0.15),
            ("desde las 00:00 horas del 01/03/2025 hasta las 24:00 horas del 01/03/2026", 0.1, 0.4, 0.8),
            ("Límite por siniestro: 600.000,00 €", 0.1, 0.45))
    c, v = extraer("seguro_rc", d)
    assert c["identificador"] == "B12345674" and c["tomador"] == "OBRAS EJEMPLO SL"   # no «CIF» (casilla vecina)
    assert c["poliza"] == "RC-1234567" and c["limite_siniestro"] == 600000.0
    assert (c["vigencia_desde"], c["vigencia_hasta"]) == (date(2025, 3, 1), date(2026, 3, 1))
    assert v["fechas_coherentes"] is True


def test_poliza_sin_cif_legible_del_tomador_queda_vacio():
    """Si no se lee el del tomador, nunca se usa el de la aseguradora de la cabecera."""
    d = doc(("SEGUROS EJEMPLO, S.A.  CIF B87654325", 0.1, 0.05, 0.6), ("TOMADOR DEL SEGURO", 0.1, 0.3, 0.3),
            ("OBRAS EJEMPLO SL", 0.1, 0.315, 0.3), ("B1234567?", 0.7, 0.315, 0.15))
    assert "identificador" not in extraer("seguro_rc", d)[0]


def test_registro_empresa_no_confunde_numero_con_fecha():
    d = doc(("REGISTRO DE EMPRESAS ACREDITADAS", 0.2, 0.05), ("N? DE INSCRIPCIÓN", 0.1, 0.3, 0.2),
            ("FECHA DE INSCRIPCIÓN", 0.5, 0.3, 0.2), ("02/10/2025", 0.5, 0.315, 0.1), ("18/50/3146717", 0.1, 0.315, 0.15),
            ("CIF", 0.7, 0.2, 0.05), ("B12345674", 0.7, 0.215, 0.15))
    c, _ = extraer("registro_empresa", d)
    assert c["numero_inscripcion"] == "18/50/3146717" and c["identificador"] == "B12345674"


_POLIZA_CABECERA = (("SEGUROS EJEMPLO, S.A.", 0.1, 0.05, 0.3),
                    ("CIF B87654325 - Compañía de seguros y reaseguros", 0.1, 0.07, 0.4),
                    ("PÓLIZA DE SEGURO DE RESPONSABILIDAD CIVIL GENERAL", 0.2, 0.13, 0.6))


def test_poliza_tomador_leido_con_f_por_t():
    """Foto: el OCR leyó «[FOMADOR DEL SEGURO» (borde de la casilla y la T como F)."""
    d = doc(*_POLIZA_CABECERA, ("[FOMADOR DEL SEGURO", 0.1, 0.25, 0.14), ("CIF", 0.71, 0.25, 0.03),
            ("[OBRAS EJEMPLO SL", 0.1, 0.27, 0.25), ("B12345674", 0.72, 0.27, 0.08))
    c, _ = extraer("seguro_rc", d)
    assert c["tomador"] == "OBRAS EJEMPLO SL" and c["identificador"] == "B12345674"


def test_poliza_sin_etiqueta_de_tomador_no_usa_la_aseguradora():
    """Caso de una foto sintética: sin leer la etiqueta del tomador se devolvían el nombre y el CIF
    de la aseguradora (los primeros del documento) y se daban por buenos."""
    d = doc(*_POLIZA_CABECERA, ("XXOMADOR DEL SEGURO", 0.1, 0.25, 0.14), ("CIF", 0.71, 0.25, 0.03),
            ("OBRAS EJEMPLO SL", 0.1, 0.27, 0.25), ("B12345674", 0.72, 0.27, 0.08))
    c, _ = extraer("seguro_rc", d)
    assert "tomador" not in c and "identificador" not in c


def test_poliza_aseguradora_no_toma_la_frase_de_la_cabecera():
    """«Compañía de seguros y reaseguros» no es la etiqueta «Compañía:» seguida del nombre."""
    d = doc(*_POLIZA_CABECERA, ("ENTIDAD ASEGURADORA", 0.52, 0.20, 0.14), ("SEGUROS EJEMPLO, S.A.", 0.53, 0.216, 0.2))
    c, _ = extraer("seguro_rc", d)
    assert c["aseguradora"] == "SEGUROS EJEMPLO, S.A"


def test_poliza_certificado_en_forma_de_carta():
    """Certificado real: el tomador va en una frase partida en dos líneas, y la aseguradora como
    «X, S.A. de Seguros y Reaseguros» (no «SEGUROS Y REASEGUROS»)."""
    d = doc(("Seguros Ejemplo, S.A. de Seguros y Reaseguros, con domicilio social en Madrid, con NIF A28011864,", 0.1, 0.10, 0.8),
            ("CERTIFICA", 0.4, 0.14, 0.1),
            ("Que la entidad tiene contratada una póliza de responsabilidad civil con efecto 01/01/2020 y", 0.1, 0.18, 0.8),
            ("vencimiento las 24 horas del día 31/12/2020 cuyo tomador es el ILUSTRE COLEGIO", 0.1, 0.20, 0.8),
            ("DE EJEMPLO DE VILLAEJEMPLO con CIF Q 1234567 D.", 0.1, 0.22, 0.6))
    c, _ = extraer("seguro_rc", d)
    assert c["tomador"] == "ILUSTRE COLEGIO DE EJEMPLO DE VILLAEJEMPLO"
    assert c["aseguradora"] == "SEGUROS EJEMPLO, S.A"
    assert "SEGUROS Y REASEGUROS" not in c["aseguradora"]


def test_poliza_tomador_de_la_poliza_y_entrada_en_vigor():
    """Certificado real: «El Tomador de la póliza» con el nombre debajo; fechas «01.08.2024»."""
    d = doc(("Certificado Seguro Responsabilidad Civil", 0.1, 0.05), ("Nº póliza 84805270", 0.1, 0.08, 0.3),
            ("El Tomador de la póliza", 0.1, 0.15, 0.25), ("UNIVERSIDAD DE EJEMPLO", 0.1, 0.165, 0.3),
            ("NIF:", 0.1, 0.18, 0.05), ("Q1234567D", 0.1, 0.195, 0.12),
            ("Entrada en vigor", 0.1, 0.30, 0.2), ("01.08.2024", 0.1, 0.315, 0.1),
            ("Vencimiento", 0.4, 0.30, 0.15), ("01.08.2025", 0.4, 0.315, 0.1))
    c, v = extraer("seguro_rc", d)
    assert c["tomador"] == "UNIVERSIDAD DE EJEMPLO" and c["identificador"] == "Q1234567D"
    assert c["vigencia_desde"] == date(2024, 8, 1) and c["vigencia_hasta"] == date(2025, 8, 1)
    assert v["fechas_coherentes"]


def _rea_estatal(*empresa):
    """Certificado del REA del modelo estatal: arriba, quien lo pide; tras «CERTIFICA», la empresa."""
    return doc(("REGISTRO DE EMPRESAS ACREDITADAS", 0.3, 0.05), ("CERTIFICADO DE INSCRIPCIÓN", 0.35, 0.10),
               ("DATOS DE LA SOLICITUD", 0.1, 0.15),
               ("Nombre y apellidos", 0.1, 0.18, 0.2), ("LUIS GOMEZ RUIZ", 0.1, 0.195, 0.3),
               ("Nº Identificador", 0.5, 0.18, 0.15), ("NIF", 0.5, 0.195, 0.05), ("12345678Z", 0.56, 0.195, 0.12),
               ("Fecha de la solicitud", 0.75, 0.18, 0.15), ("07/11/2023", 0.75, 0.195, 0.1),
               ("En representación de (si procede):", 0.1, 0.23, 0.3),
               ("Nombre o razón social", 0.1, 0.25, 0.2), ("Nº Identificador", 0.6, 0.25, 0.15),
               ("LA AUTORIDAD LABORAL DE COMUNIDAD DE MADRID", 0.1, 0.30, 0.5),
               ("CERTIFICA:", 0.1, 0.33, 0.1),
               ("Que, según los datos obrantes en el Registro de Empresas Acreditadas, la empresa cuyos datos se indican a",
                0.1, 0.36, 0.8),
               ("continuación figura inscrita en el Registro de", 0.1, 0.375, 0.5),
               ("COMUNIDAD DE MADRID desde el 22/11/2016", 0.1, 0.39, 0.5),
               *empresa)


_REA_EMPRESA = (("Nombre o razón social", 0.1, 0.42, 0.2), ("Nº Inscripción REA", 0.6, 0.42, 0.2),
                ("OBRAS EJEMPLO S.L.", 0.1, 0.435, 0.3), ("12/28/0123456", 0.6, 0.435, 0.15),
                ("Nº Identificador", 0.1, 0.52, 0.15), ("CIF", 0.1, 0.535, 0.05), ("B12345674", 0.16, 0.535, 0.12))


def test_registro_empresa_estatal_no_toma_el_nif_del_solicitante():
    """Caso real: se devolvía el NIF de quien pedía el certificado como identificador de la empresa."""
    c, v = extraer("registro_empresa", _rea_estatal(*_REA_EMPRESA))
    assert c["identificador"] == "B12345674" and v["identificador_valido"]
    assert c["razon_social"] == "OBRAS EJEMPLO S.L"
    assert c["numero_inscripcion"] == "12/28/0123456"
    assert c["fecha"] == date(2016, 11, 22)            # la de inscripción, no la de la solicitud


def test_registro_empresa_estatal_sin_cif_legible_de_la_empresa_queda_vacio():
    """Si el CIF de la empresa no se lee, nunca se usa el NIF del solicitante."""
    c, _ = extraer("registro_empresa", _rea_estatal(*_REA_EMPRESA[:4]))
    assert "identificador" not in c


def test_registro_empresa_sin_cabeceras_y_dos_identificadores_queda_vacio():
    """En una foto el OCR puede perder «DATOS DE LA SOLICITUD» y «CERTIFICA»: con el NIF del
    solicitante y el CIF de la empresa en el texto, no se elige ninguno."""
    d = doc(("REGISTRO DE EMPRESAS ACREDITADAS", 0.3, 0.05),
            ("Nombre y apellidos", 0.1, 0.18, 0.2), ("LUIS GOMEZ RUIZ", 0.1, 0.195, 0.3),
            ("NIF", 0.5, 0.195, 0.05), ("12345678Z", 0.56, 0.195, 0.12), *_REA_EMPRESA)
    c, _ = extraer("registro_empresa", d)
    assert "identificador" not in c
    assert c["numero_inscripcion"] == "12/28/0123456"


def test_registro_empresa_numero_rea_con_espacios():
    """Modelo de Madrid (renovación): «Núm. REA: 12 28 0098249»."""
    d = doc(("ÁREA DE REGISTRO DE EMPRESAS ACREDITADAS", 0.1, 0.05), ("Núm. REA: 12 28 0123456", 0.1, 0.10),
            ("En relación con la solicitud de renovación de la inscripción de la empresa OBRAS EJEMPLO SL, con CIF/NIF",
             0.1, 0.30, 0.8), ("B12345674", 0.1, 0.315, 0.12))
    c, _ = extraer("registro_empresa", d)
    assert c["numero_inscripcion"] == "12/28/0123456" and c["identificador"] == "B12345674"


def test_razon_social_con_forma_juridica_mal_leida_no_se_da_por_buena():
    from mrzlab.extractores.comunes import parece_razon_social
    for bien in ("ESTRUCTURAS DE PRUEBA SL", "ESTRUCTURAS DE PRUEBA, S.L.", "OBRAS EJEMPLO S. A.",
                 "CONSTRUCCIONES PEREZ CB", "OBRAS EJEMPLO SLU", "AYUNTAMIENTO DE VILLAEJEMPLO"):
        assert parece_razon_social(bien), bien
    for mal in ("ESTRUCTURAS DE PRUEBA S", "ESTRUCTURAS DE PRUEBA SI", "CIF", "!", "NOMBRE O RAZON SOCIAL"):
        assert not parece_razon_social(mal), mal


def test_etiqueta_pegada_por_el_ocr_no_es_un_valor():
    d = doc(("DATOS DE LA EMPRESA", 0.1, 0.1), ("NOMBREORAZON SOCIAL", 0.1, 0.2, 0.3), ("CIF/NIF", 0.7, 0.2, 0.1),
            ("CONSTRUCCIONES EJEMPLO SL", 0.1, 0.215, 0.4), ("B12345674", 0.7, 0.215, 0.15))
    c, _ = extraer("apertura_centro_trabajo", d)
    assert c.get("razon_social") in (None, "CONSTRUCCIONES EJEMPLO SL") and c["identificador"] == "B12345674"


# ── Trabajador ───────────────────────────────────────────────────────────────

def _contrato(cif_empresa="B12345674", nif_trabajador="12345678Z"):
    return doc(("CONTRATO DE TRABAJO INDEFINIDO", 0.3, 0.05), ("DATOS DE LA EMPRESA", 0.05, 0.1),
               ("CIF/NIF/NIE", 0.05, 0.12, 0.1), (cif_empresa, 0.06, 0.135, 0.15),
               ("D./DÑA.", 0.05, 0.16, 0.05), ("NIF/NIE", 0.7, 0.16, 0.07),
               ("JUAN REPRESENTANTE LEGAL", 0.06, 0.175, 0.3), ("87654321X", 0.71, 0.175, 0.15),
               ("NOMBRE O RAZÓN SOCIAL DE LA EMPRESA", 0.05, 0.2, 0.3), ("OBRAS EJEMPLO SL", 0.06, 0.215, 0.3),
               ("DATOS DE LA PERSONA TRABAJADORA", 0.05, 0.3), ("D./DÑA.", 0.05, 0.32, 0.05), ("NIF/NIE", 0.7, 0.32, 0.07),
               ("CARMEN PEÑA IBAÑEZ", 0.06, 0.335, 0.3), (nif_trabajador, 0.71, 0.335, 0.15),
               ("DATOS DE LA ASISTENCIA LEGAL", 0.05, 0.5),
               ("CUARTA: la duración será INDEFINIDA, iniciándose la relación laboral en fecha 05/08/2025", 0.05, 0.6, 0.9))


def test_contrato_completo():
    c, v = extraer("contrato_laboral", _contrato())
    assert c == {"identificador_empresa": "B12345674", "razon_social": "OBRAS EJEMPLO SL", "nif_trabajador": "12345678Z",
                 "nombre_trabajador": "CARMEN PEÑA IBAÑEZ", "fecha_inicio": date(2025, 8, 5), "tipo_contrato": "INDEFINIDO"}


def test_contrato_nunca_toma_el_nif_del_representante():
    """CIF leído «817175365» (B↔8): se corrige con el control; y si no se puede, vacío, nunca el
    NIF del representante (87654321X), que está en la misma sección."""
    c, _ = extraer("contrato_laboral", _contrato(cif_empresa="812345674", nif_trabajador="971871300."))
    assert c["identificador_empresa"] == "B12345674"
    assert c["nif_trabajador"] == "97187130D"          # «D» leída como «0», confirmada por el control
    c, _ = extraer("contrato_laboral", _contrato(cif_empresa="????????"))
    assert "identificador_empresa" not in c


def test_reconocimiento_medico_solo_resultado():
    d = doc(("CERTIFICADO DE APTITUD", 0.3, 0.05), ("NIF DEL TRABAJADOR", 0.1, 0.2, 0.2), ("12345678Z", 0.1, 0.215, 0.15),
            ("FECHA DEL RECONOCIMIENTO", 0.5, 0.2, 0.2), ("10/06/2025", 0.5, 0.215, 0.1), ("RESULTADO: APTO", 0.1, 0.3),
            ("Observaciones clínicas: hipertensión controlada", 0.1, 0.4))
    c, v = extraer("reconocimiento_medico", d)
    assert c == {"nif": "12345678Z", "fecha": date(2025, 6, 10), "apto": "APTO"} and v["apto"] is True


def test_reconocimiento_con_todas_las_opciones_sin_marcar_queda_vacio():
    d = doc(("NIF 12345678Z", 0.1, 0.2), ("Fecha: 10/06/2025", 0.1, 0.25), ("APTO   NO APTO   APTO CON RESTRICCIONES", 0.1, 0.3))
    assert "apto" not in extraer("reconocimiento_medico", d)[0]


def test_nombre_de_una_frase_no_es_un_nombre():
    """«… riesgos al trabajador» seguido de «Artículo 18 de la Ley…» no da «DE LA LEY»."""
    d = doc(("REGISTRO DE INFORMACIÓN DE RIESGOS AL TRABAJADOR", 0.2, 0.05, 0.6),
            ("Artículo 18 de la Ley 31/1995", 0.3, 0.07), ("NOMBRE Y APELLIDOS", 0.1, 0.15, 0.3),
            ("JAVIER GOMEZ PEÑA", 0.1, 0.165, 0.3))
    assert extraer("informacion_art18", d)[0]["nombre_trabajador"] == "JAVIER GOMEZ PEÑA"


def test_valor_leido_por_el_otro_motor():
    """Si lo que leyó un motor no encaja (letra final «0»), se usa la lectura del otro."""
    d = doc(("NIF", 0.1, 0.2, 0.05), ("123456780", 0.1, 0.215, 0.15, 0.012, "12345678Z"), ("Fecha: 10/06/2025", 0.1, 0.3))
    assert extraer("formacion_art19", d)[0]["nif_trabajador"] == "12345678Z"


def _titulo_con(linea_nombre):
    return doc(("Considerando que, conforme a las disposiciones vigentes,", 0.2, 0.3, 0.6),
               (linea_nombre, 0.25, 0.35, 0.5),
               ("Máster Universitario en Prevención de Riesgos Laborales", 0.2, 0.45, 0.6),
               ("por la Universidad de Ejemplo", 0.3, 0.5), ("Dado en Madrid, a 3 de octubre de 2017", 0.35, 0.6))


@pytest.mark.parametrize("linea,trat", [("Don Miguel Ángel Pérez Cuadro", "DON"),
                                        ("Doña Lucía Ortega Peña", "DOÑA"),
                                        ("D. Luis Gómez Ruiz", "DON"),
                                        ("Dña. Marta Sanz Vidal", "DOÑA")])
def test_titular_tras_don_dona(linea, trat):
    c, v = extraer("ts_prl", _titulo_con(linea))
    assert c["tratamiento"] == trat and v["titular_tras_don_dona"] is True


def test_titular_con_d_dna_no_dice_el_sexo():
    c, v = extraer("ts_prl", _titulo_con("D./Dña. Luis Gómez Ruiz con NIF 01234567L"))
    assert c["titular"] == "LUIS GOMEZ RUIZ" and "tratamiento" not in c
    assert v["titular_tras_don_dona"] is False
