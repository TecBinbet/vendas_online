# app.py (Versão Refatorada para Conexão Dinâmica por Sala)

import threading
import pymongo
from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, make_response, Response
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson.objectid import ObjectId
from bson.decimal128 import Decimal128
from datetime import datetime
from urllib.parse import quote_plus
import os
import re # Para a busca de clientes e limpeza de nome
import bcrypt
import io # Para manipulação de arquivos em memória
from functools import wraps # Para o decorator login_required
from datetime import timedelta
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
    now_utc = datetime.utcnow()
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

    # 1. CRÍTICO: Inicialização de variáveis globais em 'g'
    if not hasattr(g, 'client_control'):
        g.client_control = client_control
        g.db_control = db_control
    if not hasattr(g, 'parametros_globais'):
        g.parametros_globais = {}
    if not hasattr(g, 'db_status'):
        g.db_status = False
        
    # 2. Lógica Dinâmica da Sala ("Sticky Session")
    id_sala_url = request.args.get('id_sala')
    id_sala_sessao = session.get('id_sala')
    
    id_sala_final = None

    is_root_request = (request.path == '/')
    """
    if id_sala_url:
        # Prioridade 1: URL (Mudar de sala explicitamente)
        id_sala_final = id_sala_url
        session['id_sala'] = id_sala_url 
        print(f"[1] @before_request: Sala definida via URL: {id_sala_final}")
        
    elif is_root_request and not id_sala_url:
        # Prioridade 2 (NOVO): Acesso à raiz SEM parâmetro -> Força PADRÃO
        # Isso ignora a sessão se você estiver na tela de login sem especificar sala
        id_sala_final = DEFAULT_SALA_ID
        session['id_sala'] = DEFAULT_SALA_ID # Atualiza a sessão para o padrão
        print(f"[2] @before_request: Acesso à raiz sem ID. Resetando para PADRÃO: {id_sala_final}")

    elif id_sala_sessao:
        # Prioridade 3: Sessão (Mantém a sala em outras rotas internas)
        id_sala_final = id_sala_sessao
        print(f"[3] @before_request: Sala mantida via Sessão: {id_sala_final}")
        
    else:
        # Prioridade 4: Fallback final
        id_sala_final = DEFAULT_SALA_ID 
        session['id_sala'] = DEFAULT_SALA_ID
        print(f"[4] @before_request: Sem sala definida. Usando PADRÃO: {id_sala_final}")
    """
    if id_sala_url:
        # Prioridade 1: O parâmetro da URL (Sempre vence, força a mudança de sala)
        id_sala_final = id_sala_url
        session['id_sala'] = id_sala_url 
        #print(f"[LOG] @before_request: Sala definida via URL: {id_sala_final}")
        
    elif id_sala_sessao:
        # Prioridade 2: A Sessão (Mantém a sala atual, mesmo na página de login)
        # Esta é a lógica "Sticky Session" que você queria.
        id_sala_final = id_sala_sessao
        # print(f"[LOG] @before_request: 'id_sala' definido pela SESSÃO: {id_sala_final}")
        
    else:
        # Prioridade 3: Padrão (Primeira visita absoluta, ou sessão expirada e sem URL)
        # Se é raiz, sem URL e sem sessão -> Usa padrão
        id_sala_final = DEFAULT_SALA_ID 
        session['id_sala'] = DEFAULT_SALA_ID
        #print(f"[LOG] @before_request: 'id_sala' NÃO encontrado. Usando PADRÃO (Primeira Visita): {id_sala_final}")
    
    g.id_sala = id_sala_final
    #print(f"[LOG] @before_request: 'g.id_sala' DEFINIDO COMO: {g.id_sala}") 
    
    # 3. Verifica o Status da Conexão Master
    if db_control is None:
         g.db_status = False
    else:
         g.db_status = True 
    #print(f"[LOG] @before_request: Status do DB de Controle (g.db_status): {g.db_status}") 
    # 4. Carregamento de Parâmetros Globais (CORRIGIDO)
    default_config_cadastro = {
        "nome_cliente": True, "nick": True, "telefone": True,
        "cpf": False, "cidade": True, "chave_pix": True, "senha": True
    }
   
    # Verifica se os parâmetros no 'g' são da sala errada
    if g.parametros_globais.get('id_sala_param') != g.id_sala:
        g.parametros_globais = {} # Limpa se a sala mudou
        #print(f"[LOG] @before_request: Sala alterada ou cache vazio. Recarregando parâmetros para '{g.id_sala}'.")

    if g.db_status and not g.parametros_globais:
        #print(f"[LOG] @before_request: Tentando carregar parâmetros da coleção 'salas' para sala_id '{g.id_sala}'...") 
        try:
            # --- AQUI ESTÁ A CORREÇÃO ---
            # Procura na coleção 'salas' usando o id_sala atual
            params_doc = g.db_control.salas.find_one({'id_sala': g.id_sala})
            # --- FIM DA CORREÇÃO ---
            if params_doc:
                # Preenche 'g.parametros_globais' com os dados da coleção 'salas'
                g.parametros_globais = {
                    'url_live': params_doc.get('url_live', '#'), 
                    'url_site': params_doc.get('url_site', '#'), 
                    'nome_sala': params_doc.get('nome_sala', 'SALA PADRÃO').strip(),
                    'http_apk': params_doc.get('http_apk', 'http://localhost:5000'), 
                    'id_sala_param': g.id_sala, # Armazena a sala atual nos parâmetros cacheados
                    'tipo_cadastro_cliente': params_doc.get('tipo_cadastro_cliente', default_config_cadastro), 
                    'comissao_padrao': params_doc.get('comissao_padrao', 20), 
                }
                # --- ESTE É O LOG QUE VOCÊ QUERIA VER ---
                print(f"@before_request: Parâmetros CARREGADOS da coleção 'salas'. {g.id_sala} = {g.parametros_globais['nome_sala']}") 
            else:
                 # Se o id_sala (ex: "000") não foi encontrado na coleção 'salas'
                 g.parametros_globais = {'tipo_cadastro_cliente': default_config_cadastro, 'comissao_padrao': 20, 'nome_sala': 'SALA (DEFAULT)', 'id_sala_param': g.id_sala}
                 print(f"[LOG] @before_request: Nenhum documento encontrado em 'salas' para '{g.id_sala}', usando default.") 
        except Exception as e:
            print(f"🚨 ERRO ao carregar Parâmetros da coleção 'salas': {e}")
            g.parametros_globais = {'tipo_cadastro_cliente': default_config_cadastro, 'comissao_padrao': 20, 'nome_sala': 'SALA (ERRO)', 'id_sala_param': g.id_sala}
    
    elif g.parametros_globais:
        # Se já estava em cache, mostramos o log
        print(f"[LOG] @before_request: Parâmetros globais já estavam em cache para '{g.parametros_globais.get('nome_sala', 'N/A')}'.") 
    elif not g.db_status:
        g.parametros_globais = {'tipo_cadastro_cliente': default_config_cadastro, 'comissao_padrao': 20, 'nome_sala': 'SALA (OFFLINE)', 'id_sala_param': g.id_sala}
        print("[LOG] @before_request: DB de Controle offline, usando parâmetros default.")


