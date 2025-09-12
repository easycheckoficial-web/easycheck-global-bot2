FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Tesseract (OCR) + git para dar push
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código do projeto
COPY . .

# garantir permissão de execução do script
RUN chmod +x /app/run.sh

# Browsers (chromium)
RUN python -m playwright install chromium

# debug ligado nos primeiros runs (podes mudar no Render)
ENV DEBUG_HTML=1

CMD ["bash", "/app/run.sh"]
