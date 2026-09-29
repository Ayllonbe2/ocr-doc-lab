"""Parseo y validación de la MRZ TD1 (ICAO 9303) del DNI español.

Estructura TD1 (3 líneas × 30 caracteres):

    Línea 1: [0:2] tipo · [2:5] país · [5:14] nº soporte · [14] control · [15:30] opcional
             (en el DNI, el opcional empieza por el nº de DNI con su letra)
    Línea 2: [0:6] nacimiento · [6] control · [7] sexo · [8:14] caducidad · [14] control
             [15:18] nacionalidad · [18:29] opcional · [29] control compuesto
    Línea 3: APELLIDO1<APELLIDO2<<NOMBRE

Sin dependencias externas: la validación son dígitos de control 7-3-1 módulo 10.

Ojo: en TD1 los dígitos de control protegen el nº de soporte, el nº de DNI (vía letra y
control compuesto) y las fechas. La línea 3 (apellidos y nombre) y el sexo NO tienen control:
una MRZ «válida» puede traer el nombre mal leído. Hay que contrastarlo con el nombre declarado.
Además, el control ICAO no distingue letras cuyo valor difiere en 10 (M/W, F/P, G/Q, K/U…):
las 3 letras del nº de soporte solo están protegidas en parte. Los dígitos sí lo están del todo.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import date

LONGITUD = 30
_CHARSET = re.compile(r"[^A-Z0-9<]")
_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"

# Confusiones típicas del OCR entre letras y dígitos.
_A_DIGITO = {"O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "T": "1",
             "Z": "2", "S": "5", "G": "6", "B": "8"}
_A_LETRA = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
# Caracteres que el OCR suele leer en lugar de «<».
_RELLENO = str.maketrans({"«": "<", "‹": "<", "(": "<", "[": "<", "{": "<", "¢": "<"})

# Letras del DNI que el OCR suele leer como otro carácter (clave: lo leído).
_CONFUSION_LETRA = {"0": "DQ", "O": "DQ", "Q": "D", "D": "Q", "1": "TL", "I": "TL", "7": "T",
                    "4": "A", "8": "B", "5": "S", "2": "Z", "6": "G"}
_INICIO_DNI = re.compile(r"I[D<]ESP")
_INICIO_TD1 = re.compile(r"[IAC][A-Z<][A-Z]{3}")

# Máximo de caracteres ambiguos que se prueban por campo (2^n combinaciones).
_MAX_AMBIGUOS = 6


def valor(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    return 0  # «<» y cualquier otro


def digito_control(s: str) -> str:
    pesos = (7, 3, 1)
    return str(sum(valor(c) * pesos[i % 3] for i, c in enumerate(s)) % 10)


def letra_dni(numero: str) -> str | None:
    return _LETRAS_DNI[int(numero) % 23] if numero.isdigit() and len(numero) == 8 else None


# ── Normalización y selección de líneas ──────────────────────────────────────

def normalizar_linea(texto: str) -> str:
    t = texto.upper().translate(_RELLENO).replace(" ", "")
    return _CHARSET.sub("", t)


def ajustar_longitud(linea: str) -> str:
    """Rellena o recorta a 30 caracteres (el OCR suele perder o añadir «<» al final)."""
    return (linea + "<" * LONGITUD)[:LONGITUD]


def anclar_linea1(linea: str) -> str:
    """Quita la basura que el OCR lee antes de «IDESP» (p. ej. el borde de la tarjeta: «IIDESP»)."""
    # El patrón genérico solo si la línea trae caracteres de más (evita recortar nombres).
    patrones = (_INICIO_DNI, _INICIO_TD1) if len(linea) > LONGITUD else (_INICIO_DNI,)
    for patron in patrones:
        m = patron.search(linea, 0, 3 + 5)  # el inicio real, como mucho 3 caracteres después
        if m:
            if 0 < m.start() and len(linea) - m.start() >= LONGITUD - 6:
                return linea[m.start():]
            return linea
    return linea


def _puntuacion_estructura(l1: str, l2: str, l3: str) -> int:
    p = 0
    if l1[:1] in "IAC":
        p += 2
    if l1[2:5] == "ESP":
        p += 2
    if sum(c.isdigit() for c in l2[:6]) >= 5:
        p += 2
    if sum(c.isdigit() for c in l2[8:14]) >= 5:
        p += 2
    if l2[7:8] in ("M", "F", "<"):
        p += 1
    if "<<" in l3 and sum(c.isalpha() for c in l3) >= 4:
        p += 2
    return p


def elegir_lineas(candidatas: list[str]) -> list[str] | None:
    """Entre las líneas que devuelve un OCR (en orden de lectura), elige las 3 de la MRZ.

    Acepta líneas de 15 a 34 caracteres tras normalizar (el OCR suele perder los «<»
    finales) y busca la ventana de 3 líneas consecutivas que mejor encaja con TD1.
    """
    limpias = [normalizar_linea(c) for c in candidatas]
    utiles = [c for c in limpias if 15 <= len(c) <= 34]
    if len(utiles) < 3:
        return None
    mejor, mejor_p = None, -1
    for i in range(len(utiles) - 2):
        ventana = utiles[i:i + 3]
        # Se puntúa con la línea 1 anclada; parsear_td1 vuelve a anclarla y lo anota.
        p = _puntuacion_estructura(ajustar_longitud(anclar_linea1(ventana[0])),
                                   *(ajustar_longitud(x) for x in ventana[1:]))
        if p > mejor_p:
            mejor, mejor_p = ventana, p
    # Se devuelven sin ajustar a 30: leer() usa la longitud para detectar sobrantes.
    return mejor if mejor_p >= 4 else None


# ── Corrección guiada por dígitos de control ─────────────────────────────────

def _forzar(texto: str, tipo: str) -> str:
    """tipo por carácter: 'n' numérico, 'a' alfabético, 'x' mixto (no se toca)."""
    out = []
    for c, t in zip(texto, tipo):
        if t == "n":
            out.append(_A_DIGITO.get(c, c))
        elif t == "a":
            out.append(_A_LETRA.get(c, c))
        else:
            out.append(c)
    return "".join(out)


def _variantes(texto: str) -> list[str]:
    """Todas las combinaciones intercambiando letra↔dígito en posiciones ambiguas."""
    opciones = []
    for c in texto:
        alt = _A_DIGITO.get(c) or _A_LETRA.get(c)
        opciones.append((c, alt) if alt else (c,))
    ambiguos = sum(len(o) > 1 for o in opciones)
    if ambiguos == 0 or ambiguos > _MAX_AMBIGUOS:
        return []
    return ["".join(v) for v in itertools.product(*opciones) if "".join(v) != texto]


def _corregir_con_control(campo: str, control: str) -> tuple[str, str, bool]:
    """Si el control no cuadra, prueba variantes del campo y del propio dígito."""
    control_n = _A_DIGITO.get(control, control)
    if digito_control(campo) == control_n:
        return campo, control_n, False
    validas = [v for v in _variantes(campo) if digito_control(v) == control_n]
    if len(validas) == 1:  # solo si la corrección es inequívoca
        return validas[0], control_n, True
    return campo, control_n, False


# ── Resultado ────────────────────────────────────────────────────────────────

@dataclass
class ResultadoMRZ:
    lineas: list[str]
    campos: dict[str, str | None]
    controles: dict[str, bool]
    correcciones: list[str] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        return bool(self.controles) and all(self.controles.values())

    def a_dict(self) -> dict:
        return {
            "lineas": self.lineas,
            "campos": self.campos,
            "controles": self.controles,
            "correcciones": self.correcciones,
            "valido": self.valido,
        }


def _fecha(aammdd: str, futura: bool) -> str | None:
    if not aammdd.isdigit():
        return None
    aa, mm, dd = int(aammdd[:2]), int(aammdd[2:4]), int(aammdd[4:])
    hoy = date.today().year % 100
    siglo = 2000 if (futura or aa <= hoy) else 1900
    try:
        return date(siglo + aa, mm, dd).strftime("%d/%m/%Y")
    except ValueError:
        return None


def parsear_td1(lineas: list[str]) -> ResultadoMRZ:
    l1_norm = normalizar_linea(lineas[0])
    l1_anclada = anclar_linea1(l1_norm)
    l1, l2, l3 = (ajustar_longitud(x) for x in
                  (l1_anclada, normalizar_linea(lineas[1]), normalizar_linea(lineas[2])))
    correcciones: list[str] = []
    if l1_anclada != l1_norm:
        correcciones.append(f"línea 1: descartado «{l1_norm[:len(l1_norm) - len(l1_anclada)]}» "
                            "antes del inicio")

    def anotar(nombre: str, antes: str, despues: str) -> None:
        if antes != despues:
            correcciones.append(f"{nombre}: {antes} → {despues}")

    # Posiciones de tipo fijo: se fuerzan sin necesidad de control.
    tipo_pais = _forzar(l1[:5], "aaaaa")
    anotar("tipo/país", l1[:5], tipo_pais)
    nac_raw, sexo_raw, cad_raw = l2[0:6], l2[7], l2[8:14]
    nacimiento = _forzar(nac_raw, "nnnnnn")
    caducidad = _forzar(cad_raw, "nnnnnn")
    sexo = _forzar(sexo_raw, "a")
    nacionalidad = _forzar(l2[15:18], "aaa")
    anotar("nacimiento", nac_raw, nacimiento)
    anotar("caducidad", cad_raw, caducidad)
    anotar("sexo", sexo_raw, sexo)
    anotar("nacionalidad", l2[15:18], nacionalidad)

    # Nº de soporte del DNI: 3 letras + 6 dígitos. En otros documentos es libre.
    soporte_raw = l1[5:14]
    soporte = _forzar(soporte_raw, "aaannnnnn") if tipo_pais[2:5] == "ESP" else soporte_raw
    anotar("soporte", soporte_raw, soporte)

    es_dni = tipo_pais[2:5] == "ESP"
    if es_dni:
        c_soporte = _A_DIGITO.get(l1[14], l1[14])
    else:
        # Solo en campos mixtos (letras y dígitos libres) tiene sentido probar variantes:
        # en los de tipo fijo, forzar el tipo ya resuelve la ambigüedad, y probar más
        # combinaciones solo aumenta la probabilidad de cuadrar un control por azar.
        soporte, c_soporte, corr = _corregir_con_control(soporte, l1[14])
        if corr:
            correcciones.append(f"soporte corregido por control: {soporte}")
    c_nac = _A_DIGITO.get(l2[6], l2[6])
    c_cad = _A_DIGITO.get(l2[14], l2[14])

    # Nº de DNI en el opcional de la línea 1: 8 dígitos + letra, validada con módulo 23.
    opcional1 = l1[15:30]
    dni_raw = opcional1[:9]
    dni = _forzar(dni_raw, "nnnnnnnna")
    anotar("dni", dni_raw, dni)
    letra_ok = letra_dni(dni[:8]) == dni[8:9]

    l1c = tipo_pais + soporte + c_soporte + dni + opcional1[9:]
    l2c = nacimiento + c_nac + sexo + caducidad + c_cad + nacionalidad + l2[18:29] \
        + _A_DIGITO.get(l2[29], l2[29])

    compuesto = l1c[5:30] + l2c[0:7] + l2c[8:15] + l2c[18:29]

    # Letra del DNI leída como otro carácter (típico: D → «0»). Se sustituye por la calculada
    # solo si es una confusión visual conocida Y el control compuesto (que cubre toda la
    # línea 1) pasa a cuadrar: así la corrección queda confirmada por un control independiente.
    if es_dni and not letra_ok and dni[:8].isdigit():
        esperada = letra_dni(dni[:8])
        posibles = _CONFUSION_LETRA.get(dni_raw[8:9], "") + _CONFUSION_LETRA.get(dni[8:9], "")
        l1_prueba = tipo_pais + soporte + c_soporte + dni[:8] + esperada + opcional1[9:]
        comp_prueba = l1_prueba[5:30] + l2c[0:7] + l2c[8:15] + l2c[18:29]
        if esperada in posibles and digito_control(comp_prueba) == l2c[29] \
                and digito_control(compuesto) != l2c[29]:
            correcciones.append(f"letra DNI «{dni_raw[8]}» → «{esperada}» "
                                "(confirmada por el control compuesto)")
            dni, l1c, compuesto, letra_ok = dni[:8] + esperada, l1_prueba, comp_prueba, True

    # Nombre: APELLIDO1<APELLIDO2<<NOMBRE (los «<» sueltos separan palabras).
    l3c = _forzar(l3, "a" * LONGITUD)
    anotar("nombre", l3, l3c)
    partes = l3c.split("<<", 1)
    apellidos = partes[0].replace("<", " ").strip() or None
    nombre = partes[1].replace("<", " ").strip() if len(partes) > 1 else None

    fecha_nac = _fecha(nacimiento, futura=False)
    fecha_cad = _fecha(caducidad, futura=True)
    controles = {
        # Estructura: tipo de documento, país y nacionalidad con forma válida. Sin esto, un
        # país mal leído desactiva los controles propios del DNI y bastan 4 checksums.
        "estructura": l1c[0] in "IAC" and tipo_pais[2:5].isalpha()
        and nacionalidad.isalpha() and sexo in ("M", "F", "<"),
        "fechas": fecha_nac is not None and fecha_cad is not None,
        # La línea 3 no tiene dígito de control; al menos debe tener forma de nombre.
        "formato_nombre": re.fullmatch(r"[A-Z]+(<[A-Z]+)*<<[A-Z]+(<[A-Z]+)*<*", l3c) is not None,
        "soporte": digito_control(soporte) == c_soporte,
        "nacimiento": digito_control(nacimiento) == c_nac,
        "caducidad": digito_control(caducidad) == c_cad,
        "compuesto": digito_control(compuesto) == l2c[29],
    }
    if es_dni:
        controles["formato_soporte"] = re.fullmatch(r"[A-Z]{3}\d{6}", soporte) is not None
        controles["letra_dni"] = letra_ok

    campos = {
        "tipo": tipo_pais[:2].replace("<", ""),
        "pais": tipo_pais[2:5],
        "num_soporte": soporte,
        "dni": dni if es_dni else None,
        "fecha_nacimiento": fecha_nac,
        "sexo": sexo if sexo in ("M", "F") else None,
        "fecha_caducidad": fecha_cad,
        "nacionalidad": nacionalidad,
        "apellidos": apellidos,
        "nombre": nombre,
    }
    return ResultadoMRZ([l1c, l2c, l3c], campos, controles, correcciones)


def _versiones(linea: str, n: int) -> list[tuple[str, str | None]]:
    """Formas de dejar una línea sobrante en 30 caracteres: recortar el final o quitar uno."""
    versiones = [(linea, None)]  # parsear_td1 recorta el final
    for p in range(len(linea)):
        versiones.append((linea[:p] + linea[p + 1:],
                          f"línea {n}: sobraba «{linea[p]}» en la posición {p + 1}"))
    return versiones


def leer(candidatas: list[str]) -> ResultadoMRZ | None:
    lineas = elegir_lineas(candidatas)
    if not lineas:
        return None
    base = parsear_td1(lineas)

    # Si una línea con dígitos de control trae caracteres de más, el OCR ha insertado algo
    # (a veces en medio, aunque el sobrante parezca un «<» del final) y recortar el final es
    # solo una hipótesis. Se prueban todas las
    # combinaciones (recortar o quitar un carácter en cada línea larga) y solo se acepta si
    # hay UNA única MRZ válida: con varias, alguna cuadra por azar y no se sabe cuál.
    largas = [i for i, linea in ((0, anclar_linea1(lineas[0])), (1, lineas[1]))
              if len(linea) > LONGITUD]
    if not largas:
        return base

    opciones = [_versiones(lineas[i], i + 1) if i in largas else [(lineas[i], None)]
                for i in (0, 1)]
    validas: dict[tuple[str, ...], ResultadoMRZ] = {}
    for (v1, nota1), (v2, nota2) in itertools.product(*opciones):
        r = parsear_td1([v1, v2, lineas[2]])
        if r.valido and tuple(r.lineas) not in validas:
            r.correcciones[:0] = [n for n in (nota1, nota2) if n]
            validas[tuple(r.lineas)] = r
    if len(validas) == 1:
        return next(iter(validas.values()))
    if len(validas) > 1:
        base.controles["sin_ambiguedad"] = False
        base.correcciones.append(
            f"{len(validas)} formas distintas de corregir las líneas dan una MRZ válida: ambiguo")
    return base
