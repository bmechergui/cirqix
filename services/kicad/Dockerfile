# ============================================================
# Layrix KiCad Service — Docker headless
# Base : KiCad 8.0 + Python 3.11 + FastAPI + Freerouting
# Port : 8766 (matches KICAD_SERVICE_URL in .env.local)
# ============================================================

FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive

# KiCad PPA signing key fingerprint
ENV KICAD_PPA_KEY=FDA854F61C4D0D9572BB95E5245D5502FAD7A805

RUN apt-get update && apt-get install -y --no-install-recommends \
        gnupg \
        curl \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/* \
    && echo "deb https://ppa.launchpadcontent.net/kicad/kicad-8.0-releases/ubuntu jammy main" \
        > /etc/apt/sources.list.d/kicad-kicad-8_0-releases.list \
    && mkdir -p /root/.gnupg && chmod 700 /root/.gnupg \
    && for i in 1 2 3; do \
           curl -fsSL \
               "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${KICAD_PPA_KEY}" \
           | gpg --dearmor \
           | tee /etc/apt/trusted.gpg.d/kicad.gpg > /dev/null \
           && break || sleep 10; \
       done \
    && chmod 644 /etc/apt/trusted.gpg.d/kicad.gpg \
    && apt-get update \
    && for i in 1 2 3; do \
           apt-get install -y --no-install-recommends --fix-missing \
               kicad \
               kicad-symbols \
               kicad-footprints \
               python3-pip \
               python3-dev \
               xvfb \
               openjdk-21-jre-headless \
               zip \
               unzip \
           && break || sleep 30; \
       done \
    && rm -rf /var/lib/apt/lists/*

ENV KICAD_SYMBOL_DIR=/usr/share/kicad/symbols
ENV KICAD_FOOTPRINT_DIR=/usr/share/kicad/footprints
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# /app/circuit_synth/src — real circuit_synth package (src layout)
# NOTE: do NOT add /usr/lib/python3/dist-packages here — it would put numpy 1.21.5 before
# pip-installed numpy 2.x, breaking kicad-tools type annotations. pcbnew is found via default sys.path.
ENV PYTHONPATH=/app/circuit_synth/src:${PYTHONPATH}

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt


# Freerouting JAR v2.1.0 — started as REST API server at port 37864
RUN mkdir -p /opt/freerouting && \
    for i in 1 2 3; do \
        curl -fL https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar \
            -o /opt/freerouting/freerouting.jar && break || sleep 15; \
    done

ENV FREEROUTING_API_URL=http://127.0.0.1:37864

COPY . .

# Install circuit_synth from local source (services/kicad/circuit_synth/)
RUN pip3 install --no-cache-dir ./circuit_synth

# Install kicad-tools from local source (services/kicad/kicad_tools/)
# Move source out of /app/ first — avoids Python namespace-package shadowing (/app in sys.path would
# shadow the installed package if the source directory remains at /app/kicad_tools/)
# extras: placement=CMA-ES, drc=rtree spatial index, geometry=shapely
RUN mv /app/kicad_tools /tmp/kicad_tools && \
    pip3 install --no-cache-dir "/tmp/kicad_tools[placement,drc,geometry]"

RUN mkdir -p /tmp/kicad-jobs

EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8766/health || exit 1

# Start Xvfb + Freerouting API server (persistent JVM, 1 instance for all users)
# then uvicorn on port 8766
CMD ["sh", "-c", "Xvfb :99 -screen 0 1024x768x24 -ac & \
     java -jar /opt/freerouting/freerouting.jar \
         --api_server.enabled=true \
         --api_server-endpoints=http://127.0.0.1:37864 & \
     sleep 5 && \
     uvicorn main:app --host 0.0.0.0 --port 8766 --workers 4"]
