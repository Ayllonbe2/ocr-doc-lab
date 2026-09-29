import csv

import pytest

from mrzlab import lote, motores, sintetico


def test_normalizar():
    assert lote.normalizar("Muñoz  García", "apellidos") == "MUNOZ GARCIA"
    assert lote.normalizar("1980-01-05", "fecha_nacimiento") == "05/01/1980"
    assert lote.normalizar("5/1/1980", "fecha_nacimiento") == "05/01/1980"
    assert lote.normalizar(None, "dni") == ""


def test_comparar_acepta_nombre_recortado_por_la_mrz():
    verdad = {"nombre": "JOSE LUIS", "apellidos": "GUTIERREZ DE LA TORRE", "dni": "12345678Z"}
    leido = {"nombre": "JOSE LU", "apellidos": "GUTIERREZ DE LA TORRE", "dni": "12345678Z"}
    llena = "GUTIERREZ<DE<LA<TORRE<<JOSE<LU"
    assert all(lote.comparar(leido, verdad, llena).values())
    # Si la línea no está llena, el recorte no es de la MRZ sino un error de lectura.
    assert not lote.comparar(leido, verdad, llena[:-1] + "<")["nombre"]


def test_comparar_ignora_columnas_vacias():
    assert lote.comparar({"dni": "1"}, {"dni": "", "nombre": "ANA"}, None) == {"nombre": False}


def test_buscar_verdad_por_nombre_y_patron(tmp_path):
    ruta = tmp_path / "verdad.csv"
    ruta.write_text("archivo;dni\nfoto1.jpg;11111111H\nesp_id/*.jpg;22222222J\n", encoding="utf-8")
    verdad = lote.cargar_verdad(ruta)
    assert lote.buscar_verdad(verdad, "sub/foto1.jpg")["dni"] == "11111111H"
    assert lote.buscar_verdad(verdad, "esp_id/0001.jpg")["dni"] == "22222222J"
    assert lote.buscar_verdad(verdad, "otra.jpg") is None


def test_lote_de_extremo_a_extremo(tmp_path, capsys):
    if not motores.Tesseract().disponible()[0]:
        pytest.skip("tesseract no disponible")
    carpeta = tmp_path / "fotos"
    sintetico.generar_lote(str(carpeta), 3, semilla=5)
    salida = tmp_path / "res.csv"
    assert lote.main([str(carpeta), "--csv", str(salida), "--motores", "tesseract"]) == 0
    filas = list(csv.DictReader(open(salida, encoding="utf-8-sig"), delimiter=";"))
    assert len(filas) == 3
    assert {"tesseract.valido", "tesseract.campos_ok", "tesseract.valido_pero_erroneo"} <= filas[0].keys()
    # El CSV no lleva datos personales.
    texto = salida.read_text(encoding="utf-8-sig")
    for fila in csv.DictReader(open(carpeta / "verdad.csv", encoding="utf-8"), delimiter=";"):
        assert fila["dni"] not in texto and fila["apellidos"] not in texto
    assert "Acierto por campo" in capsys.readouterr().out


def test_resumen_con_reintentos():
    def f(archivo, grupo, veredicto, valido):
        return {"archivo": archivo, "grupo": grupo, "veredicto": veredicto,
                "tesseract.valido": "si" if valido else "no", "tesseract.ms": "100"}
    filas = [f("a-t1", "a", "apta", True), f("a-t2", "a", "apta", False),
             f("b-t1", "b", "rechazar", True), f("b-t2", "b", "apta", True),   # 1.ª rechazada
             f("c-t1", "c", "apta", False), f("c-t2", "c", "riesgo", False)]
    texto = lote.resumen(filas, ["tesseract"], con_verdad=False)
    assert "Con reintentos (3 DNI" in texto
    lineas = [l for l in texto.splitlines() if l.count("%") == 2 and l[11:14].strip() in "AB"]
    politica_a, politica_b = lineas[-2], lineas[-1]
    assert "33.3 %" in politica_a and "66.7 %" in politica_a   # con filtro de calidad
    assert politica_b.split()[1] == "66.7"                     # sin filtro: b-t1 ya vale


def test_letras_del_soporte_solo_parcialmente_protegidas():
    # M y W valen 22 y 32: el dígito de control ICAO no las distingue.
    verdad = {"num_soporte": "WNU840679"}
    r = lote.comparar({"num_soporte": "MNU840679"}, verdad, None)
    assert r["soporte_digitos"] is True and r["soporte_letras"] is False
    assert "soporte_digitos" in lote.PROTEGIDOS and "soporte_letras" in lote.SIN_CONTROL