@app.teardown_request
def teardown_request(exception=None):
    pass 

# --- ROTAS DE AUTENTICAÇÃO E INICIALIZAÇÃO ---

@app.route('/')
def login_page():
    # Esta rota apenas renderiza o formulário de login (GET)
    
    id_sala_param = request.args.get('id_sala')
    error = request.args.get('error')
    
    #print(f"[LOG] login_page (GET): Renderizando formulário. id_sala_param da URL: {id_sala_param}, Erro: {error}") 
    
    return render_template('index.html', 
                           db_error=None, 
                           error=error,
                           id_sala_exibicao=id_sala_param)


@app.route('/login', methods=['POST'])
def login():
    
    #print("[LOG] login (POST): Iniciando tentativa de login.") 
    
    nome_usuario = format_title_case(request.form.get('nome'))
    senha = request.form.get('senha')
    
    # --- AJUSTE ---
    id_sala_to_redirect = g.id_sala
    #print(f"[LOG] login (POST): 'g.id_sala' (da sessão/padrão) é: {id_sala_to_redirect}")
    
    #print(f"[LOG] login (POST): Chamando get_vendas_db()...") 
    db = get_vendas_db()
    
    if db is None:
        print(f"[LOG] login (POST): Conexão com 'db_vendas' FALHOU. Redirecionando...") 
        error_message = ""
        if g.db_control is None:
             error_message = "Erro Crítico: Não foi possível conectar ao banco de dados MESTRE de controle."
        elif not g.id_sala: 
             error_message = "Acesso Negado: Parâmetro 'id_sala' ausente." # (Não deve acontecer com o default)
        else:
             error_message = f"Erro Crítico: Não foi possível conectar ao cluster de vendas da sala '{g.id_sala}'."
             
        if 'id_sala' in session: session.pop('id_sala', None)
             
        return redirect(url_for('login_page', 
                                error=error_message,
                                id_sala=id_sala_to_redirect)) # Passa o ID que falhou

    #print(f"[LOG] login (POST): Conexão com 'db_vendas' SUCESSO. Autenticando...") 
    
    try:
        usuario = db.colaboradores.find_one({
            '$or': [
                {'nome_colaborador': nome_usuario},
                {'nick': nome_usuario}
            ]
        })
        tipo_usuario = 'colaborador'
        
        if not usuario:
            usuario = db.clientes.find_one({'nick': nome_usuario})
            tipo_usuario = 'cliente'
        
    except Exception as e:
        print(f"🚨 ERRO NA BUSCA DO USUÁRIO (Colab/Cliente): {e}")
        return redirect(url_for('login_page', 
                                error="Erro interno ao acessar credenciais.",
                                id_sala=id_sala_to_redirect))
    
    if usuario and 'senha' in usuario:
        senha_formatada_login = senha.capitalize()
        if bcrypt.checkpw(senha_formatada_login.encode('utf-8'), usuario['senha'].encode('utf-8')): 
            
            print(f"[LOG] login (POST): Autenticação BEM-SUCEDIDA para {tipo_usuario} {nome_usuario}.") 
            session['logged_in'] = True
            if tipo_usuario == 'colaborador':
                session['id_colaborador'] = usuario.get('id_colaborador') or str(usuario['_id'])
                session['nivel'] = usuario.get('nivel', 1) 
                session['nick'] = usuario.get('nick') or usuario.get('nome_colaborador')
                return redirect(url_for('menu_operacoes'))
            
            else: # tipo_usuario == 'cliente'
                session['id_cliente'] = usuario.get('id_cliente') or str(usuario['_id'])
                session['nivel'] = 0 
                session['nick'] = usuario.get('nick')
                return redirect(url_for('dashboard_cliente'))
          
    print(f"[LOG] login (POST): Autenticação FALHOU para {nome_usuario}.") 
    return redirect(url_for('login_page', 
                            error="Usuário ou senha inválidos.",
                            id_sala=id_sala_to_redirect))


@app.route('/menu')
@login_required
def menu_operacoes():
    nivel = session.get('nivel', 1) 
    nome_logado = session.get('nick', 'Colaborador')
    db_status = g.db_status 
    return render_template('menu.html', nivel=nivel, logado=nome_logado, db_status=db_status)

@app.route('/dashboard_cliente')
@login_required
def dashboard_cliente():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    if session.get('nivel', 1) != 0:
        session.clear() 
        return redirect(url_for('login_page', error="Tipo de acesso inválido."))

    nick_cliente = session.get('nick', 'Cliente')
    
    return render_template('dashboard_cliente.html', nick_cliente=nick_cliente, g=g)

# --- ROTAS DE VENDAS E CONSULTA (Todas atualizadas para usar get_vendas_db()) ---
@app.route('/consulta_status_eventos', methods=['GET'])
@login_required
def consulta_status_eventos():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    from flask import request 
    error = session.pop('error_message', None)
    success = session.pop('success_message', None)
    
    # Pega o nível da sessão para passar ao template
    nivel_usuario = session.get('nivel', 0) 
    
    eventos_status = []
    view_mode = request.args.get('mode', 'detailed') 
    
    def format_currency(value):
        if value is None: return "R$ 0,00"
        return f"R$ {safe_float(value):.2f}".replace('.', ',')

    try:
        if view_mode == 'simple':
            status_list = [re.compile('^ativo$', re.IGNORECASE)]
        else:
            status_list = [
                re.compile('^ativo$', re.IGNORECASE),
                re.compile('^paralizado$', re.IGNORECASE),
                re.compile('^finalizado$', re.IGNORECASE)
            ]
        
        eventos_cursor = db.eventos.find({'status': {'$in': status_list}}).sort("id_evento", pymongo.ASCENDING)
        
        for evento in eventos_cursor:
            id_evento_int = evento.get('id_evento')
            
            # --- Busca dados de vendas ---
            colecao_vendas = f"vendas{id_evento_int}"
            vendas_data = None
            if colecao_vendas in db.list_collection_names():
                vendas_data_list = list(db[colecao_vendas].aggregate([
                    {'$group': {'_id': None, 'total_unidades': {'$sum': '$quantidade_unidades'}, 'total_valor': {'$sum': '$valor_total'}}}
                ]))
                vendas_data = vendas_data_list[0] if vendas_data_list else None
            
            total_unidades = vendas_data.get('total_unidades', 0) if vendas_data else 0
            
            # Valores Financeiros (Float)
            valor_vendas_float = safe_float(vendas_data.get('total_valor', 0) if vendas_data else 0)
            premio_total_float = safe_float(evento.get('premio_total', 0))
            
            # Cálculo do Saldo (Lucro Bruto)
            saldo_float = valor_vendas_float - premio_total_float

            controle = db.controle_venda.find_one({'id_evento': id_evento_int})
            num_atual = controle.get('inicial_proxima_venda', evento.get('numero_inicial', 1)) if controle else evento.get('numero_inicial', 1)
            
            # Formatação de Data
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
                'data_hora': f"{evento.get('data_evento', 'N/A')} às {evento.get('hora_evento', 'N/A')}",
                'status': evento.get('status').lower(), 
                'valor_venda_unit': format_currency(evento.get('valor_de_venda')),
                'data_ativacao': data_ativado_formatada,
                'total_vendido': total_unidades,
                'valor_total_vendido': format_currency(valor_vendas_float),
                
                # --- NOVOS CAMPOS FINANCEIROS ---
                'premio_total': format_currency(premio_total_float),
                'saldo': format_currency(saldo_float),
                'saldo_is_positivo': (saldo_float >= 0),
                
                'numeracao_atual': num_atual,
                'is_ativo': evento.get('status').lower() == 'ativo' if evento.get('status') else False, 
                'limite_maximo': evento.get('numero_maximo')
            }
            eventos_status.append(evento_info)

    except Exception as e:
        print(f"ERRO CRÍTICO ao buscar status de eventos: {e}")
        return render_template('consulta_status_eventos.html', error=f"Erro interno ao carregar status: {e}", eventos_status=[], g=g, success=success, mode=view_mode, nivel=nivel_usuario)

    # Passamos 'nivel=nivel_usuario' para o template
    return render_template('consulta_status_eventos.html', eventos_status=eventos_status, g=g, mode=view_mode, error=error, success=success, nivel=nivel_usuario)


