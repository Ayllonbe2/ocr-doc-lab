# OCR Doc Lab

OCR **local, sin nube**, para documentos: un **laboratorio** para evaluar y calibrar, y un
**servicio** HTTP que usa el mismo código y solo escucha en localhost. Cubre el DNI español y
18 tipos de documento: titulaciones (de prevención y, para coordinador de seguridad y salud,
el título de arquitecto, arquitecto técnico o ingeniero industrial y el curso de coordinador),
documentos de empresa (certificados de la
TGSS y la AEAT, póliza de RC, registro de empresas, apertura de centro, planes y evaluaciones) y
del trabajador (contrato, reconocimiento médico y fichas firmadas). Ver
[OCR local multi-documento](docs/ocr-multidocumento.md) y el [Roadmap](docs/roadmap.md).

| | Qué es | Arrancar |
|---|---|---|
| **Lab** (`mrzlab/`) | Página local para comparar motores, ver lo que lee el OCR, medir la calidad de la foto y calibrar. Documentos en `/documentos` | `docker compose up --build` → <http://localhost:8080> |
| **Servicio** (`servicio/`) | API sin estado: `POST /v1/dni/verificar` y `POST /v1/documentos/{tipo}/extraer` | `docker compose --profile servicio up --build servicio` → <http://localhost:8001>. Ver [servicio/README.md](servicio/README.md) |

Con el DNI, el lab compara motores leyendo la **MRZ** (las 3 líneas `IDESP…<<<` del reverso),
valida los dígitos de control, lee los campos del anverso y evalúa la calidad de la foto
(borrosa, oscura, sobreexpuesta, reflejos, resolución).

> **Privacidad.** Las fotos se procesan en memoria en tu ordenador: no se guardan en disco, no
> se registran en logs y en ejecución no se descarga nada. El puerto solo escucha en
> `127.0.0.1`. ONNX Runtime (lo usa RapidOCR) envía por defecto telemetría de uso a Microsoft;
> el laboratorio la desactiva (`ORT_DISABLE_TELEMETRY=1`). Se ha comprobado que así no hace
> ninguna conexión saliente. **No subas fotos de DNI al repositorio**: el `.gitignore` de esta carpeta ignora
> imágenes y CSV, pero guárdalas fuera del repo de todas formas.

