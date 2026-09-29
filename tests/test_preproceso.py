import cv2
import numpy as np

from mrzlab import deteccion, preproceso, sintetico as s


def test_endereza_tarjeta_en_perspectiva():
    rng = np.random.default_rng(3)
    foto = s.perspectiva(s.reverso(), rng, fuerza=0.08)
    tarjeta = preproceso.enderezar_tarjeta(foto)
    assert tarjeta is not None
    h, w = tarjeta.shape[:2]
    assert abs(w / h - preproceso.PROPORCION_ID1) < 0.01
    # Tras enderezar, la MRZ sigue abajo y ocupa casi todo el ancho.
    x, y, cw, ch = deteccion.localizar_mrz(tarjeta)
    assert y > h * 0.5 and cw > w * 0.7


def test_tarjeta_vertical_queda_apaisada():
    foto = cv2.rotate(s.reverso(), cv2.ROTATE_90_CLOCKWISE)
    tarjeta = preproceso.enderezar_tarjeta(foto)
    assert tarjeta is not None and tarjeta.shape[1] > tarjeta.shape[0]


def test_sin_tarjeta_devuelve_none():
    assert preproceso.enderezar_tarjeta(np.full((600, 900, 3), 128, np.uint8)) is None


def test_clahe_y_umbral_adaptativo_mantienen_tamano():
    gris = cv2.cvtColor(s.sombra(s.reverso(), np.random.default_rng(1)), cv2.COLOR_BGR2GRAY)
    assert preproceso.clahe(gris).shape == gris.shape
    binaria = preproceso.umbral_adaptativo(gris, 48)
    assert binaria.shape == gris.shape and set(np.unique(binaria)) <= {0, 255}
