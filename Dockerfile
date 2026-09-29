FROM python:3.11-slim

# Tesseract para el motor «tesseract» (y castellano para el anverso); fuentes para las muestras sintéticas.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa fonts-dejavu-core curl ca-certificates libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# rapidocr arrastra opencv-python (con GUI): se sustituye por la versión headless.
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y opencv-python \
 && pip install --no-cache-dir --no-deps --force-reinstall opencv-python-headless==5.0.0.93

# Modelo de Tesseract entrenado para la fuente OCR-B de la MRZ. Sale del repositorio de FastMRZ
# (AGPL-3.0, sin licencia propia ni origen documentado): ver «Licencias» en el README.
# Se verifica el hash: si el fichero cambia en origen, el build falla en vez de usar otro modelo.
ARG MRZ_TRAINEDDATA_URL=https://raw.githubusercontent.com/sivakumar-mahalingam/fastmrz/main/tessdata/mrz.traineddata
ARG MRZ_TRAINEDDATA_SHA256=e44f5b7a6bdd3f382ef3bfa84ee0057f5897946a84a094c26910e0a124f3a9bd
RUN mkdir -p /opt/tessdata \
 && curl -fsSL -o /opt/tessdata/mrz.traineddata "$MRZ_TRAINEDDATA_URL" \
 && echo "$MRZ_TRAINEDDATA_SHA256  /opt/tessdata/mrz.traineddata" | sha256sum -c -

COPY umbrales.yaml .
COPY mrzlab ./mrzlab
COPY plantillas ./plantillas

# Todos los modelos quedan dentro de la imagen: en ejecución no se descarga nada.
# Se cargan una vez en el build para comprobarlo.
# ONNX Runtime envía telemetría a Microsoft por defecto: se desactiva.
ENV TESSDATA_MRZ=/opt/tessdata ORT_DISABLE_TELEMETRY=1
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"

RUN useradd --create-home --uid 10001 lab && chown lab /app/plantillas
USER lab
EXPOSE 8080
CMD ["uvicorn", "mrzlab.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