Solo usa datos ficticios en los tests y las muestras. Licencia: [Apache-2.0](LICENSE), con una
excepción en el modelo `mrz` de Tesseract (ver [Licencias](#licencias)).

## Arrancar (Docker, recomendado)

Requisitos: Docker Desktop.

```bash
git clone https://github.com/Ayllonbe2/ocr-doc-lab.git
cd ocr-doc-lab
docker compose up --build
```

Abre <http://localhost:8080>. La primera construcción tarda unos minutos y la imagen ocupa
~1–1,5 GB (lleva Tesseract y los modelos). Para comprobar que funciona sin internet: construye una
vez, desconecta la red y vuelve a lanzar `docker compose up`.

## Arrancar sin Docker (Windows)

1. Python 3.11 o 3.12.
2. Tesseract para Windows (instalador de UB Mannheim) y añade su carpeta al `PATH`.
3. En PowerShell, dentro de la carpeta del repositorio:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
mkdir tessdata
Invoke-WebRequest https://raw.githubusercontent.com/sivakumar-mahalingam/fastmrz/main/tessdata/mrz.traineddata -OutFile tessdata\mrz.traineddata
uvicorn mrzlab.app:app --port 8080
```

Sin `tessdata/mrz.traineddata`, Tesseract usa el modelo `eng` (peor).

## Uso

1. Pulsa **«Probar con muestras sintéticas»** para ver la herramienta funcionando con DNI
   ficticios (limpio, borroso, oscuro, sobreexpuesto, con reflejo, baja resolución).
2. Arrastra **fotos reales del reverso** hechas con móvil, como las que subiría un usuario.
   Con 20–30 fotos variadas (buena luz, poca luz, con flash, movidas…) ya se ven diferencias.
3. **Orientación.** Antes de analizarla, cada foto se gira (0/90/180/270°) hasta dejar el
   DNI derecho: la forma de la tarjeta dice si está en vertical o apaisada, y una lectura
   rápida con RapidOCR (sin su corrector de ángulo) decide en qué posición se lee mejor el
   texto. Si se ha girado, la cabecera de la foto lo indica («↻ girada 90°»). Tarda ~1–1,5 s.
   Para cada foto verás:
   - la foto con la MRZ localizada (verde) y los reflejos (rojo), y el recorte de la MRZ;
   - la **calidad** por métrica, en la foto entera y en la zona MRZ, con semáforo y veredicto:
     *Apta*, *Apta con riesgo* o *Rechazar*;
   - por motor: las 3 líneas leídas, los **dígitos de control** (✔/✘), los campos extraídos,
     las correcciones aplicadas y el tiempo.
   - el **texto detectado por el OCR** en la foto entera, línea a línea y con su confianza.
     Las cajas azules marcan en la foto lo que ha leído cada motor. Si pasas el ratón por una
     línea, se resalta su caja.
4. **Anverso.** El selector «Cara» vale para las dos caras. En modo automático se busca la MRZ
   y, además, los campos impresos del anverso junto a sus etiquetas: nº de DNI, soporte,
   apellidos, nombre, sexo, nacionalidad, nacimiento, validez y CAN. Sirven el DNI 4.0
   («APELLIDOS») y el 3.0 («PRIMER/SEGUNDO APELLIDO»). **Solo el nº de DNI tiene control (la
   letra)**; el resto se deduce por la posición y hay que contrastarlo con el reverso o con lo
   declarado. RapidOCR no conoce la «Ñ» (lee «ESPANOLA»). Tesseract usa el modelo `spa`.
   **Plantilla de posiciones.** Con un anverso bien leído (DNI con ✔), pulsa **«Aprender
   posiciones de esta foto»**: se guarda dónde está cada campo dentro de la tarjeta, en
   coordenadas relativas (0–1), en `plantillas/anverso.yaml`. **No se guarda ni la foto ni
   ningún dato**, solo las cajas; con varias fotos se promedian. Desde entonces, cada anverso
   se lee también **por posición**: se sitúa la tarjeta (por sus bordes o, si no se ven, por los
   campos ya reconocidos), se recorta la zona de cada campo y se lee con cada motor, limitando
   los caracteres según el tipo (solo dígitos en fechas y CAN, solo letras en nombres…). La
   tabla compara «por etiqueta» y «por posición». Es lo que más ayuda a Tesseract: con fotos
   sintéticas «de móvil» pasa de 0–2 campos a 6–7. La plantilla está pensada para el DNI 4.0;
   el 3.0 tiene otra disposición.
5. **Cotejo anverso ↔ reverso.** Si subes las dos caras, cada reverso se empareja con el
   anverso del mismo nº de DNI (o, si no, con el siguiente sin pareja; se puede cambiar a mano)
   y se comparan nº de DNI, nacimiento, apellidos, nombre y caducidad: **Cuadra**, **Revisar**
   (falta algún campo o un nombre solo se parece: al menos un 70 % de similitud, posible error de OCR) o
   **No cuadra**. Del anverso se toma, de todo lo leído (cada motor, por etiqueta y por
   posición), el valor que coincide con la MRZ. En los nombres se ignoran tildes, «Ñ»/«N» y
   guiones, y se admite que la MRZ corte un nombre largo (la línea tiene 30 caracteres).
   **Resultado final: APTO o NO APTO para validar la identidad** (sin mirar la calidad de la
   foto). **APTO** si la MRZ es válida, el DNI y las fechas coinciden y el nombre y los
   apellidos tienen al menos un 70 % de similitud. Cualquier otro caso es **NO APTO**, con el
   motivo: algún dato distinto, MRZ no válida, algún dato sin leer o falta una de las caras.
   La calidad de la foto es solo informativa: si el cotejo aprueba, no se muestra; si no, se
   enseña como posible causa. Opcionalmente se escriben los **datos que pone la persona**
   (nº de DNI y nombre completo): el DNI tiene que ser igual al leído y el nombre parecerse al
   menos un 70 % (sin importar tildes ni el orden «nombre apellidos» / «apellidos nombre»).
6. El **resumen del lote** da el porcentaje de acierto por motor y cruza calidad con lectura.
   En el anverso, una lectura cuenta como válida si el nº de DNI trae la letra correcta.
7. **Descargar CSV**: métricas y aciertos por foto, sin datos personales (ni DNI ni nombres).

El modo por lotes (`mrzlab.lote`) sigue midiendo solo el reverso (MRZ).

Una MRZ cuenta como **válida** si cuadran todos los dígitos de control (soporte, nacimiento,
caducidad, compuesto y letra del DNI) y la estructura es correcta (tipo, país, fechas reales,
formato del soporte, nombre sin dígitos).

> **Importante:** en la MRZ del DNI, **la línea del nombre y el sexo no tienen dígito de
> control**. Una MRZ válida garantiza el nº de DNI, el soporte y las fechas, pero el nombre
> puede venir mal leído («NAWVARRO», «3OSE»). En producción, el nombre se debe contrastar con
> el que declara el usuario (con tolerancia a errores de un carácter), como hace el servicio.
> Tampoco están del todo protegidas las **3 letras del nº de soporte**: el control ICAO no
> distingue letras cuyo valor difiere en 10 (M/W, F/P, G/Q, K/U…). En las pruebas apareció un
> «MNU» leído por «WNU» con todos los controles correctos. El nº de DNI y las fechas sí están
> protegidos del todo: cualquier cambio en un solo dígito se detecta.

## Documentos

En <http://localhost:8080/documentos>: eliges el tipo, arrastras un PDF o una foto (o pides una
muestra sintética en PDF digital, escaneado o foto) y ves lo que lee el servicio: campos con su
origen y confianza, validaciones, clasificación, firma/CSV/QR, calidad y, línea a línea, el texto
leído por cada motor sobre la página (en verde, las líneas de donde sale un campo).

Tres caminos según la entrada, decididos por página:

- **PDF con capa de texto**: texto y campos de formulario sin OCR (≈0,1 s por documento).
- **PDF escaneado**: render a 300 ppp, orientación e inclinación, Tesseract (≈3–4 s por página).
- **Foto de móvil**: se busca la hoja y se endereza; RapidOCR encuentra las líneas y las
  reconocen Tesseract y RapidOCR (≈5 s por foto con 2 CPU).

### Medir con un lote

```bash
# Lote real (fuera del repositorio): documentos + verdad.csv (archivo,tipo,campo,valor)
python -m herramientas.medir datos/reales
# Lote sintético: N documentos por tipo y por origen
python -m herramientas.medir --sintetico 2 --origenes digital,escaneado,foto
```

El informe da, por tipo y origen, cuántos documentos salen COMPLETA / INCOMPLETA / ILEGIBLE /
OTRO_DOCUMENTO, el acierto por campo, los tiempos y, lo más importante, los **campos erróneos
dados por buenos** (deben ser 0; el comando termina con error si hay alguno).

La carpeta `datos/` está en `.gitignore` y `.dockerignore`: ahí van los documentos reales (con
consentimiento) y los descargados. **Nunca** al repositorio.

## Modo por lotes (cientos o miles de fotos)

```bash
python -m mrzlab.lote CARPETA --csv resultados.csv --procesos 4
```

- Recorre la carpeta y sus subcarpetas (JPG, PNG, WEBP, TIFF, BMP).
- `--procesos N`: análisis en paralelo. Cada proceso usa un hilo, así que pon como mucho el
  número de núcleos. Como referencia, 150 fotos con los 3 motores y 4 procesos tardan unos 4 min.
- `--motores tesseract,rapidocr`: esos motores (por defecto, solo `rapidocr`). `--max 100`: solo las 100 primeras.
- Escribe un CSV sin datos personales e imprime un resumen en la terminal.

Con Docker (en PowerShell, desde la carpeta del repositorio; cambia `C:\ruta\fotos` por la tuya):
utaotos` por la tuya):

```powershell
docker compose run --rm -v C:\ruta\fotos:/fotos:ro -v ${PWD}\resultados:/resultados lab `
utaotos:/fotos:ro -v ${PWD}
esultados:/resultados lab `
  python -m mrzlab.lote /fotos --csv /resultados/lote.csv --procesos 4
```

### Comparar con los datos correctos (`verdad.csv`)

Si la carpeta tiene un `verdad.csv` (o se indica con `--verdad`), el lote compara campo a campo
lo leído con lo correcto y añade al resumen:

- **Todo correcto**: todos los campos coinciden.
- **Válida y errónea**: la MRZ se dio por válida pero un dato protegido (nº de DNI, dígitos
  del soporte, fechas) está mal. Es el indicador más importante: **debe ser 0**.
- **Válida, sin control mal**: MRZ válida con el nombre, los apellidos, el sexo o las letras
  del soporte mal leídos (posible, porque no tienen control o lo tienen incompleto).
- Acierto por campo y por motor.

Siempre, con o sin verdad, el resumen incluye además el **escenario real**:

- Cuántas fotos rechaza el filtro de calidad (en producción se pediría repetirlas) y el
  acierto sobre las que lo pasan.
- **Con reintentos**: si el `verdad.csv` tiene una columna `grupo` con varias fotos del mismo
  DNI, el porcentaje de DNI resueltos con 1, 2… fotos, con dos políticas:
  - **A**: se pide repetir si el filtro de calidad rechaza la foto o si la MRZ no valida.
  - **B**: se intenta leer siempre y solo se pide repetir si la MRZ no valida; los avisos de
    calidad sirven para decirle al usuario qué corregir.

Formato (separador `;` o `,`); las columnas vacías no se comparan:

```
archivo;grupo;dni;num_soporte;fecha_nacimiento;fecha_caducidad;sexo;apellidos;nombre
foto_ana_1.jpg;ana;12345678Z;BAA000589;01/01/1980;01/01/2031;F;GARCIA LOPEZ;ANA
foto_ana_2.jpg;ana;12345678Z;BAA000589;01/01/1980;01/01/2031;F;GARCIA LOPEZ;ANA
esp_id/*.jpg;;99999999R;;;;;;
```

`archivo` puede ser la ruta relativa, el nombre del fichero o un patrón con `*`, útil para dar
la misma verdad a todos los fotogramas de un mismo documento. Las fechas pueden ir como
`dd/mm/aaaa` o `aaaa-mm-dd`, y los nombres con o sin tildes. Si la MRZ recorta un nombre largo,
se acepta el recorte.

## Fotos de prueba

### Sintéticas "de móvil" (inmediato, sin datos personales)

```bash
python -m mrzlab.sintetico carpeta_salida -n 200 --semilla 1
python -m mrzlab.sintetico carpeta_salida -n 100 --tomas 2   # 2 fotos por DNI, para reintentos
```

Genera DNI con identidades ficticias (MRZ válida) y degradaciones al azar: perspectiva, luz
desigual, sombras, reflejos, movimiento, desenfoque, baja resolución, ruido y compresión JPEG.
Escribe también su `verdad.csv`, así que se pueden pasar directamente por el modo por lotes.
La página incluye cuatro de estas fotos (`movil-1` … `movil-4`) en las muestras sintéticas.

La tarjeta es genérica, no imita el diseño del DNI, y la fuente no es exactamente OCR-B. Sirve
para comparar motores y probar la herramienta, pero **no sustituye a las fotos reales** para
calibrar.

### Datasets públicos

- **MIDV-500, MIDV-2019 y MIDV-2020** (Smart Engines): miles de fotos y fotogramas de vídeo de
  documentos de identidad con datos ficticios, hechos con móvil en condiciones reales. Incluyen
  el documento español (`esp_id`). **Antes de usarlos, comprueba**: (1) la licencia de cada
  uno, y (2) si incluyen el **reverso con la MRZ**, porque en algunos solo está el anverso.
- Traen anotaciones de los campos: conviértelas a `verdad.csv` (con patrones `*` si todos los
  fotogramas son del mismo documento).

### Especímenes oficiales

La Policía Nacional (dnielectronico.es) y el registro PRADO del Consejo de la UE publican
especímenes del DNI 3.0 y 4.0 por las dos caras ("ESPAÑOLA ESPAÑOLA, CARMEN", 99999999R).
Imprimirlos a tamaño real y fotografiarlos con el móvil da fotos bastante realistas, aunque el
papel no refleja como el plástico. Solo para pruebas internas.

### DNI reales del equipo (calibración final)

Son imprescindibles para decidir. Usa la plantilla [`CONSENTIMIENTO.md`](CONSENTIMIENTO.md):
consentimiento por escrito, finalidad concreta, fotos fuera del repo y borrado al terminar.
Mejor 10–20 personas, con distintos móviles y DNI 3.0 y 4.0.

## Calibrar los umbrales de calidad

Los umbrales de `umbrales.yaml` son **valores iniciales** probados solo con imágenes sintéticas.
Se releen en cada análisis, así que puedes editarlos sin reiniciar. Con fotos reales:

- Si muchas fotos marcadas **«Rechazar» se leen bien**, el umbral es demasiado estricto.
- Si fotos marcadas **«Apta» fallan**, es demasiado laxo o falta una métrica.
- La tabla **«Por aviso»** dice, para cada aviso, qué porcentaje de esas fotos se leyó igualmente.

El objetivo es que el veredicto prediga si la MRZ se va a poder leer. Esos umbrales son los que
se llevarían después a producción, para pedir otra foto al usuario *antes* de enviarla.

## Motores

| Motor | Qué hace | Licencia |
|---|---|---|
| `rapidocr` | Modelos PP-OCR de **PaddleOCR** ejecutados con ONNX Runtime (sin instalar PaddlePaddle). Lee el recorte de la MRZ y también la foto entera | Apache-2.0 |
| `tesseract` | Tesseract 5 sobre el recorte de la MRZ, con el modelo `mrz` entrenado en la fuente OCR-B | Apache-2.0 (programa); el modelo `mrz`, **AGPL-3.0** (ver abajo) |

**En el DNI solo se usa RapidOCR** (lab, lote y servicio): con fotos reales lee mejor que
Tesseract. Tesseract sigue disponible para comparar (en la página, marcándolo; en el lote,
`--motores tesseract,rapidocr`) y se sigue usando en los demás documentos. Si se piden los
dos, la página y el lote muestran también **`combinado`**: RapidOCR primero y, solo si no
consigue una MRZ válida, Tesseract; su tiempo es lo que costaría usarlos en cadena.

**Cómo lee cada motor.** Cada motor prueba varios preprocesados y **para en el primero que da
una MRZ válida**:

1. Sobre la foto original: recorte de la MRZ (Tesseract, con umbral de Otsu, umbral adaptativo,
   CLAHE o gris; RapidOCR, con el recorte, la foto entera o el recorte con CLAHE).
2. Si no valida, sobre la **tarjeta enderezada**: se detectan los bordes de la tarjeta, se
   corrige la perspectiva y, si la MRZ queda arriba, se gira 180°.

FastMRZ se evaluó y se descartó: licencia AGPL-3.0 y no encontró la MRZ en la foto real
probada. Sin embargo, **el modelo `mrz.traineddata` que usa Tesseract sale de su repositorio**
(AGPL-3.0, sin licencia propia ni origen documentado). Ver [Licencias](#licencias).

El parseo de la MRZ y la validación de los dígitos de control (`mrzlab/mrz.py`) son código
propio, sin dependencias. Si el control no cuadra, se corrigen confusiones típicas del OCR
(`0↔O`, `1↔I`, `5↔S`, `8↔B`…) según el tipo de cada posición, se descarta la basura leída antes
de `IDESP` (p. ej. el borde de la tarjeta), se prueba a quitar un carácter sobrante y se
recupera la letra del DNI leída como dígito (D → `0`). Si una línea trae caracteres de más,
se prueban todas las formas de corregirla (recortar el final o quitar un carácter en cada
línea) y solo se acepta si hay **una única** MRZ válida; con varias, se marca como ambigua.
Cada corrección solo se acepta si los dígitos de control confirman un único resultado; los tests incluyen casos reales en los que una
corrección demasiado permisiva había dado por buenos datos erróneos.

## Limitaciones conocidas

- Solo documentos **TD1** (DNI 3.0/4.0 y documentos de identidad de tamaño tarjeta).
- Formatos JPG, PNG y WEBP. Las fotos **HEIC** de iPhone hay que convertirlas antes.
- La orientación EXIF se respeta. Una foto girada sin EXIF solo se corrige si se detectan los
  bordes de la tarjeta (segunda pasada con la tarjeta enderezada).
- Los tiempos son en CPU. La primera foto tarda más porque se cargan los modelos.
- Las muestras sintéticas no sustituyen a las fotos reales: sirven para ver la herramienta
  funcionando y comparar motores, no para calibrar.

## Estructura

```
mrzlab/
  app.py         API FastAPI + página
  mrz.py         parseo TD1, dígitos de control y corrección
  calidad.py     métricas de calidad de imagen
  deteccion.py   localización de la MRZ con OpenCV
  preproceso.py  enderezado de la tarjeta, CLAHE y umbral adaptativo
  motores.py     rapidocr / tesseract detrás de una interfaz común
  anverso.py     campos del anverso a partir del texto y las cajas del OCR
  plantilla.py   plantilla de posiciones del anverso: aprender, situar la tarjeta, leer por zonas
  analisis.py    análisis de una foto (lo usan la página y el lote)
  lote.py        modo por lotes y comparación con verdad.csv
  sintetico.py   DNI ficticios, degradaciones "de móvil" y generador de lotes
  documentos.py  leer un documento (PDF o imagen) y extraer los campos de un tipo
  pdf.py         capa de texto, formularios y render de PDF (pdfplumber, pypdfium2)
  pagina.py      hoja en la foto, orientación e inclinación
  ocr_documento.py  OCR de páginas: Tesseract + detección y relectura con RapidOCR
  lineas.py      formato común de lo leído (texto, caja, página, origen, confianza)
  validadores.py NIF/NIE/CIF, fechas e importes
  autenticidad.py firma PAdES, CSV/CEA, QR y metadatos
  clasificador.py qué tipo de documento es
  extractores/   un extractor por tipo (titulaciones, empresa, trabajador, firma)
  sintetico_docs.py documentos sintéticos de cada tipo (PDF, escaneo, foto)
  static/index.html, static/documentos.html
servicio/        API de producción sobre mrzlab (ver servicio/README.md)
  app.py         app FastAPI: X-Api-Key, /health
  api.py         POST /v1/dni/verificar
  documentos.py  /v1/documentos/tipos, /{tipo}/extraer, /clasificar
  lectura.py     lectura de cada cara del DNI
  verificacion.py  decisión: VERIFICADO / REPETIR / REVISION_ADMIN
herramientas/    medir.py (lotes con verdad.csv), contrato.py (openapi.json y ejemplos)
docs/            diseño, roadmap, openapi.json y ejemplos de respuesta
umbrales.yaml    umbrales de calidad (editables)
plantillas/      plantilla de posiciones del anverso (solo coordenadas)
CONSENTIMIENTO.md  plantilla para voluntarios
tests/
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest                 # todo (los de OCR real tardan unos minutos)
python -m pytest -m "not ocr"    # sin los escaneos y fotos con OCR real
```

Los tests de extremo a extremo se saltan los motores que no estén instalados. Los documentos de
los tests son sintéticos (`mrzlab/sintetico_docs.py`), con datos inventados.

## Próximos pasos

Ver el estado de cada hito en el [Roadmap](docs/roadmap.md): falta sobre todo medir con
documentos reales de cada tipo (con consentimiento) y calibrar con ellos.

## Licencias

El código de este repositorio se publica con licencia [Apache-2.0](LICENSE). Tesseract,
OpenCV, RapidOCR y los modelos PP-OCR también son Apache-2.0.

**Excepción: el modelo `mrz.traineddata`.** No está en este repositorio: el `Dockerfile` lo
descarga al construir la imagen (con el hash verificado) desde el repositorio de
[FastMRZ](https://github.com/sivakumar-mahalingam/fastmrz), que es **AGPL-3.0** y no documenta
otra licencia ni el origen del modelo. Si construyes la imagen, estás usando ese modelo bajo sus
condiciones. Sin él, Tesseract usa el modelo `eng` (peor en la MRZ) y RapidOCR no se ve afectado.
Para usar el laboratorio en un servicio, valora sustituirlo por un modelo de licencia clara.
Esto es una descripción, no asesoramiento jurídico.
