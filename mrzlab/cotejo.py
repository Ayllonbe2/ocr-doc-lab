"""Cotejo del anverso con el reverso (MRZ) del mismo DNI.

Compara nº de DNI, fecha de nacimiento, nombre, apellidos y fecha de caducidad. Del anverso
llegan varios candidatos por campo (cada motor, por etiqueta y por posición): se elige el que
coincide con la MRZ y, si ninguno coincide, el más repetido.

Diferencias de escritura que no son errores:
- La MRZ no lleva tildes ni Ñ (se escribe N), y los guiones y apóstrofos son separadores.
- La línea del nombre tiene 30 caracteres: un nombre largo puede venir cortado en la MRZ.
"""
from __future__ import annotations

import re
from collections import Counter

from .anverso import normalizar

CAMPOS = ("dni", "fecha_nacimiento", "apellidos", "nombre", "fecha_caducidad")
NOMBRES = ("apellidos", "nombre")
LONGITUD_LINEA = 30
# Similitud mínima (0-1) para dar por buena una diferencia en nombres: entre las dos caras
# (error de lectura del OCR) y entre lo leído y lo que declara la persona.
SIMILITUD_MIN = 0.70


def a_mrz(texto: str | None) -> str:
    """Un nombre tal como se escribe en la MRZ: sin tildes, Ñ→N y solo letras y espacios."""
    t = normalizar(texto or "").replace("Ñ", "N").replace("Ç", "C")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z]", " ", t)).strip()


def distancia(a: str, b: str) -> int:
    """Distancia de edición (Levenshtein)."""
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def similitud(a: str, b: str) -> float:
    """1 - distancia de edición / longitud del más largo (1 = iguales), en forma MRZ."""
    a, b = a_mrz(a), a_mrz(b)
    if not a and not b:
        return 1.0
    return 1 - distancia(a, b) / max(len(a), len(b))


def similitud_nombre_completo(declarado: str, leido: str) -> float:
    """Como similitud, pero sin importar el orden de las palabras («Nombre Apellidos» o
    «Apellidos, Nombre»)."""
    ordenar = lambda t: " ".join(sorted(a_mrz(t).split()))
    return max(similitud(declarado, leido), similitud(ordenar(declarado), ordenar(leido)))


def _linea_llena(reverso: dict) -> bool:
    """La línea 3 de la MRZ (APELLIDOS<<NOMBRE) está completa: el nombre puede estar cortado."""
    ap, nom = reverso.get("apellidos") or "", reverso.get("nombre") or ""
    return len(ap) + 2 + len(nom) >= LONGITUD_LINEA


def comparar(campo: str, valor_anv: str | None, valor_rev: str | None, linea_llena: bool = False) -> dict:
    """estado: coincide | parecido | distinto | falta (alguna cara sin leer)."""
    if not valor_anv or not valor_rev:
        return {"estado": "falta", "nota": "sin leer en el " + ("anverso" if not valor_anv else "reverso")}
    if campo not in NOMBRES:
        a, r = valor_anv.replace(" ", "").upper(), valor_rev.replace(" ", "").upper()
        return {"estado": "coincide" if a == r else "distinto", "nota": None}
    a, r = a_mrz(valor_anv), a_mrz(valor_rev)
    if a == r:
        nota = None if normalizar(valor_anv) == normalizar(valor_rev) else "igual salvo tildes, Ñ o signos"
        return {"estado": "coincide", "nota": nota}
    if a.replace(" ", "") == r.replace(" ", ""):
        return {"estado": "coincide", "nota": "igual salvo espacios"}
    if linea_llena and a.replace(" ", "").startswith(r.replace(" ", "")):
        return {"estado": "coincide", "nota": "cortado en la MRZ (la línea tiene 30 caracteres)"}
    sim = similitud(a, r)
    if sim >= SIMILITUD_MIN:
        return {"estado": "parecido", "nota": f"{sim:.0%} de similitud: posible error de lectura"}
    return {"estado": "distinto", "nota": f"{sim:.0%} de similitud (mínimo {SIMILITUD_MIN:.0%})"}


def _elegir(campo: str, candidatos: list[dict], valor_rev: str | None, linea_llena: bool) -> dict | None:
    """El candidato que coincide con la MRZ; si no, el parecido; si no, el más repetido."""
    validos = [c for c in candidatos if c.get("valor")]
    if not validos:
        return None
    for estado in ("coincide", "parecido"):
        for c in validos:
            if comparar(campo, c["valor"], valor_rev, linea_llena)["estado"] == estado:
                return c
    clave = (lambda v: a_mrz(v)) if campo in NOMBRES else (lambda v: v.replace(" ", "").upper())
    mas_comun = Counter(clave(c["valor"]) for c in validos).most_common(1)[0][0]
    return next(c for c in validos if clave(c["valor"]) == mas_comun)


