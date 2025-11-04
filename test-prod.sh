#!/bin/bash
# Script para testar a aplicação em modo produção localmente

echo "🧪 Testando aplicação em modo PRODUÇÃO..."
echo ""

# Opção 1: Testar com Docker (simula exatamente o ambiente de produção)
if [ "$1" = "docker" ]; then
    echo "📦 Usando Docker (simula DigitalOcean exatamente)"
    echo ""
    echo "1️⃣  Construindo imagem Docker..."
    docker build -t vendas-online-test .

    echo ""
    echo "2️⃣  Rodando container na porta 8080..."
    docker run -p 8080:8080 --env FLASK_ENV=production vendas-online-test

# Opção 2: Testar apenas com Gunicorn (sem Docker)
else
    echo "🐍 Usando Gunicorn diretamente"
    echo ""
    echo "Instalando/verificando Gunicorn..."
    pip install gunicorn

    echo ""
    echo "🚀 Iniciando servidor na porta 8080..."
    echo "   Acesse: http://localhost:8080"
    echo ""
    FLASK_ENV=production gunicorn --bind 0.0.0.0:8080 --workers 4 --timeout 120 --reload app:app
fi
