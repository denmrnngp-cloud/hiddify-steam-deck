ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

ARG BUILD_ARCH=amd64
ARG SINGBOX_VERSION=1.13.3

# Install runtime dependencies
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    python3 \
    py3-requests \
    iproute2 \
    ca-certificates \
    iptables \
    ip6tables \
    tzdata \
    gcompat \
    libc6-compat

# Download sing-box binary
RUN case "${BUILD_ARCH}" in \
      amd64)   ARCH="amd64" ;; \
      aarch64) ARCH="arm64" ;; \
      *) echo "Unsupported arch: ${BUILD_ARCH}" && exit 1 ;; \
    esac && \
    curl -fsSL \
      "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-${ARCH}.tar.gz" \
      -o /tmp/singbox.tar.gz && \
    tar -xzf /tmp/singbox.tar.gz -C /tmp/ && \
    mv /tmp/sing-box-${SINGBOX_VERSION}-linux-${ARCH}/sing-box /usr/local/bin/sing-box && \
    chmod +x /usr/local/bin/sing-box && \
    rm -rf /tmp/singbox*

# Data directory for configs and state
RUN mkdir -p /data/hiddify /var/lib/hiddify

COPY run.sh /run.sh
COPY parse_sub.py /parse_sub.py
COPY grpc_ctl.py /grpc_ctl.py

RUN chmod +x /run.sh

CMD ["/run.sh"]
