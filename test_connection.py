#!/usr/bin/env python3
"""Script para testar a conexão com MongoDB Atlas"""

from pymongo import MongoClient
from urllib.parse import quote_plus
import certifi

# Configuração do MongoDB (mesma do app.py)
MONGO_PASSWORD = 'TecBin24'
ENCODED_PASSWORD = quote_plus(MONGO_PASSWORD)
MONGODB_URI = f'mongodb+srv://tecbin_db_vendas:{ENCODED_PASSWORD}@cluster0.blwq4du.mongodb.net/?appName=Cluster0'

print("🔍 Tentando conectar ao MongoDB Atlas...")
print(f"URI: mongodb+srv://tecbin_db_vendas:***@cluster0.blwq4du.mongodb.net/")
print(f"Certificados SSL: {certifi.where()}")

try:
    # Cria o cliente com configuração SSL
    client = MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=10000,  # 10 segundos para teste
        tlsCAFile=certifi.where(),
        retryWrites=True,
        w='majority'
    )

    # Testa a conexão com ping
    print("\n📡 Enviando ping para o servidor...")
    client.admin.command('ping')

    print("\n✅ CONEXÃO BEM-SUCEDIDA!")

    # Mostra informações do banco
    db = client['bingo_vendas_db']
    collections = db.list_collection_names()
    print(f"\n📊 Banco de dados: bingo_vendas_db")
    print(f"📁 Coleções encontradas: {len(collections)}")
    if collections:
        print(f"   - {', '.join(collections[:5])}")
        if len(collections) > 5:
            print(f"   - ... e mais {len(collections) - 5} coleções")

    client.close()
    print("\n🔒 Conexão fechada com sucesso.")

except Exception as e:
    print(f"\n❌ ERRO NA CONEXÃO: {e}")
    print("\nDetalhes do erro:")
    import traceback
    traceback.print_exc()
