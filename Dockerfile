ARG UBUNTU_MIRROR=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

FROM ubuntu:22.04

ARG UBUNTU_MIRROR
ARG PIP_INDEX_URL

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

RUN set -eux; \
    sed -i \
        -e "s|archive.ubuntu.com|${UBUNTU_MIRROR}|g" \
        -e "s|security.ubuntu.com|${UBUNTU_MIRROR}|g" \
        /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        python3.10 \
        python3-pip \
        tzdata; \
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime; \
    echo "${TZ}" > /etc/timezone; \
    dpkg-reconfigure --frontend noninteractive tzdata; \
    rm -rf /var/lib/apt/lists/*

RUN python3.10 -m pip install \
        --no-cache-dir \
        --index-url "${PIP_INDEX_URL}" \
        requests==2.32.3

WORKDIR /function/crown

COPY crown/ /function/crown/

ENV PYTHONPATH=/function/crown
ENV LD_LIBRARY_PATH=/function/crown/libs
ENV PYTHONUNBUFFERED=1

RUN set -eux; \
    test -f /function/crown/index_fc.py; \
    test -n "$(find /function/crown -maxdepth 1 -name 'crown.cpython-310-*.so' -print -quit)"; \
    ! ldd /function/crown/crown.cpython-310-*.so | grep -q 'not found'; \
    python3.10 -c "import crown; import index_fc"

EXPOSE 9000

CMD ["python3.10", "/function/crown/index_fc.py"]
