ARG BUILD_FROM
FROM ${BUILD_FROM}

# Base image (ghcr.io/esphome/esphome) is Debian/glibc and already provides
# esphome + PlatformIO with working ESP toolchains. We only add the MCP
# server's Python dependencies on top.
#
# The base-image tag pinned in build.yaml is the ESPHome version this add-on
# compiles with. It must be bumped together with the add-on version.
#
# The base image sets UV_SYSTEM_PYTHON=true and installs esphome into the
# system interpreter, so the MCP deps must land there too (hence
# --break-system-packages) — server.main imports esphome/aioesphomeapi.
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy server code
COPY server/ /opt/server/
COPY run.sh /opt/

RUN chmod a+x /opt/run.sh

WORKDIR /opt

# The official esphome image ships an ENTRYPOINT and a HEALTHCHECK that probe
# the ESPHome dashboard (port 6052). We run the MCP server instead, so clear
# the entrypoint and REPLACE the healthcheck with one against our own
# /health route. Do not use `HEALTHCHECK NONE`: that leaves a
# `Test: ["NONE"]` entry in the image metadata, and the HA Supervisor then
# waits forever for a "healthy" event — the add-on stays in "Starting".
ENTRYPOINT []
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf "http://127.0.0.1:${MCP_PORT:-8099}/health" || exit 1
CMD ["/opt/run.sh"]