@app.route('/evento/mudar_status', methods=['POST'])
@login_required
def evento_mudar_status():
    db = get_vendas_db()
    if db is None: # <-- CORREÇÃO PYMONGO
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
                update_data['data_ativado'] = datetime.utcnow()
        
        result = db.eventos.update_one(
            {'id_evento': id_evento_int},
            {'$set': update_data}
        )
        
        if result.modified_count == 1:
            session['success_message'] = f"Evento EVE{id_evento_int} atualizado para '{novo_status.upper()}'."
        else:
            session['error_message'] = f"Evento EVE{id_evento_int} não foi modificado (ou não foi encontrado)."

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
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido para Gravação."))

    id_colaborador_edicao = request.form.get('id_colaborador_edicao') 

    try:
        default_colab_config = {
            "nome_colaborador": True, "nick": True, "telefone": False,
            "cpf": True, "cidade": False, "chave_pix": True, "senha": True,
            "nivel": True, "comissao": True 
        }
        campos_config = g.parametros_globais.get('tipo_cadastro_colaborador', default_colab_config)

        nome_colaborador = format_title_case(request.form.get('nome_colaborador'))
        nick = format_title_case(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip()
        confirma_chave_pix = request.form.get('confirma_chave_pix', '').strip()
        senha = request.form.get('senha')
        confirma_senha = request.form.get('confirma_senha') 
        nivel = int(request.form.get('nivel'))
        comissao = int(request.form.get('comissao', g.parametros_globais.get('comissao_padrao', 20)))

        # 2. Validação Dinâmica
        if campos_config.get("nivel") and not (1 <= nivel <= 3):
            raise ValueError("Nível de acesso deve ser entre 1 e 3.")
            
        if campos_config.get("comissao") and not (0 <= comissao <= 30):
             raise ValueError("Taxa de comissão deve ser entre 0 e 30.")

        if campos_config.get("nome_colaborador") and not nome_colaborador:
            raise ValueError("O campo Nome do Colaborador é obrigatório.")

        if campos_config.get("nick") and not nick:
            raise ValueError("O campo Nick é obrigatório.")
            
        if "nome_colaborador" in campos_config and nome_colaborador.upper() == 'TECBIN':
            return redirect(url_for('cadastro_colaborador', error="Este colaborador (TECBIN) não pode ser alterado.", view='listar'))

        if "chave_pix" in campos_config and chave_pix != confirma_chave_pix:
            raise ValueError("As chaves PIX não conferem.")

        if campos_config.get("nome_colaborador") and nome_colaborador and not nome_colaborador[0].isalpha():
            raise ValueError("O Nome do Colaborador deve começar com uma letra (não números ou símbolos).")

        if campos_config.get("nick") and nick and not nick[0].isalpha():
            raise ValueError("O Nick/Apelido deve começar com uma letra (não números ou símbolos).")
            
        if "senha" in campos_config:
            if not id_colaborador_edicao and campos_config.get("senha") and (not senha or senha != confirma_senha):
                raise ValueError("Senha e Confirmação de Senha não conferem ou estão vazias.")
            elif id_colaborador_edicao and senha and (senha != confirma_senha):
                raise ValueError("Senha e Confirmação de Senha não conferem.")
                
        cpf_limpo = clean_numeric_string(cpf_raw)
        if campos_config.get("cpf") == True: 
            if not cpf_raw or not validate_cpf(cpf_limpo):
                raise ValueError("CPF é obrigatório e deve ser válido.")
        elif "cpf" in campos_config and cpf_raw and not validate_cpf(cpf_limpo):
            raise ValueError("O CPF inserido não é válido.")
        
        query_exist = {}
        if id_colaborador_edicao:
            query_exist['id_colaborador'] = {'$ne': int(id_colaborador_edicao)} 
        
        if "nick" in campos_config and nick and db.colaboradores.find_one({'$and': [query_exist, {'nick': nick}]}):
             raise ValueError("Nick já está em uso, por outro colaborador.")

        if "cpf" in campos_config and cpf_limpo and db.colaboradores.find_one({'$and': [query_exist, {'cpf': cpf_limpo}] }):
             raise ValueError("CPF já cadastrado para outro colaborador.")

        dados_colaborador = {
            "nivel": nivel, 
            "comissao": comissao 
        }
        
        if "nome_colaborador" in campos_config:
            dados_colaborador["nome_colaborador"] = nome_colaborador
        if "nick" in campos_config:
            dados_colaborador["nick"] = nick
        if "telefone" in campos_config:
            dados_colaborador["telefone"] = telefone
        if "cidade" in campos_config:
            dados_colaborador["cidade"] = cidade
        if "chave_pix" in campos_config:
            dados_colaborador["chave_pix"] = chave_pix
        if "cpf" in campos_config:
            dados_colaborador["cpf"] = cpf_limpo
        
        if "senha" in campos_config and senha:
            senha = format_title_case(request.form.get('senha'))
            hashed_password = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
            dados_colaborador['senha'] = hashed_password.decode('utf-8')
        
        if id_colaborador_edicao:
            id_colaborador_int = int(id_colaborador_edicao)
            
            if id_colaborador_int == session.get('id_colaborador') and nivel < 3 and session.get('nivel') == 3 and db.colaboradores.count_documents({'nivel': 3}) == 1:
                raise ValueError("Você é o único administrador. Não pode rebaixar seu próprio nível.")
                 
            if not senha and 'senha' in dados_colaborador:
                 del dados_colaborador['senha']
                 
            db.colaboradores.update_one({'id_colaborador': id_colaborador_int}, {'$set': dados_colaborador})
            success_msg = f"Colaborador {nick} atualizado com sucesso!"
            
        else:
            novo_id_colaborador_int = get_next_colaborador_sequence()
            if novo_id_colaborador_int is None:
                raise Exception("Falha ao gerar ID sequencial do colaborador.")

            dados_colaborador['id_colaborador'] = novo_id_colaborador_int
            
            db.colaboradores.insert_one(dados_colaborador)
            success_msg = f"Colaborador {nick} salvo com sucesso! ID: {novo_id_colaborador_int}."
        
        return redirect(url_for('cadastro_colaborador', success=success_msg, view='listar'))

    except ValueError as e:
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        redirect_args = {
            'error': f"Erro de Validação: {e}",
            'view': view_redirect
        }
        if id_colaborador_edicao:
            redirect_args['id_colaborador'] = id_colaborador_edicao
            
        return redirect(url_for('cadastro_colaborador', **redirect_args))
        
    except Exception as e:
        print(f"ERRO CRÍTICO na gravação/atualização de colaborador: {e}")
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        redirect_args = {
            'error': "Erro interno ao gravar/atualizar colaborador.",
            'view': view_redirect
        }
        if id_colaborador_edicao:
            redirect_args['id_colaborador'] = id_colaborador_edicao

        return redirect(url_for('cadastro_colaborador', **redirect_args))


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


# --- ROTAS DE VENDA ---
@app.route('/venda/nova', methods=['GET'])
@login_required
def nova_venda():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    error = request.args.get('error')
    success = session.pop('success_message', None) 

    id_cliente_final = None
    cliente_encontrado = None
    custo = 0.00
    
    id_evento_param = request.args.get('id_evento')
    id_cliente_busca = request.args.get('id_cliente_busca', '').strip()
    quantidade_param = request.args.get('quantidade') 
    
    quantidade = int(quantidade_param) if quantidade_param and str(quantidade_param).isdigit() else 1
    
    eventos_ativos_cursor = db.eventos.find({'status': 'ativo'}).sort('data_evento', pymongo.ASCENDING)
    
    eventos_enriquecidos = []
    selected_event = None
    
    for evento in eventos_ativos_cursor:
        
        evento['valor_de_venda_float'] = safe_float(evento.get('valor_de_venda', 0.00))

        controle = db.controle_venda.find_one({
            'id_evento': evento.get('id_evento') 
        })
        
        inicial_proxima_venda = controle.get('inicial_proxima_venda', 1) if controle else evento.get('numero_inicial', 1)
        evento['numeracao_atual_display'] = inicial_proxima_venda
        
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
            
    if not selected_event and eventos_enriquecidos:
        selected_event = eventos_enriquecidos[0]
        
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

# Gravar Vendas
@app.route('/processar_venda', methods=['POST'])
@login_required
def processar_venda():
    """
    Processo Crítico de Venda - ATUALIZADO para incluir todos os períodos
    do cliente no comprovante e no link final.
    """
    db = get_vendas_db()
    if db is None: # <-- CORREÇÃO PYMONGO
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
                "data_venda": datetime.utcnow(),
                "quantidade_unidades": quantidade,
                "quantidade_cartelas": quantidade_cartelas_atual,
                "numero_inicial": numero_inicial_atual,
                "numero_final": numero_final_atual,
                "numero_inicial2": numero_inicial2_atual,
                "numero_final2": numero_final2_atual,
                "valor_unitario": Decimal128(str(valor_unitario)), 
                "valor_total": Decimal128(str(valor_total_atual))
            }
            
            print(f"{log_prefix} LOG 3C: Atualizando cliente {id_cliente_final}...")
            db.clientes.update_one(
                {"id_cliente": id_cliente_final}, 
                {"$set": {"data_ultimo_compra": datetime.utcnow()}}
            )

            print(f"{log_prefix} LOG 3D: Inserindo venda na coleção '{nome_colecao_venda}'...")
            db[nome_colecao_venda].insert_one(registro_venda)
            print(f"{log_prefix} ... Venda inserida.")
            
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
        if tipo_de_cartela == 15:
            link_final_limpo = f"{http_apk}?idrodada={id_evento_int_para_controle}{link_periodos_completos}"
        else:
            link_final_limpo = http_apk

        
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
            f"<strong> > Períodos Anteriores <<strong><br>"
            f"{periodos_anteriores_html}"
            f"----------------------------<br>"
            f"{periodo_atual_html}"
            f"----------------------------<br>"
            f"Total Unidades: <strong>{total_unidades_cliente}<strong><br>"
            f"Total Cartelas: <strong>{total_cartelas_cliente}<strong><br>"
            f"  VALOR TOTAL: <span style='font-size: 1.2rem; color: #B91C1C;'>R$ {total_valor_cliente:.2f}</span><br>"
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
            'quantidade': 1,
            'id_cliente_busca': f"CLI{id_cliente_final}"
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
@app.route('/buscar_clientes_json', methods=['GET'])
@login_required
def buscar_clientes_json():
    db = get_vendas_db()
    if db is None: 
        return jsonify({'error': 'DB Offline'}), 500
    
    termo = request.args.get('termo', '').strip()
    tipo = request.args.get('tipo', 'nick')
    
    if not termo or len(termo) < 2:
        return jsonify([])

    query = {}
    if tipo == 'id':
        if termo.isdigit():
            query['id_cliente'] = int(termo)
        else:
            return jsonify([]) # ID inválido
    elif tipo == 'nome':
        query['nome_cliente'] = {'$regex': termo, '$options': 'i'}
    elif tipo == 'nick':
        query['nick'] = {'$regex': termo, '$options': 'i'}
        
    try:
        # Limita a 20 resultados e retorna apenas os campos necessários
        clientes = list(db.clientes.find(query, {'_id': 0, 'id_cliente': 1, 'nome_cliente': 1, 'nick': 1, 'cidade': 1}).limit(20))
        return jsonify(clientes)
    except Exception as e:
        print(f"Erro na busca dinâmica: {e}")
        return jsonify([]), 500


