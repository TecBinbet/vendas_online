# Makefile para facilitar comandos comuns

.PHONY: help dev prod-test prod-docker clean install

# Comando padrão: mostrar ajuda
help:
	@echo "📋 Comandos disponíveis:"
	@echo ""
	@echo "  make install      - Instalar dependências"
	@echo "  make dev          - Rodar em modo desenvolvimento (porta 5001)"
	@echo "  make prod-test    - Testar produção com Gunicorn (porta 8080)"
	@echo "  make prod-docker  - Testar produção com Docker (porta 8080)"
	@echo "  make clean        - Limpar arquivos temporários"
	@echo ""

# Instalar dependências
install:
	@echo "📦 Instalando dependências..."
	pip install -r requirements.txt
	@echo "✅ Dependências instaladas!"

# Rodar em modo desenvolvimento
dev:
	@echo "🔧 Iniciando em modo DESENVOLVIMENTO..."
	@echo "   Acesse: http://localhost:5001"
	@echo ""
	python app.py

# Testar produção com Gunicorn
prod-test:
	@echo "🐍 Testando PRODUÇÃO com Gunicorn..."
	@echo "   Acesse: http://localhost:8080"
	@echo ""
	FLASK_ENV=production gunicorn --bind 0.0.0.0:8080 --workers 4 --timeout 120 --reload app:app

# Testar produção com Docker
prod-docker:
	@echo "🐳 Testando PRODUÇÃO com Docker..."
	@echo ""
	@echo "1️⃣  Construindo imagem..."
	docker build -t vendas-online-test .
	@echo ""
	@echo "2️⃣  Iniciando container..."
	@echo "   Acesse: http://localhost:8080"
	@echo ""
	docker run -p 8080:8080 --env FLASK_ENV=production vendas-online-test

# Limpar arquivos temporários
clean:
	@echo "🧹 Limpando arquivos temporários..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Limpeza concluída!"
