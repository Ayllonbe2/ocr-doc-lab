"""NIF, NIE, CIF, fechas e importes. Todos los datos son ficticios."""
from datetime import date

import pytest

from mrzlab import validadores as v


@pytest.mark.parametrize("nif", ["12345678Z", "12.345.678-z", "X1234567L", "y1234567x", "00000000T"])
def test_nif_valido(nif):
    assert v.nif_valido(nif)


@pytest.mark.parametrize("nif", ["12345678A", "1234567Z", "X1234567A", "ABCDEFGHI", ""])
def test_nif_invalido(nif):
    assert not v.nif_valido(nif)


# Inventados: B (control con cifra), P (con letra), G (vale cualquiera de las dos).
@pytest.mark.parametrize("cif", ["B12345674", "P1234567D", "G12345674", "G1234567D"])
def test_cif_valido(cif):
    assert v.cif_valido(cif)


@pytest.mark.parametrize("cif", ["B12345675", "B1234567D", "P12345674", "B1234567", "12345678Z"])
def test_cif_invalido(cif):
    assert not v.cif_valido(cif)


def test_buscar_nifs_solo_con_letra_correcta_y_sin_repetir():
    texto = "NIF 12345678Z y también 12345678Z; otro con letra mala 87654321A y NIE X-1234567-L"
    assert v.buscar_nifs(texto) == ["12345678Z", "X1234567L"]


def test_dni_de_siete_cifras_se_completa_con_cero():
    # Los DNI antiguos se escriben con 7 cifras («1.234.567-L» es el 01234567).
    assert v.buscar_nifs("con DNI 1.234.567-L,") == ["01234567L"]


def test_no_se_toma_un_nif_dentro_de_un_numero_mas_largo():
    assert v.buscar_nifs("teléfono 912345678Z") == []


def test_correccion_de_la_letra_solo_si_la_valida_el_control():
    # «D» leída como «0»: sin corregir no hay NIF; corrigiendo, sí, porque la letra cuadra.
    assert v.buscar_nifs("97187130 0.") == [] and v.buscar_nifs("971871300.") == []
    assert v.buscar_nifs("971871300.", corregir=True) == ["97187130D"]
    # Si ninguna corrección cuadra con la letra de control, nada.
    assert v.buscar_nifs("971871301", corregir=True) == []


def test_correccion_de_la_letra_inicial_del_cif():
    assert v.buscar_cifs("812345674") == []
    assert v.buscar_cifs("812345674", corregir=True) == ["B12345674"]


@pytest.mark.parametrize("texto,esperada", [
    ("14/03/2025", date(2025, 3, 14)),
    ("14-03-2025", date(2025, 3, 14)),
    ("14.03.25", date(2025, 3, 14)),
    ("14 de marzo de 2025", date(2025, 3, 14)),
    ("Madrid, a 1 de SEPTIEMBRE del 2024", date(2024, 9, 1)),
    ("3 demayo de1985", date(1985, 5, 3)),          # palabras pegadas por el OCR
    ("15 de noviembrede2010", date(2010, 11, 15)),
])
def test_fechas(texto, esperada):
    assert v.leer_fecha(texto) == esperada


def test_fechas_imposibles_no_cuentan():
    assert v.leer_fecha("31/02/2025") is None and v.leer_fecha("45 de marzo de 2025") is None


@pytest.mark.parametrize("texto,importe", [
    ("Límite por siniestro: 600.000,00 €", 600000.0),
    ("1.200.000 euros", 1200000.0),
    ("prima de 1.250,5 EUR", 1250.5),
])
def test_importes(texto, importe):
    assert v.buscar_importes(texto) == [importe]


def test_sin_acentos_conserva_la_enye():
    assert v.sin_acentos("Peña Ibáñez, José") == "PEÑA IBAÑEZ, JOSE"