# Consulta de Cliente
@app.route('/buscar_clientes', methods=['GET'])
@login_required
def buscar_clientes():
    """
    Rota API para busca dinâmica de clientes.
    Retorna JSON para o frontend.
    """
    db = get_vendas_db()
    # --- CORREÇÃO CRÍTICA AQUI ---
    if db is None: # Era 'if not db:'
        return jsonify({'clientes': [], 'error': 'DB Offline'})
    # -----------------------------

    termo = request.args.get('termo', '').strip()
    tipo_busca = request.args.get('tipo', 'nick') # nick, nome, id
    
    if not termo or len(termo) < 2: # Mínimo 2 caracteres para buscar
         return jsonify({'clientes': []})

    query_filter = {}
    
    try:
        # Lógica de filtro baseada na opção selecionada
        if tipo_busca == 'id':
            # Remove prefixos como "CLI" se o usuário digitar
            clean_id = re.sub(r'\D', '', termo)
            if clean_id.isdigit():
                query_filter = {'id_cliente': int(clean_id)}
            else:
                return jsonify({'clientes': []}) # ID inválido
                
        elif tipo_busca == 'nome':
            regex_term = re.compile(re.escape(termo), re.IGNORECASE)
            query_filter = {'nome_cliente': {'$regex': regex_term}}
            
        else: # Padrão: 'nick'
            regex_term = re.compile(re.escape(termo), re.IGNORECASE)
            query_filter = {'nick': {'$regex': regex_term}}
            
        # Executa a busca (Limitada a 10 resultados para performance)
        clientes_cursor = db.clientes.find(
            query_filter, 
            {'id_cliente': 1, 'nome_cliente': 1, 'nick': 1, 'cidade': 1} # Projeção: Só o necessário
        ).limit(10)
        
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
        for campo_data in ['data_cadastro', 'data_ultimo_compra']:
            if cliente.get(campo_data) and isinstance(cliente[campo_data], datetime):
                cliente[f'{campo_data}_formatada'] = cliente[campo_data].strftime("%d/%m/%Y %H:%M:%S")

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
        'logado': nome_logado 
    }
    
    return render_template('cadastro_cliente.html', **context)


