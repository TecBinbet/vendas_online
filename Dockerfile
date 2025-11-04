# Dockerfile para deploy na DigitalOcean
FROM python:3.11-slim

# Defir diretório de trabalho
WORKDIR /app

# Copiar arquivos de dependências
COPY requirements.txt .

# Instalar dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY . .

# Expor a porta 8080 (porta padrão esperada pela DigitalOcean)
EXPOSE 8080

# Comando para rodar a aplicação com Gunicorn
# - 4 workers para melhor performance
# - Timeout de 120 segundos (importante para operações de DB)
# - Bind na porta 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--timeout", "120", "app:app"]
