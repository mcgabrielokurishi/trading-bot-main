

FROM python:3.11-slim AS builder

WORKDIR /build


RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    curl \
    git \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*


RUN wget -q https://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr && \
    make -j$(nproc) && \
    make install && \
    cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim

WORKDIR /app


COPY --from=builder /usr/lib/libta_lib* /usr/lib/
COPY --from=builder /usr/include/ta-lib /usr/include/ta-lib


COPY --from=builder /root/.local /root/.local

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Make Python use local packages
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Create log and data directories
RUN mkdir -p /app/logs /app/data

# Copy application source
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import config; print('OK')" || exit 1

# Default command: start the trading loop
CMD ["python", "main.py", "trade"]