@app.route('/gravar_cliente', methods=['POST'])
@login_required
def gravar_cliente():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    db_status = g.db_status
    
    next_url = request.form.get('next_url', 'menu_operacoes')
    id_evento_retorno = request.form.get('id_evento_retorno') 
    
    id_cliente_edicao = request.form.get('id_cliente_edicao') 

    if not db_status:
        view_redirect = 'alterar' if id_cliente_edicao else 'novo'
        return redirect(url_for('cadastro_cliente', error="DB Offline. Gravação Crítica Falhou.", view=view_redirect, next=next_url, id_evento=id_evento_retorno))
    
    try:
        # 1. Inicializa a variável de controle de foco
        campo_com_erro = None

        default_config = {} 
        if hasattr(g, 'parametros_globais'):
             default_config = g.parametros_globais.get('tipo_cadastro_cliente', {})
        
        campos_config = g.parametros_globais.get('tipo_cadastro_cliente', default_config)

        nome_cliente = format_title_case(request.form.get('nome_cliente'))
        nick = format_title_case(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip()
        confirma_chave_pix = request.form.get('confirma_chave_pix', '').strip()
        senha = format_title_case(request.form.get('senha'))
        confirma_senha = format_title_case(request.form.get('confirma_senha'))

        if campos_config.get("nome_cliente") and not nome_cliente:
            campo_com_erro = "nome_cliente"
            raise ValueError("O campo Nome Completo é obrigatório.")
        
        # --- VALIDAÇÕES DE CAMPOS OBRIGATÓRIOS ---
        if campos_config.get("nick") and not nick:
            campo_com_erro = "nick"
            raise ValueError("O campo Nick/Apelido é obrigatório.")
        
        if campos_config.get("cidade") and not cidade:
            campo_com_erro = "cidade"
            raise ValueError("O campo Cidade é obrigatório.")
        
        if campos_config.get("chave_pix") and not chave_pix:
            campo_com_erro = "chave_pix"
            raise ValueError("O campo Chave PIX é obrigatório.")

        if campos_config.get("nome_cliente") and nome_cliente and not nome_cliente[0].isalpha():
            campo_com_erro = "nome_cliente"
            raise ValueError("O Nome do Cliente deve começar com uma letra (não números ou símbolos).")
            
        if campos_config.get("nick") and nick and not nick[0].isalpha():
            campo_com_erro = "nick"
            raise ValueError("O Nick/Apelido deve começar com uma letra (não números ou símbolos).")

        cpf_limpo = clean_numeric_string(cpf_raw)
        if campos_config.get("cpf") == True: 
            if not cpf_raw or not validate_cpf(cpf_limpo):
                campo_com_erro = "cpf"
                raise ValueError("CPF é obrigatório e deve ser válido.")
        elif "cpf" in campos_config and cpf_raw and not validate_cpf(cpf_limpo):
            campo_com_erro = "cpf"
            raise ValueError("O CPF inserido não é válido.")

        if "chave_pix" in campos_config and chave_pix != confirma_chave_pix:
            campo_com_erro = "chave_pix"
            raise ValueError("As chaves PIX não conferem.")
        
        if "senha" in campos_config:
            if not id_cliente_edicao and campos_config.get("senha") and (not senha or senha != confirma_senha):
               campo_com_erro = "senha" 
               raise ValueError("Senha e Confirmação de Senha não conferem ou estão vazias.")
            elif id_cliente_edicao and senha and (senha != confirma_senha):
                campo_com_erro = "senha"
                raise ValueError("Senha e Confirmação de Senha não conferem.")
        
        senha_final_raw = None
        if "senha" in campos_config:
            if senha:
                senha_final_raw = senha
            elif not id_cliente_edicao: 
                if not campos_config.get("senha"): 
                    senha_final_raw = nick 
                elif senha == "": 
                     senha_final_raw = nick 

        # --- NOVA VALIDAÇÃO DE DUPLICIDADE (ATIVADA) ---
        query_duplicidade = []
        
        # 1. Verifica Nick (se ativo na config)
        if "nick" in campos_config and nick:
            query_duplicidade.append({'nick': {'$regex': f'^{re.escape(nick)}$', '$options': 'i'}})
            
        # 2. Verifica Nome (se ativo na config) - DESCOMENTADO
        #if "nome_cliente" in campos_config and nome_cliente:
        #    query_duplicidade.append({'nome_cliente': {'$regex': f'^{re.escape(nome_cliente)}$', '$options': 'i'}})

        if query_duplicidade:
            final_query = {'$or': query_duplicidade}
            
            # Se for edição, exclui o próprio ID da verificação
            if id_cliente_edicao:
                final_query = {'$and': [
                    {'id_cliente': {'$ne': int(id_cliente_edicao)}}, 
                    final_query
                ]}
            
            cliente_existente = db.clientes.find_one(final_query)
            
            if cliente_existente:
                msg_erro = "Erro de Duplicidade: "
                
                # Prioridade de erro e foco
                if "nick" in campos_config and cliente_existente.get('nick', '').lower() == nick.lower():
                    msg_erro += f"O Nick '{nick}' já está em uso. "
                    campo_com_erro = "nick" # Define o foco para o Nick
                    
                elif "nome_cliente" in campos_config and cliente_existente.get('nome_cliente', '').lower() == nome_cliente.lower():
                    msg_erro += f"O Nome '{nome_cliente}' já está cadastrado."
                    campo_com_erro = "nome_cliente" # Define o foco para o Nome
                
                raise ValueError(msg_erro)

        # --- FIM DA NOVA VALIDAÇÃO ---         
        
        dados_cliente = {
            "id_colaborador": session.get('id_colaborador', 'N/A'),
        }
        
        if "nome_cliente" in campos_config:
            dados_cliente["nome_cliente"] = nome_cliente
        if "nick" in campos_config:
            dados_cliente["nick"] = nick
        if "cpf" in campos_config:
            dados_cliente["cpf"] = cpf_limpo
        if "telefone" in campos_config:
            dados_cliente["telefone"] = telefone
        if "cidade" in campos_config:
            dados_cliente["cidade"] = cidade
        if "chave_pix" in campos_config:
            dados_cliente["chave_pix"] = chave_pix
        
        if senha_final_raw: 
            senha_formatada = senha_final_raw.capitalize()
            hashed_password = bcrypt.hashpw(senha_formatada.encode('utf-8'), bcrypt.gensalt())
            dados_cliente['senha'] = hashed_password.decode('utf-8')

        
        novo_id_cliente_int = None
        
        if id_cliente_edicao:
            id_cliente_int = int(id_cliente_edicao)
            db.clientes.update_one({'id_cliente': id_cliente_int}, {'$set': dados_cliente})
            success_msg = f"Cliente ID: CLI{id_cliente_int} atualizado com sucesso!"
            
        else:
            novo_id_cliente_int = get_next_cliente_sequence()
            if novo_id_cliente_int is None:
                raise Exception("Falha ao gerar ID sequencial do cliente.")

            dados_cliente.update({
                "id_cliente": novo_id_cliente_int, 
                "data_cadastro": datetime.utcnow(),
                "data_ultimo_compra": None 
            })
            
            db.clientes.insert_one(dados_cliente)
            success_msg = f"Cliente '{nick}' salvo com sucesso! ID: CLI{novo_id_cliente_int}."
        
        redirect_kwargs = {'success': success_msg}

        if next_url == 'nova_venda':
            cliente_id_para_retorno = id_cliente_edicao if id_cliente_edicao else str(novo_id_cliente_int)
            
            if not cliente_id_para_retorno and "nick" in dados_cliente:
                 redirect_kwargs['id_cliente_busca'] = dados_cliente['nick']
            else:
                 redirect_kwargs['id_cliente_busca'] = f"CLI{cliente_id_para_retorno}"

            if id_evento_retorno:
                redirect_kwargs['id_evento'] = id_evento_retorno
        
        if next_url != 'nova_venda':
             next_url = 'cadastro_cliente'
             redirect_kwargs['view'] = 'listar' 

        return redirect(url_for(next_url, **redirect_kwargs))


    except ValueError as e:
        session['form_data'] = dict(request.form) 
        view_redirect = 'alterar' if id_cliente_edicao else 'novo'
        
        redirect_args = {
            'error': f"Erro de Validação: {e}",
            'view': view_redirect,
            'next': next_url,
            'id_evento': id_evento_retorno
        }

        # Adiciona o parâmetro de foco se houver um campo identificado
        if campo_com_erro:
            redirect_args['focus'] = campo_com_erro

        if id_cliente_edicao:
            redirect_args['id_cliente'] = id_cliente_edicao
            
        return redirect(url_for('cadastro_cliente', **redirect_args))
        
    except Exception as e:
        print(f"ERRO CRÍTICO na gravação/atualização de cliente: {e}")
        session['form_data'] = dict(request.form) 
        view_redirect = 'alterar' if id_cliente_edicao else 'novo'
        
        redirect_args = {
            'error': "Erro interno ao gravar/atualizar cliente.",
            'view': view_redirect,
            'next': next_url,
            'id_evento': id_evento_retorno
        }
        if id_cliente_edicao:
            redirect_args['id_cliente'] = id_cliente_edicao

        return redirect(url_for('cadastro_cliente', **redirect_args))


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


# --- ROTAS DE CADASTRO DE EVENTO (NOVO CRUD) ---

@app.route('/cadastro_evento', methods=['GET'])
@login_required
def cadastro_evento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO
    
    db_status = g.db_status
    form_data_erro = session.pop('form_data', None)
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    id_evento_edicao = request.args.get('id_evento', None)
    
    evento_edicao = None 
    eventos_lista = []
    total_eventos = 0
    
    error = request.args.get('error')
    success = request.args.get('success')

    numeric_float_fields = [
        'valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 
        'premio_segundobingo', 'premio_acumulado', 'minimo_de_venda', 'premio_total'
    ]
    numeric_int_fields = [
        'unidade_de_venda', 'numero_inicial', 'numero_maximo', 'tipo_de_cartela',
        'quantidade_de_linhas', 'bola_tope_acumulado'
    ]
    all_numeric_fields = numeric_float_fields + numeric_int_fields

    if form_data_erro:
        evento_edicao = form_data_erro
        
        if 'id_evento_edicao' in form_data_erro and form_data_erro['id_evento_edicao']:
             active_view = 'alterar'
             id_evento_edicao = form_data_erro['id_evento_edicao']
        else:
             active_view = 'novo'
        
        for key in all_numeric_fields:
            if key in evento_edicao:
                evento_edicao[key] = safe_float(evento_edicao.get(key, 0.0))
             
    elif active_view == 'alterar' and id_evento_edicao and db_status:
        try:
            id_evento_int = int(id_evento_edicao)
            evento_edicao = db.eventos.find_one({'id_evento': id_evento_int})
            
            if evento_edicao:
                if '_id' in evento_edicao: evento_edicao['_id'] = str(evento_edicao['_id'])

                data_evento_db = evento_edicao.get('data_evento') 
                if data_evento_db and isinstance(data_evento_db, str):
                    try:
                        dt_obj = datetime.strptime(data_evento_db, '%d/%m/%Y')
                        evento_edicao['data_evento'] = dt_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        pass 
                
                for key in all_numeric_fields:
                    if key in evento_edicao: 
                        evento_edicao[key] = safe_float(evento_edicao.get(key, 0.0))

            else:
                 error = f"Evento ID {id_evento_int} não encontrado para edição."
                 active_view = 'listar'
                 
        except (ValueError, TypeError):
            error = "ID de Evento inválido para edição."
            active_view = 'listar'
            
    if db_status:
        try:
            total_eventos = db.eventos.count_documents({})
            
            if active_view == 'listar':
                eventos_cursor = db.eventos.find({}).sort([("data_evento", pymongo.ASCENDING), ("hora_evento", pymongo.ASCENDING)])
                eventos_lista = list(eventos_cursor)
            
            elif active_view == 'consulta' and search_term:
                query_filter = {}
                
                if search_term.isdigit(): 
                    query_filter = {'id_evento': int(search_term)}
                
                if not query_filter:
                    regex_term = re.compile(re.escape(search_term), re.IGNORECASE)
                    query_filter = {
                        '$or': [
                            {'descricao': {'$regex': regex_term}},
                            {'data_evento': {'$regex': regex_term}}
                        ]
                    }
                    
                eventos_cursor = db.eventos.find(query_filter).sort("data_evento", pymongo.ASCENDING)
                eventos_lista = list(eventos_cursor) 

        except Exception as e:
            print(f"Erro ao buscar dados no MongoDB em cadastro_evento: {e}")
            error = f"Erro crítico ao carregar dados do DB: {e}"

    for evento in eventos_lista:
        if '_id' in evento: evento['_id'] = str(evento['_id'])
        # --- INÍCIO DA ADIÇÃO ---
        id_evento_atual = evento.get('id_evento')
        nome_colecao_venda = f"vendas{id_evento_atual}"
    
        # Verifica se a coleção existe e conta os documentos
        qtd_vendas = 0
        # Nota: list_collection_names é mais seguro para checar existência
        if nome_colecao_venda in db.list_collection_names():
            qtd_vendas = db[nome_colecao_venda].count_documents({})
    
        evento['qtd_vendas'] = qtd_vendas
        # --- FIM DA ADIÇÃO ---
        for key in all_numeric_fields:
            if key in evento:
                evento[key] = safe_float(evento.get(key, 0.0))

    context = {
        'total_eventos': total_eventos,
        'eventos_lista': eventos_lista,
        'active_view': active_view,
        'query': search_term, 
        'evento_edicao': evento_edicao, 
        'error': error,
        'success': success,
        'g': g
    }
    
    return render_template('cadastro_evento.html', **context)


@app.route('/gravar_evento', methods=['POST'])
@login_required
def gravar_evento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido para Gravação."))

    id_evento_edicao = request.form.get('id_evento_edicao') 
    
    def clean_float_input(form_key, default_value='0'):
        """Trata a entrada do formulário, convertendo '' para default_value e trocando ',' por '.'"""
        value_raw = request.form.get(form_key, default_value)
        if not value_raw or value_raw.strip() == '':
            value_raw = str(default_value)
        return float(value_raw.replace(',', '.'))

    try:
        data_evento_str = request.form.get('data_evento') # YYYY-MM-DD
        hora_evento = request.form.get('hora_evento')
        descricao = format_title_case(request.form.get('descricao'))
        unidade_de_venda = int(request.form.get('unidade_de_venda', 1))
        tipo_de_cartela = int(request.form.get('tipo_de_cartela', 15)) 
        
        valor_de_venda = clean_float_input('valor_de_venda')
        premio_quadra = clean_float_input('premio_quadra')
        premio_linha = clean_float_input('premio_linha')
        premio_bingo = clean_float_input('premio_bingo')
        premio_segundobingo = clean_float_input('premio_segundobingo', default_value='0')
        premio_acumulado = clean_float_input('premio_acumulado', default_value='0')
        minimo_de_venda = clean_float_input('minimo_de_venda', default_value='0') 

        numero_inicial = int(request.form.get('numero_inicial', 1))
        numero_maximo = int(request.form.get('numero_maximo', 72000))
        quantidade_de_linhas = int(request.form.get('quantidade_de_linhas', 1))
        bola_tope_acumulado = int(request.form.get('bola_tope_acumulado', 0)) 
        
        if not all([data_evento_str, hora_evento, descricao, unidade_de_venda]):
             raise ValueError("Preencha todos os campos obrigatórios (*).")
        
        if tipo_de_cartela not in [15, 25]:
            raise ValueError("O tipo de cartela deve ser 15 ou 25 números.")
        
        if not (1 <= unidade_de_venda <= 6):
             raise ValueError("Unidade de venda deve ser entre 1 e 6.")

        if not (1 <= quantidade_de_linhas <= 3):
             raise ValueError("Quantidade de linhas deve ser entre 1 e 3.")

        try:
             data_obj = datetime.strptime(data_evento_str, '%Y-%m-%d')
             data_evento_str_gravar = data_obj.strftime('%d/%m/%Y')
        except ValueError:
             raise ValueError("Formato de data inválido. Use AAAA-MM-DD.")
        
        data_hora_evento_str = f"{data_evento_str} {hora_evento}" 
        data_hora_evento_dt = datetime.strptime(data_hora_evento_str, '%Y-%m-%d %H:%M')
        
        premio_total = premio_quadra + (premio_linha * quantidade_de_linhas) + premio_bingo + premio_segundobingo + premio_acumulado
        
        dados_evento = {
            "data_evento": data_evento_str_gravar, 
            "hora_evento": hora_evento, 
            "data_hora_evento": data_hora_evento_dt, 
            "descricao": descricao,
            "unidade_de_venda": unidade_de_venda,
            "tipo_de_cartela": tipo_de_cartela, 
            "valor_de_venda": Decimal128(str(valor_de_venda)),
            "numero_inicial": numero_inicial,
            "numero_maximo": numero_maximo,
            "premio_quadra": Decimal128(str(premio_quadra)),
            "quantidade_de_linhas": quantidade_de_linhas,
            "premio_linha": Decimal128(str(premio_linha)),
            "premio_bingo": Decimal128(str(premio_bingo)),
            "premio_segundobingo": Decimal128(str(premio_segundobingo)),
            "premio_total": Decimal128(str(premio_total)), 
            "premio_acumulado": Decimal128(str(premio_acumulado)),
            "bola_tope_acumulado": bola_tope_acumulado,
            "minimo_de_venda": Decimal128(str(minimo_de_venda)),
            "id_colaborador": session.get('id_colaborador', 'N/A'),
        }
        
        novo_id_evento_int = None
        
        if id_evento_edicao:
            id_evento_int = int(id_evento_edicao)
            
            if 'status' in dados_evento:
                 del dados_evento['status']
            if 'data_ativado' in dados_evento:
                 del dados_evento['data_ativado']
                 
            db.eventos.update_one({'id_evento': id_evento_int}, {'$set': dados_evento})
            success_msg = f"Evento ID: {id_evento_int} atualizado com sucesso!"
            
        else:
            novo_id_evento_int = get_next_evento_sequence()
            if novo_id_evento_int is None:
                raise Exception("Falha ao gerar ID sequencial do evento.")

            dados_evento.update({
                "id_evento": novo_id_evento_int, 
                "status": "paralizado", 
                "data_ativado": None,
                "data_cadastro": datetime.utcnow()
            })
            
            db.eventos.insert_one(dados_evento)
            success_msg = f"Evento '{dados_evento['descricao']}' salvo com sucesso! ID: {novo_id_evento_int}."
        
        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))


    except ValueError as e:
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_evento_edicao else 'novo'
        redirect_args = {
            'error': f"Erro de Validação: {e}",
            'view': view_redirect
        }
        if id_evento_edicao:
            redirect_args['id_evento'] = id_evento_edicao
        return redirect(url_for('cadastro_evento', **redirect_args))
        
    except Exception as e:
        print(f"ERRO CRÍTICO na gravação/atualização de evento: {e}")
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_evento_edicao else 'novo'
        redirect_args = {
            'error': "Erro interno ao gravar/atualizar evento.",
            'view': view_redirect
        }
        if id_evento_edicao:
            redirect_args['id_evento'] = id_evento_edicao
        return redirect(url_for('cadastro_evento', **redirect_args))


