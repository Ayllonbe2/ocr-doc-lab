from mrzlab import mrz
from mrzlab.sintetico import MRZ_EJEMPLO


def test_digito_control_ejemplos_icao():
    # Ejemplos del documento ICAO 9303, parte 3.
    assert mrz.digito_control("520727") == "3"
    assert mrz.digito_control("L898902C3") == "6"
    assert mrz.digito_control("<<<") == "0"


def test_letra_dni():
    assert mrz.letra_dni("99999999") == "R"
    assert mrz.letra_dni("12345678") == "Z"
    assert mrz.letra_dni("1234567") is None


def test_parsea_mrz_valida():
    r = mrz.parsear_td1(MRZ_EJEMPLO)
    assert r.valido
    assert r.correcciones == []
    assert r.campos == {
        "tipo": "ID", "pais": "ESP", "num_soporte": "BAA000589", "dni": "99999999R",
        "fecha_nacimiento": "01/01/1980", "sexo": "F", "fecha_caducidad": "01/01/2031",
        "nacionalidad": "ESP", "apellidos": "ESPANOLA ESPANOLA", "nombre": "CARMEN",
    }


def test_corrige_confusiones_letra_digito():
    lineas = ["IDESPBAAO00589599999999R<<<<<<",   # O en lugar de 0 en el soporte
              "8OO1O14F31O1O12ESP<<<<<<<<<<<5",   # O en lugar de 0 en las fechas
              "ESPAN0LA<ESPAN0LA<<CARMEN<<<<<"]   # 0 en lugar de O en el nombre
    r = mrz.parsear_td1(lineas)
    assert r.valido
    assert r.campos["num_soporte"] == "BAA000589"
    assert r.campos["fecha_nacimiento"] == "01/01/1980"
    assert r.campos["apellidos"] == "ESPANOLA ESPANOLA"
    assert r.correcciones


def test_detecta_digito_erroneo():
    # Un 9 leído como 8 en el DNI: la letra deja de cuadrar y el compuesto también.
    lineas = list(MRZ_EJEMPLO)
    lineas[0] = lineas[0].replace("99999999R", "99989999R")
    r = mrz.parsear_td1(lineas)
    assert not r.valido
    assert r.controles["letra_dni"] is False
    assert r.controles["compuesto"] is False


def test_detecta_fecha_erronea():
    lineas = list(MRZ_EJEMPLO)
    lineas[1] = "8001024" + lineas[1][7:]
    r = mrz.parsear_td1(lineas)
    assert r.controles["nacimiento"] is False


def test_elige_lineas_entre_ruido():
    candidatas = ["DOMICILIO", "C. EJEMPLO 1", "28000A1B2",
                  "IDESP BAA000589 5 99999999R <<<<<<", MRZ_EJEMPLO[1], MRZ_EJEMPLO[2], "otra cosa"]
    r = mrz.leer(candidatas)
    assert r is not None and r.valido


def test_elimina_caracter_sobrante():
    lineas = ["IDESPBAAO000589599999999R<<<<<<", MRZ_EJEMPLO[1], MRZ_EJEMPLO[2]]
    r = mrz.leer(lineas)
    assert r.valido
    assert "sobraba" in r.correcciones[0]


def test_rellena_linea_corta():
    lineas = [MRZ_EJEMPLO[0].rstrip("<"), MRZ_EJEMPLO[1], MRZ_EJEMPLO[2].rstrip("<")]
    r = mrz.leer(lineas)
    assert r.valido


def test_simbolos_confundidos_con_relleno():
    lineas = [MRZ_EJEMPLO[0].replace("<", "«"), MRZ_EJEMPLO[1], MRZ_EJEMPLO[2]]
    assert mrz.leer(lineas).valido


def test_sin_mrz():
    assert mrz.leer(["hola", "mundo"]) is None


# Regresiones: lecturas reales de OCR sobre fotos sintéticas que se daban por válidas
# con datos erróneos (los dígitos de control cuadraban por azar).

def test_no_reintroduce_letras_en_fechas():
    r = mrz.leer(["IDESPHAV882782721186859H<<<<<<",
                  "93O3ZZ7M3504130ESP<<<<<<<<<<<5",   # nacimiento real: 950322
                  "FERNANDEZ<GARCIA<<DAVID<<<<<<<"])
    assert not r.valido


def test_quitar_caracter_solo_si_queda_valida_y_es_unico():
    r = mrz.leer(["IDESPSYZ3706712516213487M<<<<<<",  # soporte real: SYZ376712
                  "6109097F3511255ESP<<<<<<<<<<<8",
                  "HERNANDEZ<LOPEZ<<LUCIA<<<<<<<<"])
    assert not r.valido or r.campos["num_soporte"] == "SYZ376712"


