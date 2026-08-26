ARG BUILD_FROM
FROM ${BUILD_FROM}

# Base image (ghcr.io/esphome/esphome) is Debian/glibc and already provides
# esphome + PlatformIO with working ESP toolchains. We only add the MCP
# server's Python dependencies on top.
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy server code
COPY server/ /opt/server/
COPY run.sh /opt/

RUN chmod a+x /opt/run.sh

WORKDIR /opt

# The official esphome image ships an ENTRYPOINT and a HEALTHCHECK that probe
# the ESPHome dashboard. We run the MCP server instead, so clear both —
# otherwise the failing dashboard healthcheck makes Supervisor restart the
# add-on on a ~60s loop.
ENTRYPOINT []
HEALTHCHECK NONE
CMD ["/opt/run.sh"]