def cotejar_declarado(declarado: dict, reverso: dict, anverso: dict) -> dict:
    """Lo que declara la persona frente a lo leído: el DNI exacto y el nombre completo con al
    menos SIMILITUD_MIN (el mejor de la MRZ y del anverso)."""
    out = {}
    dni = (declarado.get("dni") or "").replace(" ", "").replace("-", "").upper()
    if dni:
        leido = reverso.get("dni") or anverso.get("dni")
        out["dni"] = {"declarado": dni, "leido": leido,
                      "estado": "falta" if not leido else ("coincide" if leido == dni else "distinto")}
    nombre = (declarado.get("nombre") or "").strip()
    if nombre:
        leidos = [" ".join(x for x in (fuente.get("nombre"), fuente.get("apellidos")) if x)
                  for fuente in (reverso, anverso)]
        leidos = [x for x in leidos if x]
        mejor = max(leidos, key=lambda x: similitud_nombre_completo(nombre, x), default=None)
        sim = similitud_nombre_completo(nombre, mejor) if mejor else None
        out["nombre"] = {"declarado": nombre, "leido": mejor,
                         "similitud": None if sim is None else round(sim, 3),
                         "estado": "falta" if sim is None else
                         ("coincide" if sim == 1 else "parecido" if sim >= SIMILITUD_MIN else "distinto")}
    return out


def decidir(campos: dict, mrz_valida: bool, declarado: dict | None = None) -> tuple[str, str]:
    """Decisión final, sin mirar la calidad de la foto: si se ha leído y cuadra, se aprueba.

    aprobar: MRZ válida, DNI y fechas (con dígito de control en la MRZ) iguales en las dos
    caras, nombre y apellidos con al menos SIMILITUD_MIN, y, si se han declarado, el mismo
    DNI y un nombre con al menos SIMILITUD_MIN.
    rechazar: algún dato distinto. revisar: el resto (MRZ no válida o algún campo sin leer).
    """
    estados = {c: v["estado"] for c, v in campos.items()}
    estados.update({f"{c} declarado": v["estado"] for c, v in (declarado or {}).items()})
    if "distinto" in estados.values():
        malos = ", ".join(c for c, e in estados.items() if e == "distinto")
        return "rechazar", f"no coincide: {malos}"
    if not mrz_valida:
        return "revisar", "la MRZ no es válida (no cuadran sus dígitos de control)"
    faltan = [c for c, e in estados.items() if e == "falta"]
    if faltan:
        return "revisar", f"sin leer: {', '.join(faltan)}"
    parecidos = [c for c, e in estados.items() if e == "parecido"]
    if parecidos:
        return "aprobar", (f"DNI y fechas coinciden; {', '.join(parecidos)} con al menos "
                           f"{SIMILITUD_MIN:.0%} de similitud")
    return "aprobar", "coincide todo"


def cotejar(anverso: dict[str, list[dict]], reverso: dict, mrz_valida: bool = True,
            declarado: dict | None = None) -> dict:
    """anverso: {campo: [{"valor", "fuente"}, …]}; reverso: campos de la MRZ.

    Devuelve un resultado por campo y el global: «cuadra» si coinciden todos, «no_cuadra» si
    alguno es distinto y «revisar» si falta alguno o solo se parece. Además, la decisión
    final (ver decidir). declarado: {"dni", "nombre"} que pone la persona (opcional).
    """
    llena = _linea_llena(reverso)
    campos = {}
    for campo in CAMPOS:
        valor_rev = reverso.get(campo)
        elegido = _elegir(campo, anverso.get(campo) or [], valor_rev, llena)
        res = comparar(campo, elegido and elegido["valor"], valor_rev, llena)
        otros = sorted({c["valor"] for c in anverso.get(campo) or [] if c.get("valor")} -
                       {elegido and elegido["valor"]})
        campos[campo] = {
            "anverso": elegido and elegido["valor"],
            "fuente": elegido and elegido.get("fuente"),
            "otros_anverso": otros,
            "reverso": valor_rev,
            **res,
        }
    estados = {c["estado"] for c in campos.values()}
    if "distinto" in estados:
        resultado = "no_cuadra"
    elif estados == {"coincide"}:
        resultado = "cuadra"
    else:
        resultado = "revisar"
    decl = cotejar_declarado(declarado or {}, reverso, {c: v["anverso"] for c, v in campos.items()})
    decision, motivo = decidir(campos, mrz_valida, decl)
    return {"resultado": resultado, "decision": decision, "motivo": motivo, "campos": campos,
            "declarado": decl}