def test_pais_mal_leido_no_desactiva_controles():
    r = mrz.leer(["I1DESPCF2329S99746081183O<<<<<<",  # país «DES»: estructura incorrecta
                  "6711056F3202023ESP<<<<<<<<<<<7",
                  "PEREZ<GONZALEZ<<ISABEL<<<<<<<<"])
    assert not r.valido


def test_formato_soporte_dni():
    lineas = list(MRZ_EJEMPLO)
    r = mrz.parsear_td1(lineas)
    assert r.controles["formato_soporte"] and r.controles["estructura"] and r.controles["fechas"]


def test_mrz_generada_es_valida():
    import numpy as np
    from mrzlab import sintetico
    rng = np.random.default_rng(0)
    for _ in range(50):
        ident = sintetico.identidad_aleatoria(rng)
        r = mrz.parsear_td1(ident["lineas"])
        assert r.valido, ident
        for campo, valor in ident["verdad"].items():
            assert r.campos[campo] == valor, (campo, ident)


def test_nombre_con_digitos_no_es_valido():
    # La línea 3 no tiene dígito de control: un «3OSE» no se detectaría por checksum.
    lineas = list(MRZ_EJEMPLO)
    lineas[2] = "ESPANOLA<ESPANOLA<<CARMEN3<<<<"
    r = mrz.parsear_td1(lineas)
    assert r.controles["formato_nombre"] is False
    assert not r.valido


# ── Mejoras de acierto (sin abrir la puerta a falsos válidos) ──────────────────

def _con_dni(letra_leida: str) -> list[str]:
    """MRZ válida de 12345678Z con la letra sustituida y el compuesto de la original."""
    from mrzlab.sintetico import construir_mrz
    lineas = construir_mrz("BAA000589", "12345678", "800101", "F", "310101", "GARCIA<LOPEZ", "ANA")
    lineas[0] = lineas[0][:23] + letra_leida + lineas[0][24:]
    return lineas


def test_descarta_basura_antes_de_idesp():
    lineas = ["I" + MRZ_EJEMPLO[0], MRZ_EJEMPLO[1], MRZ_EJEMPLO[2]]
    r = mrz.leer(lineas)
    assert r.valido and r.campos["dni"] == "99999999R"
    assert any("descartado" in c for c in r.correcciones)


def test_no_ancla_nombres():
    assert mrz.anclar_linea1("MARIANO<GARCIA<<ANA<<<<<<<<<<<") == "MARIANO<GARCIA<<ANA<<<<<<<<<<<"


def test_recupera_letra_dni_confirmada_por_compuesto():
    r = mrz.leer(_con_dni("2"))   # la Z de 12345678Z leída como «2»: la corrige _forzar
    assert r.valido and r.campos["dni"] == "12345678Z"
    from mrzlab.sintetico import construir_mrz
    # D leída como «0» (la O no es letra de DNI): se recupera si el compuesto lo confirma.
    dni8 = next(f"{n:08d}" for n in range(1, 10**4) if mrz.letra_dni(f"{n:08d}") == "D")
    lineas = construir_mrz("BAA000589", dni8, "800101", "F", "310101", "GARCIA", "ANA")
    lineas[0] = lineas[0][:23] + "0" + lineas[0][24:]
    r = mrz.leer(lineas)
    assert r.valido and r.campos["dni"] == dni8 + "D"
    assert any("confirmada por el control compuesto" in c for c in r.correcciones)


def test_no_recupera_letra_si_un_digito_esta_mal():
    from mrzlab.sintetico import construir_mrz
    dni8 = next(f"{n:08d}" for n in range(1, 10**4) if mrz.letra_dni(f"{n:08d}") == "D")
    lineas = construir_mrz("BAA000589", dni8, "800101", "F", "310101", "GARCIA", "ANA")
    # Un dígito del DNI mal leído y la letra ilegible: no debe inventarse una letra válida.
    malo = dni8[:7] + str((int(dni8[7]) + 1) % 10)
    lineas[0] = lineas[0][:15] + malo + "0" + lineas[0][24:]
    r = mrz.leer(lineas)
    assert not r.valido or r.campos["dni"][:8] == dni8


def test_linea_con_caracter_insertado_y_dos_soluciones_es_ambigua():
    # Caso real: un «0» insertado en el DNI y la línea 2 con un carácter de más. Recortar el
    # final cuadraba por azar (letra y compuesto) con un DNI falso; quitar el «0» da el real.
    r = mrz.leer(["IDESPATT2GB5104541880506X<<<<<<",
                  "0211200F350514BESP<<<<<<<<<<<06",
                  "ALONSO<MARTIN<<MARIA<<<<<<<<<<"])
    assert not r.valido or r.campos["dni"] == "54188056X"
