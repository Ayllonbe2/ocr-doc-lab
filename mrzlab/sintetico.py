"""Genera reversos de DNI sintéticos (datos ficticios) y los degrada a propósito.

Solo para tests y para probar la herramienta sin fotos reales. No imita el diseño del
DNI: es una tarjeta genérica con una MRZ válida en la parte inferior.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MRZ_EJEMPLO = [
    "IDESPBAA000589599999999R<<<<<<",
    "8001014F3101012ESP<<<<<<<<<<<5",
    "ESPANOLA<ESPANOLA<<CARMEN<<<<<",
]

_FUENTES_MONO = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
]
_FUENTES_SANS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _fuente(rutas: list[str], tam: int) -> ImageFont.FreeTypeFont:
    for r in rutas:
        try:
            return ImageFont.truetype(r, tam)
        except OSError:
            continue
    return ImageFont.load_default(tam)


def reverso(lineas: list[str] | None = None, ancho_tarjeta: int = 1284) -> np.ndarray:
    """Foto sintética: tarjeta clara sobre una mesa, con la MRZ abajo. Devuelve BGR."""
    lineas = lineas or MRZ_EJEMPLO
    tw, th = ancho_tarjeta, round(ancho_tarjeta * 54 / 85.6)
    margen = round(tw * 0.12)
    lienzo = Image.new("RGB", (tw + 2 * margen, th + 2 * margen), (96, 84, 72))
    tarjeta = Image.new("RGB", (tw, th), (226, 234, 228))
    d = ImageDraw.Draw(tarjeta)

    # Fondo de seguridad genérico: ondas finas de color.
    for i in range(0, th, max(4, th // 60)):
        d.line([(0, i), (tw, i + th // 8)], fill=(206, 222, 214), width=1)

    etiquetas = _fuente(_FUENTES_SANS, max(10, th // 30))
    dato = _fuente(_FUENTES_SANS, max(12, th // 22))
    y = round(th * 0.06)
    for etiqueta, valor in [("DOMICILIO", "C. EJEMPLO 1"), ("LUGAR DE NACIMIENTO", "MADRID"),
                            ("HIJO/A DE", "JUAN / MARIA"), ("EQUIPO", "28000A1B2")]:
        d.text((round(tw * 0.05), y), etiqueta, fill=(90, 100, 110), font=etiquetas)
        d.text((round(tw * 0.05), y + th // 26), valor, fill=(30, 30, 40), font=dato)
        y += round(th * 0.12)

    # MRZ: 30 caracteres deben ocupar ~88 % del ancho de la tarjeta.
    mono = _fuente(_FUENTES_MONO, 100)
    ancho_100 = d.textlength("<" * 30, font=mono)
    mono = _fuente(_FUENTES_MONO, int(100 * tw * 0.88 / ancho_100))
    paso = round(th * 0.105)
    y0 = th - round(th * 0.06) - 3 * paso
    for i, linea in enumerate(lineas):
        d.text((round(tw * 0.06), y0 + i * paso), linea, fill=(20, 20, 25), font=mono)

    lienzo.paste(tarjeta, (margen, margen))
    return cv2.cvtColor(np.array(lienzo), cv2.COLOR_RGB2BGR)


# ── Degradaciones ────────────────────────────────────────────────────────────

def desenfocar(img: np.ndarray, radio: int = 9) -> np.ndarray:
    k = radio * 2 + 1
    return cv2.GaussianBlur(img, (k, k), 0)


def oscurecer(img: np.ndarray, factor: float = 0.2) -> np.ndarray:
    return np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def sobreexponer(img: np.ndarray, suma: int = 150) -> np.ndarray:
    return np.clip(img.astype(np.int16) + suma, 0, 255).astype(np.uint8)


def reflejo(img: np.ndarray, centro: tuple[float, float] = (0.5, 0.8),
            radio: float = 0.12) -> np.ndarray:
    """Mancha blanca saturada con bordes suaves; centro y radio relativos a la imagen."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy, r = centro[0] * w, centro[1] * h, radio * min(h, w)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
    alfa = np.clip(1.6 - dist, 0, 1)[..., None]
    return (img * (1 - alfa) + 255 * alfa).astype(np.uint8)


def reducir(img: np.ndarray, factor: float = 0.3) -> np.ndarray:
    h, w = img.shape[:2]
    return cv2.resize(img, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_AREA)


# ── Fotos de móvil realistas ─────────────────────────────────────────────────