@app.route('/excluir_evento/<int:id_evento>', methods=['POST'])
@login_required
def excluir_evento(id_evento):
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

    try:
        result = db.eventos.delete_one({'id_evento': id_evento})
        msg_extra = ""
        if result.deleted_count == 1:
            nome_colecao_venda = f"vendas{id_evento}"
            if nome_colecao_venda in db.list_collection_names():
                db[nome_colecao_venda].drop()
                msg_extra = " e todas as vendas associadas foram removidas."
            # -----------------------------------------------------
            success_msg = f"Evento ID: {id_evento} excluído{msg_extra} com sucesso."
        else:
            success_msg = f"Evento ID: {id_evento} não encontrado para exclusão."

        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO CRÍTICO na exclusão de evento ID {id_evento}: {e}")
        return redirect(url_for('cadastro_evento', error=f"Erro interno ao excluir evento.", view='listar'))


# --- Rota de Consulta de Vendas (com cálculo de comissão) ---
@app.route('/consulta_vendas', methods=['GET'])
@login_required
def consulta_vendas():
    """
    Página principal de consulta de vendas.
    (Com cálculo de comissão)
    """
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

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
            evento_oid = try_object_id(id_evento_param)
            selected_event_raw = db.eventos.find_one({'_id': evento_oid})
            selected_event = clean_event_numerics(selected_event_raw)
            
            if not selected_event:
                error = "Evento não encontrado."
                return render_template('consulta_vendas.html', error=error, g=g)

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
                    filtro_colaborador_query = {'id_colaborador': int(id_colaborador_param)}
                    selected_colab_id_str = id_colaborador_param
                elif id_colaborador_param == 'ALL':
                    selected_colab_id_str = 'ALL'

            id_evento_int = selected_event.get('id_evento')
            nome_colecao_venda = f"vendas{id_evento_int}"

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
                    'data_final': {'$max': '$data_venda'}
                }
            })
            pipeline.append({'$sort': {'nick_colaborador': 1}})
            
            resultados_cursor = db[nome_colecao_venda].aggregate(pipeline)
            
            for res in resultados_cursor:
                res['total_valor_float'] = safe_float(res['total_valor'])
                
                colab_id = res['_id'] 
                taxa_aplicada = comissao_map.get(colab_id, default_comissao) 
                
                res['taxa_comissao_aplicada'] = taxa_aplicada
                res['valor_comissao_float'] = (res['total_valor_float'] * taxa_aplicada) / 100.0
                
                resultados_agregados.append(res)
                
            if selected_colab_id_str == 'ALL' and resultados_agregados:
                total_kits_geral = sum(r['total_kits'] for r in resultados_agregados)
                total_cartelas_geral = sum(r['total_cartelas'] for r in resultados_agregados)
                total_valor_geral = sum(r['total_valor_float'] for r in resultados_agregados)
                total_vendas_geral = sum(r['total_vendas'] for r in resultados_agregados)
                total_comissao_geral = sum(r['valor_comissao_float'] for r in resultados_agregados) 
                data_inicial_geral = min(r['data_inicial'] for r in resultados_agregados)
                data_final_geral = max(r['data_final'] for r in resultados_agregados)
                
                resumo_geral = {
                    'nick_colaborador': '⭐ Resumo Geral (TODOS)',
                    '_id': 'ALL',
                    'total_kits': total_kits_geral,
                    'total_cartelas': total_cartelas_geral,
                    'total_valor_float': total_valor_geral,
                    'total_vendas': total_vendas_geral,
                    'valor_comissao_float': total_comissao_geral, 
                    'data_inicial': data_inicial_geral,
                    'data_final': data_final_geral
                }
                
            if not resultados_agregados and id_colaborador_param and not error:
                error = "Nenhuma venda encontrada para este filtro."

    except Exception as e:
        print(f"Erro em consulta_vendas: {e}")
        error = f"Erro interno ao processar consulta: {e}"

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


