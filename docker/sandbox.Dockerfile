FROM python:3.12-slim

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        jq \
        nodejs \
        npm \
        poppler-utils \
        unzip \
        zip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        beautifulsoup4==4.14.3 \
        lxml==6.0.2 \
        openpyxl==3.1.5 \
        pandas==3.0.1 \
        pillow==12.1.1 \
        pypdf==6.6.2 \
        pytest==9.1.1 \
        python-docx==1.2.0 \
        python-pptx==1.0.2 \
        reportlab==4.4.10 \
        ruff==0.15.20

RUN useradd --create-home --uid 10001 student
USER student
WORKDIR /workspace

CMD ["python", "--version"]
