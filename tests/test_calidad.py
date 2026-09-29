from pathlib import Path

import pytest

from mrzlab import calidad, deteccion, sintetico as s

UMBRALES = calidad.cargar_umbrales(Path(__file__).resolve().parent.parent / "umbrales.yaml")


@pytest.fixture(scope="module")
def limpia():
    return s.reverso()


def _evaluar(img):
    return calidad.evaluar(img, UMBRALES, deteccion.localizar_mrz(img))


def _metricas_con_aviso(ev, zona=None):
    return {a["metrica"] for a in ev.avisos if zona is None or a["zona"] == zona}


def test_localiza_la_mrz_en_la_parte_baja(limpia):
    caja = deteccion.localizar_mrz(limpia)
    assert caja is not None
    x, y, w, h = caja
    alto, ancho = limpia.shape[:2]
    assert y > alto * 0.5            # está en la mitad inferior
    assert w > ancho * 0.6           # ocupa casi todo el ancho de la tarjeta
    assert 2.5 < w / h < 8


def test_imagen_limpia_es_apta(limpia):
    ev = _evaluar(limpia)
    assert ev.veredicto == "apta", ev.avisos


def test_borrosa(limpia):
    ev = _evaluar(s.desenfocar(limpia))
    assert "nitidez" in _metricas_con_aviso(ev, "mrz")
    assert ev.veredicto == "rechazar"


def test_oscura(limpia):
    ev = _evaluar(s.oscurecer(limpia))
    assert "brillo_bajo" in _metricas_con_aviso(ev)
    assert ev.veredicto == "rechazar"


def test_sobreexpuesta(limpia):
    ev = _evaluar(s.sobreexponer(limpia))
    avisos = _metricas_con_aviso(ev)
    assert "quemados" in avisos or "brillo_alto" in avisos
    assert ev.veredicto == "rechazar"


def test_reflejo_sobre_la_mrz(limpia):
    ev = _evaluar(s.reflejo(limpia, centro=(0.5, 0.8)))
    assert "reflejo" in _metricas_con_aviso(ev, "mrz")
    assert ev.reflejos


def test_reflejo_fuera_de_la_mrz_solo_avisa(limpia):
    ev = _evaluar(s.reflejo(limpia, centro=(0.75, 0.3), radio=0.1))
    assert "reflejo" not in _metricas_con_aviso(ev, "mrz")
    assert ev.veredicto in ("apta", "riesgo")


def test_baja_resolucion(limpia):
    ev = _evaluar(s.reducir(limpia, 0.3))
    assert "lado_min_px" in _metricas_con_aviso(ev)


def test_nitidez_normalizada_por_resolucion(limpia):
    # La misma foto a dos resoluciones debe dar una nitidez del mismo orden.
    g1 = calidad._gris(limpia)
    g2 = calidad._gris(s.reducir(limpia, 0.7))
    n1, n2 = calidad.nitidez(g1, 1000), calidad.nitidez(g2, 1000)
    assert 0.5 < n1 / n2 < 2
