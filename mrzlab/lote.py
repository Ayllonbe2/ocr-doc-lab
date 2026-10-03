"""Modo por lotes: analiza una carpeta de fotos y escribe un CSV con el resultado.

    python -m mrzlab.lote CARPETA [--verdad verdad.csv] [--csv salida.csv] [--procesos 4]

Si hay un fichero de verdad (por defecto CARPETA/verdad.csv), compara campo a campo lo leído
con los datos correctos. Formato (separador «;»):

    archivo;dni;num_soporte;fecha_nacimiento;fecha_caducidad;sexo;apellidos;nombre

«archivo» puede ser la ruta relativa, el nombre del fichero o un patrón con comodines
(p. ej. «esp_id/*.jpg») para dar la misma verdad a todos los fotogramas de un documento.
Las columnas que falten o estén vacías no se comparan.

El CSV de salida no contiene datos personales: solo métricas, aciertos y fallos por campo.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import re
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import analisis, calidad, motores

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
CAMPOS = ["dni", "num_soporte", "fecha_nacimiento", "fecha_caducidad", "sexo", "apellidos", "nombre"]
# Campos cubiertos por completo por dígitos de control (solo dígitos: cualquier cambio en un
# dígito se detecta). Sexo, apellidos y nombre no tienen control, y las letras del soporte solo
# en parte: el control ICAO no distingue letras cuyo valor difiere en 10 (M/W, F/P, G/Q, K/U…).
PROTEGIDOS = {"dni", "soporte_digitos", "fecha_nacimiento", "fecha_caducidad"}
SIN_CONTROL = {"sexo", "apellidos", "nombre", "soporte_letras"}
_UMBRALES: dict | None = None
_PEDIDOS: set[str] | None = None


# ── Verdad y comparación ─────────────────────────────────────────────────────

def normalizar(valor: str | None, campo: str) -> str:
    if not valor:
        return ""
    v = unicodedata.normalize("NFKD", valor.upper()).encode("ascii", "ignore").decode()
    if campo.startswith("fecha"):
        m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*", v)
        if m:
            return f"{int(m[3]):02d}/{int(m[2]):02d}/{m[1]}"
        m = re.fullmatch(r"\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\s*", v)
        if m:
            return f"{int(m[1]):02d}/{int(m[2]):02d}/{m[3]}"
        return v.strip()
    return " ".join(re.sub(r"[^A-Z0-9]", " ", v).split())


def cargar_verdad(ruta: Path) -> list[tuple[str, dict]]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        muestra = f.read(2048)
        f.seek(0)
        separador = ";" if muestra.count(";") >= muestra.count(",") else ","
        return [(fila["archivo"].strip(), {c: fila.get(c, "") for c in CAMPOS + ["grupo"]})
                for fila in csv.DictReader(f, delimiter=separador) if fila.get("archivo")]


def buscar_verdad(verdad: list[tuple[str, dict]], relativa: str) -> dict | None:
    nombre = Path(relativa).name
    for clave, datos in verdad:
        if clave in (relativa, nombre):
            return datos
    for clave, datos in verdad:
        if fnmatch.fnmatch(relativa, clave) or fnmatch.fnmatch(nombre, clave):
            return datos
    return None


def comparar(leido: dict | None, verdad: dict, linea3: str | None) -> dict[str, bool]:
    """Acierto por campo. Si la línea 3 está llena (sin «<» final), los nombres se aceptan
    recortados, igual que los recorta la propia MRZ."""
    resultado = {}
    truncada = bool(linea3) and not linea3.endswith("<")
    for campo in CAMPOS:
        esperado = normalizar(verdad.get(campo), campo)
        if not esperado:
            continue
        obtenido = normalizar((leido or {}).get(campo), campo)
        ok = obtenido == esperado
        if not ok and truncada and campo in ("apellidos", "nombre") and obtenido:
            ok = esperado.replace(" ", "").startswith(obtenido.replace(" ", ""))
        resultado[campo] = ok
    # El soporte se desdobla: dígitos (protegidos) y letras (protección parcial).
    esperado = normalizar(verdad.get("num_soporte"), "num_soporte").replace(" ", "")
    if len(esperado) == 9:
        obtenido = normalizar((leido or {}).get("num_soporte"), "num_soporte").replace(" ", "")
        resultado["soporte_digitos"] = obtenido[3:] == esperado[3:]
        resultado["soporte_letras"] = obtenido[:3] == esperado[:3]
    return resultado


# ── Análisis ─────────────────────────────────────────────────────────────────

def _iniciar(ruta_umbrales: str, pedidos: set[str] | None, hilos: int | None) -> None:
    global _UMBRALES, _PEDIDOS
    if hilos:
        motores.limitar_hilos(hilos)
    _UMBRALES = calidad.cargar_umbrales(ruta_umbrales)
    _PEDIDOS = pedidos


def _analizar_archivo(ruta: str) -> dict:
    try:
        img = analisis.decodificar(Path(ruta).read_bytes())
    except (OSError, analisis.ImagenInvalida) as e:
        return {"error": str(e)}
    # El lote mide la lectura de la MRZ (reverso), comparable con verdad.csv.
    resultado, _ = analisis.analizar(img, _UMBRALES, _PEDIDOS, lado="reverso", con_texto=False)
    for m in resultado["motores"]:
        m.pop("texto_bruto", None)
    return resultado


def listar(carpeta: Path) -> list[Path]:
    return sorted(p for p in carpeta.rglob("*") if p.suffix.lower() in EXTENSIONES and p.is_file())


def fila_csv(relativa: str, r: dict, verdad: dict | None, nombres: list[str],
             metricas: list[str]) -> dict:
    fila = {"archivo": relativa, "grupo": (verdad or {}).get("grupo", "")}
    if "error" in r:
        fila["error"] = r["error"]
        return fila
    cal = r["calidad"]
    fila.update({
        "ancho": r["dimensiones"]["ancho"], "alto": r["dimensiones"]["alto"],
        "mrz_localizada": "si" if r["caja_mrz"] else "no", "veredicto": cal["veredicto"],
        "avisos": " | ".join(f"{a['zona']}.{a['metrica']}:{a['nivel']}" for a in cal["avisos"]),
    })
    for k in metricas:
        z, m = k.split(".", 1)
        fila[k] = cal["zonas"].get(z, {}).get(m, {}).get("valor", "")
    for n in nombres:
        m = next((x for x in r["motores"] if x["motor"] == n), None)
        if m is None or not m.get("disponible"):
            continue
        mrz_ = m.get("mrz")
        fila[f"{n}.valido"] = "si" if mrz_ and mrz_["valido"] else "no"
        fila[f"{n}.ms"] = m["ms"]
        fila[f"{n}.correcciones"] = len(mrz_["correcciones"]) if mrz_ else ""
        fila[f"{n}.error"] = m.get("error") or ""
        if verdad:
            aciertos = comparar(mrz_ and mrz_["campos"], verdad, mrz_ and mrz_["lineas"][2])
            principales = {c: ok for c, ok in aciertos.items() if c in CAMPOS}
            fila[f"{n}.campos_ok"] = f"{sum(principales.values())}/{len(principales)}"
            fila[f"{n}.campos_fallidos"] = ",".join(c for c, ok in principales.items() if not ok)
            valido = bool(mrz_ and mrz_["valido"])
            # Lo grave: los dígitos de control cuadran pero un campo protegido es incorrecto.
            fila[f"{n}.valido_pero_erroneo"] = "si" if valido and any(
                not ok for c, ok in aciertos.items() if c in PROTEGIDOS) else "no"
            # Esperable (sin control o con control parcial), pero hay que medirlo.
            fila[f"{n}.valido_sin_control_erroneo"] = "si" if valido and any(
                not ok for c, ok in aciertos.items() if c in SIN_CONTROL) else "no"
    return fila


# ── Resumen ──────────────────────────────────────────────────────────────────

def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f} %" if b else "    —  "


def resumen(filas: list[dict], nombres: list[str], con_verdad: bool) -> str:
    ok = [f for f in filas if "error" not in f]
    out = [f"\nImágenes analizadas: {len(ok)}  (ilegibles: {len(filas) - len(ok)})\n"]
    out.append(f"{'Motor':<11}{'MRZ válida':>12}{'Tiempo medio':>15}"
               + (f"{'Todo correcto':>16}{'Válida y errónea*':>19}{'Válida, sin control mal**':>27}"
                  if con_verdad else ""))
    for n in nombres:
        con = [f for f in ok if f"{n}.valido" in f]
        if not con:
            continue
        val = sum(f[f"{n}.valido"] == "si" for f in con)
        ms = sum(int(f[f"{n}.ms"]) for f in con) / len(con)
        linea = f"{n:<11}{_pct(val, len(con)):>12}{ms:>12.0f} ms"
        if con_verdad:
            cv = [f for f in con if f.get(f"{n}.campos_ok")]
            todo = sum(f[f"{n}.campos_fallidos"] == "" for f in cv)
            falso = sum(f[f"{n}.valido_pero_erroneo"] == "si" for f in cv)
            sin_control = sum(f[f"{n}.valido_sin_control_erroneo"] == "si" for f in cv)
            linea += f"{_pct(todo, len(cv)):>16}{falso:>19}{sin_control:>27}"
        out.append(linea)

    if con_verdad:
        out.append("\n*  MRZ válida con un dato protegido (nº de DNI, dígitos del soporte, fechas) "
                   "incorrecto: debe ser 0.")
        out.append("** MRZ válida con un dato sin control completo incorrecto: nombre, apellidos, sexo o")
        out.append("   letras del soporte (el control no distingue M/W, F/P, G/Q…). Contrastar con lo declarado.")
        out.append("\nAcierto por campo")
        out.append(f"{'Campo':<18}" + "".join(f"{n:>12}" for n in nombres))
        for campo in CAMPOS:
            celdas = []
            for n in nombres:
                cv = [f for f in ok if f.get(f"{n}.campos_ok")]
                total = sum(1 for f in cv) if cv else 0
                fallos = sum(campo in f[f"{n}.campos_fallidos"].split(",") for f in cv)
                celdas.append(f"{_pct(total - fallos, total):>12}")
            out.append(f"{campo:<18}" + "".join(celdas))

    # Escenario real: las fotos que el filtro de calidad rechaza se piden de nuevo al usuario.
    pasan = [f for f in ok if f["veredicto"] != "rechazar"]
    out.append(f"\nEscenario real: el filtro de calidad pide repetir {len(ok) - len(pasan)} de "
               f"{len(ok)} fotos ({_pct(len(ok) - len(pasan), len(ok)).strip()})")
    out.append(f"{'Motor':<11}{'Válida (fotos que pasan el filtro)':>36}")
    for n in nombres:
        con = [f for f in pasan if f"{n}.valido" in f]
        val = sum(f[f"{n}.valido"] == "si" for f in con)
        out.append(f"{n:<11}{_pct(val, len(con)):>36}")

    grupos: dict[str, list[dict]] = {}
    for f in ok:
        if f.get("grupo"):
            grupos.setdefault(f["grupo"], []).append(f)
    if grupos and max(len(g) for g in grupos.values()) > 1:
        tomas = max(len(g) for g in grupos.values())
        out.append(f"\nCon reintentos ({len(grupos)} DNI, hasta {tomas} fotos cada uno): % de DNI resueltos.")
        out.append("  A: se pide repetir si el filtro de calidad rechaza la foto o la MRZ no valida.")
        out.append("  B: se intenta leer siempre; solo se pide repetir si la MRZ no valida.")
        cab = "".join(f"{f'≤ {k} foto' + ('s' if k > 1 else ''):>12}" for k in range(1, tomas + 1))
        out.append(f"{'Motor':<11}{'':>3}{cab}")
        for n in nombres:
            for politica, usa_filtro in (("A", True), ("B", False)):
                celdas = []
                for k in range(1, tomas + 1):
                    resueltos = 0
                    for g in grupos.values():
                        for f in sorted(g, key=lambda x: x["archivo"])[:k]:
                            if usa_filtro and f["veredicto"] == "rechazar":
                                continue
                            if f.get(f"{n}.valido") == "si":
                                resueltos += 1
                                break
                    celdas.append(f"{_pct(resueltos, len(grupos)):>12}")
                out.append(f"{n if politica == 'A' else '':<11}{politica:>3}" + "".join(celdas))

    out.append("\nCalidad × lectura (% con MRZ válida)")
    out.append(f"{'Veredicto':<11}{'Fotos':>7}" + "".join(f"{n:>12}" for n in nombres))
    for v in ("apta", "riesgo", "rechazar"):
        g = [f for f in ok if f["veredicto"] == v]
        out.append(f"{v:<11}{len(g):>7}" + "".join(
            f"{_pct(sum(f.get(f'{n}.valido') == 'si' for f in g), len(g)):>12}" for n in nombres))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    raiz = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Analiza una carpeta de fotos de DNI.")
    ap.add_argument("carpeta", type=Path)
    ap.add_argument("--verdad", type=Path, help="CSV con los datos correctos (por defecto CARPETA/verdad.csv)")
    ap.add_argument("--csv", type=Path, default=Path("mrz-lab-lote.csv"), help="CSV de salida")
    ap.add_argument("--motores", default="", help="lista separada por comas (por defecto, solo rapidocr)")
    ap.add_argument("--max", type=int, default=0, help="analizar como mucho N fotos")
    ap.add_argument("--procesos", type=int, default=1, help="procesos en paralelo (cada uno carga los modelos)")
    ap.add_argument("--umbrales", type=Path, default=raiz / "umbrales.yaml")
    a = ap.parse_args(argv)

    archivos = listar(a.carpeta)
    if a.max:
        archivos = archivos[:a.max]
    if not archivos:
        print(f"No hay imágenes en {a.carpeta}", file=sys.stderr)
        return 1
    ruta_verdad = a.verdad or (a.carpeta / "verdad.csv")
    verdad = cargar_verdad(ruta_verdad) if ruta_verdad.is_file() else []
    if a.verdad and not verdad:
        print(f"Aviso: {ruta_verdad} no tiene filas", file=sys.stderr)

    pedidos = {n for n in a.motores.split(",") if n} or set(analisis.MOTORES_DNI)
    nombres = [m.nombre for m in motores.TODOS if m.nombre in pedidos]
    if all(n in nombres for n in analisis.ORDEN_COMBINADO):
        nombres.append("combinado")
    metricas = [f"{z}.{m}" for z in ("global", "mrz")
                for m in calidad.cargar_umbrales(a.umbrales)[z]]
    metricas = [k.replace("brillo_bajo", "brillo") for k in metricas if not k.endswith("brillo_alto")]

    filas, sin_verdad = [], 0
    t0 = time.perf_counter()
    rutas = [str(p) for p in archivos]
    with ProcessPoolExecutor(max(1, a.procesos), initializer=_iniciar,
                             initargs=(str(a.umbrales), pedidos, 1 if a.procesos > 1 else None)) as ex:
        for i, (p, r) in enumerate(zip(archivos, ex.map(_analizar_archivo, rutas)), 1):
            relativa = p.relative_to(a.carpeta).as_posix()
            v = buscar_verdad(verdad, relativa) if verdad else None
            if verdad and v is None:
                sin_verdad += 1
            filas.append(fila_csv(relativa, r, v, nombres, metricas))
            print(f"\r[{i}/{len(archivos)}] {relativa[:60]:<60}", end="", file=sys.stderr, flush=True)
    print(f"\nTiempo total: {time.perf_counter() - t0:.0f} s", file=sys.stderr)

    columnas = list(dict.fromkeys(k for f in filas for k in f))
    with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";")
        w.writeheader()
        w.writerows(filas)

    print(resumen(filas, nombres, bool(verdad)))
    if sin_verdad:
        print(f"\nAviso: {sin_verdad} foto(s) sin fila en el fichero de verdad", file=sys.stderr)
    print(f"\nCSV escrito en {a.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