# --- ROTA MODIFICADA 'consulta_vendas_detalhes' ---
@app.route('/consulta_vendas/detalhes', methods=['GET'])
@login_required
def consulta_vendas_detalhes():
    """Mostra a lista detalhada de vendas para um filtro específico."""
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) # <-- CORREÇÃO PYMONGO

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
    
    default_comissao = g.parametros_globais.get('comissao_padrao', 0)
    comissao_map = {} 

    try:
        evento_oid = try_object_id(id_evento_param)
        selected_event = db.eventos.find_one({'_id': evento_oid})
        
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
        if nivel_usuario < 3:
            query_filter['id_colaborador'] = id_colaborador_logado
            info_colaborador = session.get('nick', 'N/A')
            info_telefone_cliente = session.get('telefone_cliente','')
            if isinstance(id_colaborador_logado, int):
                 colab_ids_para_buscar_comissao.append(id_colaborador_logado)       
        elif nivel_usuario == 3:
            if id_colaborador_param and id_colaborador_param != 'ALL':
                id_colab_int = int(id_colaborador_param)
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
        
        for venda in vendas_cursor:
            venda['valor_total_float'] = safe_float(venda.get('valor_total'))
            colab_id = venda.get('id_colaborador')
            taxa_comissao = comissao_map.get(colab_id, default_comissao) 
            venda['valor_comissao_float'] = (venda['valor_total_float'] * taxa_comissao) / 100.0
            vendas_detalhadas.append(venda)
            
        if not vendas_detalhadas:
            error = "Nenhuma venda detalhada encontrada."

    except Exception as e:
        print(f"Erro em consulta_vendas_detalhes: {e}")
        error = f"Erro interno: {e}"
    print(f" Telefone >>>>  :{info_telefone_cliente}")
    return render_template('consulta_vendas_detalhes.html',
                           g=g,
                           error=error,
                           vendas=vendas_detalhadas,
                           info_evento=info_evento_nome, 
                           info_evento_id=info_evento_id, 
                           info_colaborador=info_colaborador,
                           info_tipo_cartela=info_tipo_cartela,
                           info_telefone_cliente=info_telefone_cliente)


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
        link_periodos = "" 
        
        if tipo_reimpressao == 'unica':
            venda = db[nome_colecao_venda].find_one({'id_venda': id_venda_str})
            if not venda:
                return jsonify({'status': 'error', 'message': 'Venda não encontrada'})
            
            periodo_principal = f"   > {venda['numero_inicial']} a {venda['numero_final']}<br>"
            periodo_adicional = ""
            
            link_periodos = f"&periodo={venda['numero_inicial']},{venda['numero_final']}"
            
            if venda.get('numero_inicial2', 0) > 0:
                periodo_adicional = f"    > {venda['numero_inicial2']} a {venda['numero_final2']}<br>"
                link_periodos += f"&periodo={venda['numero_inicial2']},{venda['numero_final2']}"

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
                link_periodos += f"&periodo={venda['numero_inicial']},{venda['numero_final']}"
                
                if venda.get('numero_inicial2', 0) > 0:
                    periodos_html_list.append(f"    > {venda['numero_inicial2']} a {venda['numero_final2']}<br>")
                    link_periodos += f"&periodo={venda['numero_inicial2']},{venda['numero_final2']}"

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
                f"<br>"                
                f">CLIQUE NO <strong>LINK</strong> ABAIXO PARA<br>"
                f"    ACESSAR SUAS CARTELAS 📱<br>"
            )

        else:
            return jsonify({'status': 'error', 'message': 'Tipo de reimpressão inválido.'})
        
        link_final_limpo = f"{http_apk}?idrodada={id_evento_int}{link_periodos}"
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
            print(f"[AUDITORIA] Venda {id_venda_str} excluída por {session.get('nick')} em {datetime.utcnow()}")
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
        
        selected_event = db.eventos.find_one(
            {'_id': evento_oid},
            { 
                'id_evento': 1, 'unidade_de_venda': 1, 'numero_maximo': 1,
                'tipo_de_cartela': 1, 'valor_de_venda': 1, 'descricao': 1, 
                'premio_quadra': 1, 'quantidade_de_linhas': 1, 'premio_linha': 1, 
                'premio_bingo': 1, 'premio_segundobingo': 1, 'premio_acumulado': 1, 
                'bola_tope_acumulado': 1
            }
        )
        
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
            f"{safe_float(selected_event.get('premio_bingo', 0))}!"
            f"{safe_float(selected_event.get('premio_segundobingo', 0))}!"
            f"{safe_float(selected_event.get('premio_acumulado', 0))}!"
            f"{selected_event.get('bola_tope_acumulado', 0)}\r\n" # <-- CRLF
        )
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


if __name__ == '__main__':
    # Para desenvolvimento local apenas
    if os.environ.get('FLASK_ENV') != 'production':
        app.run(debug=True, host='0.0.0.0', port=5001)
    else:
        print("⚠️  AVISO: Em produção, use Gunicorn. Não execute app.py diretamente!")