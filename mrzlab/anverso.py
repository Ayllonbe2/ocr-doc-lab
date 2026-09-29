"""Lectura de los campos del anverso del DNI (3.0 y 4.0) a partir del texto del OCR.

El anverso no tiene MRZ: los datos se sacan del texto impreso junto a sus etiquetas
(«APELLIDOS», «NOMBRE», «FECHA DE NACIMIENTO»…). Cada línea leída por el OCR llega con su
caja; un valor se asocia a la etiqueta que tiene justo encima (o a su derecha).

Lo único que se puede comprobar es la **letra del DNI** (módulo 23). El resto de campos no
tiene control: son orientativos y hay que contrastarlos con el reverso o con lo declarado.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from .mrz import letra_dni

Caja = tuple[int, int, int, int]


@dataclass
class Linea:
    texto: str
    caja: Caja | None
    confianza: float | None = None

    @property
    def norm(self) -> str:
        return normalizar(self.texto)


def normalizar(texto: str) -> str:
    """Mayúsculas sin tildes (la Ñ se conserva) y espacios simples."""
    t = texto.upper().replace("Ñ", "\0")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t.replace("\0", "Ñ")).strip()


# ── Etiquetas ────────────────────────────────────────────────────────────────
# Variantes en castellano y en las lenguas cooficiales que aparecen en algunos DNI 4.0.

ETIQUETAS: dict[str, tuple[str, ...]] = {
    "apellidos": ("APELLIDOS", "COGNOMS", "ABIZENAK", "APELIDOS"),
    "primer_apellido": ("PRIMER APELLIDO", "1ER APELLIDO"),
    "segundo_apellido": ("SEGUNDO APELLIDO", "2O APELLIDO"),
    "nombre": ("NOMBRE", "NOM", "IZENA"),
    "sexo": ("SEXO", "SEXE", "SEXUA"),
    "nacionalidad": ("NACIONALIDAD", "NACIONALITAT", "NAZIONALITATEA", "NACIONALIDADE"),
    "fecha_nacimiento": ("FECHA DE NACIMIENTO", "NACIMIENTO", "NAIXEMENT", "JAIOTZE", "NACEMENTO"),
    "num_soporte": ("NUM SOPORTE", "SOPORTE", "SUPORT", "EUSKARRI"),
    "fecha_caducidad": ("VALIDEZ", "VALIDO HASTA", "VALIDESA", "BALIOZTASUNA", "HASTA"),
    "fecha_expedicion": ("EXPEDICION", "EMISION"),
    "can": ("CAN",),
    "dni": ("DNI", "DOCUMENTO NACIONAL"),
}
# Texto fijo de la tarjeta que nunca es un valor.
_FIJO = ("DOCUMENTO NACIONAL", "IDENTIDAD", "REINO DE ESPAÑA", "ESPAÑA", "ESPANA", "DATA",
         "FIRMA", "SIGNATURA")


def _parecido(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def etiquetas_de(texto: str) -> set[str]:
    """Qué etiquetas contiene una línea (tolera un error de OCR en etiquetas largas)."""
    t = re.sub(r"[^A-ZÑ0-9 ]", " ", normalizar(texto))
    palabras = t.split()
    compacto = t.replace(" ", "")
    encontradas = set()
    for clave, variantes in ETIQUETAS.items():
        for v in variantes:
            if len(v) >= 6 and v.replace(" ", "") in compacto:  # palabras pegadas por el OCR
                encontradas.add(clave)
                break
            n = len(v.split())
            ventanas = [" ".join(palabras[i:i + n]) for i in range(len(palabras) - n + 1)]
            umbral = 1.0 if len(v) <= 4 else 0.84  # «NOM», «CAN», «DNI»: exactas
            if any(w == v or (umbral < 1 and _parecido(w, v) >= umbral) for w in ventanas):
                encontradas.add(clave)
                break
    # «NOM» aparece dentro de «NOMBRE / NOM»: basta con una.
    return encontradas


def es_etiqueta(texto: str) -> bool:
    n = normalizar(texto)
    return bool(etiquetas_de(n)) or any(f in n for f in _FIJO)


# ── Valores con formato fijo ─────────────────────────────────────────────────

_A_DIGITO = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1",
                           "Z": "2", "S": "5", "G": "6", "B": "8", "T": "7"})
_A_LETRA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
_DNI = re.compile(r"(?<![0-9])([0-9OQDILSZGBT|]{8})\s?-?\s?([A-Z0-9])(?![0-9A-Z])")
_SOPORTE = re.compile(r"(?<![0-9A-Z])([A-Z0-9]{3})\s?([0-9OQDILSZGB]{6})(?![0-9A-Z])")
# El OCR a veces pega el soporte con lo que tiene al lado («ABC12345602 10 2024», la fecha de
# emisión): se acepta el principio de la palabra si empieza por 3 letras y 6 dígitos.
_SOPORTE_LARGO = re.compile(r"(?<![0-9A-Z])([A-Z0-9]{3})\s?([0-9OQDILSZGB]{6})")
_FECHA = re.compile(r"(?<!\d)(\d{2})[ ./-]{0,2}(\d{2})[ ./-]{0,2}(\d{4})(?!\d)")
_CAN = re.compile(r"(?<![0-9A-Z])(\d{6})(?![0-9A-Z])")
# Letras que el OCR suele leer como otro carácter (clave: lo leído).
_CONFUSION_LETRA = {"0": "DQ", "O": "DQ", "Q": "D", "D": "Q", "1": "TL", "I": "TL", "7": "T",
                    "4": "A", "8": "B", "5": "S", "2": "Z", "6": "G"}


def buscar_dni(texto: str) -> tuple[str, bool] | None:
    """Primer nº de DNI con letra que cuadra; si ninguno cuadra, el primero con forma de DNI."""
    candidato = None
    # RapidOCR suele pegar las palabras: «DNI99999999R».
    for m in _DNI.finditer(normalizar(texto).replace("DNI", " ")):
        if sum(c.isdigit() for c in m.group(1)) < 5:  # evita palabras leídas como número
            continue
        numero = m.group(1).translate(_A_DIGITO)
        esperada = letra_dni(numero)
        if esperada is None:
            continue
        leida = m.group(2)
        if leida == esperada or esperada in _CONFUSION_LETRA.get(leida, ""):
            return numero + esperada, True
        candidato = candidato or (numero + leida, False)
    return candidato


def buscar_soporte(texto: str) -> str | None:
    """Nº de soporte: 3 letras y 6 dígitos (sin control en el anverso; sí en la MRZ)."""
    t = normalizar(texto).replace("IDESP", " ")
    for patron, min_letras in ((_SOPORTE, 0), (_SOPORTE_LARGO, 2)):
        for m in patron.finditer(t):
            letras = m.group(1).translate(_A_LETRA)
            # Al menos 4 dígitos de verdad: «APELLIDOS» no es «APE111005». Con texto pegado,
            # además 2 letras de verdad: «021…» de una fecha no es un soporte.
            if (letras.isalpha() and sum(c.isdigit() for c in m.group(2)) >= 4
                    and sum(c.isalpha() for c in m.group(1)) >= min_letras):
                return letras + m.group(2).translate(_A_DIGITO)
    return None


def buscar_fechas(texto: str) -> list[str]:
    fechas = []
    for d, m, a in _FECHA.findall(normalizar(texto)):
        try:
            fechas.append(date(int(a), int(m), int(d)).strftime("%d/%m/%Y"))
        except ValueError:
            continue
    return fechas


def _anio(fecha: str) -> int:
    return int(fecha[-4:])


# ── Geometría: valor bajo (o junto a) una etiqueta ───────────────────────────

def _debajo(etq: Linea, lineas: list[Linea], acepta, max_lineas: int = 1) -> list[Linea]:
    """Valores alineados bajo la etiqueta (o en la misma fila, a su derecha)."""
    if etq.caja is None:
        return []
    ex, ey, ew, eh = etq.caja
    eh = max(eh, 1)
    candidatas = []
    for ln in lineas:
        if ln is etq or ln.caja is None or not acepta(ln):
            continue
        x, y, w, h = ln.caja
        cy = y + h / 2
        misma_fila = abs(cy - (ey + eh / 2)) < eh * 0.6 and x > ex + ew * 0.5 and x - (ex + ew) < eh * 12
        bajo = ey + eh * 0.5 < cy < ey + eh * 4.5 and ex - eh * 2.5 < x < ex + max(ew, eh * 5)
        if misma_fila or bajo:
            candidatas.append((0 if misma_fila else cy - ey, ln))
    candidatas.sort(key=lambda c: c[0])
    elegidas = [c[1] for c in candidatas[:1]]
    # Líneas siguientes (p. ej. dos apellidos en dos líneas) si siguen justo debajo.
    for _, ln in candidatas[1:]:
        if len(elegidas) >= max_lineas:
            break
        ult = elegidas[-1].caja
        if ln.caja[1] - (ult[1] + ult[3]) < ult[3] * 0.8:
            elegidas.append(ln)
    return elegidas


def _es_texto_de_nombre(ln: Linea) -> bool:
    n = normalizar(ln.texto)
    letras = sum(c.isalpha() for c in n)
    return letras >= 2 and letras >= 0.8 * len(n.replace(" ", "")) and not es_etiqueta(n)


def _valor_tras_etiqueta(texto: str, clave: str) -> str | None:
    """«SEXO F», «NOMBRE CARMEN»…: el valor va en la misma línea que la etiqueta."""
    n = normalizar(texto)
    for v in ETIQUETAS[clave]:
        i = n.find(v)
        if i >= 0:
            resto = re.sub(r"^[\s/:.]+", "", n[i + len(v):])
            return resto or None
    return None


# ── Extracción ───────────────────────────────────────────────────────────────

CAMPOS = ("dni", "num_soporte", "apellidos", "nombre", "sexo", "nacionalidad",
          "fecha_nacimiento", "fecha_expedicion", "fecha_caducidad", "can")


def _union(lineas: list[Linea]) -> Caja | None:
    cajas = [ln.caja for ln in lineas if ln.caja is not None]
    if not cajas:
        return None
    x0, y0 = min(c[0] for c in cajas), min(c[1] for c in cajas)
    x1, y1 = max(c[0] + c[2] for c in cajas), max(c[1] + c[3] for c in cajas)
    return (x0, y0, x1 - x0, y1 - y0)


def extraer(lineas: list[Linea]) -> dict:
    """Campos del anverso a partir de las líneas del OCR (texto + caja).

    Devuelve también la caja de cada campo en la foto («cajas»): es lo que se usa para
    aprender la plantilla de posiciones.
    """
    campos: dict[str, str | None] = {c: None for c in CAMPOS}
    cajas: dict[str, Caja | None] = {}
    origen: dict[str, str] = {}
    etiquetas: dict[str, list[Linea]] = {}
    for ln in lineas:
        for clave in etiquetas_de(ln.texto):
            etiquetas.setdefault(clave, []).append(ln)

    def poner(clave, valor, de: list[Linea], como: str | None = None):
        campos[clave] = valor
        cajas[clave] = _union(de)
        if como:
            origen[clave] = como

    # Nº de DNI: validado con la letra. Se busca en cada línea y en pares de líneas
    # (el OCR a veces separa número y letra).
    dni_ok = False
    grupos = [[ln] for ln in lineas] + [[a, b] for a, b in zip(lineas, lineas[1:])]
    for g in grupos:
        r = buscar_dni(" ".join(ln.texto for ln in g))
        if r and (r[1] or campos["dni"] is None):
            poner("dni", r[0], g, "letra correcta" if r[1] else "letra NO cuadra")
            dni_ok = r[1]
            if r[1]:
                break

    def por_etiqueta(clave, acepta, max_lineas=1) -> list[Linea]:
        for etq in etiquetas.get(clave, []):
            vals = _debajo(etq, lineas, acepta, max_lineas)
            if vals:
                return vals
        return []

    def primera(pred) -> list[Linea]:
        return next(([ln] for ln in lineas if pred(ln)), [])

    # Nº de soporte: primero bajo su etiqueta; si no, en cualquier parte.
    sop = por_etiqueta("num_soporte", lambda ln: buscar_soporte(ln.texto) is not None) \
        or primera(lambda ln: buscar_soporte(ln.texto) is not None)
    if sop:
        poner("num_soporte", buscar_soporte(sop[0].texto), sop)

    # Apellidos: DNI 3.0 (primer y segundo apellido) o 4.0 («APELLIDOS», una o dos líneas).
    # «PRIMER APELLIDO» también encaja con «APELLIDOS»: se mira antes el 3.0.
    ap = por_etiqueta("primer_apellido", _es_texto_de_nombre) + \
        por_etiqueta("segundo_apellido", _es_texto_de_nombre)
    if not ap:
        ap = por_etiqueta("apellidos", _es_texto_de_nombre, max_lineas=2)
    if ap:
        poner("apellidos", " ".join(normalizar(x.texto) for x in ap), ap, "bajo la etiqueta")

    # Un nombre compuesto largo puede partirse en dos líneas.
    nom = por_etiqueta("nombre", _es_texto_de_nombre, max_lineas=2)
    if nom:
        poner("nombre", " ".join(normalizar(x.texto) for x in nom), nom, "bajo la etiqueta")
    else:
        for etq in etiquetas.get("nombre", []):
            v = _valor_tras_etiqueta(etq.texto, "nombre")
            if v and _es_texto_de_nombre(Linea(v, None)):
                poner("nombre", v, [etq], "en la línea de la etiqueta")
                break

    # Sexo: una M o F suelta bajo «SEXO» (o en su misma línea).
    sx = por_etiqueta("sexo", lambda ln: normalizar(ln.texto) in ("M", "F"))
    if sx:
        poner("sexo", normalizar(sx[0].texto), sx)
    else:
        for etq in etiquetas.get("sexo", []):
            m = re.search(r"\b([MF])\b", _valor_tras_etiqueta(etq.texto, "sexo") or "")
            if m:
                poner("sexo", m.group(1), [etq])
                break

    esp = re.compile(r"(?<![A-Z])ESP(?![A-Z])")
    nac = por_etiqueta("nacionalidad", lambda ln: bool(esp.search(normalizar(ln.texto)))) \
        or primera(lambda ln: bool(esp.search(normalizar(ln.texto).replace("IDESP", ""))))
    if nac:
        poner("nacionalidad", "ESP", nac)

    # Fechas: por su etiqueta; si no, por el año.
    claves_fecha = ("fecha_nacimiento", "fecha_expedicion", "fecha_caducidad")
    for clave in claves_fecha:
        vals = por_etiqueta(clave, lambda ln: bool(buscar_fechas(ln.texto)))
        if vals:
            poner(clave, buscar_fechas(vals[0].texto)[0], vals, "bajo la etiqueta")
        else:
            for etq in etiquetas.get(clave, []):
                f = buscar_fechas(etq.texto)
                if f:
                    poner(clave, f[0], [etq], "en la línea de la etiqueta")
                    break
    usadas = {campos[c] for c in claves_fecha}
    fechas = sorted({f for ln in lineas for f in buscar_fechas(ln.texto)} - usadas,
                    key=lambda f: (_anio(f), f[3:5], f[:2]))
    linea_de = lambda f: primera(lambda ln: f in buscar_fechas(ln.texto))
    hoy = date.today().year
    if campos["fecha_nacimiento"] is None:
        pasadas = [f for f in fechas if _anio(f) <= hoy - 14]
        if pasadas:
            poner("fecha_nacimiento", pasadas[0], linea_de(pasadas[0]), "deducida por el año")
            fechas.remove(pasadas[0])
    if campos["fecha_caducidad"] is None:
        futuras = [f for f in fechas if _anio(f) >= hoy - 1]
        if futuras:
            poner("fecha_caducidad", futuras[-1], linea_de(futuras[-1]), "deducida por el año")
            fechas.remove(futuras[-1])
    if campos["fecha_expedicion"] is None:
        # Emisión: posterior al nacimiento y no futura.
        emision = [f for f in fechas if _anio(f) <= hoy and (
            campos["fecha_nacimiento"] is None or _anio(f) > _anio(campos["fecha_nacimiento"]))]
        if emision:
            poner("fecha_expedicion", emision[-1], linea_de(emision[-1]), "deducida por el año")

    # CAN: 6 dígitos bajo o junto a «CAN».
    can = por_etiqueta("can", lambda ln: bool(_CAN.search(normalizar(ln.texto))))
    for ln in can or etiquetas.get("can", []):
        m = _CAN.search(normalizar(ln.texto))
        if m:
            poner("can", m.group(1), [ln])
            break

    return {
        "campos": campos,
        "cajas": {k: v for k, v in cajas.items() if v is not None},
        # Las etiquetas van impresas siempre en el mismo sitio: son las mejores referencias
        # para la plantilla (no dependen de lo largo que sea el nombre de cada persona).
        "cajas_etiquetas": {k: v[0].caja for k, v in etiquetas.items() if v[0].caja is not None},
        "dni_valido": dni_ok,
        "origen": origen,
        "etiquetas": sorted(etiquetas),
        "encontrados": sum(v is not None for v in campos.values()),
    }


def parece_anverso(resultado: dict) -> bool:
    """Suficientes señales de anverso: DNI con letra correcta o varias etiquetas propias."""
    propias = {"apellidos", "primer_apellido", "nombre", "sexo", "fecha_nacimiento", "can", "num_soporte"}
    return resultado["dni_valido"] or len(propias & set(resultado["etiquetas"])) >= 2


# ── Lectura de una zona concreta (plantilla de posiciones) ───────────────────

TIPO_CAMPO = {
    "dni": "dni", "num_soporte": "alfanumerico", "apellidos": "nombre", "nombre": "nombre",
    "sexo": "sexo", "nacionalidad": "letras", "fecha_nacimiento": "fecha",
    "fecha_expedicion": "fecha", "fecha_caducidad": "fecha", "can": "digitos",
}
# Sin partículas de apellido («DE», «LA», «DEL»…): «DE LA TORRE» es un apellido.
_PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "I", "SAN", "SANTA"}
_PALABRAS_ETIQUETA = ({w for vs in ETIQUETAS.values() for v in vs for w in v.split()}
                      | {"REINO", "IDENTIDAD", "DOCUMENTO", "NACIONAL"}) - _PARTICULAS


def _sin_etiquetas(texto: str) -> str:
    """Quita las palabras de etiqueta que se cuelan en el recorte de una zona."""
    palabras = re.sub(r"[^A-ZÑ ]", " ", normalizar(texto)).split()
    return " ".join(p for p in palabras
                    if p not in _PALABRAS_ETIQUETA
                    and not any(len(e) >= 6 and _parecido(p, e) >= 0.84 for e in _PALABRAS_ETIQUETA))


def leer_campo(campo: str, texto: str) -> str | None:
    """Valor de un campo a partir del texto leído en su zona (o None si no tiene forma)."""
    n = normalizar(texto)
    tipo = TIPO_CAMPO[campo]
    if tipo == "dni":
        r = buscar_dni(n)
        return r[0] if r else None
    if tipo == "alfanumerico":
        return buscar_soporte(n)
    if tipo == "fecha":
        # En una fecha solo caben dígitos: las letras parecidas se leen como dígitos (O→0, I→1…).
        f = buscar_fechas(n) or buscar_fechas(" ".join(
            w.translate(_A_DIGITO) for w in n.split()
            if any(c.isdigit() for c in w) and all(c.isdigit() or c in "OQDILSZGBT|" for c in w)))
        return f[0] if f else None
    if tipo == "digitos":
        m = _CAN.search(n)
        return m.group(1) if m else None
    if tipo == "sexo":
        m = re.search(r"(?<![A-Z])([MF])(?![A-Z])", _sin_etiquetas(n))
        return m.group(1) if m else None
    if tipo == "letras":
        m = re.search(r"(?<![A-Z])([A-Z]{3})(?![A-Z])", _sin_etiquetas(n))
        return m.group(1) if m else None
    v = _sin_etiquetas(n)
    return v if sum(c.isalpha() for c in v) >= 2 else None
