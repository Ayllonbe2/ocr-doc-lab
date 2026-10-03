"""Cotejo anverso ↔ reverso (datos ficticios)."""
from fastapi.testclient import TestClient

from mrzlab import cotejo
from mrzlab.app import app

REVERSO = {"dni": "99999999R", "fecha_nacimiento": "01/01/1980", "apellidos": "ESPANOLA ESPANOLA",
           "nombre": "CARMEN", "fecha_caducidad": "01/01/2030", "num_soporte": "BAA000589"}


def _anv(**campos):
    return {k: [{"valor": v, "fuente": "prueba"}] for k, v in campos.items()}


def _todo(**cambios):
    base = {"dni": "99999999R", "fecha_nacimiento": "01/01/1980", "apellidos": "ESPAÑOLA ESPAÑOLA",
            "nombre": "CARMEN", "fecha_caducidad": "01/01/2030"}
    return _anv(**{**base, **cambios})


def test_cuadra_con_tildes_y_enie():
    r = cotejo.cotejar(_todo(), REVERSO)
    assert r["resultado"] == "cuadra"
    assert r["campos"]["apellidos"]["nota"] == "igual salvo tildes, Ñ o signos"


def test_fecha_distinta_no_cuadra():
    r = cotejo.cotejar(_todo(fecha_caducidad="01/01/2031"), REVERSO)
    assert r["resultado"] == "no_cuadra"
    assert r["campos"]["fecha_caducidad"]["estado"] == "distinto"
    assert r["campos"]["dni"]["estado"] == "coincide"


def test_nombre_con_una_letra_mal_leida_es_parecido():
    r = cotejo.cotejar(_todo(nombre="CARNEN"), REVERSO)
    assert r["resultado"] == "revisar"
    assert r["campos"]["nombre"]["estado"] == "parecido"


def test_falta_un_campo_es_revisar():
    anv = _todo()
    del anv["fecha_nacimiento"]
    r = cotejo.cotejar(anv, REVERSO)
    assert r["resultado"] == "revisar"
    assert r["campos"]["fecha_nacimiento"]["estado"] == "falta"


def test_elige_el_candidato_que_coincide():
    anv = _todo()
    anv["dni"] = [{"valor": "99999990R", "fuente": "a"}, {"valor": "99999999R", "fuente": "b"}]
    c = cotejo.cotejar(anv, REVERSO)["campos"]["dni"]
    assert c["estado"] == "coincide" and c["fuente"] == "b"
    assert c["otros_anverso"] == ["99999990R"]


def test_nombre_cortado_en_la_mrz():
    rev = {**REVERSO, "apellidos": "DE LA FUENTE MARTINEZ", "nombre": "MARIA DEL"}
    anv = _todo(apellidos="DE LA FUENTE MARTÍNEZ", nombre="MARÍA DEL CARMEN")
    c = cotejo.cotejar(anv, rev)["campos"]["nombre"]
    assert c["estado"] == "coincide" and "cortado" in c["nota"]


def test_nombre_mas_largo_sin_linea_llena_no_coincide():
    c = cotejo.cotejar(_todo(nombre="CARMEN LUISA"), REVERSO)["campos"]["nombre"]
    assert c["estado"] == "distinto"


def test_guion_es_separador():
    rev = {**REVERSO, "apellidos": "GARCIA LOPEZ"}
    c = cotejo.cotejar(_todo(apellidos="GARCÍA-LÓPEZ"), rev)["campos"]["apellidos"]
    assert c["estado"] == "coincide"


def test_api():
    cliente = TestClient(app)
    r = cliente.post("/api/cotejo", json={"anverso": _todo(), "reverso": REVERSO})
    assert r.status_code == 200 and r.json()["resultado"] == "cuadra"
    assert cliente.post("/api/cotejo", json={"anverso": []}).status_code == 400


def test_decision_aprobar_si_cuadra():
    r = cotejo.cotejar(_todo(), REVERSO)
    assert r["decision"] == "aprobar"


def test_decision_aprobar_con_nombre_parecido():
    r = cotejo.cotejar(_todo(nombre="CARNEN"), REVERSO)
    assert r["resultado"] == "revisar" and r["decision"] == "aprobar"


def test_decision_rechazar_si_un_dato_es_distinto():
    r = cotejo.cotejar(_todo(dni="12345678Z"), REVERSO)
    assert r["decision"] == "rechazar" and "dni" in r["motivo"]


def test_decision_revisar_sin_mrz_valida_o_sin_leer():
    assert cotejo.cotejar(_todo(), REVERSO, mrz_valida=False)["decision"] == "revisar"
    anv = _todo()
    del anv["nombre"]
    assert cotejo.cotejar(anv, REVERSO)["decision"] == "revisar"


def test_similitud_70_entre_caras():
    assert cotejo.cotejar(_todo(nombre="CARMXN"), REVERSO)["campos"]["nombre"]["estado"] == "parecido"
    # «CARLOS» vs «CARMEN»: 50 % → distinto
    assert cotejo.cotejar(_todo(nombre="CARLOS"), REVERSO)["campos"]["nombre"]["estado"] == "distinto"


def test_declarado_coincide_en_cualquier_orden():
    r = cotejo.cotejar(_todo(), REVERSO, declarado={"dni": "99999999-r", "nombre": "Carmen Española Española"})
    assert r["declarado"]["dni"]["estado"] == "coincide"
    assert r["declarado"]["nombre"]["estado"] == "coincide"
    assert r["decision"] == "aprobar"
    r = cotejo.cotejar(_todo(), REVERSO, declarado={"nombre": "Española Española, Carmen"})
    assert r["declarado"]["nombre"]["similitud"] == 1


def test_declarado_nombre_parecido_aprueba():
    r = cotejo.cotejar(_todo(), REVERSO, declarado={"nombre": "Carmen Espanyola Espanola"})
    assert r["declarado"]["nombre"]["estado"] == "parecido"
    assert r["decision"] == "aprobar"
    # Sin el 2.º apellido queda en ~62 %: por debajo del 70 %.
    r = cotejo.cotejar(_todo(), REVERSO, declarado={"nombre": "Carmen Española"})
    assert r["declarado"]["nombre"]["estado"] == "distinto"


def test_declarado_distinto_rechaza():
    r = cotejo.cotejar(_todo(), REVERSO, declarado={"dni": "12345678Z"})
    assert r["decision"] == "rechazar" and "dni declarado" in r["motivo"]
    r = cotejo.cotejar(_todo(), REVERSO, declarado={"nombre": "Pedro Gómez Ruiz"})
    assert r["declarado"]["nombre"]["estado"] == "distinto" and r["decision"] == "rechazar"


def test_api_con_declarado():
    r = TestClient(app).post("/api/cotejo", json={"anverso": _todo(), "reverso": REVERSO,
                                                   "declarado": {"dni": "99999999R", "nombre": "Carmen Española Española"}})
    assert r.status_code == 200 and r.json()["decision"] == "aprobar"
