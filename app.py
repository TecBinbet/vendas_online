# app.py (Versão Refatorada para Conexão Dinâmica por Sala)

import time
import threading
import pymongo
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, make_response, Response
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson.objectid import ObjectId
from bson.decimal128 import Decimal128
from datetime import datetime, timedelta
from urllib.parse import quote_plus
import os
import re # Para a busca de clientes e limpeza de nome
import bcrypt
import io # Para manipulação de arquivos em memória
from functools import wraps # Para o decorator login_required
import certifi  # Para certificados SSL
import html 
import unicodedata # Para limpeza de nome de arquivo

# --- VARIÁVEL GLOBAL PARA O CAMINHO DA PASTA ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARTELAS_FOLDER = os.path.join(BASE_DIR, 'cartelas') 
DEFAULT_SALA_ID = "000"
JaLogado = 0


# --- FIM DA VARIÁVEL GLOBAL ---

class PDF(FPDF):
    def __init__(self, evento_nome='N/A', colaborador_nome='N/A'):
        super().__init__(orientation='L', unit='mm', format='A4') # 'L' = Paisagem
        # Remove acentos para o FPDF (que usa 'latin-1')
        def clean_text_for_pdf(text):
            if not text: return "N/A"
            text = str(text)
            text = re.sub(r'[áàâãä]', 'a', text, flags=re.IGNORECASE)
            text = re.sub(r'[éèêë]', 'e', text, flags=re.IGNORECASE)
            text = re.sub(r'[íìîï]', 'i', text, flags=re.IGNORECASE)
            text = re.sub(r'[óòôõö]', 'o', text, flags=re.IGNORECASE)
            text = re.sub(r'[úùûü]', 'u', text, flags=re.IGNORECASE)
            text = re.sub(r'[ç]', 'c', text, flags=re.IGNORECASE)
            # Remove caracteres não-latin1
            return text.encode('latin-1', 'ignore').decode('latin-1')

        self.evento_nome = clean_text_for_pdf(evento_nome)
        self.colaborador_nome = clean_text_for_pdf(colaborador_nome)

    def header(self):
        self.set_font('Helvetica', 'B', 15) 
        self.cell(0, 10, f'Relatorio de Vendas - {self.evento_nome}', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C') 
        self.set_font('Helvetica', '', 10) 
        self.cell(0, 5, f"Colaborador: {self.colaborador_nome}", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C') 
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8) 
        self.cell(0, 10, 'Pagina ' + str(self.page_no()) + '/{nb}', border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C') 
# --- FIM DA CLASSE PDF ---

class PDFCartelas(FPDF):
    """Classe FPDF customizada para gerar cartelas de Bingo."""
    
    def header(self):
        # Verifica se foram passados dados personalizados, senão usa padrão
        titulo = getattr(self, 'nome_sala', 'Cartelas de Bingo')
        subtitulo = getattr(self, 'infos_evento', '')

        self.set_font('Helvetica', 'B', 14) 
        # Imprime Nome da Sala
        self.cell(0, 6, titulo, border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C') 
        
        # Imprime Detalhes do Evento (se houver)
        if subtitulo:
            self.set_font('Helvetica', 'B', 10)
            self.cell(0, 5, subtitulo, border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C') 
        
        self.ln(2) # Pequeno espaço após o cabeçalho

    def footer(self):
        self.set_y(-10) # Rodapé mais curto para caber 5 linhas de cartela
        self.set_font('Helvetica', 'I', 8) 
        self.cell(0, 10, 'Pagina ' + str(self.page_no()) + '/{nb}', border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C') 
        
    def desenhar_cartela(self, numero_cartela, dados_cartela_2d, pos_x, pos_y):
        """
        Desenha uma cartela de 25 números (5x5) na posição (x, y).
        Layout ajustado para caber 6 por página.
        """
        # --- Título da Cartela ---
        self.set_xy(pos_x, pos_y)
        self.set_font('Helvetica', 'B', 10) 
        largura_total_cartela = 70 
        # Altura do título
        self.cell(largura_total_cartela, 6, f"Cartela N {numero_cartela:04d}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C') 
        
        # --- Cabeçalho B-I-N-G-O ---
        self.set_x(pos_x) 
        self.set_font('Helvetica', 'B', 14) 
        self.set_fill_color(230, 230, 230) 
        
        cell_width = 14 
        cell_height_header = 8 
        
        cabecalho = ["B", "I", "N", "G", "O"]
        for letra in cabecalho:
             new_x = XPos.LMARGIN if letra == "O" else XPos.RIGHT
             new_y = YPos.NEXT if letra == "O" else YPos.TOP
             self.cell(cell_width, cell_height_header, letra, border=1, new_x=new_x, new_y=new_y, align='C', fill=True)
        
        # --- Números da Cartela (5 Linhas) ---
        self.set_font('Helvetica', 'B', 12) 
        cell_height_num = 10 
        
        for i in range(5): 
            self.set_x(pos_x) 
            for j in range(5): 
                numero = str(dados_cartela_2d[i][j])
                
                # Destaque para o FREE (se houver)
                if numero.upper() == "FREE":
                    self.set_font('Helvetica', 'B', 10) # Fonte menor para caber
                else:
                    self.set_font('Helvetica', 'B', 12)

                self.cell(cell_width, cell_height_num, numero, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C') 
            
            self.ln(cell_height_num)

    def desenhar_cartela_15(self, numero_cartela, dados_cartela_2d, pos_x, pos_y):
        """
        Desenha uma cartela de 15 números (3x5) na posição (x, y).
        Otimizada para economizar espaço vertical.
        """
        # --- Título da Cartela ---
        self.set_xy(pos_x, pos_y)
        self.set_font('Helvetica', 'B', 9) # Fonte levemente menor
        largura_total_cartela = 70 
        # Altura reduzida do título da cartela para 5mm
        self.cell(largura_total_cartela, 5, f"Cartela N {numero_cartela:04d}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C') 
        
        # --- Cabeçalho B-I-N-G-O ---
        self.set_x(pos_x) 
        self.set_font('Helvetica', 'B', 12) 
        self.set_fill_color(230, 230, 230) 
        
        cell_width = 14 
        cell_height_header = 6 # Altura reduzida do cabeçalho BINGO
        
        cabecalho = ["B", "I", "N", "G", "O"]
        for letra in cabecalho:
             new_x = XPos.LMARGIN if letra == "O" else XPos.RIGHT
             new_y = YPos.NEXT if letra == "O" else YPos.TOP
             self.cell(cell_width, cell_height_header, letra, border=1, new_x=new_x, new_y=new_y, align='C', fill=True)
        
        # --- Números da Cartela (3 Linhas) ---
        self.set_font('Helvetica', 'B', 11) 
        cell_height_num = 9 # Altura reduzida das células de número
        
        for i in range(3): 
            self.set_x(pos_x) 
            for j in range(5): 
                numero = str(dados_cartela_2d[i][j])
                self.cell(cell_width, cell_height_num, numero, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C') 
            
            self.ln(cell_height_num) 


# --- FIM DA CLASSE PDFCartelas ---

# --- CONFIGURAÇÃO E CONEXÃO MONGODB (DINÂMICA) ---
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui' 
app.permanent_session_lifetime = timedelta(minutes=60) 

# --- NOVO FILTRO DE MOEDA ---
@app.template_filter('format_moeda')
def format_moeda(value):
    try:
        if value is None or value == "":
            return "0,00"
            
        # Converte Decimal128 ou string para float se necessário
        if hasattr(value, 'to_decimal'):
            value = float(value.to_decimal())
        elif isinstance(value, str):
             # Tenta limpar string se vier suja
             value = float(value.replace('R$', '').replace('.', '').replace(',', '.'))
        
        # Formata: 
        # {:,.2f} -> 1,200.50
        # replace -> 1.200,50
        return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "0,00"

# Helper genérico de float para Decimal128 caso não exista no seu scope:
def safe_dec(value):
    try:
        val = str(value).replace(',', '.')
        return Decimal128(str(float(val)))
    except:
        return Decimal128("0.00")

def safe_get_float(val):
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    try:
        return float(val)
    except:
        return 0.0

def safe_get_int(val):
    if isinstance(val, Decimal128):
        return int(val.to_decimal())
    try:
        return int(float(val))
    except:
        return 0

def hora_brasil():
# 1. Pega a hora exata no fuso de SP
    agora_sp = datetime.now(ZoneInfo('America/Sao_Paulo'))
    
    # 2. Remove a 'etiqueta' de fuso horário (.replace(tzinfo=None))
    # Assim o banco salva exatamente o que vê, sem tentar converter.
    return agora_sp.replace(tzinfo=None)

# --- MOTOR MATEMÁTICO CENTRAL (PRÊMIOS DINÂMICOS) ---
def calcular_premios_dinamicos(db, evento, param_doc):
    """
    MOTOR MATEMÁTICO (ATUALIZADO): 
    Calcula, reajusta as premiações e GRAVA NO BANCO se houver aumento.
    """
    # 1. Verifica se o evento está elegível para cálculo dinâmico
    if str(evento.get('tipo_premiacao', '')).lower() != 'porcentagem':
        return evento

    porcento_premios = safe_float(param_doc.get('porcento_premios', 0))
    if porcento_premios <= 0:
        return evento

    # 2. Resgata e calcula as vendas (Garante que qtd_vendas exista no dict)
    qtd_vendas = evento.get('qtd_vendas', 0)
    
    # Se a qtd não foi passada no dicionário, calcula aqui para segurança
    id_evento_int = evento.get('id_evento')
    nome_cv = f"vendas{id_evento_int}"
    if qtd_vendas == 0 and nome_cv in db.list_collection_names():
        vendas_data_list = list(db[nome_cv].aggregate([
            {'$group': {'_id': None, 'total_unidades': {'$sum': '$quantidade_unidades'}}}
        ]))
        if vendas_data_list:
            qtd_vendas = vendas_data_list[0].get('total_unidades', 0)
            evento['qtd_vendas'] = qtd_vendas

    valor_venda = safe_float(evento.get('valor_de_venda', 0))
    total_arrecadado = qtd_vendas * valor_venda

    if total_arrecadado <= 0:
        return evento

    # 3. Matemática de Comparação
    premio_potencial = total_arrecadado * (porcento_premios / 100.0)
    # Pega o valor atual do banco para saber se já foi engordado antes
    premio_atual_banco = safe_float(evento.get('premio_total', 0))

    # 4. Distribuição e GRAVAÇÃO (Apenas se o Potencial bater o Atual)
    # Usamos uma margem de 5 reais para evitar gravações em loop por falhas de float
    if (premio_potencial - premio_atual_banco) >= 5.0:   
        tipo_cartela = int(evento.get('tipo_de_cartela', 15))
        qtd_linhas = int(evento.get('quantidade_de_linhas', 1))
        
        # Detecção Automática de Regras
        tem_quadra = safe_float(evento.get('premio_quadra', 0)) > 0
        faltaum_val = safe_float(evento.get('premio_faltaum', 0))
        
        # Isola o valor do "Falta Um" da distribuição percentual
        premio_distribuir = premio_potencial - faltaum_val
        
        # Preparamos um dicionário apenas com os campos a atualizar no banco
        updates_db = {}

        if tipo_cartela == 15:
            if tem_quadra:
                regra = param_doc.get('porcento_15_quadra', {})
                evento['premio_quadra'] = premio_distribuir * (safe_float(regra.get('quadra', 0)) / 100.0)
                evento['premio_linha'] = (premio_distribuir * (safe_float(regra.get('linha', 0)) / 100.0)) / qtd_linhas if qtd_linhas > 0 else 0
                evento['premio_bingo'] = premio_distribuir * (safe_float(regra.get('bingo', 0)) / 100.0)
                evento['premio_segundobingo'] = premio_distribuir * (safe_float(regra.get('segundobingo', 0)) / 100.0)
            elif qtd_linhas == 3:
                regra = param_doc.get('porcento_15_3linhas', {})
                evento['premio_linha'] = (premio_distribuir * (safe_float(regra.get('linhas', 0)) / 100.0)) / qtd_linhas if qtd_linhas > 0 else 0
                evento['premio_bingo'] = premio_distribuir * (safe_float(regra.get('bingo', 0)) / 100.0)
                evento['premio_segundobingo'] = premio_distribuir * (safe_float(regra.get('segundobingo', 0)) / 100.0)
            else:
                regra = param_doc.get('porcento_15', {})
                evento['premio_linha'] = (premio_distribuir * (safe_float(regra.get('linha', 0)) / 100.0)) / qtd_linhas if qtd_linhas > 0 else 0
                evento['premio_bingo'] = premio_distribuir * (safe_float(regra.get('bingo', 0)) / 100.0)
                evento['premio_segundobingo'] = premio_distribuir * (safe_float(regra.get('segundobingo', 0)) / 100.0)
        
        elif tipo_cartela == 25:
            if tem_quadra: # 4 Cantos
                regra = param_doc.get('porcento_25_4cantos', {})
                evento['premio_quadra'] = premio_distribuir * (safe_float(regra.get('4cantos', 0)) / 100.0)
                evento['premio_linha'] = (premio_distribuir * (safe_float(regra.get('linha', 0)) / 100.0)) / qtd_linhas if qtd_linhas > 0 else 0
                evento['premio_bingo'] = premio_distribuir * (safe_float(regra.get('bingo', 0)) / 100.0)
            else:
                regra = param_doc.get('porcento_25', {})
                evento['premio_linha'] = (premio_distribuir * (safe_float(regra.get('linha', 0)) / 100.0)) / qtd_linhas if qtd_linhas > 0 else 0
                evento['premio_bingo'] = premio_distribuir * (safe_float(regra.get('bingo', 0)) / 100.0)

        # Atualiza o Total no objeto local e adiciona flag
        evento['premio_total'] = premio_potencial
        evento['is_premio_dinamico_ativo'] = True
        
        # Prepara a atualização para o MongoDB garantindo formato Decimal128
        for k in ['premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_total']:
            if k in evento:
                updates_db[k] = Decimal128(str(evento[k]))
        
        updates_db['is_premio_dinamico_ativo'] = True

        # GRAVAÇÃO REAL NO BANCO DE DADOS
        try:
             db.eventos.update_one({'id_evento': id_evento_int}, {'$set': updates_db})
             #print(f"[MOTOR] Evento {id_evento_int} atualizado no banco. Novo prêmio: R$ {premio_potencial:.2f}")
        except Exception as e:
             print(f"[MOTOR ERRO] Falha ao gravar reajuste no banco para evento {id_evento_int}: {e}")

    return evento


# --- LOCKS GLOBAIS PARA SINCRONIZAÇÃO DE SEQUÊNCIAS ---
venda_lock = threading.Lock()
cliente_lock = threading.Lock()
colaborador_lock = threading.Lock()
evento_lock = threading.Lock()

# --- CONFIGURAÇÃO DE MÚLTIPLOS BANCOS DE DADOS ---

# 1. Configuração do MongoDB FIXO (Controle Master)
DB_CONTROL_NAME = 'db_master_controle'
MONGO_PASSWORD = 'TecBin24' 
ENCODED_PASSWORD = quote_plus(MONGO_PASSWORD)

MONGODB_URI_CONTROL = os.environ.get('MONGODB_URI_CONTROL', 
    f'mongodb+srv://tecbin_db_vendas:{ENCODED_PASSWORD}@cluster0.blwq4du.mongodb.net/{DB_CONTROL_NAME}?appName=Cluster0')


client_control = None
db_control = None 

try:
    client_control = MongoClient(
        MONGODB_URI_CONTROL,
        serverSelectionTimeoutMS=5000, 
        tlsCAFile=certifi.where(),
        retryWrites=True,
        w='majority'
    )
    client_control.admin.command('ping') 
    print("✅ CLIENTE GLOBAL DE CONTROLE MONGODB CRIADO COM SUCESSO.")
    db_control = client_control[DB_CONTROL_NAME]
except Exception as e:
    print(f"🚨 ERRO IRRECUPERÁVEL AO CRIAR O CLIENTE DE CONTROLE: {e}")


# 2. Configuração Dinâmica para Salas de Vendas
DB_VENDAS_CLIENT_CACHE = {} 
db_vendas_client_cache_lock = threading.Lock()
DB_NAME_VENDAS = 'bingo_vendas_db' 

# --- FUNÇÃO DE CONEXÃO DINÂMICA (CRÍTICA) ---
def get_vendas_db():
    """
    Retorna o objeto do banco de dados de vendas com base no id_sala
    armazenado em g.id_sala. Gerencia o cache de clientes (clusters).
    """
    id_sala = getattr(g, 'id_sala', None)
    #print(f"[LOG] get_vendas_db: Tentando obter BD para g.id_sala = {id_sala}")
    if not id_sala:
        return None 
    
    if id_sala in DB_VENDAS_CLIENT_CACHE:
        #print(f"[LOG] get_vendas_db: CACHE HIT para sala: {id_sala}")
        client_vendas = DB_VENDAS_CLIENT_CACHE[id_sala]
        return client_vendas[DB_NAME_VENDAS]
    
    if db_control is None:
        #print("[LOG] get_vendas_db: ERRO - Banco de controle (master) não está conectado para buscar o URI.")
        return None
        
    with db_vendas_client_cache_lock:
        if id_sala in DB_VENDAS_CLIENT_CACHE:
            #print(f"[LOG] get_vendas_db: CACHE HIT (pós-lock) para sala: {id_sala}")
            client_vendas = DB_VENDAS_CLIENT_CACHE[id_sala]
            return client_vendas[DB_NAME_VENDAS]
            
        #print(f"[LOG] get_vendas_db: CACHE MISS. Buscando URI no 'db_control' para sala: {id_sala}")
        
        # --- CORREÇÃO (Baseada no seu feedback dos dados) ---
        sala_info = db_control.salas.find_one(
            {"id_sala": id_sala},
            {"url_parte1": 1, "url_parte2": 1}  # Projeção
        )
        
        if not sala_info or 'url_parte1' not in sala_info or 'url_parte2' not in sala_info:
            #print(f"[LOG] get_vendas_db: ERRO - 'url_parte1' ou 'url_parte2' da sala '{id_sala}' não encontrados no BD de controle.")
            return None
            
        uri_vendas = f"{sala_info['url_parte1']}{ENCODED_PASSWORD}{sala_info['url_parte2']}"
        
        print(f"[LOG] get_vendas_db: URI construída. Tentando nova conexão com cluster...")
        print(f"[LOG] URL: {uri_vendas}")
        # --- FIM DA CORREÇÃO ---
        
        try:
            client_vendas = MongoClient(
                uri_vendas,
                serverSelectionTimeoutMS=5000, 
                tlsCAFile=certifi.where(),
                retryWrites=True,
                w='majority'
            )
            client_vendas.admin.command('ping') 
            
            DB_VENDAS_CLIENT_CACHE[id_sala] = client_vendas
            #print(f"✅ [LOG] get_vendas_db: Nova conexão para sala '{id_sala}' estabelecida e cacheada.")
            
            return client_vendas[DB_NAME_VENDAS]
            
        except Exception as e:
            #print(f"🚨 [LOG] get_vendas_db: ERRO ao conectar ao cluster da sala '{id_sala}'. Verifique a URI e a password. Erro: {e}")
            return None


# --- DECORATOR DE AUTENTICAÇÃO ---
def login_required(f):
    """Decorator para exigir login em uma rota."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # Preservar id_sala no redirect de falha de login
            id_sala_atual = session.get('id_sala') or request.args.get('id_sala')
            redirect_args = {'error': "Acesso restrito. Faça o login."}
            if id_sala_atual:
                redirect_args['id_sala'] = id_sala_atual
            return redirect(url_for('login_page', **redirect_args))
        return f(*args, **kwargs)
    return decorated_function

# --- FUNÇÕES AUXILIARES GLOBAIS (DB/UTILS) ---

def clean_for_filename(text):
    """
    Remove acentos, espaços e caracteres especiais de uma string
    e a retorna em minúsculas para uso em nomes de arquivo.
    """
    if not text:
        return ""
    
    normalized = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode('utf-8')
    cleaned = re.sub(r'[^\w\s-]', '', normalized).strip().lower()
    cleaned = re.sub(r'[-\s]+', '_', cleaned) 
    
    return cleaned

def try_object_id(id_string):
    """Converte string para ObjectId, ou retorna a string se falhar ou se já for None."""
    if not id_string:
        return None
    try:
        return ObjectId(id_string)
    except:
        return id_string

def safe_float(value):
    """
    Converte valores numéricos do MongoDB (incluindo Decimal128) para float.
    """
    if value is None:
        return 0.0
    if isinstance(value, Decimal128):
        return float(str(value))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0 

def get_next_global_sequence(db, sequence_name):
    """Incrementa e retorna o próximo valor sequencial de forma atômica."""
    try:
        update_result = db.contadores.find_one_and_update(
            {'_id': sequence_name},
            {'$inc': {'sequence_value': 1}}, 
            return_document=pymongo.ReturnDocument.AFTER, 
            upsert=True 
        )
        
        if update_result and 'sequence_value' in update_result:
            return update_result['sequence_value']
        else:
            print(f"DEBUG: Falha na atualização do contador {sequence_name}.")
            return None
            
    except Exception as e:
        print(f"ERRO CRÍTICO GERAL ao obter valor sequencial para {sequence_name}: {e}")
        return None

def get_next_cliente_sequence():
    """Obtém o próximo ID sequencial do cliente de forma atômica e segura."""
    db = get_vendas_db() 
    if db is None: return None # <-- CORREÇÃO PYMONGO

    if cliente_lock.acquire(timeout=5):
        try:
            return get_next_global_sequence(db, 'id_clientes_global')
        finally:
            cliente_lock.release()
    return None

def get_next_colaborador_sequence():
    """Gera o próximo ID sequencial para Colaboradores (atômico)."""
    db = get_vendas_db() 
    if db is None: return None # <-- CORREÇÃO PYMONGO

    with colaborador_lock:
        seq_doc = db.contadores.find_one_and_update(
            {'_id': 'id_colaborador_global'},
            {'$inc': {'sequence_value': 1}},
            upsert=True,
            return_document=pymongo.ReturnDocument.AFTER
        )
        return seq_doc['sequence_value'] if seq_doc else None

def get_next_evento_sequence():
    """Gera o próximo ID sequencial para Eventos (atômico)."""
    db = get_vendas_db() 
    if db is None: return None # <-- CORREÇÃO PYMONGO

    with evento_lock:
        seq_doc = db.contadores.find_one_and_update(
            {'_id': 'id_evento_global'},
            {'$inc': {'sequence_value': 1}},
            upsert=True,
            return_document=pymongo.ReturnDocument.AFTER
        )
        return seq_doc['sequence_value'] if seq_doc else None

def get_next_bilhete_sequence(db, id_evento, increment_field, quantidade_cartelas, limite_maximo):
    """
    Incrementa o campo de sequência (inicial_proxima_venda) por `quantidade_cartelas`
    e aplica um rollover se atingir `limite_maximo`.
    """
    
    VALOR_INICIAL_PADRAO = 1 
    now_utc = hora_brasil()
    data_hora_formatada = now_utc.strftime("%d-%m/%Y %H:%M:%S")

    update_pipeline = [
        {
            '$set': {
                increment_field: {
                    '$cond': {
                        'if': { 
                            '$gte': [ 
                                { '$add': ["$" + increment_field, quantidade_cartelas] }, 
                                limite_maximo 
                            ] 
                        },
                        'then': { 
                            '$subtract': [ 
                                { '$add': ["$" + increment_field, quantidade_cartelas] }, 
                                limite_maximo 
                            ] 
                        },
                        'else': { 
                            '$add': ["$" + increment_field, quantidade_cartelas] 
                        }
                    }
                },
                "data_hora": data_hora_formatada
            }
        }
    ]
    
    try:
        query = {'id_evento': id_evento}
        
        update_result = db.controle_venda.find_one_and_update(
            query,
            update_pipeline, 
            return_document=pymongo.ReturnDocument.BEFORE,
            upsert=True,
            projection={increment_field: 1} 
        )

        if update_result and increment_field in update_result:
            return update_result[increment_field] 
        else:
            if update_result is None:
                return VALOR_INICIAL_PADRAO
            return None 
            
    except Exception as e:
        print(f"ERRO CRÍTICO ao obter valor sequencial de bilhete/cartela para {id_evento}: {e}")
        return None

def format_title_case(s):
    """Formata as primeiras letras de cada palavra para maiúscula."""
    if not s: return ""
    return s.strip().title()

def clean_numeric_string(s):
    """Remove caracteres não-numéricos de uma string (para CPF/Telefone)."""
    if not s: return ""
    return re.sub(r'\D', '', str(s))

def validate_cpf(cpf_str):
    """Validação básica de CPF (apenas verifica se tem 11 dígitos)."""
    cpf = clean_numeric_string(cpf_str)
    if not cpf or len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    
    def check_digit(n):
        soma = sum(int(cpf[i]) * ((n + 1) - i) for i in range(n))
        remainder = 11 - (soma % 11)
        return 0 if remainder > 9 else remainder

    if check_digit(9) != int(cpf[9]): return False
    if check_digit(10) != int(cpf[10]): return False
        
    return True

# --- FUNÇÕES DE CACHE E BUSCA DE CARTELAS ---
def carregar_linha_cartela(numero_cartela, tipo_cartela):
    """
    Função de leitura otimizada.
    Lê o arquivo TXT correspondente e retorna os dados da linha que
    corresponde ao número da cartela (índice baseado em 1).
    """
    caminho_arquivo = os.path.join(CARTELAS_FOLDER, f'cartelas.{tipo_cartela}')
    
    try:
        with open(caminho_arquivo, 'r', encoding='latin-1') as f:
            for _ in range(numero_cartela - 1):
                next(f)
            
            linha = next(f, None)
            
            if linha is None:
                return None

            linha = linha.strip()
            dados = linha.split('!')
            
            numeros_raw = [
                (int(n) if str(n).strip().isdigit() else n.strip().upper())
                for n in dados[1:]
            ]
            
            if int(dados[0]) != numero_cartela:
                 print(f"ALERTA CRÍTICO: ID no arquivo ({dados[0]}) não corresponde à linha ({numero_cartela}).")
                 
            return numeros_raw

    except FileNotFoundError:
        print(f"ERRO CRÍTICO: Arquivo de cartelas não encontrado em: {caminho_arquivo}")
        return None
    except Exception as e:
        print(f"ERRO ao ler linha {numero_cartela}: {e}")
        return None


def buscar_dados_cartela_2d(numero_cartela, tipo_cartela):
    """
    Busca os dados no arquivo e os formata em uma lista 2D.
    Suporta tipos 25 (5x5) e 15 (3x5).
    """
    numeros_lista = carregar_linha_cartela(numero_cartela, tipo_cartela)

    if not numeros_lista:
        return None
    
    if tipo_cartela == 25:
        if len(numeros_lista) < 25: return None
        cartela_2d = []
        for i in range(5): 
            linha = []
            for j in range(5): 
                indice = (j * 5) + i
                linha.append(numeros_lista[indice]) 
            cartela_2d.append(linha)
        
        #if cartela_2d[2][2] != "FREE": cartela_2d[2][2] = "FREE"
        return cartela_2d
        
    elif tipo_cartela == 15:
        # Lógica para cartela de 15 números (3 linhas x 5 colunas)
        if len(numeros_lista) < 15: return None
        
        cartela_2d = []
        for i in range(3): # 3 Linhas
            linha = []
            for j in range(5): # 5 Colunas
                # A fórmula do índice depende de como seu TXT é gerado.
                # Assumindo ordem: Coluna 1 completa, depois Coluna 2... (Padrão Bingo)
                indice = (j * 3) + i
                linha.append(numeros_lista[indice])
            cartela_2d.append(linha)
        return cartela_2d
    
    return None


# --- HOOKS DA APLICAÇÃO ---@app.before_request
@app.before_request
def before_request():
    global client_control, db_control, DEFAULT_SALA_ID

    # Setup Básico
    if not hasattr(g, 'client_control'): 
        g.client_control = client_control
    
    if not hasattr(g, 'parametros_globais'): 
        g.parametros_globais = {}
    
    # CORREÇÃO AQUI: Verificamos explicitamente se não é None
    g.db_status = True if db_control is not None else False

    # 1. Define ID SALA (URL > Sessão > Default)
    id_sala_url = request.args.get('id_sala')
    id_sala_sessao = session.get('id_sala')
    
    if id_sala_url:
        g.id_sala = id_sala_url
        session['id_sala'] = id_sala_url
    elif id_sala_sessao:
        g.id_sala = id_sala_sessao
    else:
        g.id_sala = "000"
        session['id_sala'] = "000"

    # 2. Carrega Parâmetros (Apenas se DB estiver ON)
    if g.db_status:
        try:
            db = get_vendas_db() 
            
            # Valores padrão
            default_config_cadastro = {
                "nome_cliente": True, "nick": True, "telefone": True,
                "cpf": False, "cidade": True, "chave_pix": True, "senha": True
            }
            
            # Verifica se db não é None antes de usar
# Verifica se db não é None antes de usar
            if db is not None:
                #print(f"\n[DEBUG] --- Iniciando busca de parâmetros para sala: '{g.id_sala}' ---")
                
                # Busca parametros no banco específico da sala
                params = db.parametros.find_one({'id_sala': g.id_sala})
                
                # Se não achar por ID exato, tenta com prefixo "SALA"
                if params is None:
                     #print(f"[DEBUG] ID exato não encontrado. Tentando buscar por 'SALA{g.id_sala}'...")
                     params = db.parametros.find_one({'id_sala': f"SALA{g.id_sala}"})

                if params is not None:
                    # LOGS PARA CONFERÊNCIA
                    val_banco = params.get('limite_de_credito')
                    #print(f"[DEBUG] SUCESSO! Documento encontrado.")
                    #print(f"[DEBUG] > Nome Sala no Banco: {params.get('nome_sala')}")
                    #print(f"[DEBUG] > Limite Crédito no Banco: {val_banco} (Tipo: {type(val_banco)})")
                    
                    val_limite_bruto = params.get('limite_de_credito', 100) 
                    limite_convertido = float(str(val_limite_bruto))

                    g.parametros_globais = {
                        'url_live': params.get('url_live', '#'), 
                        'url_site': params.get('url_site', '#'), 
                        'nome_sala': params.get('nome_sala', 'SALA PADRÃO').strip(),
                        'http_apk': params.get('http_apk', 'http://localhost:5000'), 
                        'http_vendas': params.get('http_vendas', 'http://localhost:5000'),
                        'id_sala_param': g.id_sala,
                        'tipo_cadastro_cliente': params.get('tipo_cadastro_cliente', default_config_cadastro), 
                        'comissao_padrao': params.get('comissao_padrao', 20),
                        'comissao_autoatendimento': params.get('comissao_autoatendimento', 10), 
                        
                        # Conversão explícita e Logada
                        'limite_de_credito': limite_convertido,
                        
                        'tipo_cadastro_colaborador': params.get('tipo_cadastro_colaborador', {})
                    }
                    #print(f"[DEBUG] > Parâmetro Global Final 'limite_de_credito': {g.parametros_globais['limite_de_credito']}")
                else:
                    # Defaults se não achar parametros
                    print(f"[DEBUG] AVISO: Nenhum parâmetro encontrado no banco. Usando DEFAULTS (Limite 100.0).")
                    g.parametros_globais = {'tipo_cadastro_cliente': default_config_cadastro, 'comissao_padrao': 20, 'nome_sala': 'SALA (DEFAULT)', 'id_sala_param': g.id_sala, 'limite_de_credito': 100.00}

        except Exception as e:
            print(f"Erro ao carregar parâmetros no before_request: {e}")


@app.teardown_request
def teardown_request(exception=None):
    pass 

# --- ROTAS DE AUTENTICAÇÃO E INICIALIZAÇÃO ---

@app.route('/')
def login_page():
    # Esta rota apenas renderiza o formulário de login (GET)
    
    id_sala_param = request.args.get('id_sala')
    ref_param = request.args.get('ref') # <--- Captura o código do colaborador
    error = request.args.get('error')

 # LÓGICA DE REDIRECIONAMENTO AUTOMÁTICO
    # Se o link tiver 'ref', enviamos direto para o auto cadastro
    if ref_param:
        return redirect(url_for('auto_cadastro_page', id_sala=id_sala_param, ref=ref_param))  
    
    return render_template('index.html', 
                           db_error=None, 
                           error=error,
                           id_sala_exibicao=id_sala_param,
                           g=g) # <--- IMPORTANTE: Adicionar isto


@app.route('/login', methods=['POST'])
def login():
    
    #print("\n=== [DEBUG] INÍCIO DO LOGIN ===")
    
    nome_raw = request.form.get('nome')
    senha_raw = request.form.get('senha')
    
    # Padroniza o nome para busca (Title Case)
    nome_usuario = format_title_case(nome_raw)
    
    id_sala_to_redirect = g.id_sala
    db = get_vendas_db()
    
    if db is None:
        return redirect(url_for('login_page', error="Erro de Conexão DB.", id_sala=id_sala_to_redirect))

    usuario = None
    tipo_usuario = 'desconhecido'

    try:
        # Busca em Colaboradores
        usuario = db.colaboradores.find_one({
            '$or': [{'nome_colaborador': nome_usuario}, {'nick': nome_usuario}]
        })
        
        if usuario:
            tipo_usuario = 'colaborador'
        #else:
            # Busca em Clientes
            #usuario = db.clientes.find_one({'nick': nome_usuario})
            #if usuario: tipo_usuario = 'cliente'

    except Exception as e:
        print(f"🚨 [DEBUG] Erro busca usuário: {e}")
        return redirect(url_for('login_page', error="Erro interno.", id_sala=id_sala_to_redirect))
    
    if usuario and 'senha' in usuario:
        senha_hash_banco = usuario.get('senha', '')
        senha_limpa = senha_raw.strip() # Remove espaços
        
        # --- LÓGICA HÍBRIDA (NOVO + LEGADO) ---
        autenticado = False
        senha_eficaz = senha_limpa # Qual versão da senha funcionou?

        # 1. Tenta EXATAMENTE como digitou (Para o futuro)
        try:
            if bcrypt.checkpw(senha_limpa.encode('utf-8'), senha_hash_banco.encode('utf-8')):
                autenticado = True
            else:
                # 2. Se falhar, tenta o formato LEGADO (Capitalize) para usuários antigos
                senha_legacy = senha_limpa.capitalize()
                if bcrypt.checkpw(senha_legacy.encode('utf-8'), senha_hash_banco.encode('utf-8')):
                    autenticado = True
                    senha_eficaz = senha_legacy # Marca que a versão Capitalized foi a que funcionou
        except Exception as e:
            print(f"[DEBUG] Erro no bcrypt: {e}")

        if autenticado:
            session['logged_in'] = True
            
            # Configura Sessão
            if tipo_usuario == 'colaborador':
                session['id_colaborador'] = usuario.get('id_colaborador') or str(usuario['_id'])
                session['nivel'] = usuario.get('nivel', 1) 
                session['nick'] = usuario.get('nick') or usuario.get('nome_colaborador')
                session['tipo_usuario_logado'] = 'colaborador'
            #else:
                #session['id_cliente'] = usuario.get('id_cliente')
                #session['nick'] = usuario.get('nick')
                #session['nivel'] = 0
                #session['tipo_usuario_logado'] = 'cliente'

            # --- VERIFICAÇÃO DE SENHA PADRÃO ---
            # Verifica se a senha que funcionou é "Senha" ou "senha"
            if senha_eficaz.lower() == "senha" and tipo_usuario == 'colaborador':
                #print("[DEBUG] Senha padrão detectada. Forçando troca.")
                return render_template('trocar_senha_obrigatoria.html', id_sala=id_sala_to_redirect)
            
            # Redirecionamento Sucesso
            if tipo_usuario == 'colaborador':
                return redirect(url_for('menu_operacoes'))
            #else:
                #return redirect(url_for('minha_carteira'))
        else:
            print(f"[DEBUG] Falha: Senha incorreta (Testado '{senha_limpa}' e '{senha_limpa.capitalize()}')")

    return redirect(url_for('login_page', error="Usuário ou senha inválidos.", id_sala=id_sala_to_redirect))



@app.route('/menu')
@login_required
def menu_operacoes():
    nivel = session.get('nivel', 1) 
    nome_logado = session.get('nick', 'Colaborador')
    db_status = g.db_status 

    error = request.args.get('error')
   
    return render_template('menu.html', 
                           nivel=session.get('nivel', 1), 
                           logado=session.get('nick', 'Colaborador'), 
                           db_status=g.db_status, 
                           error=error,
                           g=g) # <--- IMPORTANTE: Adicionar isto


@app.route('/submenu_eventos')
@login_required
def submenu_eventos():
    return render_template('submenu_eventos.html')


# ==============================================================================
# --- ROTA DE STATUS DE EVENTOS (ATUALIZADA COM O MOTOR MATEMÁTICO) ---
# ==============================================================================
@app.route('/consulta_status_eventos', methods=['GET'])
@login_required
def consulta_status_eventos():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    error = session.pop('error_message', None)
    success = session.pop('success_message', None)
    
    nivel_usuario = session.get('nivel', 0) 
    view_mode = request.args.get('mode', 'detailed') 
    
    # Busca configurações globais antes do loop para otimização
    param_doc_global = {}
    if g.db_status:
        try:
            param_doc_global = db.parametros.find_one({}) or {}
        except Exception as e:
            print(f"Aviso parametros status: {e}")

    filtro_padrao = "ativo,paralizado"
    filtro_str = request.args.get('filtro', filtro_padrao)
    
    if filtro_str == 'todos':
        status_list = ['ativo', 'paralizado', 'finalizado']
    else:
        status_list = filtro_str.split(',')
        status_list = [s.strip().lower() for s in status_list if s.strip().lower() in ['ativo', 'paralizado', 'finalizado']]
        if not status_list: status_list = ['ativo', 'paralizado']
            
    status_regex_list = [re.compile(f'^{s}$', re.IGNORECASE) for s in status_list]
    eventos_status = []
    
    def format_currency(value):
        if value is None: return "R$ 0,00"
        return f"R$ {safe_float(value):.2f}".replace('.', ',')

    try:
        eventos_cursor = db.eventos.find({'status': {'$in': status_regex_list}}).sort("data_hora_evento", pymongo.ASCENDING)
        
        for evento in eventos_cursor:
            id_evento_int = evento.get('id_evento')
            
            # 1. Busca dados de vendas
            colecao_vendas = f"vendas{id_evento_int}"
            vendas_data = None
            if colecao_vendas in db.list_collection_names():
                vendas_data_list = list(db[colecao_vendas].aggregate([
                    {'$group': {'_id': None, 'total_unidades': {'$sum': '$quantidade_unidades'}, 'total_valor': {'$sum': '$valor_total'}}}
                ]))
                vendas_data = vendas_data_list[0] if vendas_data_list else None
            
            total_unidades = vendas_data.get('total_unidades', 0) if vendas_data else 0
            valor_vendas_float = safe_float(vendas_data.get('total_valor', 0) if vendas_data else 0)

            # --- 2. INJEÇÃO DO MOTOR MATEMÁTICO ---
            # Prepara os dados que a função calcular_premios_dinamicos exige ler do evento
            evento['qtd_vendas'] = total_unidades
            
            # Converte os campos críticos para float nativo antes de passar para o motor
            for k in ['valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_faltaum', 'premio_total']:
                if k in evento: evento[k] = safe_float(evento[k])
                
            # Roda a função para engordar o prémio caso o lucro o permita
            evento = calcular_premios_dinamicos(db, evento, param_doc_global)

            # 3. Agora extrai os totais (já atualizados pelo motor, se for o caso)
            premio_total_float = safe_float(evento.get('premio_total', 0))
            saldo_float = valor_vendas_float - premio_total_float
            # --------------------------------------

            controle = db.controle_venda.find_one({'id_evento': id_evento_int})
            num_atual = controle.get('inicial_proxima_venda', evento.get('numero_inicial', 1)) if controle else evento.get('numero_inicial', 1)
            
            data_ativado = evento.get('data_ativado')
            data_ativado_formatada = 'N/A'
            if isinstance(data_ativado, str):
                try:
                    data_ativado_dt = datetime.strptime(data_ativado.strip(), '%Y-%m-%d')
                    data_ativado_formatada = data_ativado_dt.strftime("%d/%m/%Y") 
                except ValueError: data_ativado_formatada = data_ativado 
            elif isinstance(data_ativado, datetime):
                data_ativado_formatada = data_ativado.strftime("%d/%m/%Y %H:%M:%S")
            
            evento_info = {
                'id_evento': evento.get('id_evento'),
                'descricao': evento.get('descricao'),
                # Garantia da DATA que estava faltando
                'data_evento': evento.get('data_evento', 'N/A'),
                'hora_evento': evento.get('hora_evento', 'N/A'),
                'data_hora': f"{evento.get('data_evento', 'N/A')} às {evento.get('hora_evento', 'N/A')}",
                'status': evento.get('status').lower(), 
                'tipo_de_evento': evento.get('tipo_de_evento', 'Normal'),
                'valor_venda_unit': format_currency(evento.get('valor_de_venda')),
                'data_ativacao': data_ativado_formatada,
                'total_vendido': total_unidades,
                'valor_total_vendido': format_currency(valor_vendas_float),
                'premio_total': format_currency(premio_total_float),
                'saldo': format_currency(saldo_float),
                'saldo_is_positivo': (saldo_float >= 0),
                'numeracao_atual': num_atual,
                'is_ativo': evento.get('status').lower() == 'ativo' if evento.get('status') else False, 
                'limite_maximo': evento.get('numero_maximo'),
                # Flag para exibir o foguetinho no HTML
                'is_premio_dinamico': evento.get('is_premio_dinamico_ativo', False)
            }
            eventos_status.append(evento_info)

    except Exception as e:
        print(f"ERRO CRÍTICO ao buscar status de eventos: {e}")
        return render_template('consulta_status_eventos.html', error=f"Erro interno: {e}", eventos_status=[], g=g, success=success, mode=view_mode, nivel=nivel_usuario, filtro_atual=filtro_str)

    return render_template('consulta_status_eventos.html', 
                           eventos_status=eventos_status, g=g, 
                           mode=view_mode, error=error, success=success, 
                           nivel=nivel_usuario, 
                           filtro_atual=filtro_str)


@app.route('/evento/mudar_status', methods=['POST'])
@login_required
def evento_mudar_status():
    db = get_vendas_db()
    if db is None: 
        session['error_message'] = "Erro de conexão com o BD de Vendas."
        return redirect(url_for('consulta_status_eventos'))
    
    if session.get('nivel', 0) < 3:
        session['error_message'] = "Acesso Negado. Nível 3 Requerido."
        return redirect(url_for('consulta_status_eventos'))
        
    try:
        id_evento_int = int(request.form.get('id_evento_int'))
        novo_status = request.form.get('novo_status').lower() 
        current_mode = request.form.get('current_mode', 'detailed')
    except Exception as e:
        session['error_message'] = f"Dados inválidos: {e}"
        return redirect(url_for('consulta_status_eventos'))
        
    if novo_status not in ['ativo', 'paralizado', 'finalizado']:
        session['error_message'] = "Status inválido."
        return redirect(url_for('consulta_status_eventos', mode=current_mode))

    try:
        update_data = {'status': novo_status}
        if novo_status == 'ativo':
            evento = db.eventos.find_one({'id_evento': id_evento_int}, {'data_ativado': 1})
            if evento and evento.get('data_ativado') is None:
                update_data['data_ativado'] = hora_brasil()
        
        result = db.eventos.update_one({'id_evento': id_evento_int}, {'$set': update_data})
        if result.modified_count == 1:
            session['success_message'] = f"Evento EVE{id_evento_int} atualizado para '{novo_status.upper()}'."
        else:
            session['error_message'] = f"Evento EVE{id_evento_int} não foi modificado."

    except Exception as e:
        session['error_message'] = f"Erro de banco de dados: {e}"
        
    return redirect(url_for('consulta_status_eventos', mode=current_mode))


# --- Rotas de Colaborador ---

@app.route('/cadastro_colaborador', methods=['GET'])
@login_required
def cadastro_colaborador():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))
        
    db_status = g.db_status
    form_data_erro = session.pop('form_data', None)
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    id_colaborador_edicao = request.args.get('id_colaborador', None) 
    
    colaborador_edicao = None 
    colaboradores_lista = []
    total_colaboradores = 0
    
    error = request.args.get('error')
    success = request.args.get('success')

    if form_data_erro:
        colaborador_edicao = form_data_erro
        if 'id_colaborador_edicao' in form_data_erro and form_data_erro['id_colaborador_edicao']:
             active_view = 'alterar'
             id_colaborador_edicao = form_data_erro['id_colaborador_edicao']
        else:
             active_view = 'novo'

    elif active_view == 'alterar' and id_colaborador_edicao and db_status:
        try:
            id_colaborador_int = int(id_colaborador_edicao)
            colaborador_edicao = db.colaboradores.find_one({'id_colaborador': id_colaborador_int})
            
            if colaborador_edicao:
                if '_id' in colaborador_edicao: colaborador_edicao['_id'] = str(colaborador_edicao['_id'])
                if 'senha' in colaborador_edicao: del colaborador_edicao['senha'] 
            else:
                 error = f"Colaborador ID {id_colaborador_int} não encontrado para edição."
                 active_view = 'listar' 
                 
        except (ValueError, TypeError):
            error = "ID de Colaborador inválido para edição."
            active_view = 'listar'
            
    if db_status:
        try:
            total_colaboradores = db.colaboradores.count_documents({})
            
            if active_view == 'listar':
                colaboradores_cursor = db.colaboradores.find({}).sort("nick", pymongo.ASCENDING)
                colaboradores_lista = list(colaboradores_cursor)
            
            elif active_view == 'consulta' and search_term:
                query_filter = {}
                
                if search_term.isdigit(): 
                    query_filter = {'$or': [{'id_colaborador': int(search_term)}, {'cpf': search_term}]}
                
                if not query_filter:
                    regex_term = re.compile(re.escape(search_term), re.IGNORECASE)
                    query_filter = {
                        '$or': [
                            {'nick': {'$regex': regex_term}},
                            {'chave_pix': {'$regex': regex_term}},
                            {'cpf': {'$regex': regex_term}},
                        ]
                    }
                    
                colaboradores_cursor = db.colaboradores.find(query_filter)
                colaboradores_lista = list(colaboradores_cursor) 

        except Exception as e:
            print(f"Erro ao buscar dados no MongoDB em cadastro_colaborador: {e}")
            error = f"Erro crítico ao carregar dados do DB: {e}"

    for colab in colaboradores_lista:
        if '_id' in colab: colab['_id'] = str(colab['_id'])
        if 'senha' in colab: del colab['senha']
        
    default_comissao = g.parametros_globais.get('comissao_padrao', 20)

    context = {
        'total_colaboradores': total_colaboradores,
        'colaboradores_lista': colaboradores_lista,
        'active_view': active_view,
        'query': search_term, 
        'colaborador_edicao': colaborador_edicao,
        'error': error,
        'success': success,
        'g': g,
        'default_comissao': default_comissao 
    }
    
    return render_template('cadastro_colaborador.html', **context)


@app.route('/gravar_colaborador', methods=['POST'])
@login_required
def gravar_colaborador():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))

    id_colaborador_edicao = request.form.get('id_colaborador_edicao') 

    try:
        default_colab_config = { "nome_colaborador": True, "nick": True, "telefone": True, "cpf": False, "cidade": False, "chave_pix": True, "senha": True, "nivel": True, "comissao": True }
        campos_config = g.parametros_globais.get('tipo_cadastro_colaborador', default_colab_config)

        # Captura dos campos
        nome_colaborador = format_title_case(request.form.get('nome_colaborador'))
        nick = format_title_case(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip().lower()
        confirma_chave_pix = request.form.get('confirma_chave_pix', '').strip().lower()
        senha = request.form.get('senha')
        confirma_senha = request.form.get('confirma_senha') 
        nivel = int(request.form.get('nivel'))
        comissao = int(request.form.get('comissao', g.parametros_globais.get('comissao_padrao', 20)))
        
        # --- LIMITE DE CRÉDITO ---
        padrao_global = g.parametros_globais.get('limite_de_credito', 100.00)
        limite_credito_str = request.form.get('limite_credito')
       
        if limite_credito_str:
            limite_credito = float(limite_credito_str.replace(',', '.'))
        else:
            limite_credito = float(padrao_global)
        if limite_credito < 0:
            raise ValueError("O Limite de Crédito não pode ser menor que zero.")

        # VALIDAÇÕES BÁSICAS
        if campos_config.get("nome_colaborador") and not nome_colaborador:
            raise ValueError("O campo Nome do Colaborador é obrigatório.")
        if campos_config.get("nick") and not nick:
            raise ValueError("O campo Nick é obrigatório.")
        
        # Validação PIX Básica
        if "chave_pix" in campos_config: 
            if not chave_pix:
                raise ValueError("A Chave PIX é obrigatória.")
            if chave_pix != confirma_chave_pix:
                raise ValueError("As chaves PIX não conferem.")
            
            # 1. Monta a Query Regex
            query_pix_colab = {
                'chave_pix': {'$regex': f'^{re.escape(chave_pix)}$', '$options': 'i'}
            }
            
            # 2. Adiciona filtro de ID se for edição
            if id_colaborador_edicao:
                try:
                    id_exclude = int(id_colaborador_edicao)
                    query_pix_colab['id_colaborador'] = {'$ne': id_exclude}
                    print(f"[DEBUG PIX] Modo EDIÇÃO. Excluindo ID: {id_exclude}")
                except:
                    print(f"[DEBUG PIX] ERRO ao converter ID para exclusão: {id_colaborador_edicao}")
            
            # 3. Executa a busca
            colaborador_existente = db.colaboradores.find_one(query_pix_colab)
            
            # --- TESTE DE PROVA REAL (DEBUG) ---
            # Vamos listar todos os PIX que existem no banco para você ver se tem "sujeira"
            if not colaborador_existente:
                # Busca simples por qualquer coisa que contenha parte da string
                parecidos = db.colaboradores.find({'chave_pix': {'$regex': re.escape(chave_pix), '$options': 'i'}})
                for p in parecidos:
                    print(f"   -> EXISTE NO BANCO: ID {p.get('id_colaborador')} | Pix: '{p.get('chave_pix')}'")
            
            if colaborador_existente:
                nick_encontrado = colaborador_existente.get('nick', 'Desconhecido')
                raise ValueError(f"A Chave PIX '{chave_pix}' já está em uso pelo colaborador: {nick_encontrado}.")

        dados_colaborador = {
            "nome_colaborador": nome_colaborador,
            "nick": nick,
            "telefone": telefone,
            "cpf": clean_numeric_string(cpf_raw),
            "cidade": cidade,
            "chave_pix": chave_pix,
            "nivel": nivel, 
            "comissao": comissao,
            "limite_credito": limite_credito 
        }        

        if "senha" in campos_config and senha:
            senha_limpa = senha.strip() 
            hashed_password = bcrypt.hashpw(senha_limpa.encode('utf-8'), bcrypt.gensalt())
            dados_colaborador['senha'] = hashed_password.decode('utf-8')
        
        # GRAVAÇÃO
        if id_colaborador_edicao:
            # Edição
            id_colaborador_int = int(id_colaborador_edicao)
            
            if id_colaborador_int == session.get('id_colaborador') and nivel < 3 and session.get('nivel') == 3 and db.colaboradores.count_documents({'nivel': 3}) == 1:
                raise ValueError("Você é o único administrador. Não pode rebaixar seu próprio nível.")
            
            if not senha and 'senha' in dados_colaborador: 
                del dados_colaborador['senha']
                 
            db.colaboradores.update_one({'id_colaborador': id_colaborador_int}, {'$set': dados_colaborador})
            success_msg = f"Colaborador {nick} atualizado com sucesso! Limite: R$ {limite_credito:.2f}"
            
        else:
            # Novo
            novo_id_colaborador_int = get_next_colaborador_sequence()
            if novo_id_colaborador_int is None: raise Exception("Falha sequence.")
            dados_colaborador['id_colaborador'] = novo_id_colaborador_int
            dados_colaborador['status'] = 'ativo'
            
            if 'senha' not in dados_colaborador:
                 senha_padrao = "Senha"
                 dados_colaborador['senha'] = bcrypt.hashpw(senha_padrao.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            db.colaboradores.insert_one(dados_colaborador)
            success_msg = f"Colaborador {nick} salvo! ID: {novo_id_colaborador_int}"
        
        return redirect(url_for('cadastro_colaborador', success=success_msg, view='listar'))

    except ValueError as e:
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        redirect_args = {'error': f"Erro de Validação: {e}", 'view': view_redirect}
        if id_colaborador_edicao: redirect_args['id_colaborador'] = id_colaborador_edicao
        return redirect(url_for('cadastro_colaborador', **redirect_args))
        
    except Exception as e:
        print(f"ERRO CRÍTICO colab: {e}")
        import traceback
        traceback.print_exc()
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        return redirect(url_for('cadastro_colaborador', error="Erro interno.", view=view_redirect))


@app.route('/colaborador/excluir/<int:id_colaborador>', methods=['POST'])
@login_required
def excluir_colaborador(id_colaborador):
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO
    
    if session.get('nivel', 0) < 3: 
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))
    
    if int(session.get('id_colaborador', 0)) == id_colaborador:
        return redirect(url_for('cadastro_colaborador', error="Não é possível excluir o próprio usuário logado.", view='listar'))

    try:
        colaborador = db.colaboradores.find_one({'id_colaborador': id_colaborador})
        
        if not colaborador:
             return redirect(url_for('cadastro_colaborador', error=f"Colaborador ID: {id_colaborador} não encontrado.", view='listar'))

        if colaborador.get('nick', '').upper() == 'TECBIN':
            return redirect(url_for('cadastro_colaborador', error="Este colaborador (TECBIN) não pode ser excluído.", view='listar'))

        result = db.colaboradores.delete_one({'id_colaborador': id_colaborador})
        
        if result.deleted_count == 1:
            success_msg = f"Colaborador ID: {id_colaborador} excluído com sucesso."
        else:
            success_msg = f"Colaborador ID: {id_colaborador} não encontrado para exclusão."

        return redirect(url_for('cadastro_colaborador', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO CRÍTICO na exclusão de colaborador ID {id_colaborador}: {e}")
        return redirect(url_for('cadastro_colaborador', error=f"Erro interno ao excluir colaborador.", view='listar'))

@app.route('/colaborador/alternar_status/<int:id_colaborador>', methods=['POST'])
@login_required
def alternar_status_colaborador(id_colaborador):
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    # Apenas admin (nível 3) pode bloquear/ativar
    if session.get('nivel', 0) < 3: 
        return redirect(url_for('cadastro_colaborador', view='listar', error="Acesso Negado."))
    
    # Não pode bloquear a si mesmo
    if int(session.get('id_colaborador', 0)) == id_colaborador:
        return redirect(url_for('cadastro_colaborador', view='listar', error="Você não pode bloquear seu próprio usuário."))

    try:
        colaborador = db.colaboradores.find_one({'id_colaborador': id_colaborador})
        if not colaborador:
             return redirect(url_for('cadastro_colaborador', view='listar', error="Colaborador não encontrado."))

        # Lógica de alternância (Toggle)
        status_atual = colaborador.get('status', 'ativo') # Assume ativo se não existir
        novo_status = 'bloqueado' if status_atual == 'ativo' else 'ativo'
        
        db.colaboradores.update_one(
            {'id_colaborador': id_colaborador},
            {'$set': {'status': novo_status}}
        )
        
        acao = "BLOQUEADO" if novo_status == 'bloqueado' else "ATIVADO"
        msg = f"Colaborador {colaborador.get('nick')} foi {acao} com sucesso."
        
        # Redireciona mantendo a view atual se possível (listar ou consulta)
        view_retorno = request.args.get('view', 'listar')
        return redirect(url_for('cadastro_colaborador', view=view_retorno, success=msg))

    except Exception as e:
        print(f"Erro ao alternar status: {e}")
        return redirect(url_for('cadastro_colaborador', view='listar', error="Erro interno ao alterar status."))



# --- ROTAS DE VENDA ---
@app.route('/venda/nova', methods=['GET'])
@login_required
def nova_venda():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    # --- VERIFICAÇÃO DE SEGURANÇA: STATUS DO COLABORADOR ---
    # Verifica no banco se o usuário foi bloqueado recentemente
    if 'id_colaborador' in session:
        try:
            uid = session.get('id_colaborador')
            query_colab = {'id_colaborador': int(uid)} if str(uid).isdigit() else {'_id': try_object_id(uid)}
            
            colab_atual = db.colaboradores.find_one(query_colab, {'status': 1})
            
            if colab_atual and colab_atual.get('status') == 'bloqueado':
                # ALTERAÇÃO: Não desloga (session.clear removido) e manda para o MENU
                return redirect(url_for('menu_operacoes', 
                                      error="⛔ ACESSO BLOQUEADO: Seu usuário está restrito para realizar vendas."))
        except Exception as e:
            print(f"Erro ao verificar bloqueio de usuário: {e}")
    # -------------------------------------------------------

    error = request.args.get('error')
    success = session.pop('success_message', None) 

    id_cliente_final = None
    cliente_encontrado = None
    custo = 0.00
    
    id_evento_param = request.args.get('id_evento')
    id_cliente_busca = request.args.get('id_cliente_busca', '').strip()
    quantidade_param = request.args.get('quantidade') 
    
    quantidade = int(quantidade_param) if quantidade_param and str(quantidade_param).isdigit() else 0
    
    eventos_ativos_cursor = db.eventos.find({'status': 'ativo'}).sort('data_evento', pymongo.ASCENDING)
    
    eventos_enriquecidos = []
    selected_event = None

    param_doc_global = {}
    if g.db_status:
        try:
            param_doc_global = db.parametros.find_one({}) or {}
        except Exception:
            pass
    
    for evento in eventos_ativos_cursor:
        
        evento['valor_de_venda_float'] = safe_float(evento.get('valor_de_venda', 0.00))

        controle = db.controle_venda.find_one({
            'id_evento': evento.get('id_evento') 
        })
        
        inicial_proxima_venda = controle.get('inicial_proxima_venda', 1) if controle else evento.get('numero_inicial', 1)
        evento['numeracao_atual_display'] = inicial_proxima_venda

        for key in ['valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_faltaum', 'premio_total']:
            if key in evento: evento[key] = safe_float(evento[key])
            
        evento = calcular_premios_dinamicos(db, evento, param_doc_global)
        
        def format_date_safe(field_name, format_output, format_input=None):
            value = evento.get(field_name)
            if isinstance(value, datetime):
                return value.strftime(format_output)
            elif isinstance(value, str) and value.strip() and format_input:
                try:
                    dt_obj = datetime.strptime(value.strip(), format_input)
                    return dt_obj.strftime(format_output)
                except ValueError:
                    if re.match(r'^\d{2}/\d{2}/\d{4}$', value.strip()):
                        return value.strip()
                    return value
            return value
        
        evento['data_evento'] = format_date_safe('data_evento', '%d/%m/%Y', format_input='%Y-%m-%d')
        evento['hora_evento'] = format_date_safe('hora_evento', '%H:%M') 
        
        eventos_enriquecidos.append(evento)
        
    if id_evento_param:
        try:
            evento_oid = ObjectId(id_evento_param)
            selected_event = next((e for e in eventos_enriquecidos if e['_id'] == evento_oid), None)
            
        except Exception:
            error = "ID de evento inválido."
            selected_event = None
            
    #if not selected_event and eventos_enriquecidos:
    #    selected_event = eventos_enriquecidos[0]
        
    if selected_event and id_cliente_busca and g.db_status:
        search_term_clean = id_cliente_busca 
        cliente = None
        
        search_term_clean_id = search_term_clean
        if search_term_clean.upper().startswith('CLI'):
            search_term_clean_id = search_term_clean[3:].strip() 
        
        if search_term_clean_id.isdigit():
            cliente_id_int = int(search_term_clean_id)
            cliente = db.clientes.find_one({'id_cliente': cliente_id_int})
            
        if not cliente and search_term_clean:
            regex_query = re.compile(re.escape(search_term_clean), re.IGNORECASE)
            query_filter = {
                '$or': [
                    {'nome_cliente': {'$regex': regex_query}},
                    {'nick': {'$regex': regex_query}}
                ]
            }
            cliente = db.clientes.find_one(query_filter)

        if cliente:
            cliente_encontrado = cliente
            id_cliente_final = cliente.get('id_cliente')

            # --- NOVO: Prepara o saldo para exibição ---
            val_decimal = cliente_encontrado.get('saldo_atual', 0.0)
            # Usa safe_float ou converte direto se safe_float não estiver no escopo local
            if isinstance(val_decimal, Decimal128):
                cliente_encontrado['saldo_float'] = float(str(val_decimal))
            else:
                cliente_encontrado['saldo_float'] = float(val_decimal)
            # -------------------------------------------
            
            valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
            custo = valor_unitario * quantidade
        
    elif selected_event:
        valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
        custo = valor_unitario * quantidade
        
    return render_template('venda.html', 
                           db_status=g.db_status,
                           error=error,
                           success=success,
                           eventos=eventos_enriquecidos,
                           selected_event=selected_event,
                           id_cliente_final=id_cliente_final,
                           cliente_busca=id_cliente_busca,
                           cliente_encontrado=cliente_encontrado,
                           quantidade=quantidade,
                           custo=custo,
                           g=g)


@app.route('/processar_venda', methods=['POST'])
@login_required
def processar_venda():
    """
    Processo Crítico de Venda - ATUALIZADO para incluir todos os períodos
    do cliente no comprovante e no link final.
    INCLUI TRAVA DE SEGURANÇA DE STATUS DO EVENTO.
    """
    db = get_vendas_db()
    if db is None: 
        return redirect(url_for('nova_venda', error="DB Offline. Transação Crítica Falhou."))

    id_evento_string = request.form.get('id_evento') 
    id_cliente_final_str = request.form.get('id_cliente_final') 
    quantidade_str = request.form.get('quantidade', '0')
    
    log_prefix = f"[VENDA REQ_COLAB:{session.get('nick', 'N/A')}_CLI:{id_cliente_final_str}_QTD:{quantidade_str}]"
    
    error_redirect_kwargs = {
        'id_evento': id_evento_string,
        'id_cliente_busca': f"CLI{id_cliente_final_str}" if id_cliente_final_str else '',
    }

    try:
        id_cliente_final = int(id_cliente_final_str)
        quantidade = int(quantidade_str)
        if quantidade <= 0: raise ValueError("Quantidade deve ser positiva")
    except (TypeError, ValueError) as e:
        error_redirect_kwargs['error'] = f"Dados inválidos: {e}"
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    id_evento_mongo = try_object_id(id_evento_string)
    if not id_evento_mongo:
        return redirect(url_for('nova_venda', error="Dados inválidos: Evento não selecionado."))
    
    selected_event = db.eventos.find_one({'_id': id_evento_mongo})
    cliente_doc = db.clientes.find_one({"id_cliente": id_cliente_final})
    
    if not selected_event or not cliente_doc:
        error_redirect_kwargs['error'] = "Evento ou Cliente não encontrado no sistema."
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    # --- [CRÍTICO] VERIFICAÇÃO DE STATUS DO EVENTO ---
    status_atual = selected_event.get('status', '').lower()
    if status_atual != 'ativo':
        error_redirect_kwargs['error'] = (
            f"⛔ VENDA CANCELADA! O evento não está mais Ativo. "
            f"Status atual: '{status_atual.upper()}'. "
            f"Por favor, selecione outro evento."
        )
        return redirect(url_for('nova_venda', **error_redirect_kwargs))
    # --------------------------------------------------
        
    id_evento_int_para_controle = selected_event.get('id_evento') 
    limite_maximo_cartelas = int(selected_event.get('numero_maximo', 72000))
    if not isinstance(id_evento_int_para_controle, int):
        error_redirect_kwargs['error'] = "Erro: ID sequencial do evento (int) não encontrado."
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
    unidade_de_venda = int(selected_event.get('unidade_de_venda', 1))

    valor_total_atual = valor_unitario * quantidade
    quantidade_cartelas_atual = quantidade * unidade_de_venda
    colaborador_id = session.get('id_colaborador', 'N/A')
    nick_colaborador = session.get('nick', 'Colaborador') 
    nome_colecao_venda = f"vendas{str(id_evento_int_para_controle).strip()}"

    # --- Busca Chave PIX do Colaborador para o Comprovante ---
    chave_pix_colaborador = "Consulte o Colaborador"
    try:
        if colaborador_id != 'N/A':
            colab_doc_pix = db.colaboradores.find_one({'id_colaborador': int(colaborador_id)})
            if colab_doc_pix and colab_doc_pix.get('chave_pix'):
                chave_pix_colaborador = colab_doc_pix.get('chave_pix')
    except Exception as e:
        print(f"Erro ao buscar PIX do colaborador: {e}")

    id_venda_formatado = None
    numero_inicial_atual = None
    numero_final_atual = None
    numero_inicial2_atual = 0 
    numero_final2_atual = 0 
    
    print(f"{log_prefix} LOG 2: Tentando adquirir 'venda_lock' (timeout=8s)...")
    
    if venda_lock.acquire(timeout=8): 
        print(f"{log_prefix} LOG 3: 'venda_lock' ADQUIRIDO.")
        try:
            print(f"{log_prefix} LOG 3A: Gerando ID da Venda...")
            novo_id_venda_int = get_next_global_sequence(db, 'id_vendas_global')
            if novo_id_venda_int is None:
                raise Exception("Falha ao gerar o ID sequencial da venda.")
            id_venda_formatado = f"V{novo_id_venda_int:05d}" 

            print(f"{log_prefix} LOG 3B: Gerando IDs de Bilhetes...")
            numero_inicial_evento = int(selected_event.get('numero_inicial', 1))
            numero_inicial_atual = get_next_bilhete_sequence(db, 
                                                       id_evento_int_para_controle, 
                                                       'inicial_proxima_venda', 
                                                       quantidade_cartelas_atual,
                                                       limite_maximo_cartelas)
            if numero_inicial_atual is None:
                raise Exception("Falha ao obter o número inicial do bilhete/cartela.")

            if numero_inicial_atual == 1: 
                numero_inicial_atual = numero_inicial_evento
                db.controle_venda.update_one(
                    {'id_evento': id_evento_int_para_controle},
                    {'$set': {'inicial_proxima_venda': numero_inicial_atual + quantidade_cartelas_atual}}
                )

            numero_final_atual = numero_inicial_atual + quantidade_cartelas_atual - 1
            
            if numero_final_atual > limite_maximo_cartelas:
                numero_inicial2_atual = 1
                numero_final2_atual = numero_final_atual - limite_maximo_cartelas
                numero_final_atual = limite_maximo_cartelas
            
            print(f"{log_prefix} ... IDs Bilhete gerados: {numero_inicial_atual}-{numero_final_atual}...")

            registro_venda = {
                "id_venda": id_venda_formatado,
                "id_evento_ObjectId": id_evento_mongo, 
                "id_evento": id_evento_int_para_controle, 
                "descricao_evento": selected_event.get('descricao'),
                "id_cliente": id_cliente_final, 
                "nome_cliente": cliente_doc.get('nick'),
                "telefone_cliente": cliente_doc.get('telefone',''),
                "id_colaborador": colaborador_id,
                "nick_colaborador": nick_colaborador,
                "data_venda": hora_brasil() ,     #  << data correta
                "quantidade_unidades": quantidade,
                "quantidade_cartelas": quantidade_cartelas_atual,
                "numero_inicial": numero_inicial_atual,
                "numero_final": numero_final_atual,
                "numero_inicial2": numero_inicial2_atual,
                "numero_final2": numero_final2_atual,
                "valor_unitario": Decimal128(str(valor_unitario)), 
                "valor_total": Decimal128(str(valor_total_atual)),
                "origem": "terminal_colaborador"
            }
            
            print(f"{log_prefix} LOG 3C: Atualizando cliente {id_cliente_final}...")
            db.clientes.update_one(
                {"id_cliente": id_cliente_final}, 
                {"$set": {"data_ultimo_compra": hora_brasil()}}
            )

            print(f"{log_prefix} LOG 3D: Inserindo venda na coleção '{nome_colecao_venda}'...")
            db[nome_colecao_venda].insert_one(registro_venda)
            print(f"{log_prefix} ... Venda inserida.")
 
            # --- ATUALIZAÇÃO DO BUFFER PARA O ROBÔ DE PRÊMIOS ---
            # Adiciona o valor desta venda ao acumulador invisível do evento
            db.eventos.update_one(
                {"id_evento": id_evento_int_para_controle},
                {"$inc": {"valor_pendente_telemovel": float(valor_total_atual)}}
            )
            # ----------------------------------------------------
           
            # Gravar da movimentação do cliente.
            saldo_verificacao = 0.0

            if cliente_doc: 
                saldo_verificacao = safe_float(cliente_doc.get('saldo_atual', 0.0))
            
            #if saldo_verificacao > 0:
            valor_debito = -abs(valor_total_atual) 
            desc_transacao = f"Compra de {quantidade} kit(s) - {selected_event.get('descricao')}"

            registrar_transacao_cliente(
                db=db,
                id_cliente=id_cliente_final,
                valor=valor_debito,
                tipo='compra',
                descricao=desc_transacao,
                id_evento=id_evento_int_para_controle,
                id_venda=id_venda_formatado
            )
            
        except Exception as e:
            venda_lock.release()
            print(f"{log_prefix} LOG 5 (ERRO INTERNO): Erro crítico durante a transação: {e}")
            error_redirect_kwargs['error'] = f"Erro interno no DB: Falha ao gravar a transação."
            error_redirect_kwargs['quantidade'] = quantidade
            return redirect(url_for('nova_venda', **error_redirect_kwargs))
            
        finally:
            if venda_lock.locked():
                 print(f"{log_prefix} LOG FIM (LOCK): Liberando 'venda_lock'.")
                 venda_lock.release()
            
    else:
        print(f"{log_prefix} LOG 6 (TIMEOUT): 'venda_lock' não adquirido após 8s. (Sistema ocupado)")
        error_redirect_kwargs['error'] = "Sistema muito ocupado. Por favor, tente novamente em alguns segundos."
        error_redirect_kwargs['quantidade'] = quantidade
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    # --- FIM DO BLOCO DE LOCK ---

    print(f"{log_prefix} LOG 4: Venda gravada. Montando comprovante completo...")
    
    try:
        vendas_cliente_cursor = db[nome_colecao_venda].find(
            {'id_cliente': id_cliente_final}
        ).sort('data_venda', pymongo.ASCENDING) 
        
        lista_periodos_antigos_html = []
        periodo_atual_html = ""
        link_periodos_completos = "" 
        
        total_unidades_cliente = 0
        total_cartelas_cliente = 0
        total_valor_cliente = 0.0

        for venda in vendas_cliente_cursor:
            total_unidades_cliente += venda['quantidade_unidades']
            total_cartelas_cliente += venda['quantidade_cartelas']
            total_valor_cliente += safe_float(venda['valor_total'])
            
            link_periodos_completos += f"&periodo={venda['numero_inicial']},{venda['numero_final']}"
            if venda.get('numero_inicial2', 0) > 0:
                link_periodos_completos += f"&periodo={venda['numero_inicial2']},{venda['numero_final2']}"
            
            periodo_str = f" > {venda['numero_inicial']} a {venda['numero_final']}<br>"
            if venda.get('numero_inicial2', 0) > 0:
                periodo_str += f" > {venda['numero_inicial2']} a {venda['numero_final2']}<br>"

            if venda['id_venda'] == id_venda_formatado:
                periodo_atual_html = (
                    f"<strong> > PERÍODO ATUAL (Qtd: {quantidade}) <strong><br>"
                    f"<span style='font-size: 1.4rem; color: #0047AB;'><strong>{periodo_str}</strong></span>"
                )
            else:
                lista_periodos_antigos_html.append(
                    f"<span style='font-size: 0.9rem; color: #555;'>{periodo_str}</span>"
                )

        periodos_anteriores_html = "".join(lista_periodos_antigos_html)

        tipo_de_cartela = int(selected_event.get('tipo_de_cartela', 25))
        nome_sala = g.parametros_globais.get('nome_sala', '')
        data_evento_str = selected_event.get('data_evento', 'N/A')
        hora_evento_str = selected_event.get('hora_evento', 'N/A')
        data_evento_formatada = data_evento_str.replace('/', '-') if data_evento_str else 'N/A'

        http_apk = g.parametros_globais.get('http_apk', '')

        link_final_limpo = f"{http_apk}?idcliente={id_cliente_final}"
        
        success_msg = (
            f"<strong>✅COMPROVANTE DE COMPRA</strong><br>"
            f"  <span style='font-size: 1.2rem; color: #B91C1C;'>{nome_sala}</span><br>"
            f"</strong>     >  {id_venda_formatado}  < </strong><br>"
            f"----------------------------<br>"
            f"Cliente: <strong>{cliente_doc.get('nick')}</strong><br>"
            f"Evento: {selected_event.get('descricao')}<br>"
            f"<strong>Data: {data_evento_formatada} às {hora_evento_str}</strong><br>"
            f"Colaborador:{colaborador_id}-{nick_colaborador}<br>"
            f"----------------------------<br>"
            f"<strong> > Períodos Anteriores <</strong><br>"
            f"{periodos_anteriores_html}"
            f"----------------------------<br>"
            f"{periodo_atual_html}"
            f"----------------------------<br>"
            f"Total Unidades: <strong>{total_unidades_cliente}</strong><br>"
            f"Total Cartelas: <strong>{total_cartelas_cliente}</strong><br>"
            f"  VALOR TOTAL: <span style='font-size: 1.2rem; color: #B91C1C;'>R$ {total_valor_cliente:.2f}</span><br>"
            f"<br>"
            f"   🔑   CHAVE PIX   💸<br>"
            f"   <strong>{chave_pix_colaborador}</strong><br>"
            f"<br>"
            f"CLIQUE NO <strong>LINK</strong> ABAIXO PARA<br>"
            f"    ACESSAR SUAS CARTELAS 📱<br>"
            f"<br>"
            f"<strong> {link_final_limpo} </strong>"
        )
        
        print(f"{log_prefix} LOG 5: Comprovante completo gerado.")
        
        session['success_message'] = success_msg 
        redirect_kwargs = {
            'id_evento': id_evento_string,
            'quantidade': '',
            'id_cliente_busca':  '' # f"CLI{id_cliente_final}"
        }
        return redirect(url_for('nova_venda', **redirect_kwargs))

    except Exception as e:
        print(f"{log_prefix} LOG 7 (ERRO PÓS-VENDA): Erro ao montar comprovante: {e}")
        session['success_message'] = (
            f"<strong>VENDA {id_venda_formatado} GRAVADA!</strong><br>"
            f"Ocorreu um erro ao gerar o comprovante completo, mas a venda foi registrada."
        )
        return redirect(url_for('nova_venda', id_evento=id_evento_string))



# --- ROTAS DE CADASTRO DE CLIENTE ---
# No seu arquivo app.py

@app.route('/buscar_clientes_json', methods=['GET'])
@login_required
def buscar_clientes_json():
    db = get_vendas_db()
    if db is None: return jsonify({'error': 'DB Offline'}), 500
    
    termo = request.args.get('termo', '').strip()
    tipo = request.args.get('tipo', 'nick')
    
    if not termo or len(termo) < 2:
        return jsonify([])

    query = {}
    if tipo == 'id':
        if termo.isdigit():
            query['id_cliente'] = int(termo)
        else:
            return jsonify([])
    elif tipo == 'nome':
        # Adicionado o ^ para buscar apenas o início
        query['nome_cliente'] = {'$regex': f'^{re.escape(termo)}', '$options': 'i'}
    elif tipo == 'nick':
        # Adicionado o ^ para buscar apenas o início
        query['nick'] = {'$regex': f'^{re.escape(termo)}', '$options': 'i'}
        
    try:
        clientes = list(db.clientes.find(query, {'_id': 0, 'id_cliente': 1, 'nome_cliente': 1, 'nick': 1, 'cidade': 1}).limit(20))
        return jsonify(clientes)
    except Exception as e:
        print(f"Erro na busca dinâmica json: {e}")
        return jsonify([]), 500


# Consulta de Cliente
# No seu arquivo app.py

@app.route('/buscar_clientes', methods=['GET'])
@login_required
def buscar_clientes():
    """
    Rota API para busca dinâmica de clientes.
    AJUSTADA PARA BUSCAR APENAS O INÍCIO DA PALAVRA (STARTSWITH)
    """
    db = get_vendas_db()
    if db is None: 
        return jsonify({'clientes': [], 'error': 'DB Offline'})

    termo = request.args.get('termo', '').strip()
    tipo_busca = request.args.get('tipo', 'nick') # nick, nome, id
    
    if not termo or len(termo) < 2: 
         return jsonify({'clientes': []})

    query_filter = {}
    
    try:
        if tipo_busca == 'id':
            # ID continua sendo busca exata ou contém digitos
            clean_id = re.sub(r'\D', '', termo)
            if clean_id.isdigit():
                query_filter = {'id_cliente': int(clean_id)}
            else:
                return jsonify({'clientes': []})
                
        elif tipo_busca == 'nome':
            # --- MUDANÇA AQUI: Adicionado o '^' antes do termo ---
            # O '^' diz ao Banco: "Busque apenas se COMEÇAR com isso"
            regex_term = re.compile(f"^{re.escape(termo)}", re.IGNORECASE)
            query_filter = {'nome_cliente': {'$regex': regex_term}}
            
        else: # Padrão: 'nick'
            # --- MUDANÇA AQUI TAMBÉM ---
            regex_term = re.compile(f"^{re.escape(termo)}", re.IGNORECASE)
            query_filter = {'nick': {'$regex': regex_term}}
            
        clientes_cursor = db.clientes.find(
            query_filter, 
            {'id_cliente': 1, 'nome_cliente': 1, 'nick': 1, 'cidade': 1}
        ).limit(10) # Mantém o limite para ser rápido
        
        resultados = []
        for cli in clientes_cursor:
            resultados.append({
                'id': cli.get('id_cliente'),
                'nome': cli.get('nome_cliente'),
                'nick': cli.get('nick'),
                'cidade': cli.get('cidade', 'N/A')
            })
            
        return jsonify({'clientes': resultados})

    except Exception as e:
        print(f"Erro na busca dinâmica: {e}")
        return jsonify({'clientes': [], 'error': str(e)})


@app.route('/cadastro_cliente', methods=['GET'])
@login_required
def cadastro_cliente():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    db_status = g.db_status

    nivel_usuario = session.get('nivel', 1)
    nome_logado = session.get('nick', 'Colaborador') 
    id_logado = session.get('id_colaborador', 'N/A')
    
    form_data_erro = session.pop('form_data', None)
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    next_url = request.args.get('next', 'menu_operacoes')
    id_evento_retorno = request.args.get('id_evento') 
    id_cliente_edicao = request.args.get('id_cliente', None)
    
    clientes_lista = []
    total_clientes = 0
    cliente_edicao = None 
    
    error = request.args.get('error')
    success = request.args.get('success')

    if form_data_erro:
        cliente_edicao = form_data_erro
        if 'id_cliente_edicao' in form_data_erro and form_data_erro['id_cliente_edicao']:
             active_view = 'alterar'
             id_cliente_edicao = form_data_erro['id_cliente_edicao']
        else:
             active_view = 'novo'
            
    elif active_view == 'alterar' and id_cliente_edicao and db_status:
        try:
            id_cliente_int = int(id_cliente_edicao)
            cliente_edicao = db.clientes.find_one({'id_cliente': id_cliente_int})
            
            if cliente_edicao:
                if '_id' in cliente_edicao: cliente_edicao['_id'] = str(cliente_edicao['_id'])
            else:
                 error = f"Cliente ID {id_cliente_int} não encontrado para edição."
                 active_view = 'listar' 
                 
        except (ValueError, TypeError):
            error = "ID de Cliente inválido para edição."
            active_view = 'listar'
            
    if db_status:
        try:
            total_clientes = db.clientes.count_documents({})
            
            if active_view == 'listar':
               clientes_cursor = db.clientes.find({}).sort("nick", pymongo.ASCENDING)
               clientes_lista = list(clientes_cursor)
            elif active_view == 'consulta' and search_term:
                query_filter = {}
                
                if search_term.isdigit(): 
                    query_filter = {'id_cliente': int(search_term)}
                
                if not query_filter:
                    regex_term = re.compile(re.escape(search_term), re.IGNORECASE)
                    query_filter = {
                        '$or': [
                            {'nome_cliente': {'$regex': regex_term}},
                            {'nick': {'$regex': regex_term}}
                        ]
                    }
                    
                clientes_cursor = db.clientes.find(query_filter)
                clientes_lista = list(clientes_cursor) 

        except Exception as e:
            print(f"Erro ao buscar dados no MongoDB em cadastro_cliente: {e}")
            error = f"Erro crítico ao carregar dados do DB: {e}"

    for cliente in clientes_lista:
        if '_id' in cliente: cliente['_id'] = str(cliente['_id'])

        val_decimal = cliente.get('saldo_atual', 0.0)
        cliente['saldo_float'] = safe_float(val_decimal)

        for campo_data in ['data_cadastro', 'data_ultimo_compra']:
            if cliente.get(campo_data) and isinstance(cliente[campo_data], datetime):
                cliente[f'{campo_data}_formatada'] = cliente[campo_data].strftime("%d/%m/%Y %H:%M:%S")

    # 1. INSIRA A LÓGICA DE BUSCA AQUI (Antes do context)
    lista_bloqueio = []
    if active_view == 'bloqueio' and db_status:
        try:
            config = db.config_bloqueio.find_one({'tipo': 'nicks_proibidos'})
            if config and 'palavras' in config:
                lista_bloqueio = sorted(config['palavras'])
        except Exception as e:
            print(f"Erro ao carregar bloqueios: {e}")

    context = {
        'total_clientes': total_clientes,
        'clientes_lista': clientes_lista,
        'active_view': active_view,
        'query': search_term, 
        'cliente_edicao': cliente_edicao,
        'next_url': next_url, 
        'id_evento_retorno': id_evento_retorno,
        'error': error,
        'success': success,
        'g': g,
        'nivel': nivel_usuario,
        'id_logado': id_logado,  
        'logado': nome_logado,
        'lista_bloqueio': lista_bloqueio
    }
    
    return render_template('cadastro_cliente.html', **context)


@app.route('/gravar_cliente', methods=['POST'])
@login_required
def gravar_cliente():
    db = get_vendas_db()
    if db is None:
        return redirect(url_for('menu_operacoes', error="Erro DB."))

    # Captura e Logs Iniciais
    id_cliente_raw = request.form.get('id_cliente')
    next_page = request.form.get('next', 'menu_operacoes')
    view_mode = 'novo' if not id_cliente_raw else 'alterar'
    
    print(f"\n[DEBUG] --- INICIANDO GRAVAR CLIENTE ---")

    try:
        # 1. Coleta de Dados
        default_config = {
            "nome_cliente": True, "nick": True, "telefone": True,
            "cpf": False, "cidade": True, "chave_pix": True, "senha": True
        }
        campos_config = getattr(g, 'parametros_globais', {}).get('tipo_cadastro_cliente', default_config)

        nome_cliente = format_title_case(request.form.get('nome_cliente'))
        nick = format_title_case(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip().lower()
        observacao = request.form.get('observacao', '')
        senha = request.form.get('senha', '')
        confirma_senha = request.form.get('confirma_senha', '')

        # 2. Validações Básicas
        if campos_config.get("nome_cliente") and not nome_cliente:
            raise ValueError("O campo Nome Completo é obrigatório.")
        if campos_config.get("telefone") and not telefone:
            raise ValueError("O campo WhatsApp/Telefone é obrigatório.")

        # CPF
        cpf_limpo = clean_numeric_string(cpf_raw)
        if campos_config.get("cpf") == True: 
            if not cpf_raw or not validate_cpf(cpf_limpo): raise ValueError("CPF inválido.")
        elif cpf_raw and not validate_cpf(cpf_limpo): raise ValueError("CPF inválido.")

        # 3. Validação de Duplicidade (Telefone e Nick)
        cliente_tel = db.clientes.find_one({'telefone': telefone})
        if cliente_tel and str(cliente_tel.get('id_cliente')) != str(id_cliente_raw or ''):
            raise ValueError(f"Telefone {telefone} já pertence ao cliente ID: {cliente_tel.get('id_cliente')} - {cliente_tel.get('nick')}.")

        if campos_config.get("nick") and nick:
            cliente_nick = db.clientes.find_one({'nick': {'$regex': f'^{re.escape(nick)}$', '$options': 'i'}})
            if cliente_nick and str(cliente_nick.get('id_cliente')) != str(id_cliente_raw or ''):
                raise ValueError(f"O Nick '{nick}' já está em uso.")

        # --- NOVA LÓGICA DE SENHA (CORREÇÃO) ---
        hashed_password = None
        
        if not id_cliente_raw:  # NOVO CADASTRO
            # Se não digitou senha, define o padrão "senha"
            senha_final = senha if senha else "Senha"
            
            # Se ele digitou algo, validamos a confirmação
            if senha and senha != confirma_senha:
                raise ValueError("As senhas não conferem.")
                
            # Criptografa a senha (seja a digitada ou a padrão "senha")
            hashed_password = bcrypt.hashpw(senha_final.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            print(f"[DEBUG] Definindo senha para novo cliente: {'Padrão' if not senha else 'Manual'}")
            
        else:  # EDIÇÃO
            # Na edição, só processamos se o campo de senha não estiver vazio
            if senha:
                if senha != confirma_senha:
                    raise ValueError("As senhas não conferem.")
                hashed_password = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                print("[DEBUG] Atualizando senha do cliente (Manual)")

        # 4. Montagem do dicionário de dados
        dados_cliente = {
            "nome_cliente": nome_cliente,
            "nick": nick,
            "telefone": telefone,
            "cpf": cpf_limpo,
            "cidade": cidade,
            "chave_pix": chave_pix,
            "observacao": observacao,
            "data_atualizacao": hora_brasil()
        }
        
        # Só adicionamos a chave "senha" ao dicionário se ela foi gerada
        if hashed_password:
            dados_cliente["senha"] = hashed_password

        # 5. Gravação no Banco
        if id_cliente_raw:
            # Edição
            print(f"[DEBUG] Atualizando ID {id_cliente_raw}")
            db.clientes.update_one({'id_cliente': int(id_cliente_raw)}, {'$set': dados_cliente})
            success_msg = f"Cliente {nick} atualizado com sucesso!"
        else:
            # Novo
            print(f"[DEBUG] Criando Novo Cliente")
            novo_id = get_next_cliente_sequence()
            if not novo_id: raise Exception("Erro Sequence ID.")
            
            dados_cliente.update({
                "id_cliente": novo_id,
                "id_colaborador": session.get('id_colaborador'),
                "data_cadastro": hora_brasil(),
                "origem": "interno",
                "saldo_atual": Decimal128("0.00") # Inicializa saldo
            })
            
            db.clientes.insert_one(dados_cliente)
            success_msg = f"Cliente {nick} cadastrado! ID: CLI{novo_id}"

        print(f"[DEBUG] Sucesso! Redirecionando...\n")
        return redirect(url_for('cadastro_cliente', view='listar', success=success_msg))

    except ValueError as ve:
        print(f"[DEBUG] ERRO DE VALIDAÇÃO: {ve}")
        cliente_form = {
            'id_cliente': id_cliente_raw, 'nome_cliente': nome_cliente, 'nick': nick,
            'telefone': telefone, 'cpf': cpf_raw, 'cidade': cidade,
            'chave_pix': request.form.get('chave_pix'), 'observacao': observacao
        }
        return render_template('cadastro_cliente.html', 
                               error=str(ve),
                               cliente_edicao=cliente_form, 
                               view=view_mode,
                               active_view=view_mode,
                               nivel=session.get('nivel', 1),
                               colaborador={'nick': session.get('nick'), 'nivel': session.get('nivel', 1)},
                               g=g)

    except Exception as e:
        print(f"[DEBUG] ERRO CRÍTICO: {e}")
        import traceback
        traceback.print_exc()
        return render_template('cadastro_cliente.html', 
                               error=f"Erro interno: {e}",
                               view=view_mode,
                               active_view=view_mode,
                               nivel=session.get('nivel', 1),
                               colaborador={'nick': session.get('nick'), 'nivel': session.get('nivel', 1)},
                               g=g)


@app.route('/cliente/excluir/<int:id_cliente>', methods=['POST'])
@login_required
def excluir_cliente(id_cliente):
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    try:
        result = db.clientes.delete_one({'id_cliente': id_cliente})
        
        if result.deleted_count == 1:
            success_msg = f"Cliente ID: CLI{id_cliente} excluído com sucesso."
        else:
            success_msg = f"Cliente ID: CLI{id_cliente} não encontrado para exclusão."

        return redirect(url_for('cadastro_cliente', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO CRÍTICO na exclusão de cliente ID {id_cliente}: {e}")
        return redirect(url_for('cadastro_cliente', error=f"Erro interno ao excluir cliente.", view='listar'))


# --- ROTAS DE GERENCIAMENTO DE BLOQUEIO (NICKS) ---

@app.route('/adicionar_bloqueio', methods=['POST'])
@login_required
def adicionar_bloqueio():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('cadastro_cliente', view='bloqueio', error="Acesso Negado."))

    termo = request.form.get('termo', '').strip().lower()
    
    if not termo:
        return redirect(url_for('cadastro_cliente', view='bloqueio', error="Digite uma palavra."))

    try:
        # 1. VERIFICA SE JÁ EXISTE (Sua solicitação)
        existe = db.config_bloqueio.find_one({
            'tipo': 'nicks_proibidos', 
            'palavras': termo 
        })
        
        if existe:
            return redirect(url_for('cadastro_cliente', view='bloqueio', error=f"O termo '{termo}' já está na lista de bloqueio."))

        # 2. SE NÃO EXISTE, ADICIONA
        db.config_bloqueio.update_one(
            {'tipo': 'nicks_proibidos'},
            {'$push': {'palavras': termo}}, # $push adiciona ao final
            upsert=True # Cria o documento se não existir
        )
        
        return redirect(url_for('cadastro_cliente', view='bloqueio', success=f"Termo '{termo}' bloqueado com sucesso."))

    except Exception as e:
        return redirect(url_for('cadastro_cliente', view='bloqueio', error=f"Erro interno: {e}"))


@app.route('/remover_bloqueio', methods=['POST'])
@login_required
def remover_bloqueio():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('cadastro_cliente', view='bloqueio', error="Acesso Negado."))

    termo = request.form.get('termo')
    
    try:
        # Usa $pull para remover a palavra da lista
        db.config_bloqueio.update_one(
            {'tipo': 'nicks_proibidos'},
            {'$pull': {'palavras': termo}}
        )
        return redirect(url_for('cadastro_cliente', view='bloqueio', success=f"Termo '{termo}' liberado."))
    except Exception as e:
        return redirect(url_for('cadastro_cliente', view='bloqueio', error=f"Erro: {e}"))


# --- ROTAS DE AUTO CADASTRO (PÚBLICAS) ---
# Cole este bloco no final do seu app.py para registrar as rotas
@app.route('/cadastre-se', methods=['GET'])
def auto_cadastro_page():
    """
    Exibe a tela pública de cadastro para o cliente.
    Recebe id_sala e ref (colaborador) da URL.
    """
    id_sala = request.args.get('id_sala')
    ref_colaborador = request.args.get('ref', '')
    
    # Se g.db_status estiver False, conexão falhou
    if not g.db_status:
        return render_template('auto_cadastro.html', 
                             error="Sistema temporariamente indisponível (DB).",
                             id_sala=id_sala,
                             ref_colaborador=ref_colaborador)

    return render_template('auto_cadastro.html', 
                           id_sala=id_sala, 
                           ref_colaborador=ref_colaborador)


@app.route('/salvar_auto_cadastro', methods=['POST'])
def salvar_auto_cadastro():
    """
    Processa o formulário de auto cadastro.
    """
    # Garante que o ID da sala esteja disponível para a conexão com o banco
    id_sala = request.form.get('id_sala') or request.args.get('id_sala')
    g.id_sala = id_sala
    
    db = get_vendas_db()
    ref_colaborador = request.form.get('ref_colaborador', 'N/A')

    if db is None:
        return render_template('auto_cadastro.html', 
                               error="Erro de conexão ao tentar salvar (DB Offline). Tente novamente.",
                               id_sala=id_sala,
                               ref_colaborador=ref_colaborador)

    try:
        # 1. Configurações
        default_config = {
            "nome_cliente": True, "nick": True, "telefone": True,
            "cpf": False, "cidade": True, "chave_pix": True, "senha": True
        }
        # Tenta pegar config do g, se falhar usa default
        campos_config = getattr(g, 'parametros_globais', {}).get('tipo_cadastro_cliente', default_config)

        # 2. Coleta de Dados (com tratamento seguro para None)
        nome_cliente = format_title_case(request.form.get('nome_cliente'))
        nick = format_title_case(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip()
        confirma_chave_pix = request.form.get('confirma_chave_pix', '').strip()
        
        # Correção: Garante que senha seja string vazia se for None, para evitar erro no if
        senha = request.form.get('senha', '') 
        confirma_senha = request.form.get('confirma_senha', '')

        # 3. Validações
        if campos_config.get("nome_cliente") and not nome_cliente:
            raise ValueError("O campo Nome Completo é obrigatório.")
        if campos_config.get("nick") and not nick:
            raise ValueError("O campo Nick/Apelido é obrigatório.")
        if campos_config.get("telefone") and not telefone:
            raise ValueError("O campo WhatsApp/Telefone é obrigatório.")
        if campos_config.get("cidade") and not cidade:
            raise ValueError("O campo Cidade é obrigatório.")
        
        if campos_config.get("chave_pix"):
            if not chave_pix:
                raise ValueError("O campo Chave PIX é obrigatório.")
            if chave_pix != confirma_chave_pix:
                raise ValueError("As chaves PIX não conferem.")
            
        if not senha:
            raise ValueError("A Senha é obrigatória.")
        if senha != confirma_senha:
             raise ValueError("As senhas não conferem.")

        cpf_limpo = clean_numeric_string(cpf_raw)
        if campos_config.get("cpf") == True:
            if not cpf_raw or not validate_cpf(cpf_limpo):
                raise ValueError("CPF é obrigatório e deve ser válido.")
        elif "cpf" in campos_config and cpf_raw and not validate_cpf(cpf_limpo):
            raise ValueError("O CPF inserido não é válido.")

        # 4. Verificação de Duplicidade
        if campos_config.get("nick") and nick:
            if db.clientes.find_one({'nick': {'$regex': f'^{re.escape(nick)}$', '$options': 'i'}}):
                raise ValueError(f"O Nick '{nick}' já está em uso. Escolha outro.")
        
        if cpf_limpo and db.clientes.find_one({'cpf': cpf_limpo}):
             raise ValueError("CPF já cadastrado.")

        # 5. Tratamento ID Colaborador
        id_colab_val = 'AUTO'
        if ref_colaborador and ref_colaborador != 'N/A':
            try:
                id_colab_val = int(ref_colaborador)
            except:
                id_colab_val = ref_colaborador

        # 6. Geração de ID e Hash de Senha (CORREÇÃO CRÍTICA AQUI)
        novo_id = get_next_cliente_sequence()
        if not novo_id: 
            raise Exception("Falha interna ao gerar ID do cliente (Sequence Error).")

        hashed_password = None
        if senha:
            senha_formatada = senha.capitalize()
            hashed_password = bcrypt.hashpw(senha_formatada.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        dados_cliente = {
            "id_cliente": novo_id,
            "id_colaborador": id_colab_val,
            "data_cadastro": hora_brasil(),
            "data_ultimo_compra": None,
            "origem": "auto_cadastro"
        }
        
        if nome_cliente: dados_cliente["nome_cliente"] = nome_cliente
        if nick: dados_cliente["nick"] = nick
        if telefone: dados_cliente["telefone"] = telefone
        if cpf_limpo: dados_cliente["cpf"] = cpf_limpo
        if cidade: dados_cliente["cidade"] = cidade
        if chave_pix: dados_cliente["chave_pix"] = chave_pix
        if hashed_password: dados_cliente["senha"] = hashed_password

        db.clientes.insert_one(dados_cliente)

        success_msg = f"Cadastro realizado com sucesso! Seu ID é <strong>CLI{novo_id}</strong>.<br>Clique no botão abaixo para fazer login."
        return render_template('auto_cadastro.html', success=success_msg, id_sala=id_sala)

    except ValueError as e:
        return render_template('auto_cadastro.html', 
                               error=str(e),
                               id_sala=id_sala,
                               ref_colaborador=ref_colaborador)
    except Exception as e:
        # Log do erro no console para debug real
        print(f"ERRO CRÍTICO NO AUTO CADASTRO: {e}")
        import traceback
        traceback.print_exc() # Imprime onde foi o erro exatamente
        
        return render_template('auto_cadastro.html', 
                               error=f"Erro interno no servidor: {e}",
                               id_sala=id_sala,
                               ref_colaborador=ref_colaborador)


# --- ROTAS DE CADASTRO DE EVENTO (NOVO CRUD) ---


@app.route('/api/check_event_availability', methods=['GET'])
@login_required
def check_event_availability():
    db = get_vendas_db()
    if db is None: return jsonify({'error': 'DB Offline'}), 500

    data_input = request.args.get('data') # YYYY-MM-DD
    hora_input = request.args.get('hora') # HH:MM
    exclude_id = request.args.get('exclude_id') 

    if not data_input or not hora_input:
        return jsonify({'exists': False})

    try:
        dt_obj = datetime.strptime(data_input, '%Y-%m-%d')
        data_formatada = dt_obj.strftime('%d/%m/%Y')
        
        query = {
            'data_evento': data_formatada,
            'hora_evento': hora_input,
            'status': {'$ne': 'finalizado'} 
        }

        if exclude_id and exclude_id.isdigit():
            query['id_evento'] = {'$ne': int(exclude_id)}
        
        count = db.eventos.count_documents(query)
        
        if count > 0:
            return jsonify({
                'exists': True, 
                'msg': f'Já existe um evento em {data_formatada} às {hora_input}.'
            })
        
        return jsonify({'exists': False})

    except Exception as e:
        print(f"Erro check availability: {e}")
        return jsonify({'exists': False})


@app.route('/cadastro_evento', methods=['GET'])
@login_required
def cadastro_evento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) 
    db_status = g.db_status
    form_data_erro = session.pop('form_data', None)
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    id_evento_edicao = request.args.get('id_evento', None)
    evento_edicao, eventos_lista, total_eventos = None, [], 0
    error, success = request.args.get('error'), request.args.get('success')

    numeric_float_fields = ['valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_acumulado', 'minimo_de_venda', 'premio_total', 'premio_faltaum', 'premiacao_fixa']
    numeric_int_fields = ['unidade_de_venda', 'numero_inicial', 'numero_maximo', 'tipo_de_cartela', 'quantidade_de_linhas', 'bola_tope_acumulado']
    all_numeric_fields = numeric_float_fields + numeric_int_fields

    if form_data_erro:
        evento_edicao = form_data_erro
        if 'id_evento_edicao' in form_data_erro and form_data_erro['id_evento_edicao']: active_view, id_evento_edicao = 'alterar', form_data_erro['id_evento_edicao']
        else: active_view = 'novo'
        for key in numeric_float_fields:
             if key in evento_edicao: evento_edicao[key] = safe_float(evento_edicao.get(key, 0.0))
        for key in numeric_int_fields:
             if key in evento_edicao:
                  v = evento_edicao.get(key, 0)
                  try: evento_edicao[key] = int(float(str(v.to_decimal() if isinstance(v, Decimal128) else v)))
                  except: evento_edicao[key] = 0
             
    elif active_view == 'alterar' and id_evento_edicao and db_status:
        try:
            id_ev_int = int(id_evento_edicao)
            evento_edicao = db.eventos.find_one({'id_evento': id_ev_int})
            if evento_edicao:
                if '_id' in evento_edicao: evento_edicao['_id'] = str(evento_edicao['_id'])
                dev = evento_edicao.get('data_evento') 
                if dev and isinstance(dev, str):
                    try: evento_edicao['data_evento'] = datetime.strptime(dev, '%d/%m/%Y').strftime('%Y-%m-%d')
                    except: pass 
                for key in numeric_float_fields:
                    if key in evento_edicao: evento_edicao[key] = safe_float(evento_edicao.get(key, 0.0))
                for key in numeric_int_fields:
                    if key in evento_edicao:
                        v = evento_edicao.get(key, 0)
                        try: evento_edicao[key] = int(float(str(v.to_decimal() if isinstance(v, Decimal128) else v)))
                        except: evento_edicao[key] = 0
            else: error, active_view = f"Não encontrado.", 'listar'
        except: error, active_view = "ID inválido.", 'listar'
            
    if db_status:
        try:
            total_eventos = db.eventos.count_documents({})
            if active_view == 'listar': eventos_lista = list(db.eventos.find({}).sort([("data_evento", -1), ("hora_evento", -1)]))
            elif active_view == 'consulta' and search_term:
                query_filter = {'id_evento': int(search_term)} if search_term.isdigit() else {'$or': [{'descricao': {'$regex': re.compile(re.escape(search_term), re.IGNORECASE)}}, {'data_evento': {'$regex': re.compile(re.escape(search_term), re.IGNORECASE)}}]}
                eventos_lista = list(db.eventos.find(query_filter).sort("data_evento", -1))
        except Exception as e: error = f"Erro: {e}"

    cartela_limits, default_acumulado, default_tope = {'15': 72000, '25': 90000}, 0.0, 0
    param_doc_global = {}

    if db_status:
        try:
            param_doc_global = db.parametros.find_one({}) or {}
            if param_doc_global:
                if 'arquivo_cartela_15' in param_doc_global: cartela_limits['15'] = int(param_doc_global['arquivo_cartela_15'])
                if 'arquivo_cartela_25' in param_doc_global: cartela_limits['25'] = int(param_doc_global['arquivo_cartela_25'])
                if 'acumulado' in param_doc_global: default_acumulado = safe_float(param_doc_global['acumulado'])
                if 'tope' in param_doc_global: default_tope = int(param_doc_global['tope'])
        except: pass

    for evento in eventos_lista:
        if '_id' in evento: evento['_id'] = str(evento['_id'])
        id_ev = evento.get('id_evento')
        nome_cv = f"vendas{id_ev}"
        qtd = 0

        if nome_cv in db.list_collection_names():
            # 🔴 CORREÇÃO AQUI: Em vez de contar documentos (faturas), soma as unidades (Kits) vendidos.
            vendas_data_list = list(db[nome_cv].aggregate([
                {'$group': {'_id': None, 'total_unidades': {'$sum': '$quantidade_unidades'}}}
            ]))
            if vendas_data_list:
                qtd = vendas_data_list[0].get('total_unidades', 0)
                
        evento['qtd_vendas'] = qtd
        
        for key in all_numeric_fields:
            if key in evento: evento[key] = safe_float(evento.get(key, 0.0))
            
        # INJEÇÃO DO MOTOR MATEMÁTICO: Apenas para a listagem
        evento = calcular_premios_dinamicos(db, evento, param_doc_global)
        
        # Garante que o prêmio seja float para a formatação do template
        evento['premio_total_float'] = safe_float(evento.get('premio_total', 0.0))

    context = {
        'total_eventos': total_eventos,
        'eventos_lista': eventos_lista,
        'active_view': active_view,
        'query': search_term, 
        'evento_edicao': evento_edicao, 
        'error': error,
        'success': success,
        'g': g,
        'cartela_limits': cartela_limits,
        'default_acumulado': default_acumulado,
        'default_tope': default_tope
    }
    
    return render_template('cadastro_evento.html', **context)


@app.route('/gravar_evento', methods=['POST'])
@login_required
def gravar_evento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    id_evento_edicao = request.form.get('id_evento_edicao') 
    
    def clean_float_input(form_key, default_value='0'):
        """Trata a entrada do formulário, convertendo '' para default_value e trocando ',' por '.'"""
        value_raw = request.form.get(form_key, default_value)
        if not value_raw or value_raw.strip() == '':
            value_raw = str(default_value)
        return float(value_raw.replace(',', '.'))

    try:
        data_evento_str = request.form.get('data_evento')
        hora_evento = request.form.get('hora_evento')
        descricao = format_title_case(request.form.get('descricao'))
        unidade_de_venda = int(request.form.get('unidade_de_venda', 1))
        tipo_de_cartela = int(request.form.get('tipo_de_cartela', 15)) 
        tipo_de_evento = request.form.get('tipo_de_evento', 'Normal') 
        tipo_premiacao = request.form.get('tipo_premiacao', 'Fixa')

        # --- LÓGICA DE BLOQUEIO E PADRÕES BASEADOS NO TIPO DE CARTELA ---
        if tipo_de_cartela == 25:
            premio_faltaum = 0.0
            premio_segundobingo = 0.0
            quantidade_de_linhas = 1
            
            try:
                param_doc = db.parametros.find_one({})
                numero_maximo = int(param_doc.get('arquivo_cartela_25', 90000)) if param_doc else 90000
            except:
                numero_maximo = 90000
        else:
            premio_faltaum = clean_float_input('premio_faltaum')
            premio_segundobingo = clean_float_input('premio_segundobingo')
            quantidade_de_linhas = int(request.form.get('quantidade_de_linhas', 1))
            
            try:
                param_doc = db.parametros.find_one({})
                numero_maximo = int(param_doc.get('arquivo_cartela_15', 72000)) if param_doc else 72000
            except:
                numero_maximo = 72000
        
        # Captura dos demais valores financeiros
        valor_de_venda = clean_float_input('valor_de_venda')
        premio_quadra = clean_float_input('premio_quadra')
        premio_linha = clean_float_input('premio_linha')
        premio_bingo = clean_float_input('premio_bingo')
        premio_acumulado = clean_float_input('premio_acumulado')
        minimo_de_venda = clean_float_input('minimo_de_venda') 
        premiacao_fixa = clean_float_input('premiacao_fixa', default_value='-1.00')

        numero_inicial = int(request.form.get('numero_inicial', 1))
        bola_tope_acumulado = int(request.form.get('bola_tope_acumulado', 0)) 

        if not all([data_evento_str, hora_evento, descricao, unidade_de_venda]):
             raise ValueError("Preencha todos os campos obrigatórios (*).")

        try:
             data_obj = datetime.strptime(data_evento_str, '%Y-%m-%d')
             data_evento_str_gravar = data_obj.strftime('%d/%m/%Y')
        except ValueError:
             raise ValueError("Formato de data inválido.")
        
        data_hora_evento_dt = datetime.strptime(f"{data_evento_str} {hora_evento}", '%Y-%m-%d %H:%M')
        
        # Recalcula o prêmio total no servidor por segurança
        premio_total = premio_quadra + (premio_linha * quantidade_de_linhas) + premio_bingo + premio_segundobingo + premio_faltaum
        
        dados_evento = {
            "data_evento": data_evento_str_gravar, 
            "hora_evento": hora_evento, 
            "data_hora_evento": data_hora_evento_dt, 
            "descricao": descricao,
            "unidade_de_venda": unidade_de_venda,
            "tipo_de_cartela": tipo_de_cartela, 
            "tipo_de_evento": tipo_de_evento,
            "tipo_premiacao": tipo_premiacao,
            "valor_de_venda": Decimal128(str(valor_de_venda)),
            "numero_inicial": numero_inicial,
            "numero_maximo": numero_maximo,
            "premio_quadra": Decimal128(str(premio_quadra)),
            "quantidade_de_linhas": quantidade_de_linhas,
            "premio_linha": Decimal128(str(premio_linha)),
            "premio_bingo": Decimal128(str(premio_bingo)),
            "premio_faltaum": Decimal128(str(premio_faltaum)),
            "premio_segundobingo": Decimal128(str(premio_segundobingo)),
            "premiacao_fixa": Decimal128(str(premiacao_fixa)),
            "premio_total": Decimal128(str(premio_total)), 
            "premio_acumulado": Decimal128(str(premio_acumulado)),
            "bola_tope_acumulado": bola_tope_acumulado,
            "minimo_de_venda": int(minimo_de_venda),
            "id_colaborador": session.get('id_colaborador', 'N/A'),
        }
        
        if id_evento_edicao:
            db.eventos.update_one({'id_evento': int(id_evento_edicao)}, {'$set': dados_evento})
            success_msg = f"Evento ID: {id_evento_edicao} atualizado com sucesso!"
        else:
            novo_id = get_next_evento_sequence()
            dados_evento.update({
                "id_evento": novo_id, 
                "status": "ativo", 
                "data_ativado": None,
                "data_cadastro": hora_brasil()
            })
            db.eventos.insert_one(dados_evento)
            success_msg = f"Evento '{dados_evento['descricao']}' salvo com sucesso! ID: {novo_id}."
        
        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO na gravação de evento: {e}")
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_evento_edicao else 'novo'
        return redirect(url_for('cadastro_evento', error=f"Erro ao salvar: {e}", view=view_redirect, id_evento=id_evento_edicao))



@app.route('/excluir_evento/<int:id_evento>', methods=['POST'])
@login_required
def excluir_evento(id_evento):
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    try:
        # 1. Exclui o registro principal do Evento
        result = db.eventos.delete_one({'id_evento': id_evento})
        
        msg_extra = ""
        if result.deleted_count == 1:
            
            # 2. Remove as coleções dinâmicas inteiras (Vendas e Pagamentos)
            nome_colecao_venda = f"vendas{id_evento}"
            if nome_colecao_venda in db.list_collection_names():
                db[nome_colecao_venda].drop()
                msg_extra = " e todas as vendas e sorte extra associadas foram removidas."

            nome_colecao_cupons = f"vendas_sorte_extra{id_evento}"
            if nome_colecao_cupons in db.list_collection_names():
                db[nome_colecao_cupons].drop()
            
            nome_colecao_pgtos = f"pagamentos{id_evento}"
            if nome_colecao_pgtos in db.list_collection_names():
                db[nome_colecao_pgtos].drop()

            # 3. NOVO: Remove registros vinculados nas tabelas de apoio
            # Usamos delete_many por segurança, caso haja lixo duplicado, mas geralmente é 1 registro.
            db.resultados.delete_many({'id_evento': id_evento})
            db.controle_venda.delete_many({'id_evento': id_evento})
            
            # -----------------------------------------------------
            success_msg = f"Evento ID: {id_evento} excluído{msg_extra} com sucesso."
        else:
            success_msg = f"Evento ID: {id_evento} não encontrado para exclusão."

        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO CRÍTICO na exclusão de evento ID {id_evento}: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('cadastro_evento', error=f"Erro interno ao excluir evento.", view='listar'))


@app.route('/consulta_vendas', methods=['GET'])
@login_required
def consulta_vendas():
    """
    Página principal de consulta de vendas.
    (Com correção na soma de comissões para não perder vendas antigas)
    """
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    error_from_session = session.pop('error_message', None)
    success = session.pop('success_message', None)

    nivel_usuario = session.get('nivel', 1)
    id_colaborador_logado = session.get('id_colaborador', 'N/A')
    
    id_evento_param = request.args.get('id_evento')
    id_colaborador_param = request.args.get('id_colaborador')

    eventos_ativos = []
    colaboradores_lista = []
    selected_event = None
    resultados_agregados = []
    resumo_geral = None 
    error = error_from_session
    selected_colab_id_str = None
    
    default_comissao = g.parametros_globais.get('comissao_padrao', 0)
    comissao_autoatendimento = g.parametros_globais.get('comissao_autoatendimento', 0)
    comissao_map = {} 

    try:
        def clean_event_numerics(evento):
            if not evento: return evento
            decimal_fields = [
                'valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 
                'premio_segundobingo', 'premio_acumulado', 'minimo_de_venda', 'premio_total'
            ]
            for key in decimal_fields:
                if key in evento:
                    evento[key] = safe_float(evento.get(key, 0.0))
            return evento

        if not id_evento_param:
            eventos_ativos_cursor = db.eventos.find({'status': 'ativo'}).sort('data_evento', pymongo.ASCENDING)
            for evento in eventos_ativos_cursor:
                eventos_ativos.append(clean_event_numerics(evento))
        
        else:
            # Busca Evento (Suporta ID int ou ObjectId)
            selected_event_raw = None
            if str(id_evento_param).isdigit():
                selected_event_raw = db.eventos.find_one({'id_evento': int(id_evento_param)})
            if not selected_event_raw:
                selected_event_raw = db.eventos.find_one({'_id': try_object_id(id_evento_param)})

            selected_event = clean_event_numerics(selected_event_raw)
            
            if not selected_event:
                error = "Evento não encontrado."
                return render_template('consulta_vendas.html', error=error, g=g)

            # --- LÓGICA DE FILTRO DE COLABORADORES ---
            if nivel_usuario == 3:
                colaboradores_lista.append({'nick': 'TODOS', 'id_colaborador': 'ALL'})
                colabs_cursor = db.colaboradores.find({}, {'nick': 1, 'id_colaborador': 1, 'comissao': 1}).sort('nick', pymongo.ASCENDING)
                for colab in colabs_cursor:
                    colaboradores_lista.append(colab)
                    taxa = colab.get('comissao')
                    if isinstance(taxa, (int, float)):
                        comissao_map[colab['id_colaborador']] = taxa
            
            filtro_colaborador_query = {} 
            
            if nivel_usuario < 3:
                filtro_colaborador_query = {'id_colaborador': id_colaborador_logado}
                selected_colab_id_str = str(id_colaborador_logado)
                colab_doc = db.colaboradores.find_one({'id_colaborador': id_colaborador_logado}, {'comissao': 1})
                if colab_doc:
                    taxa = colab_doc.get('comissao')
                    if isinstance(taxa, (int, float)):
                         comissao_map[id_colaborador_logado] = taxa
            
            elif nivel_usuario == 3:
                if id_colaborador_param and id_colaborador_param != 'ALL':
                    # Tenta converter para int se possível
                    try: val_id = int(id_colaborador_param)
                    except: val_id = id_colaborador_param
                    
                    filtro_colaborador_query = {'id_colaborador': val_id}
                    selected_colab_id_str = str(id_colaborador_param)
                elif id_colaborador_param == 'ALL':
                    selected_colab_id_str = 'ALL'

            id_evento_int = selected_event.get('id_evento')
            nome_colecao_venda = f"vendas{id_evento_int}"

            # --- AGREGATION PIPELINE CORRIGIDA ---
            pipeline = []
            match_stage = {'id_evento': id_evento_int}
            match_stage.update(filtro_colaborador_query) 
            pipeline.append({'$match': match_stage})

            pipeline.append({
                '$group': {
                    '_id': '$id_colaborador', 
                    'nick_colaborador': {'$first': '$nick_colaborador'},
                    'total_kits': {'$sum': '$quantidade_unidades'},
                    'total_cartelas': {'$sum': '$quantidade_cartelas'},
                    'total_valor': {'$sum': '$valor_total'},
                    'total_vendas': {'$sum': 1},
                    'data_inicial': {'$min': '$data_venda'},
                    'data_final': {'$max': '$data_venda'},
                    
                    # === CORREÇÃO CRÍTICA AQUI ===
                    # 1. Soma AUTO: Apenas se origem for 'terminal_cliente'
                    'total_valor_auto': {
                        '$sum': {
                            '$cond': [{'$eq': ['$origem', 'terminal_cliente']}, '$valor_total', 0]
                        }
                    },
                    # 2. Soma COLAB: TUDO que NÃO for 'terminal_cliente'. 
                    # Isso pega 'terminal_colaborador', 'balcao', null, etc.
                    'total_valor_colab': {
                        '$sum': {
                            '$cond': [{'$ne': ['$origem', 'terminal_cliente']}, '$valor_total', 0]
                        }
                    }
                    # =============================
                }
            })
            pipeline.append({'$sort': {'nick_colaborador': 1}})
            
            resultados_cursor = db[nome_colecao_venda].aggregate(pipeline)
            
            for res in resultados_cursor:
                res['total_valor_float'] = safe_float(res['total_valor'])

                venda_via_colab = safe_float(res.get('total_valor_colab', 0))
                venda_via_auto  = safe_float(res.get('total_valor_auto', 0))

                colab_id = res['_id'] 
                
                # Define a taxa do colaborador (ou padrão)
                taxa_aplicada = comissao_map.get(colab_id, default_comissao) 
                # Define a taxa auto (global)
                taxa_aplicada_auto = comissao_autoatendimento 

                # CALCULA A SOMA
                comissao_parte_1 = (venda_via_colab * taxa_aplicada) / 100.0
                comissao_parte_2 = (venda_via_auto * taxa_aplicada_auto) / 100.0

                valor_comissao_total = comissao_parte_1 + comissao_parte_2
                
                # Grava no objeto para o HTML ler
                res['taxa_comissao_aplicada'] = taxa_aplicada 
                res['taxa_comissao_auto'] = taxa_aplicada_auto
                res['valor_comissao_float'] = valor_comissao_total
                
                resultados_agregados.append(res)
                
            # --- TOTAIS GERAIS (RESUMO NO TOPO) ---
            if selected_colab_id_str == 'ALL' and resultados_agregados:
                resumo_geral = {
                    'nick_colaborador': '⭐ Resumo Geral (TODOS)',
                    '_id': 'ALL',
                    'total_kits': sum(r['total_kits'] for r in resultados_agregados),
                    'total_cartelas': sum(r['total_cartelas'] for r in resultados_agregados),
                    'total_valor_float': sum(r['total_valor_float'] for r in resultados_agregados),
                    'total_vendas': sum(r['total_vendas'] for r in resultados_agregados),
                    'valor_comissao_float': sum(r['valor_comissao_float'] for r in resultados_agregados), # Soma correta das comissões mistas
                    'data_inicial': min(r['data_inicial'] for r in resultados_agregados),
                    'data_final': max(r['data_final'] for r in resultados_agregados)
                }
                
            if not resultados_agregados and id_colaborador_param and not error:
                error = "Nenhuma venda encontrada para este filtro."

    except Exception as e:
        print(f"Erro em consulta_vendas: {e}")
        error = f"Erro interno ao processar consulta: {e}"
        import traceback
        traceback.print_exc()

    return render_template('consulta_vendas.html',
                           g=g,
                           error=error,
                           success=success,
                           nivel=nivel_usuario,
                           eventos=eventos_ativos, 
                           selected_event=selected_event, 
                           colaboradores=colaboradores_lista,
                           selected_colab_id=selected_colab_id_str, 
                           resumo_geral=resumo_geral, 
                           resultados_agregados=resultados_agregados)



@app.route('/consulta_vendas/detalhes', methods=['GET'])
@login_required
def consulta_vendas_detalhes():
    """Mostra a lista detalhada de vendas com cálculo de comissão mista (Auto vs Colab)."""
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) 

    nivel_usuario = session.get('nivel', 1)
    id_colaborador_logado = session.get('id_colaborador', 'N/A')
    
    id_evento_param = request.args.get('id_evento')
    id_colaborador_param = request.args.get('id_colaborador') 

    vendas_detalhadas = []
    error = None
    info_evento_nome = None
    info_evento_id = None 
    info_colaborador = "N/A"
    info_tipo_cartela = 25 
    info_telefone_cliente = ''
    
    # --- 1. PREPARA AS TAXAS ---
    default_comissao = g.parametros_globais.get('comissao_padrao', 0)
    comissao_autoatendimento = g.parametros_globais.get('comissao_autoatendimento', 0)
    comissao_map = {} 

    try:
        selected_event = None
        if id_evento_param:
            if str(id_evento_param).isdigit():
                selected_event = db.eventos.find_one({'id_evento': int(id_evento_param)})
            else:
                selected_event = db.eventos.find_one({'_id': try_object_id(id_evento_param)})
        
        if not selected_event:
            error = "Evento não encontrado."
            return render_template('consulta_vendas_detalhes.html', error=error, g=g, vendas=[])

        id_evento_int = selected_event.get('id_evento')
        info_evento_nome = selected_event.get('descricao')
        info_evento_id = id_evento_int 
        info_tipo_cartela = selected_event.get('tipo_de_cartela', 25) 
        nome_colecao_venda = f"vendas{id_evento_int}"
        
        query_filter = {'id_evento': id_evento_int}
        colab_ids_para_buscar_comissao = []
        
        # --- LÓGICA DE FILTROS DE USUÁRIO ---
        if nivel_usuario < 3:
            query_filter['id_colaborador'] = id_colaborador_logado
            info_colaborador = session.get('nick', 'N/A')
            info_telefone_cliente = session.get('telefone_cliente','')
            if isinstance(id_colaborador_logado, int):
                 colab_ids_para_buscar_comissao.append(id_colaborador_logado)        
        
        elif nivel_usuario == 3:
            if id_colaborador_param and id_colaborador_param != 'ALL':
                try:
                    id_colab_int = int(id_colaborador_param)
                except ValueError:
                    id_colab_int = id_colaborador_param 

                query_filter['id_colaborador'] = id_colab_int
                colab_ids_para_buscar_comissao.append(id_colab_int)
                
                colab_doc = db.colaboradores.find_one({'id_colaborador': id_colab_int}, {'nick': 1})
                info_colaborador = colab_doc.get('nick') if colab_doc else f"ID {id_colab_int}"
                info_telefone_cliente = session.get('telefone_cliente','')
                
            elif id_colaborador_param == 'ALL':
                info_colaborador = "TODOS"
                todos_colabs = db.colaboradores.find({}, {'id_colaborador': 1, 'comissao': 1})
                for c in todos_colabs:
                    taxa = c.get('comissao')
                    if isinstance(taxa, (int, float)):
                        comissao_map[c['id_colaborador']] = taxa
        
        # Busca taxas específicas dos colaboradores filtrados
        if colab_ids_para_buscar_comissao:
             colab_docs = db.colaboradores.find(
                 {'id_colaborador': {'$in': colab_ids_para_buscar_comissao}},
                 {'id_colaborador': 1, 'comissao': 1}
             )
             for colab_doc in colab_docs:
                 if colab_doc:
                     taxa = colab_doc.get('comissao')
                     if isinstance(taxa, (int, float)):
                         comissao_map[colab_doc['id_colaborador']] = taxa
                 
        vendas_cursor = db[nome_colecao_venda].find(query_filter).sort('data_venda', pymongo.DESCENDING)
        
        # --- LOOP CORRIGIDO COM TAXA MISTA ---
        for venda in vendas_cursor:
            venda['valor_total_float'] = safe_float(venda.get('valor_total'))
            
            # Identifica quem ganha a comissão e a origem
            colab_id = venda.get('id_colaborador')
            # Se você estiver usando 'id_colaborador_indicacao' para auto-atendimento, 
            # pode ser necessário ajustar a linha acima para:
            # colab_id = venda.get('id_colaborador_indicacao') or venda.get('id_colaborador')

            origem_venda = venda.get('origem', 'terminal_colaborador')

            # DECISÃO DA TAXA
            if origem_venda == 'terminal_cliente':
                # Venda Auto-Atendimento -> Usa taxa Fixa Auto
                taxa_final = comissao_autoatendimento
                venda['tipo_taxa'] = 'AUTO' # Opcional: para debug ou mostrar na tela
            else:
                # Venda Normal -> Usa taxa do Colaborador (ou padrão)
                taxa_final = comissao_map.get(colab_id, default_comissao)
                venda['tipo_taxa'] = 'NORMAL'

            # CÁLCULO
            venda['valor_comissao_float'] = (venda['valor_total_float'] * taxa_final) / 100.0
            
            # Grava a taxa aplicada para exibir na tabela se quiser
            venda['taxa_comissao_aplicada'] = taxa_final
            
            vendas_detalhadas.append(venda)
        # -------------------------------------
            
        if not vendas_detalhadas:
            error = "Nenhuma venda detalhada encontrada."

    except Exception as e:
        print(f"Erro em consulta_vendas_detalhes: {e}")
        error = f"Erro interno: {e}"
        import traceback
        traceback.print_exc()

    return render_template('consulta_vendas_detalhes.html',
                           g=g,
                           error=error,
                           vendas=vendas_detalhadas,
                           info_evento=info_evento_nome, 
                           info_evento_id=info_evento_id, 
                           info_colaborador=info_colaborador,
                           info_tipo_cartela=info_tipo_cartela,
                           info_telefone_cliente=info_telefone_cliente)



# Minha Conta
# --- ATUALIZAÇÃO DA ROTA MINHA CONTA ---
@app.route('/minha_conta', methods=['GET'])
@login_required
def minha_conta():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    nivel_usuario = session.get('nivel', 1)
    # Se for admin (nivel 3), pode ver a conta de outros se passar o parametro
    id_logado_session = session.get('id_colaborador')
    nick_logado_session = session.get('nick')
    
    # ID do colaborador alvo da consulta
    target_id_colaborador = request.args.get('target_id', id_logado_session)
    
    # Se tentar ver outro sem ser admin, força o próprio
    if str(target_id_colaborador) != str(id_logado_session) and nivel_usuario < 3:
        target_id_colaborador = id_logado_session

    # Conversão segura para int
    try:
        target_id_colaborador_int = int(target_id_colaborador)
    except:
        target_id_colaborador_int = None

    # Busca dados do colaborador alvo (para pegar comissão e nick correto)
    colaborador_alvo = db.colaboradores.find_one({'id_colaborador': target_id_colaborador_int})
    if not colaborador_alvo:
        return redirect(url_for('menu_operacoes', error="Colaborador não encontrado."))

    taxa_comissao = colaborador_alvo.get('comissao', g.parametros_globais.get('comissao_padrao', 20))
    
    # Lista de colaboradores para o dropdown (apenas se admin)
    colaboradores_para_selecao = []
    if nivel_usuario > 1:
        colaboradores_para_selecao = list(db.colaboradores.find({}, {'id_colaborador': 1, 'nick': 1}).sort('nick', 1))

    # Eventos Ativos para o Dropdown
    eventos_ativos = list(db.eventos.find({'status': 'ativo'}).sort('data_evento', pymongo.ASCENDING))
    
    # Dados Financeiros (Inicializa zerado)
    resumo_financeiro = {
        'total_vendas_qty': 0,
        'total_vendas_valor': 0.0,
        'comissao_valor': 0.0,
        'total_pago': 0.0,
        'saldo_devedor': 0.0
    }
    historico_pagamentos = []
    
    id_evento_selected = request.args.get('id_evento')
    evento_selecionado = None

    if id_evento_selected:
        try:
            id_evento_int = int(id_evento_selected)
            evento_selecionado = db.eventos.find_one({'id_evento': id_evento_int})
            
            if evento_selecionado:
                nome_colecao_vendas = f"vendas{id_evento_int}"
                nome_colecao_pagtos = f"pagamentos{id_evento_int}"
                
                # 1. Agregação de Vendas
                if nome_colecao_vendas in db.list_collection_names():
                    pipeline_vendas = [
                        {'$match': {'id_colaborador': target_id_colaborador_int}},
                        {'$group': {
                            '_id': None,
                            'total_qty': {'$sum': '$quantidade_unidades'},
                            'total_val': {'$sum': '$valor_total'}
                        }}
                    ]
                    res_vendas = list(db[nome_colecao_vendas].aggregate(pipeline_vendas))
                    if res_vendas:
                        resumo_financeiro['total_vendas_qty'] = res_vendas[0]['total_qty']
                        resumo_financeiro['total_vendas_valor'] = safe_float(res_vendas[0]['total_val'])
                
                # 2. Cálculo de Comissão
                resumo_financeiro['comissao_valor'] = (resumo_financeiro['total_vendas_valor'] * taxa_comissao) / 100.0
                
                # 3. Agregação de Pagamentos
                if nome_colecao_pagtos in db.list_collection_names():
                    # Lista Detalhada
                    historico_pagamentos = list(db[nome_colecao_pagtos].find(
                        {'id_colaborador': target_id_colaborador_int}
                    ).sort('data_hora', pymongo.DESCENDING))
                    
                    # Soma Total Pago
                    pipeline_pagtos = [
                        {'$match': {'id_colaborador': target_id_colaborador_int}},
                        {'$group': {
                            '_id': None,
                            'total_pago': {'$sum': '$valor_pago'}
                        }}
                    ]
                    res_pagtos = list(db[nome_colecao_pagtos].aggregate(pipeline_pagtos))
                    if res_pagtos:
                        resumo_financeiro['total_pago'] = safe_float(res_pagtos[0]['total_pago'])

                # 4. Cálculo do Saldo Devedor (Total Vendas - Total Pago)
                # OBS: O saldo devedor é sobre o bruto. A comissão é lucro do colab, mas aqui calculamos o acerto com a banca.
                # Se a regra for pagar o líquido, altere aqui. Assumindo que paga o Bruto e recebe comissão ou abate depois.
                # Lógica Padrão: Deve pagar o que vendeu.
                resumo_financeiro['saldo_devedor'] = resumo_financeiro['total_vendas_valor'] - resumo_financeiro['total_pago']

        except Exception as e:
            print(f"Erro ao calcular financeiro: {e}")

    # Formata datas do histórico
    for pag in historico_pagamentos:
        if '_id' in pag: pag['_id'] = str(pag['_id'])
        if 'data_hora' in pag and isinstance(pag['data_hora'], datetime):
            pag['data_hora_fmt'] = pag['data_hora'].strftime("%d/%m/%Y %H:%M")

    return render_template('minha_conta.html', 
                           nivel=nivel_usuario, 
                           colaboradores=colaboradores_para_selecao,
                           target_colab=colaborador_alvo, # Objeto completo do alvo
                           eventos=eventos_ativos,
                           evento_selecionado=evento_selecionado,
                           financeiro=resumo_financeiro,
                           pagamentos=historico_pagamentos,
                           g=g)


# --- NOVA ROTA: REGISTRAR PAGAMENTO ---
@app.route('/registrar_pagamento', methods=['POST'])
@login_required
def registrar_pagamento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    try:
        id_evento = int(request.form.get('id_evento'))
        id_colaborador_alvo = int(request.form.get('id_colaborador_alvo'))
        valor_pagamento = float(request.form.get('valor_pagamento').replace(',', '.'))
        
        # Validações de Segurança
        nivel_logado = session.get('nivel', 1)
        id_logado = session.get('id_colaborador')
        
        # Se não for admin, só pode pagar para si mesmo? 
        # A regra diz "colaborador efetua o pagamento a central". 
        # Vamos assumir que qualquer um pode registrar que pagou (pendente de confirmação) ou o Admin registra.
        # Por segurança, vamos deixar o próprio colaborador registrar.
        
        # Validação de Saldo (Server Side)
        nome_colecao_vendas = f"vendas{id_evento}"
        nome_colecao_pagtos = f"pagamentos{id_evento}"
        
        # Recalcula totais para validar
        total_vendas = 0.0
        total_pago = 0.0
        
        if nome_colecao_vendas in db.list_collection_names():
            res = list(db[nome_colecao_vendas].aggregate([
                {'$match': {'id_colaborador': id_colaborador_alvo}},
                {'$group': {'_id': None, 'total': {'$sum': '$valor_total'}}}
            ]))
            if res: total_vendas = safe_float(res[0]['total'])
            
        if nome_colecao_pagtos in db.list_collection_names():
            res = list(db[nome_colecao_pagtos].aggregate([
                {'$match': {'id_colaborador': id_colaborador_alvo}},
                {'$group': {'_id': None, 'total': {'$sum': '$valor_pago'}}}
            ]))
            if res: total_pago = safe_float(res[0]['total'])
            
        saldo_devedor = total_vendas - total_pago
        
        # Pequena margem para erros de ponto flutuante
        if valor_pagamento > (saldo_devedor + 0.01):
            return redirect(url_for('minha_conta', id_evento=id_evento, target_id=id_colaborador_alvo, 
                                  error=f"Valor R$ {valor_pagamento:.2f} excede o saldo devedor de R$ {saldo_devedor:.2f}"))
        
        if valor_pagamento <= 0:
             return redirect(url_for('minha_conta', id_evento=id_evento, target_id=id_colaborador_alvo, 
                                  error="Valor deve ser maior que zero."))

        # Grava Pagamento
        colab_doc = db.colaboradores.find_one({'id_colaborador': id_colaborador_alvo})
        nick_colab = colab_doc.get('nick') if colab_doc else 'Desconhecido'
        
        pagamento_doc = {
            'id_evento': id_evento,
            'id_colaborador': id_colaborador_alvo,
            'nick_colaborador': nick_colab,
            'valor_pago': Decimal128(str(valor_pagamento)),
            'data_hora': hora_brasil(),
            'registrado_por_id': id_logado,
            'registrado_por_nick': session.get('nick')
        }
        
        db[nome_colecao_pagtos].insert_one(pagamento_doc)
        
        return redirect(url_for('minha_conta', id_evento=id_evento, target_id=id_colaborador_alvo, 
                              success="Pagamento registrado com sucesso!"))

    except Exception as e:
        print(f"Erro ao registrar pagamento: {e}")
        return redirect(url_for('menu_operacoes', error=f"Erro interno: {e}"))


# --- NOVA ROTA: EXCLUIR PAGAMENTO ---
@app.route('/excluir_pagamento', methods=['POST'])
@login_required
def excluir_pagamento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return "Acesso Negado", 403
        
    try:
        id_pagamento = request.form.get('id_pagamento')
        id_evento = int(request.form.get('id_evento'))
        target_id = request.form.get('target_id') # Para redirecionar de volta
        
        nome_colecao_pagtos = f"pagamentos{id_evento}"
        
        db[nome_colecao_pagtos].delete_one({'_id': ObjectId(id_pagamento)})
        
        return redirect(url_for('minha_conta', id_evento=id_evento, target_id=target_id, 
                              success="Pagamento estornado com sucesso."))
                              
    except Exception as e:
        return redirect(url_for('menu_operacoes', error=f"Erro ao excluir: {e}"))


# --- ROTA PARA GALERIA DE RESULTADOS (Consulta Pública/Interna) ---
@app.route('/consulta_resultados', methods=['GET'])
@login_required
def consulta_resultados():
    """
    Exibe a galeria de eventos finalizados e seus ganhadores.
    Baseado no template consulta_resultados.html e na estrutura de documento único em 'resultados'.
    """
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    id_evento_param = request.args.get('id_evento')
    error = None
    
    # Função local para formatar moeda (Ajustada para aceitar "100,00")
    def format_moeda(valor):
        try:
            if valor is None:
                return "0,00"
                
            # Se for string, trata a pontuação brasileira
            if isinstance(valor, str):
                # Remove símbolos de moeda e espaços
                valor_limpo = valor.replace('R$', '').strip()
                
                # Se tiver vírgula, assume que é decimal (ex: "100,00" ou "1.000,00")
                if ',' in valor_limpo:
                    # Remove pontos de milhar (1.000,00 -> 1000,00)
                    valor_limpo = valor_limpo.replace('.', '')
                    # Troca vírgula por ponto (1000,00 -> 1000.00)
                    valor_limpo = valor_limpo.replace(',', '.')
                
                val = float(valor_limpo)
            else:
                # Se já for número (float, Decimal128), usa o safe_float do app.py
                val = safe_float(valor)

            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception as e:
            # print(f"Erro ao formatar moeda '{valor}': {e}") # Debug opcional
            return "0,00"

    # --- CENÁRIO 1: LISTAGEM DE EVENTOS FINALIZADOS (Se nenhum ID for passado) ---
    if not id_evento_param:
        eventos_finalizados = []
        try:
            # Filtra apenas eventos com status 'finalizado'
            query = {'status': {'$regex': '^finalizado$', '$options': 'i'}}
            cursor = db.eventos.find(query).sort('data_evento', pymongo.DESCENDING)

            for evt in cursor:
                # Tratamento de Data
                data_fmt = "N/A"
                if evt.get('data_evento'):
                    try:
                        raw_date = evt['data_evento']
                        if isinstance(raw_date, datetime):
                            data_fmt = raw_date.strftime("%d/%m/%Y")
                        elif isinstance(raw_date, str):
                            if '-' in raw_date:
                                dt = datetime.strptime(raw_date, '%Y-%m-%d')
                                data_fmt = dt.strftime("%d/%m/%Y")
                            else:
                                data_fmt = raw_date
                    except:
                        data_fmt = str(evt.get('data_evento'))

                eventos_finalizados.append({
                    'id_evento': evt.get('id_evento'),
                    'descricao': evt.get('descricao', 'Sem Descrição'),
                    'hora_evento': evt.get('hora_evento'),
                    'data_formatada': data_fmt,
                    'premio_total_fmt': f"R$ {format_moeda(evt.get('premio_total', 0))}"
                })

        except Exception as e:
            print(f"Erro em consulta_resultados (lista): {e}")
            error = "Erro ao buscar lista de eventos."

        return render_template('consulta_resultados.html', 
                               eventos_finalizados=eventos_finalizados,
                               selected_event=None,
                               error=error,
                               g=g)

    # --- CENÁRIO 2: EXIBIÇÃO DOS RESULTADOS (Se ID for passado) ---
    else:
        selected_event = None
        resultados = []
        # Campos extras da estrutura nova (opcional, para debug ou futura exibição)
        bolas_sorteadas = [] 
        total_bolas = 0

        try:
            id_evento_int = int(id_evento_param)
            
            # 1. Busca Dados Básicos do Evento (Coleção 'eventos')
            evento_doc = db.eventos.find_one({'id_evento': id_evento_int})
            
            if evento_doc:
                data_fmt = str(evento_doc.get('data_evento', ''))
                try:
                    if isinstance(evento_doc.get('data_evento'), datetime):
                        data_fmt = evento_doc['data_evento'].strftime("%d/%m/%Y")
                    elif isinstance(data_fmt, str) and '-' in data_fmt:
                         data_fmt = datetime.strptime(data_fmt, '%Y-%m-%d').strftime("%d/%m/%Y")
                except: pass

                selected_event = {
                    'id_evento': evento_doc.get('id_evento'),
                    'descricao': evento_doc.get('descricao'),
                    'hora_evento': evento_doc.get('hora_evento'),
                    'data_formatada': data_fmt
                }

                # 2. Busca Resultados na coleção 'resultados'
                # NOVA ESTRUTURA: Um único documento contendo array 'ganhadores'
                print(f"id_evento:   {id_evento_int}")

            if 'resultados' in db.list_collection_names():
                resultado_doc = db.resultados.find_one({'id_evento': id_evento_int})
                
                if resultado_doc:
                    # Extrai dados gerais do sorteio
                    total_bolas = resultado_doc.get('total_de_bolas', 0)
                    if 'bolas_sorteadas' in resultado_doc:
                        # Opcional: Se quiser processar as bolas sorteadas para exibir
                        pass 
                    
                    # Acessa o ARRAY de ganhadores (Lista de 5 itens no seu exemplo)
                    raw_ganhadores = resultado_doc.get('ganhadores', [])
                    
                    # Garante que é uma lista antes de iterar
                    if isinstance(raw_ganhadores, list):
                        for item in raw_ganhadores:
                            # Proteção caso algum item não seja dicionário
                            if not isinstance(item, dict): continue

                            # Tenta variações de chaves para garantir compatibilidade
                            descricao = item.get('descricao') or item.get('premio') or item.get('descricao_premio') or 'Prêmio'
                            
                            # Busca valor (incluindo valor_rateio)
                            valor = item.get('valor_rateio') or item.get('valor') or item.get('valor_premio') or 0
                            
                            # Lista de Nomes (pode vir como 'ganhadores' ou 'nome')
                            lista_nomes = item.get('ganhadores') or item.get('nome') or []
                            if isinstance(lista_nomes, str): 
                                lista_nomes = [lista_nomes]
                            
                            # Cartelas
                            cartelas_raw = item.get('cartela') or item.get('cartelas') or []
                            if isinstance(cartelas_raw, (int, str)):
                                cartelas_fmt = str(cartelas_raw)
                            elif isinstance(cartelas_raw, list):
                                cartelas_fmt = ", ".join(str(c) for c in cartelas_raw)
                            else:
                                cartelas_fmt = ""

                            # Adiciona à lista final que vai para o HTML
                            resultados.append({
                                'descricao_premio': descricao,
                                'ganhadores': lista_nomes,
                                'cartela': cartelas_fmt,
                                'valor_premio': format_moeda(valor)
                            })

                        else:
                            print("Aviso: Campo 'ganhadores' não é uma lista.")

            else:
                error = "Evento não encontrado."

        except ValueError:
            error = "ID de evento inválido."
        except Exception as e:
            print(f"Erro em consulta_resultados (detalhe): {e}")
            error = f"Erro ao processar apuração: {e}"

        return render_template('consulta_resultados.html', 
                               eventos_finalizados=[], 
                               selected_event=selected_event,
                               resultados=resultados,
                               error=error,
                               g=g)


# --- ROTA DE REIMPRESSÃO (TXT) ---
@app.route('/reimprimir_comprovante_txt', methods=['POST'])
@login_required
def reimprimir_comprovante_txt():
    """
    Gera o texto (TXT) de um comprovante para "Venda Única" ou "Vendas Cliente"
    e retorna como JSON para ser copiado pela área de transferência.
    """
    db = get_vendas_db()
    if db is None: # <-- CORREÇÃO PYMONGO
        return jsonify({'status': 'error', 'message': 'DB Offline'})

    try:
        data = request.json
        tipo_reimpressao = data.get('tipo_reimpressao') 
        id_venda_str = data.get('id_venda')           
        id_evento_int = int(data.get('id_evento'))
        id_cliente_int = int(data.get('id_cliente'))
        
        evento = db.eventos.find_one({'id_evento': id_evento_int})
        if not evento:
            return jsonify({'status': 'error', 'message': 'Evento não encontrado'})

        http_apk = g.parametros_globais.get('http_apk', '')
        nome_sala = g.parametros_globais.get('nome_sala', '')
        data_evento_str = evento.get('data_evento', 'N/A')
        hora_evento_str = evento.get('hora_evento', 'N/A')
        data_evento_formatada = data_evento_str.replace('/', '-') if data_evento_str else 'N/A'
        
        nome_colecao_venda = f"vendas{id_evento_int}"
        
        receipt_html = "" 
        link_final_limpo = f"{http_apk}?idcliente={id_cliente_int}"
        if tipo_reimpressao == 'unica':
            venda = db[nome_colecao_venda].find_one({'id_venda': id_venda_str})
            if not venda:
                return jsonify({'status': 'error', 'message': 'Venda não encontrada'})
            
            periodo_principal = f"   > {venda['numero_inicial']} a {venda['numero_final']}<br>"
            periodo_adicional = ""
                       
            if venda.get('numero_inicial2', 0) > 0:
                periodo_adicional = f"    > {venda['numero_inicial2']} a {venda['numero_final2']}<br>"
                #link_periodos += f"&periodo={venda['numero_inicial2']},{venda['numero_final2']}"

            receipt_html = (
                f"<strong>✅COMPROVANTE DE COMPRA</strong><br>"
                f"      {nome_sala}<br>"
                f"     >  {venda['id_venda']}  < <br>"
                f"--------------------------------------------------------<br>"
                f"Cliente: <strong>{venda['nome_cliente']}</strong><br>"
                f"Evento: {evento['descricao']}<br>"
                f"<strong>Data: {data_evento_formatada} às {hora_evento_str}</strong><br>"
                f"Colaborador:{venda['id_colaborador']}-{venda['nick_colaborador']}<br>"
                f"--------------------------------------------------------<br>"
                f"Unidades Compradas: <strong>{venda['quantidade_unidades']}<strong><br>"
                f"     (Cartelas: {venda['quantidade_cartelas']})<br>"
                f"<strong> >  Período de Cartelas  <<strong><br>"
                f"{periodo_principal}"
                f"{periodo_adicional}"
                f"  VALOR: R$ {safe_float(venda['valor_total']):.2f}<br>"
            )

        elif tipo_reimpressao == 'cliente':
            vendas_cliente = list(db[nome_colecao_venda].find(
                {'id_cliente': id_cliente_int}
            ).sort('numero_inicial', 1))
            
            if not vendas_cliente:
                return jsonify({'status': 'error', 'message': 'Nenhuma venda encontrada para este cliente no evento.'})

            # --- Busca Chave PIX do Colaborador para o Comprovante ---           
            idColaborador = vendas_cliente[0]['id_colaborador']
            chave_pix_colaborador = "Consulte o Colaborador"
            try:
                if idColaborador!= 'N/A':
                     colab_doc_pix = db.colaboradores.find_one({'id_colaborador': int(idColaborador)})
                     if colab_doc_pix and colab_doc_pix.get('chave_pix'):
                         chave_pix_colaborador = colab_doc_pix.get('chave_pix')
            except Exception as e:
                 print(f"Erro ao buscar PIX do colaborador: {e}")

            nome_cliente = vendas_cliente[0]['nome_cliente']
            
            total_unidades = 0
            total_cartelas = 0
            total_valor = 0.0
            periodos_html_list = []
            
            for venda in vendas_cliente:
                total_unidades += venda['quantidade_unidades']
                total_cartelas += venda['quantidade_cartelas']
                total_valor += safe_float(venda['valor_total'])
                
                periodos_html_list.append(f"   > {venda['numero_inicial']} a {venda['numero_final']}<br>")
                
                if venda.get('numero_inicial2', 0) > 0:
                    periodos_html_list.append(f"    > {venda['numero_inicial2']} a {venda['numero_final2']}<br>")

            todos_periodos_html = "".join(periodos_html_list)

            receipt_html = (
                f"<strong>🧾 COMPROVANTE CLIENTE</strong><br>"
                f".         {nome_sala}<br>"
                f".        Resumo do Cliente <br>"
                f" <strong>{nome_cliente}</strong> (ID: {id_cliente_int})<br>"
                f"--------------------------------------------------------<br>"
                f"Evento: {evento['descricao']}<br>"
                f"<strong>Data: {data_evento_formatada} às {hora_evento_str}</strong><br>"
                f"Gerado por: {session.get('nick', 'N/A')}<br>"
                f"--------------------------------------------------------<br>"
                f".       Total Unidades: <strong>{total_unidades}<strong><br>"
                f".       (Total Cartelas: {total_cartelas})<br>"
                f"<strong> >  Períodos Adquiridos  <<strong><br>"
                f"{todos_periodos_html}"
                f"  VALOR TOTAL: R$ {total_valor:.2f}<br>"
                f"<br>" 
                f"   🔑   CHAVE PIX   💸<br>"
                f"   <strong>{chave_pix_colaborador}</strong><br>"
                f"<br>"
                f"<br>"                
                f">CLIQUE NO <strong>LINK</strong> ABAIXO PARA<br>"
                f"    ACESSAR SUAS CARTELAS 📱<br>"
            )

        else:
            return jsonify({'status': 'error', 'message': 'Tipo de reimpressão inválido.'})
        
        receipt_html += f"<br><strong> {link_final_limpo} </strong>"

        def clean_html_to_txt(html_str):
            txt = re.sub(r'<br\s*/?>', '\n', html_str, flags=re.IGNORECASE)
            txt = re.sub(r'<[^>]+>', '', txt)
            txt = html.unescape(txt)
            txt_limpo = '\n'.join([linha.strip() for linha in txt.split('\n')])
            return txt_limpo.strip()

        receipt_text = clean_html_to_txt(receipt_html)

        return jsonify({
            'status': 'success',
            'receipt_text': receipt_text 
        })

    except Exception as e:
        print(f"Erro ao reimprimir comprovante: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Erro interno: {e}'})

# --- EXCLUIR VENDA
@app.route('/excluir_venda', methods=['POST'])
@login_required
def excluir_venda():
    """
    Exclui uma venda específica baseada no ID e Evento fornecidos.
    Requer nível de acesso 3 (Administrador) para segurança.
    """
    db = get_vendas_db()
    if db is None:
        return jsonify({'status': 'error', 'message': 'DB Offline'})

    # Verifica permissão (Nível 3 Obrigatório para exclusão)
    if session.get('nivel', 0) < 3:
        return jsonify({'status': 'error', 'message': 'Acesso Negado. Apenas administradores podem excluir vendas.'})

    try:
        data = request.json
        id_venda_str = data.get('id_venda')
        id_evento_int = int(data.get('id_evento'))

        if not id_venda_str or not id_evento_int:
            return jsonify({'status': 'error', 'message': 'Dados incompletos para exclusão.'})

        nome_colecao_venda = f"vendas{id_evento_int}"
        
        # Verifica se a venda existe antes de excluir
        venda = db[nome_colecao_venda].find_one({'id_venda': id_venda_str})
        if not venda:
            return jsonify({'status': 'error', 'message': 'Venda não encontrada.'})

        # Executa a exclusão
        result = db[nome_colecao_venda].delete_one({'id_venda': id_venda_str})

        if result.deleted_count == 1:
            # Opcional: Logar quem excluiu (pode ser útil para auditoria)
            print(f"[AUDITORIA] Venda {id_venda_str} excluída por {session.get('nick')} em {hora_brasil()}")
            return jsonify({'status': 'success', 'message': 'Venda excluída com sucesso.'})
        else:
            return jsonify({'status': 'error', 'message': 'Não foi possível excluir o registro.'})

    except Exception as e:
        print(f"Erro ao excluir venda: {e}")
        return jsonify({'status': 'error', 'message': f'Erro interno: {e}'})


# --- ROTA GERAR LISTA (DOWNLOAD TXT) ---
@app.route('/gerar_lista_vendas')
@login_required
def gerar_lista_vendas():
    """
    Gera um arquivo TXT em memória (com cabeçalho e dados de cliente)
    e o envia para download.
    """
    
    db = get_vendas_db()
    if db is None: # <-- CORREÇÃO PYMONGO
        session['error_message'] = "Erro de conexão com o BD de Vendas."
        return redirect(url_for('consulta_vendas'))

    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    id_evento_param = request.args.get('id_evento')
    
    redirect_url = url_for('consulta_vendas', 
                           id_evento=id_evento_param, 
                           id_colaborador='ALL')

    if not id_evento_param:
        session['error_message'] = "Erro: ID do Evento não fornecido."
        return redirect(url_for('consulta_vendas'))

    try:
        evento_oid = try_object_id(id_evento_param)
        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        
        selected_event = db.eventos.find_one(
            {'_id': evento_oid},
            { 
                'id_evento': 1, 'unidade_de_venda': 1, 'numero_maximo': 1,
                'tipo_de_cartela': 1, 'valor_de_venda': 1, 'descricao': 1, 
                'premio_quadra': 1, 'quantidade_de_linhas': 1, 'premio_linha': 1, 
                'premio_faltaum': 1,'premio_bingo': 1, 'premio_segundobingo': 1,
                'premio_acumulado': 1,'bola_tope_acumulado': 1
            }
        )

        #   

        if not selected_event:
            session['error_message'] = "Erro: Evento não encontrado."
            return redirect(redirect_url)
            
        id_evento_int = selected_event.get('id_evento')
        nome_colecao_venda = f"vendas{id_evento_int}"
        
        file_name = f"periodo.{id_evento_int}"

        io_buffer = io.StringIO()
        
        header_line = (
            f"{selected_event.get('unidade_de_venda', 6)}!"
            f"{selected_event.get('numero_maximo', 12000)}!"
            f"{selected_event.get('tipo_de_cartela', 15)}!"
            f"{safe_float(selected_event.get('valor_de_venda', 0))}!"
            f"{selected_event.get('descricao', 'N/A')}!"
            f"{safe_float(selected_event.get('premio_quadra', 0))}!"
            f"{selected_event.get('quantidade_de_linhas', 1)}!"
            f"{safe_float(selected_event.get('premio_linha', 0))}!"
            f"{safe_float(selected_event.get('premio_faltaum', 0))}!"
            f"{safe_float(selected_event.get('premio_bingo', 0))}!"
            f"{safe_float(selected_event.get('premio_segundobingo', 0))}!"
            f"{safe_float(selected_event.get('premio_acumulado', 0))}!"
            f"{selected_event.get('bola_tope_acumulado', 0)}!" 
            f"{nome_sala}\r\n")  # <--- ADICIONADO AQUI NO FINAL        

        io_buffer.write(header_line)

        vendas_cursor = db[nome_colecao_venda].find(
            {'id_evento': id_evento_int},
            { 
                'numero_inicial': 1, 'numero_final': 1, 'numero_inicial2': 1,
                'numero_final2': 1, 'id_cliente': 1, 'nome_cliente': 1,
                'id_colaborador': 1, 'nick_colaborador': 1
            }
        ).sort('numero_inicial', pymongo.ASCENDING)
        
        lista_vendas = list(vendas_cursor) 
        
        if not lista_vendas:
            session['error_message'] = "Não há nenhuma venda neste evento para gerar o arquivo."
            return redirect(redirect_url)

        cliente_ids_set = {v.get('id_cliente') for v in lista_vendas if v.get('id_cliente')}
        
        clientes_cursor = db.clientes.find(
            {'id_cliente': {'$in': list(cliente_ids_set)}},
            {'id_cliente': 1, 'telefone': 1, 'cidade': 1} 
        )
        
        clientes_map = {c['id_cliente']: c for c in clientes_cursor}

        for venda in lista_vendas:
            id_cliente = venda.get('id_cliente')
            cliente_info = clientes_map.get(id_cliente, {})
            
            line_venda = (
                f"{venda.get('numero_inicial', 0)}!"
                f"{venda.get('numero_final', 0)}!"
                f"{venda.get('numero_inicial2', 0)}!"
                f"{venda.get('numero_final2', 0)}!"
                f"{id_cliente or 'N/A'}!"
                f"{venda.get('nome_cliente', 'N/A')}!"
                f"{venda.get('id_colaborador', 'N/A')}!"
                f"{venda.get('nick_colaborador', 'N/A')}!"
                f"{cliente_info.get('telefone', 'N/A')}!"
                f"{cliente_info.get('cidade', 'N/A')}\r\n" # <-- CRLF
            )
            io_buffer.write(line_venda)
        
        output_text = io_buffer.getvalue()
        
        return Response(
            output_text.encode('latin-1', 'ignore'), 
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment;filename={file_name}"}
        )

    except Exception as e:
        print(f"ERRO GERAL ao gerar lista: {e}")
        session['error_message'] = f"Erro inesperado ao gerar arquivo: {e}"
        return redirect(redirect_url)

# --- ROTAS DE GERAÇÃO DE PDF E ARQUIVOS ---
@app.route('/gerar_cartelas_pdf_25')
@login_required
def gerar_cartelas_pdf_25():
    """
    Gera PDF de cartelas de 25 números.
    Layout: 6 cartelas por página (2 colunas x 3 linhas).
    Cabeçalho: Nome da Sala + Descrição/Data do Evento.
    """
    db = get_vendas_db() 
    if db is None: 
        return "Erro de Conexão: DB Offline.", 500
    
    TIPO_CARTELA = 25 

    try:
        # Parâmetros da URL
        try:
            numero_inicial_pdf = int(request.args.get('numero_inicial_pdf'))
            numero_final_pdf = int(request.args.get('numero_final_pdf'))
            id_evento = int(request.args.get('id_evento', 0))
            nome_cliente = request.args.get('nome_cliente', 'cliente')
        except (ValueError, TypeError):
             return "Erro: Parâmetros inválidos na URL."
        
        if numero_inicial_pdf > numero_final_pdf:
             return "Erro: Número inicial maior que final."

        # --- Lógica de Cabeçalho Personalizado ---
        evento = db.eventos.find_one({'id_evento': id_evento})
        if not evento:
            return "Erro: Evento não encontrado."

        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        descricao_evento = evento.get('descricao', '')
        
        # Formata data
        data_str = evento.get('data_evento', '')
        hora_str = evento.get('hora_evento', '')
        if '-' in str(data_str):
            try:
                dt = datetime.strptime(str(data_str), '%Y-%m-%d')
                data_str = dt.strftime('%d/%m/%Y')
            except: pass
            
        infos_evento = f"{descricao_evento} - {data_str} as {hora_str}"

        # Verifica arquivo TXT
        caminho_check = os.path.join(CARTELAS_FOLDER, f'cartelas.{TIPO_CARTELA}')
        if not os.path.exists(caminho_check):
             return f"Erro: Arquivo 'cartelas.25' não encontrado no servidor em {caminho_check}."
        
        # Configura PDF
        pdf = PDFCartelas(orientation='P', unit='mm', format='A4') 
        
        # Injeta textos para o header()
        pdf.nome_sala = nome_sala
        pdf.infos_evento = infos_evento
        
        pdf.alias_nb_pages()
        
        # --- CONFIGURAÇÃO DE LAYOUT (6 por página) ---
        margem_x = 15
        margem_top_inicial = 25 # Espaço para o cabeçalho da página
        largura_cartela = 70
        
        # Altura da Cartela 25 nums:
        # Título(6) + Header(8) + 5*Num(10) = 64mm
        altura_cartela_total = 64 
        
        espaco_horizontal = 10
        espaco_vertical = 12 
        
        # Gera as coordenadas para 6 cartelas: (X, Y)
        # 2 Colunas x 3 Linhas
        posicoes = []
        for linha in range(3): # Linhas 0, 1, 2
            y = margem_top_inicial + (linha * (altura_cartela_total + espaco_vertical))
            
            # Coluna 1
            posicoes.append((margem_x, y))
            # Coluna 2
            posicoes.append((margem_x + largura_cartela + espaco_horizontal, y))
            
        cartela_idx_na_pagina = 0

        for num_cartela in range(numero_inicial_pdf, numero_final_pdf + 1):
            
            if cartela_idx_na_pagina == 0:
                pdf.add_page()
            
            dados_cartela = buscar_dados_cartela_2d(num_cartela, TIPO_CARTELA)
            
            if not dados_cartela:
                 print(f"Aviso: Dados da cartela {num_cartela} (tipo 25) não encontrados.")
            else:
                if cartela_idx_na_pagina < len(posicoes):
                    pos_x, pos_y = posicoes[cartela_idx_na_pagina]
                    pdf.desenhar_cartela(num_cartela, dados_cartela, pos_x, pos_y)
            
            cartela_idx_na_pagina += 1
            
            if cartela_idx_na_pagina >= len(posicoes):
                cartela_idx_na_pagina = 0
        
        pdf_output = bytes(pdf.output()) 
        
        nick_limpo = clean_for_filename(nome_cliente)
        nome_arquivo = f'{nick_limpo}_eve{id_evento}_25nums_{numero_inicial_pdf}_{numero_final_pdf}.pdf'
        
        response = make_response(pdf_output)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
        
        return response

    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar PDF 25: {e}")
        import traceback
        traceback.print_exc()
        return f"Erro interno: {e}"


# Rota para cartelas de 15 números (PLACEHOLDER)
@app.route('/gerar_cartelas_pdf_15')
@login_required
def gerar_cartelas_pdf_15():
    """
    Gera PDF de cartelas de 15 números.
    Layout: 10 cartelas por página (2 colunas x 5 linhas).
    Cabeçalho: Nome da Sala + Descrição/Data do Evento.
    """
    db = get_vendas_db() 
    if db is None: 
        return "Erro de Conexão: DB Offline.", 500
    
    TIPO_CARTELA = 15 

    try:
        # Parâmetros da URL
        try:
            numero_inicial_pdf = int(request.args.get('numero_inicial_pdf'))
            numero_final_pdf = int(request.args.get('numero_final_pdf'))
            id_evento = int(request.args.get('id_evento', 0))
            nome_cliente = request.args.get('nome_cliente', 'cliente')
        except (ValueError, TypeError):
             return "Erro: Parâmetros inválidos na URL."
        
        if numero_inicial_pdf > numero_final_pdf:
             return "Erro: Número inicial maior que final."
        
        # Busca dados do evento para o cabeçalho
        evento = db.eventos.find_one({'id_evento': id_evento})
        if not evento:
            return "Erro: Evento não encontrado."

        # Prepara textos do cabeçalho
        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        descricao_evento = evento.get('descricao', '')
        
        # Formata data e hora
        data_str = evento.get('data_evento', '')
        hora_str = evento.get('hora_evento', '')
        # Se data vier no formato YYYY-MM-DD, converte para DD/MM/YYYY
        if '-' in str(data_str):
            try:
                dt = datetime.strptime(str(data_str), '%Y-%m-%d')
                data_str = dt.strftime('%d/%m/%Y')
            except: pass
            
        infos_evento = f"{descricao_evento} - {data_str} as {hora_str}"

        # Verifica arquivo TXT
        caminho_check = os.path.join(CARTELAS_FOLDER, f'cartelas.{TIPO_CARTELA}')
        if not os.path.exists(caminho_check):
             return f"Erro: Arquivo 'cartelas.15' não encontrado no servidor em {caminho_check}."
        
        # Configura PDF
        pdf = PDFCartelas(orientation='P', unit='mm', format='A4') 
        
        # Injeta os textos personalizados na instância do PDF para o header() usar
        pdf.nome_sala = nome_sala
        pdf.infos_evento = infos_evento
        
        pdf.alias_nb_pages()
        
        # --- CONFIGURAÇÃO DE LAYOUT (10 por página) ---
        margem_x = 15
        margem_top_inicial = 25 # Espaço reservado para o cabeçalho customizado
        largura_cartela = 70
        
        # Altura calculada na classe PDFCartelas:
        # Título(5) + Header(6) + 3*Num(9) = 38mm altura total da cartela
        altura_cartela_total = 38 
        
        espaco_horizontal = 10
        espaco_vertical = 6 # Espaço entre linhas de cartelas
        
        # Gera as coordenadas para 10 cartelas: (X, Y)
        # 2 Colunas x 5 Linhas
        posicoes = []
        for linha in range(5): # 0 a 4
            y = margem_top_inicial + (linha * (altura_cartela_total + espaco_vertical))
            
            # Coluna 1
            posicoes.append((margem_x, y))
            # Coluna 2
            posicoes.append((margem_x + largura_cartela + espaco_horizontal, y))
            
        # posicoes agora tem 10 tuplas [(x,y)...]
        
        cartela_idx_na_pagina = 0

        for num_cartela in range(numero_inicial_pdf, numero_final_pdf + 1):
            
            if cartela_idx_na_pagina == 0:
                pdf.add_page()
            
            dados_cartela = buscar_dados_cartela_2d(num_cartela, TIPO_CARTELA)
            
            if not dados_cartela:
                 print(f"Aviso: Dados da cartela {num_cartela} (tipo 15) não encontrados.")
            else:
                if cartela_idx_na_pagina < len(posicoes):
                    pos_x, pos_y = posicoes[cartela_idx_na_pagina]
                    pdf.desenhar_cartela_15(num_cartela, dados_cartela, pos_x, pos_y)
            
            cartela_idx_na_pagina += 1
            
            # Se preencheu as 10 posições, zera para criar nova página
            if cartela_idx_na_pagina >= len(posicoes):
                cartela_idx_na_pagina = 0
        
        pdf_output = bytes(pdf.output()) 
        nick_limpo = clean_for_filename(nome_cliente)
        nome_arquivo = f'{nick_limpo}_eve{id_evento}_15nums_{numero_inicial_pdf}_{numero_final_pdf}.pdf'
        
        response = make_response(pdf_output)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
        
        return response

    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar PDF 15: {e}")
        import traceback
        traceback.print_exc()
        return f"Erro interno: {e}"


# controle de movimentação dos clientes
def registrar_transacao_cliente(db, id_cliente, valor, tipo, descricao, id_evento=None, id_venda=None):
    """
    Centraliza toda movimentação financeira do cliente.
    valor: float ou Decimal128 (positivo para crédito, negativo para débito)
    tipo: 'compra', 'premio', 'recarga', 'ajuste'
    """
    try:
        # 1. Converte valor para Decimal128 para precisão financeira
        valor_decimal = Decimal128(str(valor))
        
        # 2. Busca saldo atual (Atomicamente para evitar condição de corrida)
        # Se o cliente não tiver o campo 'saldo', assume 0.00
        cliente = db.clientes.find_one({'id_cliente': id_cliente})
        if not cliente:
            return False, "Cliente não encontrado."
            
        saldo_anterior = safe_float(cliente.get('saldo_atual', 0.00))
        saldo_novo = saldo_anterior + float(valor)
        
        # Opcional: Impedir saldo negativo se for compra
        # if tipo == 'compra' and saldo_novo < 0:
        #    return False, "Saldo insuficiente."

        # 3. Atualiza o saldo no cadastro do cliente
        db.clientes.update_one(
            {'id_cliente': id_cliente},
            {'$set': {'saldo_atual': Decimal128(str(saldo_novo))}}
        )

        # 4. Grava o histórico (Extrato)
        transacao_doc = {
            'id_cliente': id_cliente,
            'data_hora': hora_brasil(),
            'tipo': tipo,
            'valor': valor_decimal,
            'saldo_anterior': Decimal128(str(saldo_anterior)),
            'saldo_posterior': Decimal128(str(saldo_novo)),
            'descricao': descricao,
            'id_evento': id_evento,
            'id_venda': id_venda,
            'registrado_por': session.get('nick', 'Sistema') # Rastreabilidade
        }
        db.transacoes_clientes.insert_one(transacao_doc)
        
        return True, "Sucesso"

    except Exception as e:
        print(f"Erro ao registrar transação: {e}")
        return False, str(e)


# --- NOVA ROTA: ADICIONAR CRÉDITO (RECARGA) ---
@app.route('/cliente/adicionar_credito', methods=['POST'])
@login_required
def adicionar_credito_cliente():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    try:
        id_cliente = int(request.form.get('id_cliente'))
        valor_recarga = float(request.form.get('valor_recarga', '0').replace(',', '.'))
        
        if valor_recarga <= 0:
            return redirect(url_for('cadastro_cliente', view='consulta', error="Valor da recarga deve ser positivo."))

        # Chama a função de transação
        sucesso = registrar_transacao_cliente(
            db, 
            id_cliente, 
            valor_recarga, 
            'recarga', 
            f"Recarga via Colaborador ({session.get('nick')})"
        )
        
        if sucesso:
            msg = f"Recarga de R$ {valor_recarga:.2f} realizada com sucesso para o Cliente {id_cliente}."
            return redirect(url_for('cadastro_cliente', view='consulta', success=msg, query=str(id_cliente)))
        else:
            return redirect(url_for('cadastro_cliente', view='consulta', error="Erro ao registrar recarga."))

    except Exception as e:
        return redirect(url_for('cadastro_cliente', view='consulta', error=f"Erro interno: {e}"))


@app.route('/minha_carteira')
@login_required
def minha_carteira():
    """
    Exibe o extrato financeiro do cliente logado.
    """
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    # Verifica se é cliente mesmo
    if session.get('nivel', 1) != 0:
        return redirect(url_for('menu_operacoes', error="Acesso exclusivo para clientes."))

    id_cliente = int(session.get('id_cliente'))
    
    # 1. Busca Dados do Cliente (Saldo Atual)
    cliente = db.clientes.find_one({'id_cliente': id_cliente})
    saldo_atual = safe_float(cliente.get('saldo_atual', 0.00))
    
    # 2. Busca Extrato (Últimas 50 movimentações)
    # Se a coleção não existir ainda, retorna lista vazia
    transacoes = []
    if 'transacoes_clientes' in db.list_collection_names():
        transacoes_cursor = db.transacoes_clientes.find(
            {'id_cliente': id_cliente}
        ).sort('data_hora', pymongo.DESCENDING).limit(50)
        
        for t in transacoes_cursor:
            # Formatações para o Template
            t['valor_float'] = safe_float(t['valor'])
            t['saldo_pos_float'] = safe_float(t.get('saldo_posterior', 0))
            if 'data_hora' in t:
                t['data_fmt'] = t['data_hora'].strftime("%d/%m/%Y %H:%M")
            transacoes.append(t)

    return render_template('carteira_cliente.html', 
                           cliente=cliente, 
                           saldo_atual=saldo_atual, 
                           transacoes=transacoes,
                           g=g)



# --- ROTA TEMPORÁRIA: RESET DE SENHAS ---
@app.route('/admin/reset_senhas_global_temp')
@login_required
def reset_senhas_global_temp():
    """
    ATENÇÃO: Rota temporária para resetar a senha de TODOS os clientes.
    Define a senha como 'senha' (que o sistema converte para 'Senha' no login).
    """
    # 1. Segurança Básica (Apenas Admin)
    if session.get('nivel', 0) < 3:
        return "ACESSO NEGADO. Apenas administradores.", 403

    db = get_vendas_db()
    if db is None: return "Erro de conexão com o banco.", 500

    try:
        # 2. Gera o Hash da senha padrão "Senha"
        # O sistema de login usa .capitalize(), então "senha" vira "Senha"
        senha_padrao = "Senha"
        hash_senha = bcrypt.hashpw(senha_padrao.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # 3. Atualiza TODOS os documentos da coleção 'clientes'
        resultado = db.clientes.update_many(
            {}, # Filtro vazio pega todos os registros
            {'$set': {'senha': hash_senha}}
        )

        return (
            f"<h1>Operação Concluída com Sucesso!</h1>"
            f"<p>Total de clientes encontrados: {resultado.matched_count}</p>"
            f"<p>Total de senhas atualizadas: {resultado.modified_count}</p>"
            f"<p>Agora todos os clientes podem logar com a senha: <strong>senha</strong></p>"
            f"<br><a href='/menu'>Voltar ao Menu</a>"
        )

    except Exception as e:
        return f"Erro crítico ao resetar senhas: {e}"


# --- ROTA: MONITOR DE SAQUES ---
@app.route('/monitor_saques', methods=['GET'])
@login_required
def monitor_saques():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    filtro_status = request.args.get('status', 'pendente')
    
    # 1. Captura o limite (Padrão: 30 registros)
    try:
        limit_param = int(request.args.get('limit', 30))
    except ValueError:
        limit_param = 30 # Fallback se digitarem texto
        
    query = {}
    if filtro_status != 'todos':
        query['status'] = filtro_status

    try:
        # 2. Aplica o .limit() na consulta
        saques_cursor = db.requisao_saque.find(query)\
            .sort('data_requisicao', pymongo.DESCENDING)\
            .limit(limit_param)
            
        saques = list(saques_cursor)
        
        # Tratamento de dados (seu código existente de conversão de data/float)
        for s in saques:
            s['_id'] = str(s['_id'])
            s['valor_requerido'] = safe_float(s.get('valor_requerido'))
            if 'data_requisicao' in s and isinstance(s['data_requisicao'], str):
                try:
                    s['data_requisicao'] = datetime.strptime(s['data_requisicao'], '%Y-%m-%dT%H:%M:%S.%f')
                except ValueError:
                    try:
                        s['data_requisicao'] = datetime.strptime(s['data_requisicao'], '%Y-%m-%dT%H:%M:%S')
                    except: pass

    except Exception as e:
        print(f"Erro ao buscar saques: {e}")
        saques = []

    # 3. Passamos 'limit_atual' para o template manter o input preenchido
    return render_template('monitor_saques.html', 
                           saques=saques, 
                           filtro_atual=filtro_status,
                           limit_atual=limit_param, 
                           g=g)


# --- ROTA: AÇÃO DO SAQUE (PAGAR ou REJEITAR) ---
@app.route('/acao_saque', methods=['POST'])
@login_required
def acao_saque():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    try:
        id_saque = request.form.get('id_saque')
        acao = request.form.get('acao') # 'pagar' ou 'rejeitar'
        
        saque = db.requisao_saque.find_one({'_id': ObjectId(id_saque)})
        if not saque:
            return redirect(url_for('monitor_saques', error="Solicitação não encontrada."))
        
        if saque.get('status') != 'pendente':
            return redirect(url_for('monitor_saques', error="Esta solicitação já foi processada."))

        id_cliente = saque.get('id_cliente')
        valor = safe_float(saque.get('valor_requerido'))
        
        if acao == 'pagar':
            # Pega o ID que estava salvo no pedido de saque
            id_raw = saque.get('id_cliente')
            
            # --- CORREÇÃO: BUSCA INTELIGENTE (HÍBRIDA) ---
            # Monta uma lista de possibilidades para achar o cliente
            # Ex: Se id_raw for "20", ele vai procurar por "20" E por 20
            possiveis_ids = [id_raw]
            
            try:
                # Tenta criar a versão numérica
                if str(id_raw).isdigit():
                    possiveis_ids.append(int(id_raw))
                # Tenta criar a versão texto
                possiveis_ids.append(str(id_raw))
            except:
                pass
            
            # Busca no banco usando o operador $in (procura por qualquer um da lista)
            cliente = db.clientes.find_one({'id_cliente': {'$in': possiveis_ids}})
            # ---------------------------------------------

            if not cliente:
                # Se mesmo procurando de todos os jeitos não achar, aí sim é erro real
                return redirect(url_for('monitor_saques', error=f"Erro Crítico: Cliente {id_raw} deletado ou não encontrado."))

            # Continua o processo de pagamento...
            saldo_atual = safe_float(cliente.get('saldo_atual', 0))
            
            if saldo_atual < valor:
                return redirect(url_for('monitor_saques', error=f"Erro: Cliente tem apenas R$ {saldo_atual:.2f}. Saque de R$ {valor:.2f} impossível."))

            # 2. Debita o saldo
            sucesso, msg = registrar_transacao_cliente(
                db=db,
                id_cliente=cliente.get('id_cliente'), # Usa o ID oficial achado no banco
                valor=-abs(valor), 
                tipo='saque',
                descricao=f"Saque Aprovado (Req: {str(id_saque)[-4:]})",
                id_evento=None,
                id_venda=None
            )
            
            if not sucesso:
                 return redirect(url_for('monitor_saques', error=f"Erro ao debitar: {msg}"))

            # 3. Atualiza status do saque para PAGO
            db.requisao_saque.update_one(
                {'_id': ObjectId(id_saque)},
                {'$set': {
                    'status': 'pago',
                    'data_pgto': hora_brasil(),
                    'operador_pgto': session.get('nick'),
                    'saldo_atual_pgto': saldo_atual - valor
                }}
            )
            msg_sucesso = "Saque APROVADO e saldo debitado com sucesso!"

        elif acao == 'rejeitar':
            # Apenas muda o status, não mexe no saldo (pois não foi debitado na solicitação)
            db.requisao_saque.update_one(
                {'_id': ObjectId(id_saque)},
                {'$set': {
                    'status': 'rejeitado',
                    'data_pgto': hora_brasil(),
                    'operador_pgto': session.get('nick')
                }}
            )
            msg_sucesso = "Solicitação de Saque REJEITADA."

        else:
            return redirect(url_for('monitor_saques', error="Ação inválida."))

        return redirect(url_for('monitor_saques', success=msg_sucesso))

    except Exception as e:
        print(f"Erro critico acao_saque: {e}")
        return redirect(url_for('monitor_saques', error=f"Erro interno: {e}"))


@app.route('/financeiro_evento', methods=['GET'])
@login_required
def financeiro_evento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    id_evento_param = request.args.get('id_evento')

    # SE NÃO TEM EVENTO SELECIONADO: MOSTRA LISTA
    if not id_evento_param:
        eventos = list(db.eventos.find(
            {'status': {'$in': ['ativo', 'paralizado', 'finalizado']}}
        ).sort('data_evento', -1))
        
        for e in eventos:
            e['_id'] = str(e['_id'])
            if 'data_evento' in e:
                 try: e['data_fmt'] = e['data_evento'].strftime('%d/%m/%Y') if hasattr(e['data_evento'], 'strftime') else e['data_evento']
                 except: e['data_fmt'] = str(e['data_evento'])

        return render_template('financeiro_evento_selecao.html', eventos=eventos, g=g)

    # SE TEM EVENTO: CALCULA O RELATÓRIO
    try:
        id_evento_int = int(id_evento_param)
        evento = db.eventos.find_one({'id_evento': id_evento_int})
        if not evento:
            return redirect(url_for('financeiro_evento', error="Evento não encontrado"))

        # 1. Carrega Parâmetros e Mapas
        default_comissao = g.parametros_globais.get('comissao_padrao', 20)
        comissao_auto = g.parametros_globais.get('comissao_autoatendimento', 10)
        
        colabs = list(db.colaboradores.find({}))
        mapa_comissao = {c.get('id_colaborador'): c.get('comissao', default_comissao) for c in colabs}
        
        # Mapa de Nicks Híbrido
        #mapa_nicks = {}

        # REGRA MANUAL: ID 0 usa a comissão de AutoAtendimento
        mapa_comissao[0] = comissao_auto
        mapa_comissao['0'] = comissao_auto
        mapa_comissao[None] = comissao_auto

        # --- MAPA DE NICKS (COM A NOVA REGRA) ---
        # Inicializamos já com a regra do AutoAtendimento para ID 0 ou Nulo
        mapa_nicks = {
            0: 'AutoAtendimento',
            '0': 'AutoAtendimento',
            None: 'AutoAtendimento',
            'None': 'AutoAtendimento'
        }

        for c in colabs:
            cid = c.get('id_colaborador')
            cnick = c.get('nick') or c.get('nome_colaborador') or f"ID {cid}"
            mapa_nicks[cid] = cnick
            mapa_nicks[str(cid)] = cnick

        # 2. Definição das Coleções
        nome_col_vendas = f"vendas{id_evento_int}"
        nome_col_pagtos = f"pagamentos{id_evento_int}"
        nome_col_cupons = f"vendas_sorte_extra{id_evento_int}" # <--- NOVA TABELA

        # 3. Agregação de VENDAS (BINGO)
        vendas_agg = []
        if nome_col_vendas in db.list_collection_names():
            pipeline = [
                {
                    '$group': {
                        '_id': { 'id_colab': '$id_colaborador', 'origem': '$origem' },
                        'total_qtd': {'$sum': '$quantidade_unidades'},
                        'total_val': {'$sum': '$valor_total'}
                    }
                }
            ]
            vendas_agg = list(db[nome_col_vendas].aggregate(pipeline))

        # 4. Agregação de SORTE EXTRA (NOVO)
        cupons_agg = []
        if nome_col_cupons in db.list_collection_names():
            pipeline_cupons = [
                {
                    '$group': {
                        '_id': '$id_colaborador', # Quem vendeu
                        'total_qtd_cupons': {'$sum': '$qtd_cartelas'}, # Campo Int32
                        'total_val_cupons': {'$sum': '$valor_total'}   # Campo Double
                    }
                }
            ]
            cupons_agg = list(db[nome_col_cupons].aggregate(pipeline_cupons))

        # 5. Agregação de PAGAMENTOS
        pagtos_agg = {}
        if nome_col_pagtos in db.list_collection_names():
            pipeline_pagtos = [
                {
                    '$group': {
                        '_id': '$id_colaborador',
                        'total_pago': {'$sum': '$valor_pago'}
                    }
                }
            ]
            raw_pagtos = list(db[nome_col_pagtos].aggregate(pipeline_pagtos))
            pagtos_agg = {p['_id']: safe_float(p['total_pago']) for p in raw_pagtos}

        # 6. Consolidação dos Dados
        relatorio = {} 
        
        # Processa Vendas BINGO
        for v in vendas_agg:
            id_colab = v['_id'].get('id_colab')
            origem = v['_id'].get('origem')
            qtd = v['total_qtd']
            valor = safe_float(v['total_val'])
            
            taxa = comissao_auto if origem == 'terminal_cliente' else mapa_comissao.get(id_colab, default_comissao)
            valor_comissao = (valor * taxa) / 100.0
            
            if id_colab not in relatorio:
                relatorio[id_colab] = {
                    'id': id_colab,
                    'nick': mapa_nicks.get(id_colab, f'ID {id_colab}') if id_colab != 'N/A' else 'Auto-Atendimento',
                    'qtd': 0, 'vendas': 0.0, 'comissao': 0.0, 
                    'qtd_cupons': 0, 'vendas_cupons': 0.0, # Novos Campos
                    'pago_central': 0.0
                }
            
            relatorio[id_colab]['qtd'] += qtd
            relatorio[id_colab]['vendas'] += valor
            relatorio[id_colab]['comissao'] += valor_comissao

        # Processa SORTE EXTRA (NOVO)
        for c in cupons_agg:
            id_colab_cupom = c['_id']
            qtd_c = c['total_qtd_cupons']
            val_c = safe_float(c['total_val_cupons'])
            
            if id_colab_cupom not in relatorio:
                relatorio[id_colab_cupom] = {
                    'id': id_colab_cupom,
                    'nick': mapa_nicks.get(id_colab_cupom, f'ID {id_colab_cupom}'),
                    'qtd': 0, 'vendas': 0.0, 'comissao': 0.0,
                    'qtd_cupons': 0, 'vendas_cupons': 0.0,
                    'pago_central': 0.0
                }
            
            relatorio[id_colab_cupom]['qtd_cupons'] += qtd_c
            relatorio[id_colab_cupom]['vendas_cupons'] += val_c

        # Processa Pagamentos
        for id_colab_pag, valor_pago in pagtos_agg.items():
            if id_colab_pag not in relatorio:
                relatorio[id_colab_pag] = {
                    'id': id_colab_pag,
                    'nick': mapa_nicks.get(id_colab_pag, f'ID {id_colab_pag}'),
                    'qtd': 0, 'vendas': 0.0, 'comissao': 0.0,
                    'qtd_cupons': 0, 'vendas_cupons': 0.0,
                    'pago_central': 0.0
                }
            relatorio[id_colab_pag]['pago_central'] += valor_pago

# 7. Totais Finais (COM ATUALIZAÇÃO DE PRÊMIOS DIVIDIDOS)
        lista_final = []
        totais = {
            'vendas': 0.0, 'qtd': 0, 'comissao': 0.0, 
            'vendas_cupons': 0.0, 'qtd_cupons': 0, 
            'pago_central': 0.0, 'pendente_central': 0.0,
            'premios_pagos': 0.0 
        }

        for dados in relatorio.values():
            # Cálculo do Líquido Devido
            liquido_bingo = dados['vendas'] - dados['comissao']
            liquido_total_devido = liquido_bingo + dados['vendas_cupons']
            
            # Regra: AutoAtendimento já conta como pago
            if dados['id'] in [0, '0', None, 'None']:
                dados['pago_central'] = liquido_total_devido
            
            # Cálculo do Saldo Final (Dívida)
            saldo_final = liquido_total_devido - dados['pago_central']
            
            dados['pendente'] = saldo_final if saldo_final > 0 else 0.0
            dados['a_receber_colab'] = abs(saldo_final) if saldo_final < 0 else 0.0
            
            lista_final.append(dados)
            
            # Soma Totais Gerais
            totais['vendas'] += dados['vendas']
            totais['qtd'] += dados['qtd']
            totais['comissao'] += dados['comissao']
            totais['vendas_cupons'] += dados['vendas_cupons']
            totais['qtd_cupons'] += dados['qtd_cupons']
            totais['pago_central'] += dados['pago_central'] 
            totais['pendente_central'] += dados['pendente']

        lista_final.sort(key=lambda x: str(x['nick']))
        
        # --- LÓGICA DE PRÊMIOS (BINGO + EXTRA) ---
        premio_bingo = safe_float(evento.get('premio_total', 0)) # Campo original
        premio_extra = safe_float(evento.get('premios_sorte_extra', 0)) # Novo Campo
        
        premio_total_geral = premio_bingo + premio_extra
        
        premios_pagos = 0.0 
        premios_pendentes = premio_total_geral - premios_pagos
        # -----------------------------------------
        
        # Saldo Projetado (Receita Líquida - Total de Prêmios)
        receita_liquida_casa = (totais['vendas'] - totais['comissao']) + totais['vendas_cupons']
        saldo_evento_projetado = receita_liquida_casa - premio_total_geral

        dados_painel = {
            'total_vendas_bingo': totais['vendas'],
            'total_vendas_cupons': totais['vendas_cupons'],
            'receita_bruta_total': totais['vendas'] + totais['vendas_cupons'],
            'total_comissao': totais['comissao'],
            
            # Novos Dados de Prêmio para o Template
            'premio_bingo': premio_bingo,
            'premio_extra': premio_extra,
            'premio_total_geral': premio_total_geral,
            
            'saldo_projetado': saldo_evento_projetado,
            'total_recebido': totais['pago_central'],
            'total_a_receber': totais['pendente_central'],
            'premios_pagos': premios_pagos,
            'premios_pendentes': premios_pendentes
        }
        
        return render_template('financeiro_evento.html', 
                               evento=evento, 
                               lista=lista_final, 
                               painel=dados_painel,
                               totais=totais,
                               g=g)

    except Exception as e:
        print(f"Erro financeiro_evento: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('financeiro_evento', error=f"Erro interno: {e}"))



# --- ROTA UTILITÁRIA: LIMPAR TABELA ESPECÍFICA ---
@app.route('/admin/limpar_tabela/<string:nome_tabela>', methods=['GET'])
@login_required
def limpar_tabela_dinamica(nome_tabela):
    """
    Limpa todos os dados de uma tabela específica passada por parâmetro na URL.
    Uso: /admin/limpar_tabela/nome_da_colecao
    """
    db = get_vendas_db()
    if db is None: 
        return jsonify({'status': 'error', 'msg': 'Banco de dados offline.'}), 500

    # 1. SEGURANÇA: Apenas Nível 3 (Admin)
    if session.get('nivel', 0) < 3:
        return jsonify({'status': 'error', 'msg': 'ACESSO NEGADO: Apenas administradores.'}), 403

    # 2. SEGURANÇA: Lista de tabelas INTOCÁVEIS (Para não quebrar o sistema)
    tabelas_proibidas = ['colaboradores', 'parametros', 'salas', 'contadores']
    
    if nome_tabela in tabelas_proibidas:
        return jsonify({
            'status': 'error', 
            'msg': f'PROIBIDO: A tabela "{nome_tabela}" é crítica para o sistema e não pode ser limpa por aqui.'
        }), 400

    try:
        # Verifica se a coleção existe antes de tentar limpar
        if nome_tabela not in db.list_collection_names():
             return jsonify({'status': 'error', 'msg': f'A tabela "{nome_tabela}" não existe no banco.'}), 404

        # 3. EXECUÇÃO: Apaga todos os registros (mantém a estrutura e índices)
        # Se quiser apagar a tabela inteira (drop), use: db[nome_tabela].drop()
        resultado = db[nome_tabela].delete_many({})
        
        msg = f"SUCESSO: Foram removidos {resultado.deleted_count} registros da tabela '{nome_tabela}'."
        print(f"[AUDITORIA] Admin {session.get('nick')} limpou a tabela {nome_tabela}.")
        
        return jsonify({
            'status': 'success',
            'msg': msg,
            'registros_removidos': resultado.deleted_count
        })

    except Exception as e:
        return jsonify({'status': 'error', 'msg': f'Erro interno: {e}'}), 500


@app.route('/salvar_senha_obrigatoria', methods=['POST'])
@login_required 
def salvar_senha_obrigatoria():
    db = get_vendas_db()
    if db is None: 
        return render_template('trocar_senha_obrigatoria.html', error="Erro de conexão com o banco.", id_sala=g.id_sala)

    nova_senha = request.form.get('nova_senha', '').strip()
    confirma_senha = request.form.get('confirma_senha', '').strip()
    
    if not nova_senha or not confirma_senha:
        return render_template('trocar_senha_obrigatoria.html', error="Preencha os dois campos.", id_sala=g.id_sala)
    
    if nova_senha != confirma_senha:
        return render_template('trocar_senha_obrigatoria.html', error="As senhas não conferem.", id_sala=g.id_sala)
    
    senha_formatada = nova_senha.capitalize()
    if senha_formatada == "Senha":
        return render_template('trocar_senha_obrigatoria.html', error="A nova senha NÃO pode ser a senha padrão 'Senha'.", id_sala=g.id_sala)

    try:
        hashed_password = bcrypt.hashpw(senha_formatada.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        tipo = session.get('tipo_usuario_logado')
        
        if tipo == 'colaborador':
            id_colab = session.get('id_colaborador')
            query = {'id_colaborador': int(id_colab)} if str(id_colab).isdigit() else {'_id': try_object_id(id_colab)}
            
            db.colaboradores.update_one(query, {'$set': {'senha': hashed_password}})
            return redirect(url_for('menu_operacoes'))
            
        # BLOCO DE CLIENTE REMOVIDO DAQUI
            
        else:
            session.clear()
            return redirect(url_for('login_page', error="Sessão inválida ou tipo de usuário não permitido para esta operação."))

    except Exception as e:
        print(f"Erro ao salvar nova senha: {e}")
        return render_template('trocar_senha_obrigatoria.html', error=f"Erro interno: {e}", id_sala=g.id_sala)


#=====================================
# Rotas da Sorte Extra
#=====================================
@app.route('/controle_sorte_extra')
@login_required
def controle_sorte_extra():
    db = get_vendas_db()
    if db is None: 
        return redirect(url_for('menu_operacoes', error="Banco de Dados Offline"))
    
    # Busca eventos que não estão finalizados para o select
    eventos_ativos = list(db.eventos.find(
        {"status": {"$ne": "finalizado"}}, 
        {"id_evento": 1, "descricao": 1, "data_evento": 1, "hora_evento": 1}
    ).sort("data_evento", -1))
    
    # Busca a configuração atual (único registro)
    config = db.sorte_extra_config.find_one({})
    
    # Tratamento para exibir valores decimais corretamente no template
    if config:
        for campo in ['preco_cupom', 'premio_maximo', 'premio_intermediario', 'premio_base', 'premio_minimo']:
            if campo in config:
                config[campo] = safe_float(config[campo])

    return render_template('controle_sorte_extra_config.html', 
                           eventos=eventos_ativos, 
                           config=config,
                           g=g)

                       
@app.route('/salvar_config_sorte_extra', methods=['POST'])
@login_required
def salvar_config_sorte_extra():
    db = get_vendas_db()
    if db is None: 
        return redirect(url_for('menu_operacoes', error="Banco de Dados Offline"))

    def validar_decimal(valor):
        """
        Limpa a string do formulário e garante que o Decimal128 
        receba um valor numérico válido, evitando o erro ConversionSyntax.
        """
        if not valor:
            return Decimal128("0.00")
        
        try:
            # Remove R$, espaços e ajusta padrão brasileiro (1.000,00 -> 1000.00)
            limpo = str(valor).replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
            
            # Se após a limpeza sobrar apenas um ponto ou nada, retorna zero
            if limpo == "." or not limpo:
                return Decimal128("0.00")
                
            return Decimal128(limpo)
        except Exception:
            return Decimal128("0.00")

    try:
        id_evento_raw = request.form.get('id_evento')
        if not id_evento_raw:
            return redirect(url_for('controle_sorte_extra', error="Selecione um evento."))

        id_evento = int(id_evento_raw)
        
        # Busca detalhes do evento para compor a string de exibição
        evento_info = db.eventos.find_one({'id_evento': id_evento})
        if not evento_info:
            return redirect(url_for('controle_sorte_extra', error="Evento não localizado."))
            
        desc_completa = f"{evento_info.get('descricao')} - {evento_info.get('data_evento')} {evento_info.get('hora_evento')}"

        # Montagem dos dados tratando cada campo individualmente
        dados_config = {
            "id_evento": id_evento,
            "qtde_dezenas": int(request.form.get('qtde_dezenas', 5) or 5),
            "qtde_tope_sorte_extra": int(request.form.get('qtde_tope_sorte_extra', 10) or 10),
            "preco_cupom": validar_decimal(request.form.get('preco_cupom')),
            "premio_maximo": validar_decimal(request.form.get('premio_maximo')),
            "premio_intermediario": validar_decimal(request.form.get('premio_intermediario')),
            "premio_base": validar_decimal(request.form.get('premio_base')),
            "premio_minimo": validar_decimal(request.form.get('premio_minimo')),
            "texto_regra_vitoria": request.form.get('texto_regra_vitoria', ''),
            "data_hora_evento": desc_completa,
            "status": request.form.get('status', 'paralisado'),
            "data_atualizacao": hora_brasil()
        }

        # O MongoDB criará o campo 'premio_minimo' automaticamente aqui se ele não existir
        db.sorte_extra_config.update_one({}, {"$set": dados_config}, upsert=True)

        return redirect(url_for('controle_sorte_extra', success="Parâmetros da Sorte Extra salvos com sucesso!"))

    except Exception as e:
        print(f"Erro ao salvar config sorte extra: {e}")
        return redirect(url_for('controle_sorte_extra', error=f"Erro na gravação: {str(e)}"))


@app.route('/api/previa_replicacao', methods=['POST'])
@login_required
def previa_replicacao():
    """
    Recebe os dados via AJAX e calcula os próximos N horários com base no intervalo.
    Verifica no banco se cada horário está livre (retorna True/False para cada).
    """
    db = get_vendas_db()
    if db is None:
        return jsonify({"error": "Banco de dados inacessível"}), 500

    dados = request.get_json()
    
    if not dados:
        return jsonify({"error": "Nenhum dado recebido."}), 400

    id_evento_molde = dados.get('id_evento')
    
    # Assegura que qtd e intervalo são inteiros para evitar erros de cálculo
    try:
        qtd = int(dados.get('qtd', 1))
        intervalo_minutos = int(dados.get('intervalo', 30))
    except (ValueError, TypeError) as e:
        return jsonify({"error": "Quantidade ou intervalo inválidos."}), 400

    if not id_evento_molde:
        return jsonify({"error": "ID do evento não fornecido."}), 400

    try:
        # 1. Obter o evento molde
        evento_molde = db.eventos.find_one({'id_evento': int(id_evento_molde)})
        if not evento_molde:
            return jsonify({"error": "Evento molde não encontrado."}), 404
        
        # 2. Reconstruir a data/hora original do evento (DD/MM/YYYY HH:MM)
        data_str = evento_molde.get('data_evento')
        hora_str = evento_molde.get('hora_evento')
        
        if not data_str or not hora_str:
             return jsonify({"error": "Evento molde com dados de data/hora incompletos."}), 400
             
        base_dt = datetime.strptime(f"{data_str} {hora_str}", "%d/%m/%Y %H:%M")

        lista_previa = []

        # 3. Calcular e verificar os próximos N slots
        for i in range(1, qtd + 1):
            # O primeiro slot criado é base + (1 * intervalo)
            proximo_dt = base_dt + timedelta(minutes=intervalo_minutos * i)
            
            data_formatada_verificar = proximo_dt.strftime("%d/%m/%Y")
            hora_formatada_verificar = proximo_dt.strftime("%H:%M")

            # Verifica colisão
            existe = db.eventos.find_one({
                "data_evento": data_formatada_verificar,
                "hora_evento": hora_formatada_verificar
            })

            lista_previa.append({
                "data_hora_formatada": proximo_dt.strftime("%d/%m/%Y às %H:%M"),
                "livre": not bool(existe)
            })
            
        return jsonify({"previa": lista_previa})

    except Exception as e:
        import traceback
        traceback.print_exc() # Imprime a stack trace completa no console para ajudar no debug
        return jsonify({"error": "Erro interno ao calcular horários."}), 500


@app.route('/api/gravar_replicacao', methods=['POST'])
@login_required
def gravar_replicacao():
    """
    Rota final que grava as cópias caso o operador confirme.
    Refaz a verificação de segurança por precaução.
    """
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    db = get_vendas_db()
    if db is None:
        return redirect(url_for('menu_operacoes', error="Banco de Dados Offline"))

    id_evento_molde = int(request.form.get('id_evento_molde'))
    qtd = int(request.form.get('qtd', 0))
    intervalo_minutos = int(request.form.get('intervalo', 0))
    status_replicas = request.form.get('status_replicas', 'paralizado')

    if qtd <= 0 or intervalo_minutos <= 0:
        return redirect(url_for('cadastro_evento', view='alterar', id_evento=id_evento_molde, error="Parâmetros inválidos."))

    try:
        evento_molde = db.eventos.find_one({'id_evento': id_evento_molde})
        if not evento_molde:
            raise ValueError("Evento molde não localizado.")

        # Data Base
        base_dt = datetime.strptime(f"{evento_molde['data_evento']} {evento_molde['hora_evento']}", "%d/%m/%Y %H:%M")
        
        # Resgatar e formatar o prémio para a nova descrição
        # Trata o Decimal128 caso venha do Mongo
        premio_bruto = evento_molde.get('premio_total', Decimal128("0.00"))
        if isinstance(premio_bruto, Decimal128):
            premio_bruto = float(premio_bruto.to_decimal())
        
        # Formatação: 1500.0 -> "1.500,00" (Ajuste padrão brasileiro de moeda)
        premio_formatado = f"{premio_bruto:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

        eventos_para_inserir = []

        # Dupla verificação de segurança (backend check)
        for i in range(1, qtd + 1):
            novo_dt = base_dt + timedelta(minutes=intervalo_minutos * i)
            data_str = novo_dt.strftime("%d/%m/%Y")
            hora_str = novo_dt.strftime("%H:%M")

            if db.eventos.find_one({"data_evento": data_str, "hora_evento": hora_str}):
                return redirect(url_for('cadastro_evento', view='alterar', id_evento=id_evento_molde, 
                                        error=f"Conflito de horário detectado em {data_str} {hora_str}. Cancelado."))

            # Gera ID Seguro
            novo_id = get_next_evento_sequence()

            # REGRA 3: Formatação Automática da Descrição
            nova_descricao = f"{novo_dt.strftime('%d/%m')} às {hora_str} - R$ {premio_formatado}"

            # Cópia profunda do dicionário, removendo a raiz do MongoDB
            novo_evento = evento_molde.copy()
            if '_id' in novo_evento:
                del novo_evento['_id']

            # Atualização dos campos específicos da réplica
            novo_evento.update({
                "id_evento": novo_id,
                "data_evento": data_str,
                "hora_evento": hora_str,
                "data_hora_evento": novo_dt,
                "descricao": nova_descricao,
                "status": status_replicas,
                "data_ativado": None if status_replicas != 'ativo' else hora_brasil(),
                "data_cadastro": hora_brasil(),
                "id_colaborador": session.get('id_colaborador', 'N/A')
            })

            eventos_para_inserir.append(novo_evento)

        # Inserção em Lote (Bulk Insert)
        if eventos_para_inserir:
            db.eventos.insert_many(eventos_para_inserir)
            msg = f"Sucesso! {qtd} evento(s) replicado(s) com o status '{status_replicas}'."
            return redirect(url_for('cadastro_evento', success=msg, view='listar'))
        
        return redirect(url_for('cadastro_evento', view='listar'))

    except Exception as e:
        return redirect(url_for('cadastro_evento', view='alterar', id_evento=id_evento_molde, error="Falha ao replicar eventos."))


@app.route('/parametros', methods=['GET'])
@login_required
def parametros():
    """
    Exibe a tela de configuração técnica.
    Bloqueia o acesso de qualquer utilizador que não seja o TECBIN.
    """
    # 1. VALIDAÇÃO DE SEGURANÇA (EASTER EGG LOCK)
    nick_operador = session.get('nick', '').upper()
    nome_operador = session.get('operador', '').upper()
    
    if nick_operador != 'TECBIN' and nome_operador != 'TECBIN':
        print(f"[SECURITY] Tentativa de acesso não autorizada a /parametros por: {nick_operador or nome_operador}")
        return redirect(url_for('menu_operacoes', error="Acesso Negado: Permissão de Engenharia Necessária."))

    db = get_vendas_db()
    if db is None:
        return redirect(url_for('menu_operacoes', error="Banco de dados inacessível."))

    # 2. CARREGAR DADOS EXISTENTES (OU INICIALIZAR VAZIO)
    param_doc = db.parametros.find_one({})
    
    # Se o documento não existir, criamos a estrutura base em memória
    if not param_doc:
        param_doc = {
            'comissao_padrao': 0,
            'limite_de_credito': 0,
            'acumulado': Decimal128("0.00"),
            'tope': 0,
            'porcento_premios': 0,
            'porcento_15': {'linha': Decimal128("0.00"), 'bingo': Decimal128("0.00"), 'segundobingo': Decimal128("0.00")},
            'porcento_25': {'linha': Decimal128("0.00"), 'bingo': Decimal128("0.00")},
            'porcento_25_4cantos': {'4cantos': Decimal128("0.00"), 'linha': Decimal128("0.00"), 'bingo': Decimal128("0.00")},
            'porcento_15_3linhas': {'linhas': Decimal128("0.00"), 'bingo': Decimal128("0.00"), 'segundobingo': Decimal128("0.00")},
            'porcento_15_quadra': {'quadra': Decimal128("0.00"), 'linha': Decimal128("0.00"), 'bingo': Decimal128("0.00"), 'segundobingo': Decimal128("0.00")}
        }
    
    # Garantir que os sub-objetos existem, mesmo em documentos parcialmente preenchidos antigos
    p15 = param_doc.get('porcento_15', {})
    p25 = param_doc.get('porcento_25', {})
    p25_4cantos = param_doc.get('porcento_25_4cantos', {})
    p15_3linhas = param_doc.get('porcento_15_3linhas', {})
    p15_quadra  = param_doc.get('porcento_15_quadra', {})

    # Objeto simplificado para o template (AGORA UTILIZANDO safe_get_int)
    context_p = {
        'comissao_padrao': safe_get_int(param_doc.get('comissao_padrao', 0)),
        'limite_de_credito': safe_get_int(param_doc.get('limite_de_credito', 0)),
        'acumulado': safe_get_float(param_doc.get('acumulado', 0)),
        'tope': safe_get_int(param_doc.get('tope', 0)),
        'porcento_premios': safe_get_int(param_doc.get('porcento_premios', 0)),

        # --- NOVOS CAMPOS (ROBÔ E INTEGRAÇÕES) ---
        'tempo_atualizacao_premios': safe_get_int(param_doc.get('tempo_atualizacao_premios', 1)),
        'minimo_atualizacao_premios': safe_get_float(param_doc.get('minimo_atualizacao_premios', 50.0)),
        'receber_pix': bool(param_doc.get('receber_pix', False)),
        'chat_id_telegram': param_doc.get('chat_id_telegram', ''),
        'token_telegram': param_doc.get('token_telegram', ''),
        
        # Padrão
        'porcento_15_linha': safe_get_float(p15.get('linha', 0)),
        'porcento_15_bingo': safe_get_float(p15.get('bingo', 0)),
        'porcento_15_segundobingo': safe_get_float(p15.get('segundobingo', 0)),
        
        'porcento_25_linha': safe_get_float(p25.get('linha', 0)),
        'porcento_25_bingo': safe_get_float(p25.get('bingo', 0)),
        
        # 25 Números - 4 Cantos
        'porcento_25_4cantos_4cantos': safe_get_float(p25_4cantos.get('4cantos', 0)),
        'porcento_25_4cantos_linha': safe_get_float(p25_4cantos.get('linha', 0)),
        'porcento_25_4cantos_bingo': safe_get_float(p25_4cantos.get('bingo', 0)),
        
        # 15 Números - 3 Linhas
        'porcento_15_3linhas_linhas': safe_get_float(p15_3linhas.get('linhas', 0)),
        'porcento_15_3linhas_bingo': safe_get_float(p15_3linhas.get('bingo', 0)),
        'porcento_15_3linhas_segundobingo': safe_get_float(p15_3linhas.get('segundobingo', 0)),
        
        # 15 Números - Quadra
        'porcento_15_quadra_quadra': safe_get_float(p15_quadra.get('quadra', 0)),
        'porcento_15_quadra_linha': safe_get_float(p15_quadra.get('linha', 0)),
        'porcento_15_quadra_bingo': safe_get_float(p15_quadra.get('bingo', 0)),
        'porcento_15_quadra_segundobingo': safe_get_float(p15_quadra.get('segundobingo', 0)),
    }

    return render_template(
        'parametros.html', 
        p=context_p, 
        error=request.args.get('error'), 
        success=request.args.get('success')
    )


@app.route('/gravar_parametros', methods=['POST'])
@login_required
def gravar_parametros():
    """
    Grava os parâmetros na base de dados formatando devidamente para Decimal128 e Object.
    Valida se as percentagens de cada grupo somam 100%.
    """
    # 1. NOVA VALIDAÇÃO DE SEGURANÇA NA ESCRITA
    nick_operador = session.get('nick', '').upper()
    nome_operador = session.get('operador', '').upper()
    
    if nick_operador != 'TECBIN' and nome_operador != 'TECBIN':
        return redirect(url_for('menu_operacoes', error="Acesso Negado na Gravação."))

    db = get_vendas_db()

    try:
        def get_float_val(field_name):
            try:
                return float(request.form.get(field_name, '0').replace(',', '.'))
            except:
                return 0.0
     
        porcento_premios_val = int(request.form.get('porcento_premios', 0))

        # VALIDAÇÃO A 100% PARA CADA GRUPO
        # Somente se a distribuição de prémios percentuais estiver ativada (> 0)
        if porcento_premios_val > 0:
            
            # Padrão 15
            soma_15 = get_float_val('porcento_15_linha') + get_float_val('porcento_15_bingo') + get_float_val('porcento_15_segundobingo')
            if abs(soma_15 - 100.0) > 0.01: # Permite uma margem de erro de arredondamento ínfima
                 return redirect(url_for('parametros', error=f"Erro: O total de prémios para 15 Números (Padrão) deve ser exatamente 100%. Atualmente é {soma_15}%."))

            # Padrão 25
            soma_25 = get_float_val('porcento_25_linha') + get_float_val('porcento_25_bingo')
            if abs(soma_25 - 100.0) > 0.01:
                 return redirect(url_for('parametros', error=f"Erro: O total de prémios para 25 Números (Padrão) deve ser exatamente 100%. Atualmente é {soma_25}%."))

            # 25 - 4 Cantos
            soma_25_4cantos = get_float_val('porcento_25_4cantos_4cantos') + get_float_val('porcento_25_4cantos_linha') + get_float_val('porcento_25_4cantos_bingo')
            if abs(soma_25_4cantos - 100.0) > 0.01:
                 return redirect(url_for('parametros', error=f"Erro: O total para 25 Números (4 Cantos) deve ser 100%. Atualmente é {soma_25_4cantos}%."))

            # 15 - 3 Linhas
            soma_15_3linhas = get_float_val('porcento_15_3linhas_linhas') + get_float_val('porcento_15_3linhas_bingo') + get_float_val('porcento_15_3linhas_segundobingo')
            if abs(soma_15_3linhas - 100.0) > 0.01:
                 return redirect(url_for('parametros', error=f"Erro: O total para 15 Números (3 Linhas) deve ser 100%. Atualmente é {soma_15_3linhas}%."))

            # 15 - Quadra
            soma_15_quadra = get_float_val('porcento_15_quadra_quadra') + get_float_val('porcento_15_quadra_linha') + get_float_val('porcento_15_quadra_bingo') + get_float_val('porcento_15_quadra_segundobingo')
            if abs(soma_15_quadra - 100.0) > 0.01:
                 return redirect(url_for('parametros', error=f"Erro: O total para 15 Números (Quadra) deve ser 100%. Atualmente é {soma_15_quadra}%."))


        # 2. CONSTRUÇÃO DO DICIONÁRIO DE ATUALIZAÇÃO
        dados_atualizados = {
            'comissao_padrao': int(request.form.get('comissao_padrao', 0)),
            'limite_de_credito': int(request.form.get('limite_de_credito', 0)),
            'acumulado': safe_dec(request.form.get('acumulado', '0')),
            'tope': int(request.form.get('tope', 0)),
            'porcento_premios': int(request.form.get('porcento_premios', 0)),

            # --- NOVOS CAMPOS CORRIGIDOS (ROBÔ E INTEGRAÇÕES) ---
            'tempo_atualizacao_premios': int(request.form.get('tempo_atualizacao_premios', 1)),
            'minimo_atualizacao_premios': safe_dec(request.form.get('minimo_atualizacao_premios', '50.00')),
            'receber_pix': True if request.form.get('receber_pix') else False,
            'chat_id_telegram': request.form.get('chat_id_telegram', '').strip(),
            'token_telegram': request.form.get('token_telegram', '').strip(),
            

            # Aninhando os objetos padrão
            'porcento_15': {
                'linha': safe_dec(request.form.get('porcento_15_linha', '0')),
                'bingo': safe_dec(request.form.get('porcento_15_bingo', '0')),
                'segundobingo': safe_dec(request.form.get('porcento_15_segundobingo', '0'))
            },
            'porcento_25': {
                'linha': safe_dec(request.form.get('porcento_25_linha', '0')),
                'bingo': safe_dec(request.form.get('porcento_25_bingo', '0'))
            },
            
            # Aninhando os novos objetos
            'porcento_25_4cantos': {
                '4cantos': safe_dec(request.form.get('porcento_25_4cantos_4cantos', '0')),
                'linha': safe_dec(request.form.get('porcento_25_4cantos_linha', '0')),
                'bingo': safe_dec(request.form.get('porcento_25_4cantos_bingo', '0'))
            },
            'porcento_15_3linhas': {
                'linhas': safe_dec(request.form.get('porcento_15_3linhas_linhas', '0')),
                'bingo': safe_dec(request.form.get('porcento_15_3linhas_bingo', '0')),
                'segundobingo': safe_dec(request.form.get('porcento_15_3linhas_segundobingo', '0'))
            },
            'porcento_15_quadra': {
                'quadra': safe_dec(request.form.get('porcento_15_quadra_quadra', '0')),
                'linha': safe_dec(request.form.get('porcento_15_quadra_linha', '0')),
                'bingo': safe_dec(request.form.get('porcento_15_quadra_bingo', '0')),
                'segundobingo': safe_dec(request.form.get('porcento_15_quadra_segundobingo', '0'))
            }
        }

        # 3. UPSERT NO MONGODB
        # Atualiza o primeiro documento encontrado ou cria um novo se a coleção estiver vazia
        db.parametros.update_one({}, {'$set': dados_atualizados}, upsert=True)
        
        print(f"[SYS ADMIN] Parâmetros técnicos atualizados com sucesso por TECBIN.")
        return redirect(url_for('parametros', success="Parâmetros atualizados e gravados na base de dados com sucesso!"))

    except Exception as e:
        print(f"Erro Crítico ao gravar parâmetros: {e}")
        return redirect(url_for('parametros', error=f"Erro interno ao salvar as configurações: {e}"))


def motor_background_premios():
    """
    Background Thread: Roda a cada X minutos varrendo as salas.
    Localiza eventos cujo 'valor_pendente_telemovel' atingiu o gatilho,
    recalcula os prêmios e subtrai o valor lido para evitar perda de concorrência.
    """
    print("[ROBÔ] 🤖 Inicializando thread de recálculo de prêmios...")
    
    while True:
        # Aguarda até o banco principal estar conectado
        if db_control is None:
            time.sleep(10)
            continue
            
        tempo_sleep_global = 60 # Padrão: 60 segundos
        
        try:
            # 1. Procura todas as salas ativas
            salas = list(db_control.salas.find({}, {"id_sala": 1, "url_parte1": 1, "url_parte2": 1}))
            
            for sala in salas:
                id_sala = sala.get('id_sala')
                
                try:
                    # Conecta ao banco de vendas da sala (usa cache se possível)
                    client_sala = DB_VENDAS_CLIENT_CACHE.get(id_sala)
                    if not client_sala:
                        uri_vendas = f"{sala['url_parte1']}{ENCODED_PASSWORD}{sala['url_parte2']}"
                        client_sala = MongoClient(uri_vendas, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
                        DB_VENDAS_CLIENT_CACHE[id_sala] = client_sala
                        
                    db_sala = client_sala[DB_NAME_VENDAS]
                    
                    # 2. Busca os parâmetros de gatilho
                    params = db_sala.parametros.find_one({}) or {}
                    minimo_atualizacao = safe_float(params.get('minimo_atualizacao_premios', 50.0))
                    tempo_sala = safe_get_int(params.get('tempo_atualizacao_premios', 1)) * 60
                    
                    if tempo_sala > 0:
                        tempo_sleep_global = tempo_sala

                    # 3. Busca APENAS eventos que bateram a meta de acumulação
                    query_eventos = {
                        "status": "ativo",
                        "tipo_premiacao": "Porcentagem",
                        "valor_pendente_telemovel": {"$gte": minimo_atualizacao}
                    }
                    
                    eventos_para_atualizar = list(db_sala.eventos.find(query_eventos))
                    
                    for ev in eventos_para_atualizar:
                        # TRAVA DE SEGURANÇA: Lê o exato valor antes de calcular
                        valor_lido = safe_float(ev.get('valor_pendente_telemovel', 0))
                        
                        if valor_lido >= minimo_atualizacao:
                            # Chama a nossa função principal que atualiza e grava a premiação
                            calcular_premios_dinamicos(db_sala, ev, params)
                            
                            # MÁGICA DA CONCORRÊNCIA: Subtrai exatamente o que lemos. 
                            # Se entraram R$5 durante o cálculo, eles continuam lá!
                            db_sala.eventos.update_one(
                                {"_id": ev["_id"]},
                                {"$inc": {"valor_pendente_telemovel": -valor_lido}}
                            )
                            print(f"[ROBÔ SALA {id_sala}] 🚀 Prêmio EVE{ev['id_evento']} atualizado! Buffer abatido em: R$ {valor_lido:.2f}")

                except Exception as e_sala:
                    print(f"[ROBÔ ERRO] Falha ao processar sala {id_sala}: {e_sala}")
                    
        except Exception as e_global:
            print(f"[ROBÔ ERRO GLOBAL] Falha no loop principal do robô: {e_global}")
            
        # O robô volta a dormir pelos minutos configurados no painel Parâmetros
        time.sleep(tempo_sleep_global)

# Inicia o robô invisível junto com a inicialização do Flask
threading.Thread(target=motor_background_premios, daemon=True).start()


# =============================
# Correcções do sistema
# =============================

@app.route('/admin/popular_bloqueios')
@login_required
def popular_bloqueios():
    """
    Popula a tabela 'config_bloqueio' com um único documento contendo 
    o array de termos proibidos, apagando qualquer registro anterior.
    Acessível apenas para administradores de nível 3.
    """
    # 1. Verificação de segurança: Apenas administradores nível 3
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso negado. Nível 3 requerido."))

    db = get_vendas_db()
    if db is None:
        return redirect(url_for('cadastro_cliente', error="Erro de ligação à base de dados."))

    try:
        # 2. Lista de termos fornecida para bloqueio
        termos_para_bloquear = [
            "site_concorrente", "golpe", "fraude", "puta", "puto", "caralho", 
            "porra", "buceta", "boceta", "pica", "merda", "cu", "cuzão", 
            "viado", "arrombado", "foda", "pinto", "rola", "cacete", 
            "piranha", "vagabundo", "vagabunda", "corno", "xoxota", 
            "chupa", "chupeta", "putaria", "bicha", "traveco", "rapariga", 
            "prostituta", "veado", "bichona", "vagina", "bosta", "fuck", 
            "vaca", "boi", "penis", "xola"
        ]

        # 3. Limpeza e padronização da lista (remove duplicados e ordena)
        termos_limpos = sorted(list(set([t.strip().lower() for t in termos_para_bloquear])))

        # 4. ROTINA DE LIMPEZA: Apaga todos os registros existentes na coleção
        delete_result = db.config_bloqueio.delete_many({})
        print(f"[MANUTENÇÃO] Removidos {delete_result.deleted_count} registros antigos de bloqueio.")

        # 5. Execução da gravação do novo documento único (Array Format)
        db.config_bloqueio.update_one(
            {'tipo': 'nicks_proibidos'},
            {
                '$set': {
                    'tipo': 'nicks_proibidos',
                    'palavras': termos_limpos,
                    'data_atualizacao': hora_brasil()
                }
            },
            upsert=True
        )

        contagem = len(termos_limpos)
        msg = f"Limpeza concluída e lista atualizada! {contagem} termos salvos no formato oficial."
        print(f"[LOG ADMIN] {session.get('nick')} resetou e atualizou bloqueios na sala {g.id_sala}.")
        
        return redirect(url_for('cadastro_cliente', success=msg, view='bloqueio'))

    except Exception as e:
        print(f"Erro ao processar limpeza/população de bloqueios: {e}")
        return redirect(url_for('cadastro_cliente', error=f"Erro interno: {e}"))


@app.route('/admin/corrigir_senhas_faltantes')
@login_required
def corrigir_senhas_faltantes():
    """
    Localiza clientes sem o campo 'senha' no banco de dados da sala atual 
    e define a senha padrão como 'Senha' (com S maiúsculo) via bcrypt.
    """
    # 1. Segurança: Permite acesso apenas para administradores nível 3
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso negado. Nível 3 requerido."))

    # 2. Obtém a conexão com o banco de dados dinâmico da sala ativa
    db = get_vendas_db()
    if db is None:
        return redirect(url_for('cadastro_cliente', error="Erro de conexão com o banco de dados."))

    try:
        # 3. Gera o hash para a string "Senha"
        # O salt é gerado automaticamente pelo bcrypt.gensalt()
        senha_padrao = "Senha"
        hashed = bcrypt.hashpw(senha_padrao.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # 4. Filtro para encontrar documentos onde o campo 'senha' NÃO existe
        filtro = {"senha": {"$exists": False}}
        
        # 5. Executa a atualização em massa (update_many)
        # O operador $set criará o campo para quem não tem
        resultado = db.clientes.update_many(
            filtro,
            {"$set": {"senha": hashed}}
        )

        # 6. Retorna para a listagem com a contagem de quantos foram corrigidos
        msg = f"Manutenção concluída! {resultado.modified_count} clientes foram atualizados com a senha 'Senha'."
        print(f"[MANUTENÇÃO] Admin {session.get('nick')} corrigiu senhas na sala {g.id_sala}.")
        
        return redirect(url_for('cadastro_cliente', success=msg, view='listar'))

    except Exception as e:
        # Log de erro caso algo falhe no processo de banco ou criptografia
        print(f"Erro na manutenção de senhas: {e}")
        return redirect(url_for('cadastro_cliente', error=f"Erro interno na correção: {e}"))


if __name__ == '__main__':
    # Para desenvolvimento local apenas
    if os.environ.get('FLASK_ENV') != 'production':
        app.run(debug=True, host='0.0.0.0', port=5001)
    else:
        print("⚠️  AVISO: Em produção, use Gunicorn. Não execute app.py diretamente!")


# limpar registros de tala tebela; exemplo tabela "requisao_saque"
# deve estar logando como administrador
#http://localhost:5001/admin/limpar_tabela/requisao_saque