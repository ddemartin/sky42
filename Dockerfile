# sky42 in container, come brain42 e stock42 sulla stessa macchina.
#
# Dentro ci va solo Python: nessun servizio esterno, nessuna GPU da vedere.
FROM python:3.13-slim

# Il parallelismo lo decidiamo noi e non la libreria: senza queste, numpy si
# prende tutti i core per una singola operazione su array, e il Mac mini fa
# girare anche brain42 e stock42. Vanno lette al caricamento di numpy, quindi
# devono essere nell'ambiente prima che il processo parta.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    OMP_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ ./core/
COPY services/ ./services/
COPY gui/ ./gui/
COPY main.py cli.py ./

# `docs/schema.sql` **non è documentazione**: è lo schema che `core/db.py` legge
# all'avvio per creare il database. Se non entra nell'immagine, il primo avvio
# su un volume vuoto fallisce con un file non trovato.
COPY docs/schema.sql ./docs/schema.sql

# La configurazione degli osservatori è versionata in git e sta nell'immagine:
# si cambia con un commit e un rebuild, non modificando un file dentro il
# container che al prossimo build tornerebbe indietro.
COPY config/ ./config/

RUN useradd --create-home --uid 1000 sky42 \
 && mkdir -p /app/data \
 && chown -R sky42:sky42 /app
USER sky42

ENV SKY42_DATA_DIR=/app/data \
    SKY42_HOST=0.0.0.0 \
    SKY42_PORT=8000

EXPOSE 8000

# `degraded` (dati vecchi) non è `unhealthy`: il servizio risponde, e riavviare
# il container non farebbe comparire un catalogo aggiornato. Si riavvia solo se
# non risponde affatto.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,httpx; r=httpx.get('http://127.0.0.1:8000/health',timeout=4).json(); sys.exit(0 if r['status'] in ('ok','degraded') else 1)"

CMD ["python", "main.py"]
