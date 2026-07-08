FROM python:3.12-slim

# Browser Playwright scaricato una sola volta a build time (stessa versione per il
# binding Python e per @playwright/test) cosi' i container a runtime, senza rete,
# lo trovano gia' pronto in questo path condiviso.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        fonts-liberation \
        git \
        jq \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        nodejs \
        npm \
        poppler-utils \
        shared-mime-info \
        unzip \
        zip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        beautifulsoup4==4.14.3 \
        lxml==6.0.2 \
        openpyxl==3.1.5 \
        pandas==3.0.1 \
        pillow==12.1.1 \
        playwright==1.61.0 \
        pypdf==6.6.2 \
        pytest==9.1.1 \
        python-docx==1.2.0 \
        python-pptx==1.0.2 \
        reportlab==4.4.10 \
        ruff==0.15.20 \
        weasyprint==69.0 \
    && playwright install --with-deps chromium \
    && chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH" \
    && mkdir -p /opt/npm-cache /opt/npm-template \
    && npm install --cache=/opt/npm-cache --prefix /opt/npm-template @playwright/test@1.61.0 \
    && chmod -R a+rwX /opt/npm-cache /opt/npm-template \
    && printf 'cache=/opt/npm-cache\noffline=true\n' > /etc/npmrc

# npm gira sempre offline dalla cache seminata sopra: un pacchetto non precaricato
# fallisce subito con un errore chiaro, invece dell'attesa DNS che si vedeva prima.
RUN useradd --create-home --uid 10001 student
USER student
WORKDIR /workspace

CMD ["python", "--version"]