def perspectiva(img: np.ndarray, rng: np.random.Generator, fuerza: float = 0.06) -> np.ndarray:
    """Mueve las esquinas al azar, como una foto no tomada de frente."""
    h, w = img.shape[:2]
    origen = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = rng.uniform(-fuerza, fuerza, (4, 2)) * [w, h]
    destino = np.float32(origen + jitter)
    m = cv2.getPerspectiveTransform(origen, destino)
    return cv2.warpPerspective(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE)


def movimiento(img: np.ndarray, longitud: int = 9, angulo: float = 0.0) -> np.ndarray:
    """Desenfoque de movimiento (pulso tembloroso)."""
    k = np.zeros((longitud, longitud), np.float32)
    k[longitud // 2, :] = 1
    rot = cv2.getRotationMatrix2D((longitud / 2 - 0.5, longitud / 2 - 0.5), angulo, 1)
    k = cv2.warpAffine(k, rot, (longitud, longitud))
    return cv2.filter2D(img, -1, k / max(k.sum(), 1e-6))


def degradado_luz(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Luz desigual: un lado más oscuro que otro, más viñeteado."""
    h, w = img.shape[:2]
    ang = rng.uniform(0, 2 * np.pi)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    lineal = (np.cos(ang) * (xx / w - 0.5) + np.sin(ang) * (yy / h - 0.5))
    fuerza = rng.uniform(0.2, 0.6)
    vinieta = 1 - 0.35 * (((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) * 2)
    factor = (1 + fuerza * lineal) * vinieta
    return np.clip(img * factor[..., None], 0, 255).astype(np.uint8)


def sombra(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Sombra de la mano o del móvil: un polígono oscuro con bordes suaves."""
    h, w = img.shape[:2]
    pts = np.int32(rng.uniform([0, 0], [w, h], (4, 2)))
    mascara = np.zeros((h, w), np.float32)
    cv2.fillConvexPoly(mascara, cv2.convexHull(pts), 1.0)
    mascara = cv2.GaussianBlur(mascara, (0, 0), max(h, w) / 40)
    oscuridad = rng.uniform(0.35, 0.6)
    return np.clip(img * (1 - oscuridad * mascara[..., None]), 0, 255).astype(np.uint8)


def ruido(img: np.ndarray, rng: np.random.Generator, sigma: float = 8.0) -> np.ndarray:
    return np.clip(img + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


def jpeg(img: np.ndarray, calidad: int = 60) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def foto_movil(img: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, list[str]]:
    """Aplica al azar las degradaciones típicas de una foto de móvil. Devuelve qué aplicó."""
    aplicadas = []
    img = perspectiva(img, rng)
    aplicadas.append("perspectiva")
    if rng.random() < 0.7:
        img = degradado_luz(img, rng)
        aplicadas.append("luz desigual")
    if rng.random() < 0.3:
        img = sombra(img, rng)
        aplicadas.append("sombra")
    if rng.random() < 0.25:
        img = reflejo(img, (rng.uniform(0.2, 0.8), rng.uniform(0.2, 0.9)), rng.uniform(0.05, 0.12))
        aplicadas.append("reflejo")
    if rng.random() < 0.4:
        lon = int(rng.integers(5, 17))
        img = movimiento(img, lon, rng.uniform(0, 180))
        aplicadas.append(f"movimiento {lon}px")
    elif rng.random() < 0.3:
        img = desenfocar(img, int(rng.integers(1, 5)))
        aplicadas.append("desenfoque")
    escala = rng.uniform(0.45, 1.0)
    img = reducir(img, escala)
    aplicadas.append(f"escala {escala:.2f}")
    img = ruido(img, rng, rng.uniform(2, 10))
    q = int(rng.integers(45, 90))
    img = jpeg(img, q)
    aplicadas.append(f"jpeg {q}")
    return img, aplicadas


# ── Identidades ficticias ────────────────────────────────────────────────────

_APELLIDOS = ["GARCIA", "RODRIGUEZ", "GONZALEZ", "FERNANDEZ", "LOPEZ", "MARTINEZ", "SANCHEZ",
              "PEREZ", "GOMEZ", "MARTIN", "JIMENEZ", "RUIZ", "HERNANDEZ", "DIAZ", "MORENO",
              "MUNOZ", "ALVAREZ", "ROMERO", "ALONSO", "GUTIERREZ", "NAVARRO", "DE LA TORRE"]
_NOMBRES = {"F": ["MARIA", "CARMEN", "ANA", "LAURA", "ISABEL", "MARIA JOSE", "LUCIA", "PAULA"],
            "M": ["ANTONIO", "JOSE", "MANUEL", "FRANCISCO", "DAVID", "JUAN", "JAVIER", "JOSE LUIS"]}


def construir_mrz(soporte: str, dni8: str, nacimiento: str, sexo: str, caducidad: str,
                  apellidos: str, nombre: str) -> list[str]:
    """Líneas TD1 de un DNI con sus dígitos de control. Fechas en AAMMDD."""
    from .mrz import digito_control as dc, letra_dni
    dni = dni8 + letra_dni(dni8)
    l1 = ("IDESP" + soporte + dc(soporte) + dni).ljust(30, "<")[:30]
    l2 = (nacimiento + dc(nacimiento) + sexo + caducidad + dc(caducidad) + "ESP").ljust(29, "<")
    l2 += dc(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])
    l3 = (apellidos.replace(" ", "<") + "<<" + nombre.replace(" ", "<")).ljust(30, "<")[:30]
    return [l1, l2, l3]


def identidad_aleatoria(rng: np.random.Generator) -> dict:
    """Datos ficticios coherentes y su MRZ. Devuelve la «verdad» para comparar."""
    sexo = str(rng.choice(["F", "M"]))
    ap1, ap2 = rng.choice(_APELLIDOS, 2, replace=False)
    nombre = str(rng.choice(_NOMBRES[sexo]))
    letras = "ABCDEFGHJKLMNPRSTUVWXYZ"
    soporte = "".join(rng.choice(list(letras), 3)) + f"{int(rng.integers(0, 10**6)):06d}"
    dni8 = f"{int(rng.integers(10**7, 10**8)):08d}"
    nac = (int(rng.integers(1950, 2006)), int(rng.integers(1, 13)), int(rng.integers(1, 29)))
    cad = (int(rng.integers(2026, 2036)), int(rng.integers(1, 13)), int(rng.integers(1, 29)))
    aammdd = lambda f: f"{f[0] % 100:02d}{f[1]:02d}{f[2]:02d}"
    dd = lambda f: f"{f[2]:02d}/{f[1]:02d}/{f[0]}"
    lineas = construir_mrz(soporte, dni8, aammdd(nac), sexo, aammdd(cad), f"{ap1} {ap2}", nombre)
    # La MRZ recorta los nombres largos: la verdad es lo que cabe en ella, como en un DNI real.
    ap_mrz, _, nom_mrz = lineas[2].partition("<<")
    apellidos = ap_mrz.replace("<", " ").strip()
    nombre = nom_mrz.replace("<", " ").strip()
    return {
        "lineas": lineas,
        "verdad": {
            "dni": lineas[0][15:24], "num_soporte": soporte, "fecha_nacimiento": dd(nac),
            "fecha_caducidad": dd(cad), "sexo": sexo, "apellidos": apellidos, "nombre": nombre,
        },
    }


def _movil(semilla: int) -> np.ndarray:
    rng = np.random.default_rng(semilla)
    return foto_movil(reverso(identidad_aleatoria(rng)["lineas"]), rng)[0]


def _movil_anverso(semilla: int) -> np.ndarray:
    rng = np.random.default_rng(semilla)
    return foto_movil(anverso(), rng)[0]


ANVERSO_EJEMPLO = {
    "dni": "99999999R", "apellidos": ["ESPAÑOLA", "ESPAÑOLA"], "nombre": "CARMEN", "sexo": "F",
    "nacionalidad": "ESP", "nacimiento": "01 01 1980", "soporte": "BAA000589",
    "emision": "01 01 2021", "validez": "01 01 2031", "can": "123456",
}


def anverso(datos: dict | None = None, ancho_tarjeta: int = 1284) -> np.ndarray:
    """Anverso sintético con la disposición del DNI 4.0 (etiqueta pequeña y valor debajo).

    Tarjeta genérica: no imita el diseño del DNI, solo la posición de etiquetas y valores.
    """
    d_ = {**ANVERSO_EJEMPLO, **(datos or {})}
    tw, th = ancho_tarjeta, round(ancho_tarjeta * 54 / 85.6)
    margen = round(tw * 0.12)
    lienzo = Image.new("RGB", (tw + 2 * margen, th + 2 * margen), (96, 84, 72))
    tarjeta = Image.new("RGB", (tw, th), (228, 232, 240))
    d = ImageDraw.Draw(tarjeta)
    for i in range(0, th, max(4, th // 60)):
        d.line([(0, i + th // 8), (tw, i)], fill=(212, 218, 232), width=1)

    etq = _fuente(_FUENTES_SANS, max(10, th // 34))
    val = _fuente(_FUENTES_SANS, max(12, th // 20))
    grande = _fuente(_FUENTES_SANS, max(14, th // 15))
    d.text((round(tw * 0.04), round(th * 0.04)), "REINO DE ESPAÑA", fill=(60, 60, 90), font=val)
    d.text((round(tw * 0.04), round(th * 0.13)), "DOCUMENTO NACIONAL DE IDENTIDAD", fill=(60, 60, 90), font=etq)
    d.text((round(tw * 0.55), round(th * 0.04)), "DNI " + d_["dni"], fill=(20, 20, 30), font=grande)
    # Foto: un rectángulo gris a la izquierda.
    d.rectangle([round(tw * 0.04), round(th * 0.24), round(tw * 0.30), round(th * 0.90)], fill=(170, 170, 180))

    x0 = round(tw * 0.34)
    paso = th // 9

    def campo(x, y, etiqueta, valor):
        d.text((x, y), etiqueta, fill=(90, 100, 120), font=etq)
        d.text((x, y + th // 28), valor, fill=(20, 20, 30), font=val)

    y = round(th * 0.24)
    d.text((x0, y), "APELLIDOS", fill=(90, 100, 120), font=etq)
    for i, ap in enumerate(d_["apellidos"]):
        d.text((x0, y + th // 28 + i * th // 16), ap, fill=(20, 20, 30), font=val)
    y += round(th * 0.20)
    campo(x0, y, "NOMBRE", d_["nombre"])
    y += paso + th // 40
    campo(x0, y, "SEXO", d_["sexo"])
    campo(x0 + round(tw * 0.14), y, "NACIONALIDAD", d_["nacionalidad"])
    campo(x0 + round(tw * 0.36), y, "FECHA DE NACIMIENTO", d_["nacimiento"])
    y += paso + th // 40
    campo(x0, y, "NUM SOPORTE", d_["soporte"])
    campo(x0 + round(tw * 0.18), y, "EMISION", d_["emision"])
    campo(x0 + round(tw * 0.42), y, "VALIDEZ", d_["validez"])
    campo(round(tw * 0.80), round(th * 0.84), "CAN", d_["can"])

    lienzo.paste(tarjeta, (margen, margen))
    return cv2.cvtColor(np.array(lienzo), cv2.COLOR_RGB2BGR)


MUESTRAS = {
    "anverso": lambda: anverso(),
    "anverso-movil": lambda: _movil_anverso(5),
    "limpia": lambda: reverso(),
    "borrosa": lambda: desenfocar(reverso()),
    "oscura": lambda: oscurecer(reverso()),
    "sobreexpuesta": lambda: sobreexponer(reverso()),
    "reflejo-en-mrz": lambda: reflejo(reverso()),
    "baja-resolucion": lambda: reducir(reverso(), 0.3),
    "movil-1": lambda: _movil(1),
    "movil-2": lambda: _movil(2),
    "movil-3": lambda: _movil(3),
    "movil-4": lambda: _movil(4),
}


def generar_lote(carpeta: str, n: int, semilla: int = 0, tomas: int = 1) -> None:
    """Escribe n DNI sintéticos «de móvil» y un verdad.csv con los datos correctos.

    Con tomas > 1, cada DNI se fotografía varias veces con defectos distintos (mismo «grupo»),
    para medir el acierto cuando el usuario repite la foto.
    """
    import csv
    from pathlib import Path
    salida = Path(carpeta)
    salida.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(semilla)
    campos = ["archivo", "grupo", "dni", "num_soporte", "fecha_nacimiento", "fecha_caducidad",
              "sexo", "apellidos", "nombre", "degradaciones"]
    with open(salida / "verdad.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        for i in range(n):
            ident = identidad_aleatoria(rng)
            tarjeta = reverso(ident["lineas"])
            for t in range(1, tomas + 1):
                img, aplicadas = foto_movil(tarjeta, rng)
                nombre = f"sintetica-{i:04d}.jpg" if tomas == 1 else f"sintetica-{i:04d}-t{t}.jpg"
                cv2.imwrite(str(salida / nombre), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                w.writerow({"archivo": nombre, "grupo": f"{i:04d}", **ident["verdad"],
                            "degradaciones": ", ".join(aplicadas)})


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Genera DNI sintéticos con aspecto de foto de móvil.")
    ap.add_argument("carpeta")
    ap.add_argument("-n", type=int, default=50, help="número de DNI distintos (50)")
    ap.add_argument("--tomas", type=int, default=1, help="fotos por DNI, para medir reintentos (1)")
    ap.add_argument("--semilla", type=int, default=0)
    a = ap.parse_args()
    generar_lote(a.carpeta, a.n, a.semilla, a.tomas)
    print(f"{a.n * a.tomas} fotos ({a.n} DNI × {a.tomas} tomas) y verdad.csv escritos en {a.carpeta}")
