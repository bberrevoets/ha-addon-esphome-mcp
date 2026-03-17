ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install build dependencies for ESPHome native compilation
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    platformio-core \
    git

# Install Python dependencies and ESPHome
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && pip3 install --no-cache-dir esphome \
    && rm /tmp/requirements.txt

# Copy server code
COPY server/ /opt/server/
COPY run.sh /opt/

RUN chmod a+x /opt/run.sh

CMD ["/opt/run.sh"]
