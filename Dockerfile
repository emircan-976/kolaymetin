# kolaymetin — Türkçe Kolay Dil denetim aracı
# Tek komutla kurulum: docker compose up
# Kapsayıcı çalışırken hiçbir dış servise bağlanmaz. Ağ yalnızca kurulum (build) sırasında
# Python paketlerini indirmek için gerekir.

FROM python:3.12-slim AS derleme
WORKDIR /kaynak
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY docs/rehber ./docs/rehber
RUN pip wheel --wheel-dir /tekerlek .

FROM python:3.12-slim
LABEL org.opencontainers.image.title="kolaymetin" \
      org.opencontainers.image.description="Türkçe Kolay Dil / Sade Dil denetim aracı" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="1.0.0"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONIOENCODING=utf-8
COPY --from=derleme /tekerlek /tekerlek
RUN pip install --no-index --find-links=/tekerlek kolaymetin && rm -rf /tekerlek \
    && useradd --create-home --uid 10001 kolaymetin
USER kolaymetin
WORKDIR /home/kolaymetin
# zeyrek sözlüğünü kurulumda bir kez yükleyerek bozuk kurulumu erken yakala
RUN python -c "from kolaymetin import analyze; print(analyze('Su gelecek.').morphology)"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/saglik', timeout=4).status == 200 else 1)"
CMD ["kolaymetin", "sunucu", "--host", "0.0.0.0", "--port", "8000"]
