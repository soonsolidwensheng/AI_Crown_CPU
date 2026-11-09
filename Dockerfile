ARG FUNCTION_DIR="/function"
ARG WORK_DIR="/crown"

FROM ubuntu:22.04

ARG FUNCTION_DIR
ARG WORK_DIR
ARG TARGETARCH

RUN test "${TARGETARCH}" = "amd64" && \
    mkdir -p "${FUNCTION_DIR}${WORK_DIR}"

COPY crown/ "${FUNCTION_DIR}${WORK_DIR}/"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.10 \
        python3-pip \
        ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN python3.10 -m pip install --no-cache-dir \
    --target "${FUNCTION_DIR}${WORK_DIR}" \
    awslambdaric==3.1.1 \
    requests==2.32.3 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR "${FUNCTION_DIR}${WORK_DIR}"
ENV PYTHONPATH="${FUNCTION_DIR}${WORK_DIR}"
ENV LD_LIBRARY_PATH="${FUNCTION_DIR}${WORK_DIR}/libs"

RUN set -eux; \
    test -f "${FUNCTION_DIR}${WORK_DIR}/crown.cpython-310-x86_64-linux-gnu.so"; \
    test -f "${FUNCTION_DIR}${WORK_DIR}/libs/libcrownJsonProcessor.so.0"; \
    if find "${FUNCTION_DIR}${WORK_DIR}" -maxdepth 1 \
        -name 'crown.cpython-311-*.so' -print -quit | grep -q .; then exit 1; fi; \
    ! ldd "${FUNCTION_DIR}${WORK_DIR}/crown.cpython-310-x86_64-linux-gnu.so" | grep -q 'not found'; \
    python3.10 -c "import crown; import index"

ENTRYPOINT ["python3.10", "-m", "awslambdaric"]
CMD ["index.handler"]
