# 🧪 Guia de Teste em Produção (Local)

Este guia mostra como testar a aplicação em modo produção **antes** de fazer deploy na DigitalOcean.

## 🎯 Por que testar localmente?

- ✅ Verificar se o Gunicorn funciona corretamente
- ✅ Testar na porta 8080 (mesma porta da DigitalOcean)
- ✅ Confirmar que o Docker build funciona
- ✅ Evitar erros em produção

---

## 🚀 Opção 1: Testar com Docker (RECOMENDADO)

Esta opção simula **exatamente** o ambiente da DigitalOcean.

```bash
# Usar o script helper
./test-prod.sh docker

# OU manualmente:

# 1. Construir a imagem
docker build -t vendas-online-test .

# 2. Rodar o container
docker run -p 8080:8080 --env FLASK_ENV=production vendas-online-test

# 3. Acessar
# Abra: http://localhost:8080
```

### Parar o container:
```bash
# Listar containers rodando
docker ps

# Parar container
docker stop <CONTAINER_ID>

# Limpar (opcional)
docker rm <CONTAINER_ID>
docker rmi vendas-online-test
```

---

## 🐍 Opção 2: Testar apenas com Gunicorn (Mais Rápido)

Esta opção testa apenas o Gunicorn, sem Docker.

```bash
# Usar o script helper
./test-prod.sh

# OU manualmente:

# 1. Instalar Gunicorn (se necessário)
pip install gunicorn

# 2. Rodar com Gunicorn na porta 8080
FLASK_ENV=production gunicorn --bind 0.0.0.0:8080 --workers 4 --timeout 120 app:app

# 3. Acessar
# Abra: http://localhost:8080
```

### Parar o servidor:
```
Ctrl+C no terminal
```

---

## 📋 Checklist de Testes

Após iniciar o servidor, teste:

- [ ] Acessar http://localhost:8080 (deve carregar a página de login)
- [ ] Fazer login como colaborador
- [ ] Fazer login como cliente
- [ ] Verificar se não há mensagens de erro no terminal
- [ ] Confirmar que está usando Gunicorn (não Flask debug server)
- [ ] Verificar logs - NÃO deve aparecer "WARNING: This is a development server"

---

## ✅ Como saber se está em modo produção?

### ❌ Modo Desenvolvimento (ERRADO para produção):
```
* Serving Flask app 'app'
* Debug mode: on
WARNING: This is a development server.
* Running on http://0.0.0.0:5001
```

### ✅ Modo Produção (CORRETO):
```
✅ CLIENTE GLOBAL MONGODB CRIADO COM SUCESSO.
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:8080
[INFO] Using worker: sync
[INFO] Booting worker with pid: 123
```

---

## 🔍 Troubleshooting

### Erro: "Address already in use"
```bash
# Verificar o que está usando a porta 8080
lsof -i :8080

# Matar o processo
kill -9 <PID>
```

### Erro: "Cannot connect to MongoDB"
- Verifique sua conexão com internet
- Confirme que o MongoDB Atlas está acessível
- Verifique as credenciais no app.py

### Docker não está instalado
```bash
# macOS
brew install docker

# Ou baixe: https://www.docker.com/products/docker-desktop
```

---

## 🎓 Comandos Úteis

```bash
# Ver logs do Docker em tempo real
docker logs -f <CONTAINER_ID>

# Entrar no container (debug)
docker exec -it <CONTAINER_ID> /bin/bash

# Ver processos do Gunicorn
ps aux | grep gunicorn

# Testar health check (como a DigitalOcean faz)
curl -I http://localhost:8080/
```

---

## 📦 Depois de testar com sucesso

```bash
# 1. Commit as mudanças
git add .
git commit -m "Add production configuration for DigitalOcean"
git push

# 2. Deploy na DigitalOcean
# O deploy agora deve funcionar!
```

---

## 🆘 Problemas?

Se algo não funcionar:
1. Verifique os logs no terminal
2. Confirme que todas as dependências estão instaladas
3. Teste primeiro com a Opção 2 (Gunicorn), depois Opção 1 (Docker)
4. Compare os logs locais com os logs da DigitalOcean
