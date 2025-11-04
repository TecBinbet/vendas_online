# app.py (Versão Final com Rotas de Colaborador, Cliente e Eventos)

import threading
import pymongo
from flask import Flask, render_template, request, redirect, url_for, session, g
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson.objectid import ObjectId
from bson.decimal128 import Decimal128
from datetime import datetime
from urllib.parse import quote_plus
import os
import re # Para a busca de clientes
import bcrypt
from functools import wraps # Para o decorator login_required
from datetime import timedelta
import certifi  # Para certificados SSL
#from passlib.hash import bcrypt # Para hashing de senhas de colaboradores

# --- Configuração ---
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui' 
app.permanent_session_lifetime = timedelta(minutes=60) # Tempo de sessão

# Configuração do MongoDB
DB_NAME = 'bingo_vendas_db'
MONGO_PASSWORD = 'TecBin24' 
ENCODED_PASSWORD = quote_plus(MONGO_PASSWORD)
MONGODB_URI = os.environ.get('MONGODB_URI', f'mongodb+srv://tecbin_db_vendas:{ENCODED_PASSWORD}@cluster0.blwq4du.mongodb.net/?appName=Cluster0')

client_global = None
try:
    # Definimos um timeout de seleção de servidor e configuração SSL explícita
    client_global = MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=5000,  # Aumentado para 5 segundos
        tlsCAFile=certifi.where(),  # Usa certificados do certifi
        retryWrites=True,
        w='majority'
    )
    print("✅ CLIENTE GLOBAL MONGODB CRIADO COM SUCESSO.")

except Exception as e:
    # Se a URI for malformada, o erro é capturado aqui, e o client_global será None.
    print(f"🚨 ERRO IRRECUPERÁVEL AO CRIAR O CLIENTE GLOBAL: {e}")
    client_global = None

# --- Locks de Sincronização ---
# Usados para operações críticas que requerem exclusividade (atomicidade)
venda_lock = threading.Lock()
cliente_lock = threading.Lock() 
colaborador_lock = threading.Lock() 
evento_lock = threading.Lock() # NOVO LOCK para sequência de Eventos

# --- DECORATOR DE AUTENTICAÇÃO ---
def login_required(f):
    """Decorator para exigir login em uma rota."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page', error="Acesso restrito. Faça o login."))
        return f(*args, **kwargs)
    return decorated_function

# --- FUNÇÕES AUXILIARES GLOBAIS (DB/UTILS) ---

# FUNÇÃO AUXILIAR CRÍTICA 1: Converte String para ObjectId
def try_object_id(id_string):
    """Converte string para ObjectId, ou retorna a string se falhar ou se já for None."""
    if not id_string:
        return None
    try:
        return ObjectId(id_string)
    except:
        return id_string

# FUNÇÃO AUXILIAR CRÍTICA 2: Converte Decimal128 para float
def safe_float(value):
    """
    Converte valores numéricos do MongoDB (incluindo Decimal128) para float.
    CRÍTICO: Isso previne o erro `TypeError: must be real number, not Decimal128` no Jinja.
    """
    if value is None:
        return 0.0
    if isinstance(value, Decimal128):
        # Converte Decimal128 para string e depois para float
        return float(str(value))
    # Tenta converter diretamente para float
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0 # Retorna 0.0 se não for um valor convertível

# FUNÇÃO AUXILIAR GLOBAL 1: Gerar ID Sequencial (Atomicamente)
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

# Geração Atômica do ID do Cliente (INT)
def get_next_cliente_sequence(db):
    """Obtém o próximo ID sequencial do cliente de forma atômica e segura (protegido por lock)."""
    if cliente_lock.acquire(timeout=5):
        try:
            return get_next_global_sequence(db, 'id_clientes_global')
        finally:
            cliente_lock.release()
    return None

def get_next_colaborador_sequence(db):
    """Gera o próximo ID sequencial para Colaboradores (atômico)."""
    with colaborador_lock:
        seq_doc = db.contadores.find_one_and_update(
            {'_id': 'id_colaborador_global'},
            {'$inc': {'sequence_value': 1}},
            upsert=True,
            return_document=pymongo.ReturnDocument.AFTER
        )
        return seq_doc['sequence_value'] if seq_doc else None

# NOVO: Geração Atômica do ID do Evento (INT)
def get_next_evento_sequence(db):
    """Gera o próximo ID sequencial para Eventos (atômico)."""
    with evento_lock:
        seq_doc = db.contadores.find_one_and_update(
            {'_id': 'id_evento_global'},
            {'$inc': {'sequence_value': 1}},
            upsert=True,
            return_document=pymongo.ReturnDocument.AFTER
        )
        return seq_doc['sequence_value'] if seq_doc else None

# FUNÇÃO AUXILIAR 2: Incremento para Controle de Cartelas (Atomicamente com Limite)
def get_next_bilhete_sequence(db, id_evento, increment_field, quantidade_cartelas, limite_maximo):
    """
    Incrementa o campo de sequência (inicial_proxima_venda) por `quantidade_cartelas`
    e aplica um rollover se atingir `limite_maximo`.
    Retorna o valor *anterior* do campo (o número inicial da venda atual).
    """
    
    # Valor padrão de início para a sequência, caso seja o primeiro documento
    VALOR_INICIAL_PADRAO = 1 
    
    # Obtém a data/hora UTC e formata para o padrão Brasileiro (como string, sem pytz)
    now_utc = datetime.utcnow()
    data_hora_formatada = now_utc.strftime("%d-%m/%Y %H:%M:%S")

    # Prepara o pipeline de atualização para o rollover
    update_pipeline = [
        {
            '$set': {
                increment_field: {
                    '$cond': {
                        # 1. Condição: Checa se (Valor Atual + Quantidade) é maior ou igual ao limite
                        'if': { 
                            '$gte': [ 
                                { '$add': ["$" + increment_field, quantidade_cartelas] }, 
                                limite_maximo 
                            ] 
                        },
                        # 2. Se SIM (Rollover): Calcula (Valor Atual + Quantidade) - Limite
                        'then': { 
                            '$subtract': [ 
                                { '$add': ["$" + increment_field, quantidade_cartelas] }, 
                                limite_maximo 
                            ] 
                        },
                        # 3. Se NÃO (Incremento normal): Calcula Valor Atual + Quantidade
                        'else': { 
                            '$add': ["$" + increment_field, quantidade_cartelas] 
                        }
                    }
                },
                "data_hora": data_hora_formatada # Grava a data/hora da última atualização de sequência
            }
        }
    ]
    
    try:
        query = {'id_evento': id_evento}
        
        # find_one_and_update com pipeline retorna o documento ANTES da modificação.
        update_result = db.controle_venda.find_one_and_update(
            query,
            update_pipeline, # Passa o pipeline de agregação
            return_document=pymongo.ReturnDocument.BEFORE,
            upsert=True,
            projection={increment_field: 1} # Projeta apenas o campo necessário
        )

        if update_result and increment_field in update_result:
            # Caso comum: O documento existia, retorna o valor ANTERIOR do campo.
            return update_result[increment_field] 
        else:
            # Caso de NOVO DOCUMENTO (upsert): 
            # Retorna o valor de início padrão (1) para a primeira venda.
            if update_result is None:
                return VALOR_INICIAL_PADRAO
                 
            return None 
            
    except Exception as e:
        print(f"ERRO CRÍTICO ao obter valor sequencial de bilhete/cartela para {id_evento}: {e}")
        return None

# --- Funções de Formatação de Dados ---
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
    # Em um sistema real, usaria uma validação de dígito verificador mais complexa
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

# --- Funções de Conexão com o Banco de Dados e Parâmetros ---
def get_db():
    """Reutiliza o cliente global e define o status e o objeto DB no 'g'."""
    if 'db_status' not in g:
        g.db_status = False
        g.db = None
        g.parametros_globais = {}
        
        if client_global:
            try:
                client_global.admin.command('ping') 
                g.db = client_global[DB_NAME]
                g.db_status = True
            except Exception as e:
                print(f"🚨 ERRO: Falha de Conexão/Ping com MongoDB. Detalhes: {e}")
                g.db_status = False 
    
    return g.db

@app.before_request
def before_request():
    """Garante que g.db e g.db_status sejam definidos no início de cada rota e carrega parâmetros."""
    get_db()
    
    # Carregamento de Parâmetros Globais (se o DB estiver ativo)
    if g.db_status and not g.parametros_globais:
        try:
            # Assumindo que o documento de parâmetros tem um ID fixo ou é o primeiro
            params_doc = g.db.parametros.find_one({'_id': 'config_global'})
            if params_doc:
                g.parametros_globais = {
                    'url_live': params_doc.get('url_live', '#'),
                    'url_site': params_doc.get('url_site', '#'),
                    'nome_sala': params_doc.get('nome_sala', 'LIVE THE BET').strip(),
                    'http_apk': params_doc.get('http_apk', 'http://localhost:5000'),
                    'id_sala': params_doc.get('id_sala', 'SALA001'),
                }
        except Exception as e:
            print(f"🚨 ERRO ao carregar Parâmetros Globais: {e}")
            g.parametros_globais = {}


# --- ROTAS DE NAVEGAÇÃO E AUTENTICAÇÃO ---

@app.route('/menu')
@login_required
def menu_operacoes():
    nivel = session.get('nivel', 1) 
    db_status = g.db_status 
    return render_template('menu.html', nivel=nivel, db_status=db_status)

@app.route('/login', methods=['POST'])
def login():
    nome_usuario = request.form.get('nome')
    senha = request.form.get('senha')
    if not g.db_status:
         return redirect(url_for('login_page', error="DB Offline. Tente novamente.")) 

    db = g.db
    try:
        # Tenta login como Colaborador
        usuario = db.colaboradores.find_one({
            '$or': [
                {'nome_colaborador': nome_usuario},
                {'nick': nome_usuario}
            ]
        })
        tipo_usuario = 'colaborador'
        
        # Se não encontrar, tenta login como Cliente
        if not usuario:
            usuario = db.clientes.find_one({'nick': nome_usuario})
            tipo_usuario = 'cliente'

    except Exception as e:
        print(f"🚨 ERRO NA BUSCA DO USUÁRIO (Colab/Cliente): {e}")
        return redirect(url_for('login_page', error="Erro interno ao acessar credenciais."))
    
    if usuario and 'senha' in usuario:
        
        # --- CORREÇÃO CRÍTICA ---
        # Aplica a mesma regra de formatação (Capitalize) usada no cadastro
        # antes de comparar a senha.
        senha_formatada_login = senha.capitalize()
        
        # Verifica a senha formatada com o hash do DB
        if bcrypt.checkpw(senha_formatada_login.encode('utf-8'), usuario['senha'].encode('utf-8')): 
            session['logged_in'] = True
            
            if tipo_usuario == 'colaborador':
                session['id_colaborador'] = usuario.get('id_colaborador') or str(usuario['_id'])
                session['nivel'] = usuario.get('nivel', 1) 
                session['nick'] = usuario.get('nick') or usuario.get('nome_colaborador')
                return redirect(url_for('menu_operacoes'))
            
            else: # tipo_usuario == 'cliente'
                session['id_cliente'] = usuario.get('id_cliente') or str(usuario['_id'])
                session['nivel'] = 0 # Nível 0 para cliente
                session['nick'] = usuario.get('nick')
                
                # AJUSTE: Redireciona o cliente para o dashboard dele
                return redirect(url_for('dashboard_cliente'))

          
    return redirect(url_for('login_page', error="Usuário ou senha inválidos."))


@app.route('/')
def login_page():
    db_error = None
    if not g.db_status:
        db_error = "Falha de conexão com o Banco de Dados. Operações de DB não funcionarão."
    error = request.args.get('error')
    return render_template('index.html', db_error=db_error, error=error)

@app.route('/consulta_eventos')
@login_required
def consulta_eventos_old():
    # Rota mantida apenas para navegação
    return render_template('consulta_eventos.html')

@app.route('/consulta_status_eventos', methods=['GET'])
@login_required
def consulta_status_eventos():
    from flask import request 
    db = g.db
    if not g.db_status:
        return render_template('consulta_status_eventos.html', error="DB Offline. Status indisponível.", eventos_status=[], g=g)

    eventos_status = []
    
    # Captura o modo de visualização. 'detailed' é o padrão.
    view_mode = request.args.get('mode', 'detailed') 
    
    # Funções auxiliares para formatação de moeda
    def format_currency(value):
        if value is None: return "R$ 0,00"
        return f"R$ {safe_float(value):.2f}".replace('.', ',')

    try:
        # 1. Define o filtro com base no modo de visualização
        if view_mode == 'simple':
            # MODO SIMPLES (Operacional): MOSTRAR APENAS EVENTOS ATIVOS
            status_list = [re.compile('^ativo$', re.IGNORECASE)]
        else:
            # MODO DETALHADO (Gerencial): MOSTRAR ATIVOS, PARALISADOS E FINALIZADOS
            status_list = [
                re.compile('^ativo$', re.IGNORECASE),
                re.compile('^paralizado$', re.IGNORECASE),
                re.compile('^finalizado$', re.IGNORECASE)
            ]

        eventos_cursor = db.eventos.find({
            'status': {'$in': status_list}
        }).sort("id_evento", pymongo.ASCENDING)
        
        for evento in eventos_cursor:
            
            id_evento_int = evento.get('id_evento')
            evento['id_evento_str'] = str(evento.get('_id'))
            
            # --- 2. Busca Dados de Venda (Tabela vendas<ID>) ---
            colecao_vendas = f"vendas{id_evento_int}"
            
            if db[colecao_vendas].count_documents({}) > 0:
                vendas_data = db[colecao_vendas].aggregate([
                    {
                        '$group': {
                            '_id': None,
                            'total_unidades': {'$sum': '$quantidade_unidades'},
                            'total_valor': {'$sum': '$valor_total'} 
                        }
                    }
                ]).next()
            else:
                vendas_data = None
            
            total_unidades = vendas_data.get('total_unidades', 0) if vendas_data else 0
            total_valor = vendas_data.get('total_valor', 0) if vendas_data else 0
            
            # --- 3. Busca Numeração Atual (Tabela controle_venda) ---
            controle = db.controle_venda.find_one({'id_evento': id_evento_int})
            
            num_atual = controle.get('inicial_proxima_venda', evento.get('numero_inicial', 1)) if controle else evento.get('numero_inicial', 1)
            
            # --- 4. Formatação e Montagem do Cartão ---
            data_ativado = evento.get('data_ativado')
            
            if isinstance(data_ativado, str):
                try:
                    data_ativado_dt = datetime.strptime(data_ativado.strip(), '%Y-%m-%d')
                    data_ativado_formatada = data_ativado_dt.strftime("%d/%m/%Y") 
                except ValueError:
                    data_ativado_formatada = data_ativado 
            elif isinstance(data_ativado, datetime):
                data_ativado_formatada = data_ativado.strftime("%d/%m/%Y %H:%M:%S")
            else:
                data_ativado_formatada = 'N/A'
            
            evento_info = {
                'id_evento': evento.get('id_evento'),
                'descricao': evento.get('descricao'),
                'data_hora': f"{evento.get('data_evento', 'N/A')} às {evento.get('hora_evento', 'N/A')}",
                'status': evento.get('status'),
                'valor_venda_unit': format_currency(evento.get('valor_de_venda')),
                'data_ativacao': data_ativado_formatada,
                'total_vendido': total_unidades,
                'valor_total_vendido': format_currency(total_valor),
                'numeracao_atual': num_atual,
                'is_ativo': evento.get('status').lower() == 'ativo' if evento.get('status') else False, 
                'limite_maximo': evento.get('numero_maximo')
            }
            eventos_status.append(evento_info)

    except Exception as e:
        print(f"ERRO CRÍTICO ao buscar status de eventos: {e}")
        return render_template('consulta_status_eventos.html', error=f"Erro interno ao carregar status: {e}", eventos_status=[], g=g)

    return render_template('consulta_status_eventos.html', eventos_status=eventos_status, g=g, mode=view_mode)


# --- Rotas de Colaborador ---

@app.route('/cadastro_colaborador', methods=['GET'])
@login_required
def cadastro_colaborador():
    db = g.db
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))
        
    db_status = g.db_status
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    
    # NOVO: Captura o ID do colaborador para edição
    id_colaborador_edicao = request.args.get('id_colaborador', None) 
    
    colaborador_edicao = None 
    colaboradores_lista = []
    total_colaboradores = 0
    
    error = request.args.get('error')
    success = request.args.get('success')

    if db_status:
        try:
            total_colaboradores = db.colaboradores.count_documents({})
            
            # LÓGICA DE BUSCA DO COLABORADOR PARA EDIÇÃO
            if active_view == 'alterar' and id_colaborador_edicao:
                 try:
                     id_colaborador_int = int(id_colaborador_edicao)
                     colaborador_edicao = db.colaboradores.find_one({'id_colaborador': id_colaborador_int})
                     
                     if colaborador_edicao:
                         if '_id' in colaborador_edicao: colaborador_edicao['_id'] = str(colaborador_edicao['_id'])
                         if 'senha' in colaborador_edicao: del colaborador_edicao['senha'] # Remove a hash
                     else:
                          error = f"Colaborador ID {id_colaborador_int} não encontrado para edição."
                          active_view = 'listar' # Volta para a lista se não encontrar
                          
                 except (ValueError, TypeError):
                     error = "ID de Colaborador inválido para edição."
                     active_view = 'listar'

            # 2. Lógica de Consulta/Listagem
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

    context = {
        'total_colaboradores': total_colaboradores,
        'colaboradores_lista': colaboradores_lista,
        'active_view': active_view,
        'query': search_term, 
        'colaborador_edicao': colaborador_edicao, 
        'error': error,
        'success': success,
        'g': g
    }
    
    return render_template('cadastro_colaborador.html', **context)


@app.route('/gravar_colaborador', methods=['POST'])
@login_required
def gravar_colaborador():
    db = g.db
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido para Gravação."))

    # Verifica se é uma inserção (Novo) ou uma atualização (Alterar)
    id_colaborador_edicao = request.form.get('id_colaborador_edicao') 

    try:
        # 1. Coleta e Limpeza de Dados
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

        # 2. Validação
        if not (1 <= nivel <= 3):
            raise ValueError("Nível de acesso deve ser entre 1 e 3.")

        # 4. NOVAS VALIDAÇÕES (PIX e Senha)
        if chave_pix != confirma_chave_pix:
            raise ValueError("As chaves PIX não conferem.")
        
        # VALIDAÇÃO CRÍTICA DE SENHA
        if not id_colaborador_edicao:
            # Se for novo cadastro, ambas são obrigatórias e devem ser iguais
            if not senha or senha != confirma_senha:
                raise ValueError("Senha e Confirmação de Senha não conferem ou estão vazias.")
        elif senha and senha != confirma_senha:
            # Se for alteração e a senha foi digitada, ela deve conferir
            raise ValueError("Senha e Confirmação de Senha não conferem.")
            
        # VALIDAÇÃO CRÍTICA DO CPF (AGORA OBRIGATÓRIO)
        if not cpf_raw or not validate_cpf(cpf_raw):
            raise ValueError("CPF é obrigatório e deve ser válido.")
        
        # 3. Verificação de unicidade (Nick e CPF)
        cpf_limpo = clean_numeric_string(cpf_raw)
        query_exist = {}
        if id_colaborador_edicao:
            query_exist['id_colaborador'] = {'$ne': int(id_colaborador_edicao)} 
        
        if db.colaboradores.find_one({'$and': [query_exist, {'nick': nick}]}):
             raise ValueError("Nick já está em uso.")

        if db.colaboradores.find_one({'$and': [query_exist, {'cpf': cpf_limpo}] }):
             raise ValueError("CPF já cadastrado para outro colaborador.")


        # 4. Montagem do Documento
        dados_colaborador = {
            "nome_colaborador": nome_colaborador,
            "nick": nick,
            "telefone": telefone,
            "cidade": cidade,
            "chave_pix": chave_pix,
            "nivel": nivel,
            "cpf": cpf_limpo # Garante que o CPF limpo seja salvo
        }
        
        # Hash da Senha (Apenas se foi fornecida)
        if senha:
            hashed_password = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
            dados_colaborador['senha'] = hashed_password.decode('utf-8')
        
        # 5. Lógica de Inserção/Atualização
        if id_colaborador_edicao:
            # --- Modo ATUALIZAÇÃO (UPDATE) ---
            id_colaborador_int = int(id_colaborador_edicao)
            
            # Não permite que um admin altere seu próprio nível se for o único admin (regra de segurança)
            if id_colaborador_int == session.get('id_colaborador') and nivel < 3 and session.get('nivel') == 3 and db.colaboradores.count_documents({'nivel': 3}) == 1:
                raise ValueError("Você é o único administrador. Não pode rebaixar seu próprio nível.")
                 
            # Remove a senha do set se ela não foi alterada, para não apagar a hash existente
            if not senha and 'senha' in dados_colaborador:
                 del dados_colaborador['senha']
                 
            db.colaboradores.update_one({'id_colaborador': id_colaborador_int}, {'$set': dados_colaborador})
            success_msg = f"Colaborador {nick} atualizado com sucesso!"
            
        else:
            # --- Modo INSERÇÃO (INSERT) ---
            novo_id_colaborador_int = get_next_colaborador_sequence(db)
            if novo_id_colaborador_int is None:
                raise Exception("Falha ao gerar ID sequencial do colaborador.")

            dados_colaborador['id_colaborador'] = novo_id_colaborador_int
            
            db.colaboradores.insert_one(dados_colaborador)
            success_msg = f"Colaborador {nick} salvo com sucesso! ID: {novo_id_colaborador_int}."
        
        # 6. Redirecionamento de Sucesso
        return redirect(url_for('cadastro_colaborador', success=success_msg, view='listar'))


    except ValueError as e:
        # Erros de validação
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        return redirect(url_for('cadastro_colaborador', error=f"Erro de Validação: {e}", view=view_redirect))
        
    except Exception as e:
        # Erros gerais (DB, Geração de ID)
        print(f"ERRO CRÍTICO na gravação/atualização de colaborador: {e}")
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        return redirect(url_for('cadastro_colaborador', error="Erro interno ao gravar/atualizar colaborador.", view=view_redirect))


@app.route('/colaborador/excluir/<int:id_colaborador>', methods=['POST'])
@login_required
def excluir_colaborador(id_colaborador):
    db = g.db
    
    if session.get('nivel', 0) < 3: # Ajustado para Nível 3 (geralmente exclusão é nível admin)
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))
    
    # 1. Não permite que o próprio usuário logado se exclua
    if int(session.get('id_colaborador', 0)) == id_colaborador:
        return redirect(url_for('cadastro_colaborador', error="Não é possível excluir o próprio usuário logado.", view='listar'))

    try:
        # 2. NOVO: Busca o colaborador para verificar o Nick
        colaborador = db.colaboradores.find_one({'id_colaborador': id_colaborador})
        
        if not colaborador:
             return redirect(url_for('cadastro_colaborador', error=f"Colaborador ID: {id_colaborador} não encontrado.", view='listar'))

        # 3. NOVO: Regra de Negócio "TECBIN"
        if colaborador.get('nick', '').upper() == 'TECBIN':
            return redirect(url_for('cadastro_colaborador', error="Este colaborador (TECBIN) não pode ser excluído.", view='listar'))

        # 4. Tenta excluir
        result = db.colaboradores.delete_one({'id_colaborador': id_colaborador})
        
        if result.deleted_count == 1:
            success_msg = f"Colaborador ID: {id_colaborador} excluído com sucesso."
        else:
            # Este caso é raro, pois já verificamos acima, mas é uma boa prática
            success_msg = f"Colaborador ID: {id_colaborador} não encontrado para exclusão."

        return redirect(url_for('cadastro_colaborador', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO CRÍTICO na exclusão de colaborador ID {id_colaborador}: {e}")
        return redirect(url_for('cadastro_colaborador', error=f"Erro interno ao excluir colaborador.", view='listar'))


# --- ROTAS DE VENDA ---
@app.route('/venda/nova', methods=['GET'])
@login_required
def nova_venda():
    db = g.db
    error = request.args.get('error')
    
    # NOVO: Tenta ler a mensagem de sucesso da sessão e a remove imediatamente
    success = session.pop('success_message', None) 

    # --- INICIALIZAÇÃO CRÍTICA DAS VARIÁVEIS ---
    id_cliente_final = None
    cliente_encontrado = None
    custo = 0.00
    
    # Parâmetros vindos do formulário 
    id_evento_param = request.args.get('id_evento')
    id_cliente_busca = request.args.get('id_cliente_busca', '').strip()
    quantidade_param = request.args.get('quantidade') 
    
    # Tenta definir a quantidade, default 1
    quantidade = int(quantidade_param) if quantidade_param and str(quantidade_param).isdigit() else 1
    
    # 1. Obter todos os eventos ATIVOS e enriquecê-los com a numeração atual
    eventos_ativos_cursor = db.eventos.find({'status': 'ativo'}).sort('data_evento', pymongo.ASCENDING)
    
    eventos_enriquecidos = []
    selected_event = None
    
    for evento in eventos_ativos_cursor:
        
        # Converte o valor para float para uso no Jinja/JS
        evento['valor_de_venda_float'] = safe_float(evento.get('valor_de_venda', 0.00))

        # Buscar o controle de venda (usando id_evento INT se disponível)
        controle = db.controle_venda.find_one({
            'id_evento': evento.get('id_evento') 
        })
        
        # Calcula a próxima numeração
        inicial_proxima_venda = controle.get('inicial_proxima_venda', 1) if controle else evento.get('numero_inicial', 1)
            
        # Adiciona a numeração atual ao objeto evento
        evento['numeracao_atual_display'] = inicial_proxima_venda
        
        # CORREÇÃO CRÍTICA DE TIPAGEM PARA DATA E HORA
        def format_date_safe(field_name, format_output, format_input=None):
            value = evento.get(field_name)
            if isinstance(value, datetime):
                return value.strftime(format_output)
            elif isinstance(value, str) and value.strip() and format_input:
                # Tenta converter string YYYY-MM-DD para DD/MM/YYYY
                try:
                    dt_obj = datetime.strptime(value.strip(), format_input)
                    return dt_obj.strftime(format_output)
                except ValueError:
                    return value
            return value
        
        # O MongoDB salva data_evento como string 'YYYY-MM-DD', precisamos formatar.
        evento['data_evento'] = format_date_safe('data_evento', '%d/%m/%Y', format_input='%Y-%m-%d')
        evento['hora_evento'] = format_date_safe('hora_evento', '%H:%M') 
        
        eventos_enriquecidos.append(evento)
        
    # 3. Identificar o Evento Selecionado (Se houver)
    if id_evento_param:
        try:
            evento_oid = ObjectId(id_evento_param)
            selected_event = next((e for e in eventos_enriquecidos if e['_id'] == evento_oid), None)
            
        except Exception:
            error = "ID de evento inválido."
            selected_event = None
            
    # Se não houver evento selecionado, e houver eventos ativos, seleciona o primeiro por padrão
    if not selected_event and eventos_enriquecidos:
        selected_event = eventos_enriquecidos[0]
        
    # 4. Busca de Cliente
    
    print(f"DEBUG BUSCA: Termo recebido = '{id_cliente_busca}'")
    
    if selected_event and id_cliente_busca and g.db_status:
        search_term_clean = id_cliente_busca # Já está limpo por .strip()
        
        cliente = None
        
        # 4a. Tenta buscar por ID Sequencial (INT), ignorando prefixo "CLI"
        search_term_clean_id = search_term_clean
        if search_term_clean.upper().startswith('CLI'):
            search_term_clean_id = search_term_clean[3:].strip() # Remove 'CLI'
        
        if search_term_clean_id.isdigit():
            cliente_id_int = int(search_term_clean_id)
            cliente = db.clientes.find_one({'id_cliente': cliente_id_int})
            print(f"DEBUG BUSCA: Tentativa por ID INT {cliente_id_int}. Encontrado: {'Sim' if cliente else 'Nao'}")
            
        # 4b. Se não encontrou por ID, tenta buscar por Nome/Nick (usando o termo original não processado)
        if not cliente and search_term_clean:
            # Usamos Regex para buscar SUBSTRING (.*term.*) e garantir que a capitalização seja ignorada
            regex_query = re.compile(re.escape(search_term_clean), re.IGNORECASE)
            query_filter = {
                '$or': [
                    {'nome_cliente': {'$regex': regex_query}},
                    {'nick': {'$regex': regex_query}}
                ]
            }
            cliente = db.clientes.find_one(query_filter)
            print(f"DEBUG BUSCA: Tentativa por Nome/Nick '{search_term_clean}'. Encontrado: {'Sim' if cliente else 'Nao'}")

        if cliente:
            cliente_encontrado = cliente
            id_cliente_final = cliente.get('id_cliente')
            
            # 5. Cálculo do Custo
            valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
            custo = valor_unitario * quantidade
        
    elif selected_event:
        # Se não houver busca de cliente, mas houver evento selecionado, calcula o custo com quantidade default
        valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
        custo = valor_unitario * quantidade
        
    return render_template('venda.html', 
                           db_status=g.db_status,
                           error=error,
                           success=success, # <--- Passa o 'success' da sessão
                           eventos=eventos_enriquecidos,
                           selected_event=selected_event,
                           id_cliente_final=id_cliente_final,
                           cliente_busca=id_cliente_busca,
                           cliente_encontrado=cliente_encontrado,
                           quantidade=quantidade,
                           custo=custo)



@app.route('/processar_venda', methods=['POST'])
@login_required
def processar_venda():
    """Processo Crítico de Venda - Aplica atomicidade e grava no MongoDB."""

    if not g.db_status:
        # Tenta pegar os IDs para devolver no redirecionamento de erro
        id_evento_string = request.form.get('id_evento')
        id_cliente_final_str = request.form.get('id_cliente_final')
        error_redirect_kwargs = {
            'id_evento': id_evento_string,
            'id_cliente_busca': f"CLI{id_cliente_final_str}" if id_cliente_final_str else '',
            'error': "DB Offline. Transação Crítica Falhou."
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    db = g.db
    
    # 1. Leitura de Variáveis do Formulário
    id_evento_string = request.form.get('id_evento') 
    id_cliente_final_str = request.form.get('id_cliente_final') 
    
    try:
        # CRÍTICO CLIENTE: Converte ID do cliente (que é INT)
        id_cliente_final = int(id_cliente_final_str)
    except (TypeError, ValueError):
        error_redirect_kwargs = {
            'id_evento': id_evento_string, 
            'error': "ID de Cliente inválido ou ausente."
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    # Tentativa de conversão do ID do evento para uso no Mongo (para buscar o Evento pelo _id)
    id_evento_mongo = try_object_id(id_evento_string)

    try:
        quantidade = int(request.form.get('quantidade'))
        if quantidade <= 0: raise ValueError
    except:
        error_redirect_kwargs = {
            'id_evento': id_evento_string,
            'id_cliente_busca': f"CLI{id_cliente_final_str}",
            'error': "Quantidade inválida."
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))
    
    # Validação de IDs
    if not id_evento_mongo:
        return redirect(url_for('nova_venda', error="Dados inválidos: Evento não selecionado/enviado no formulário."))
    
    # 2. Busca Evento e Cliente (para dados e validação)
    selected_event = db.eventos.find_one({'_id': id_evento_mongo})
    cliente_doc = db.clientes.find_one({"id_cliente": id_cliente_final})
    
    if not selected_event:
        return redirect(url_for('nova_venda', error="Evento inválido ou não encontrado no DB."))
    if not cliente_doc:
         error_redirect_kwargs = {
            'id_evento': id_evento_string,
            'error': "Cliente não encontrado no sistema.",
            'id_cliente_busca': f"CLI{id_cliente_final_str}"
        }
         return redirect(url_for('nova_venda', **error_redirect_kwargs))
        
    # Extração de Dados Críticos
    id_evento_int_para_controle = selected_event.get('id_evento') 
    limite_maximo_cartelas = int(selected_event.get('numero_maximo', 72000))
    if not isinstance(id_evento_int_para_controle, int):
        error_redirect_kwargs = {
            'id_evento': id_evento_string,
            'id_cliente_busca': f"CLI{id_cliente_final_str}",
            'error': "Erro: ID sequencial do evento (int) não encontrado no documento do evento."
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
    unidade_de_venda = int(selected_event.get('unidade_de_venda', 1))

    # Cálculo da Venda
    valor_total = valor_unitario * quantidade
    quantidade_cartelas = quantidade * unidade_de_venda

    # Colaborador (e nick para o comprovante)
    colaborador_id = session.get('id_colaborador', 'N/A')
    nick_colaborador = session.get('nick', 'Colaborador') 

    # --- 3. ETAPA CRÍTICA: Geração de IDs e Números de Bilhetes (Atomicidade) ---
    id_evento_para_controle = id_evento_int_para_controle 
    
    if venda_lock.acquire(timeout=5): 
        try:
            # 3a. Geração Atômica do ID da Venda (Contador global: 'id_vendas_global')
            novo_id_venda_int = get_next_global_sequence(db, 'id_vendas_global')
            if novo_id_venda_int is None:
                raise Exception("Falha ao gerar o ID sequencial da venda.")
                
            id_venda_formatado = f"V{novo_id_venda_int:05d}"

            # 3b. Geração Atômica dos Números de Bilhetes/Cartelas
            numero_inicial_evento = int(selected_event.get('numero_inicial', 1))

            numero_inicial = get_next_bilhete_sequence(db, 
                                                       id_evento_para_controle, 
                                                       'inicial_proxima_venda', 
                                                       quantidade_cartelas,
                                                       limite_maximo_cartelas)
            
            if numero_inicial is None:
                raise Exception("Falha ao obter o número inicial do bilhete/cartela.")

            # Se a sequência de controle for igual ao valor inicial padrão, ajusta para o numero_inicial do evento.
            if numero_inicial == 1: 
                numero_inicial = numero_inicial_evento
                
                # Corrigir o contador para o próximo valor, se a primeira venda usar o numero_inicial do evento
                db.controle_venda.update_one(
                    {'id_evento': id_evento_para_controle},
                    {'$set': {'inicial_proxima_venda': numero_inicial + quantidade_cartelas}}
                )

            numero_final = numero_inicial + quantidade_cartelas - 1
            numero_final2 = 0
            numero_inicial2 = 0  
            
            if numero_final > limite_maximo_cartelas:
                numero_inicial2 = 1
                numero_final2 = numero_final - limite_maximo_cartelas
                numero_final = limite_maximo_cartelas
                periodo_adicional = (
                        f"    <span style='font-size: 1.4rem; color: #0047AB;'><strong>{numero_inicial2} a {numero_final2}</strong></span><br>"
                    )
            else:
                periodo_adicional = (
                        f"<br>"
                    )                              
            # 4. Gravação Final do Registro de Venda
            registro_venda = {
                "id_venda": id_venda_formatado,
                "id_evento_ObjectId": id_evento_mongo, 
                "id_evento": id_evento_para_controle, 
                "descricao_evento": selected_event.get('descricao'),
                "id_cliente": id_cliente_final, # ID Sequencial do Cliente (INT)
                "nome_cliente": cliente_doc.get('nome_cliente'),
                "id_colaborador": colaborador_id,
                "nick_colaborador": nick_colaborador,
                "data_venda": datetime.utcnow(),
                "quantidade_unidades": quantidade,
                "quantidade_cartelas": quantidade_cartelas,
                "numero_inicial": numero_inicial,
                "numero_final": numero_final,
                "numero_inicial2": numero_inicial2,
                "numero_final2": numero_final2,
                "valor_unitario": Decimal128(str(valor_unitario)), 
                "valor_total": Decimal128(str(valor_total))
            }
            
            # 5. Atualiza data da última compra do cliente (opcional, pode ser async)
            db.clientes.update_one(
                {"id_cliente": id_cliente_final}, 
                {"$set": {"data_ultimo_compra": datetime.utcnow()}}
            )

            # 6. Inserção no Banco de Dados (Coleção 'vendas' = id_evento)
            nome_colecao_venda = f"vendas{str(id_evento_para_controle).strip()}"
            db[nome_colecao_venda].insert_one(registro_venda)
            
            # 7. Pós-Venda (Comprovante)
            data_evento_str = selected_event.get('data_evento', 'N/A')
            hora_evento_str = selected_event.get('hora_evento', 'N/A')
            http_apk = g.parametros_globais.get('http_apk', '')
            
            data_evento_formatada = data_evento_str
            if data_evento_str:
                 try:
                      # Se estiver DD/MM/YYYY, apenas garante o separador '-'
                      data_evento_formatada = data_evento_str.replace('/', '-')
                 except Exception:
                      pass
            
            nome_sala  = g.parametros_globais.get('nome_sala', '')
             
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
                f"Unidades Compradas: <strong>{quantidade}<strong><br>"
                f"     <strong>(Cartelas: {quantidade_cartelas})<strong><br>"
                f"<strong> >  Período de Cartelas  <<strong><br>"
                f"   <span style='font-size: 1.4rem; color: #0047AB;'><strong>{numero_inicial} a {numero_final}</strong></span><br>"
                f"{periodo_adicional}"
                f"  VALOR:<span style='font-size: 1.2rem; color: #B91C1C;'>R$ {valor_total:.2f}</span><br>"
                f"<br>"
                f"<strong> {http_apk} <strong>"
            )
            
            # NOVO: Salva a mensagem de sucesso na sessão
            session['success_message'] = success_msg 

            # Argumentos para redirecionamento: mantém o evento e RESETA o cliente/quantidade
            redirect_kwargs = {
                'id_evento': id_evento_string,
                'quantidade': 1 # Reseta a quantidade para 1
                # id_cliente_busca É INTENCIONALMENTE REMOVIDO para limpar o campo de busca
            }

            # Retorna para a página de venda
            return redirect(url_for('nova_venda', **redirect_kwargs))

        except Exception as e:
            print(f"Erro Crítico durante a venda no DB: {e}")
            error_redirect_kwargs = {
                'id_evento': id_evento_string,
                'error': f"Erro interno no DB: Falha ao gravar a transação.",
                'id_cliente_busca': f"CLI{id_cliente_final_str}",
                'quantidade': quantidade
            }
            return redirect(url_for('nova_venda', **error_redirect_kwargs))
            
        finally:
            venda_lock.release()

# --- ROTAS DE CADASTRO DE CLIENTE ---
@app.route('/cadastro_cliente', methods=['GET'])
@login_required
def cadastro_cliente():
    db = g.db
    db_status = g.db_status
    
    # 1. Variáveis de Estado (Inicialização Garantida)
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    next_url = request.args.get('next', 'menu_operacoes')
    id_evento_retorno = request.args.get('id_evento') # Captura, mas pode ser None
    id_cliente_edicao = request.args.get('id_cliente', None)
    
    clientes_lista = []
    total_clientes = 0
    cliente_edicao = None 
    
    error = request.args.get('error')
    success = request.args.get('success')

    if db_status:
        try:
            # 2. Contagem Total
            total_clientes = db.clientes.count_documents({})
            
            # 3. Lógica de BUSCA DO CLIENTE PARA EDIÇÃO
            if active_view == 'alterar' and id_cliente_edicao:
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
            
            # 4. Lógica de Consulta/Listagem

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

    # 5. CRÍTICO: Conversão de tipos de dados para o Jinja
    for cliente in clientes_lista:
        if '_id' in cliente: cliente['_id'] = str(cliente['_id'])
        # Formatação de datas
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
        'g': g
    }
    
    return render_template('cadastro_cliente.html', **context)



@app.route('/gravar_cliente', methods=['POST'])
@login_required
def gravar_cliente():
    db = g.db
    db_status = g.db_status
    
    # CRÍTICO: Captura a URL de retorno e o ID do evento
    next_url = request.form.get('next_url', 'menu_operacoes')
    id_evento_retorno = request.form.get('id_evento_retorno') 
    
    # Verifica se é uma inserção (Novo) ou uma atualização (Alterar)
    id_cliente_edicao = request.form.get('id_cliente_edicao') 

    if not db_status:
        # CORREÇÃO DE FLUXO: Mantém o destino original e os dados em caso de erro.
        view_redirect = 'alterar' if id_cliente_edicao else 'novo'
        return redirect(url_for('cadastro_cliente', error="DB Offline. Gravação Crítica Falhou.", view=view_redirect, next=next_url, id_evento=id_evento_retorno))
    
    try:
        # 1. Coleta e Limpeza de Dados
        nome_cliente = format_title_case(request.form.get('nome_cliente'))
        nick = format_title_case(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip()
        confirma_chave_pix = request.form.get('confirma_chave_pix', '').strip()
        senha = request.form.get('senha')
        confirma_senha = request.form.get('confirma_senha')

        # 2. Validação Mínima
        if not nome_cliente or not nick or not cidade or not chave_pix:
            raise ValueError("Preencha todos os campos obrigatórios (*).")
        
        # 3. Validação de CPF 
        if cpf_raw and not validate_cpf(cpf_raw):
             raise ValueError("O CPF inserido não é válido.")

        # 4. NOVAS VALIDAÇÕES (PIX e Senha)
        if chave_pix != confirma_chave_pix:
            raise ValueError("As chaves PIX não conferem.")
        
        if senha != confirma_senha:
            raise ValueError("As senhas não conferem.")

        # 5. LÓGICA DA SENHA (Padrão = Nick)
        if senha:
            senha_final_raw = senha
        elif not id_cliente_edicao: 
            # Se for NOVO cadastro e a senha estiver vazia, usa o Nick
            senha_final_raw = nick 
        else:
            # Se for ALTERAÇÃO e a senha estiver vazIA, não faz nada (mantém a senha antiga)
            senha_final_raw = None

        # 6. Dados a serem inseridos/atualizados
        dados_cliente = {
            "nome_cliente": nome_cliente,
            "cpf": clean_numeric_string(cpf_raw),
            "nick": nick,
            "telefone": telefone,
            "cidade": cidade,
            "chave_pix": chave_pix,
            "id_colaborador": session.get('id_colaborador', 'N/A'),
        }
        
        # 7. Adiciona a senha apenas se ela foi definida
        if senha_final_raw:
            # Formata a senha (Primeira maiúscula)
            senha_formatada = senha_final_raw.capitalize()
            hashed_password = bcrypt.hashpw(senha_formatada.encode('utf-8'), bcrypt.gensalt())
            dados_cliente['senha'] = hashed_password.decode('utf-8') # Salva a senha com hash

        
        # 8. Lógica de Inserção/Atualização
        novo_id_cliente_int = None
        
        if id_cliente_edicao:
            # --- Modo ATUALIZAÇÃO (UPDATE) ---
            id_cliente_int = int(id_cliente_edicao)
            
            # Se a senha não foi alterada (senha_final_raw é None), não a incluímos no $set
            if 'senha' not in dados_cliente:
                 # Recupera a senha antiga do DB se necessário, mas o melhor é não tocar nela
                 pass 
                 
            db.clientes.update_one({'id_cliente': id_cliente_int}, {'$set': dados_cliente})
            success_msg = f"Cliente ID: CLI{id_cliente_int} atualizado com sucesso!"
            
        else:
            # --- Modo INSERÇÃO (INSERT) ---
            novo_id_cliente_int = get_next_cliente_sequence(db)
            if novo_id_cliente_int is None:
                raise Exception("Falha ao gerar ID sequencial do cliente.")

            dados_cliente.update({
                "id_cliente": novo_id_cliente_int, # CRÍTICO: INT
                "data_cadastro": datetime.utcnow(),
                "data_ultimo_compra": None 
            })
            
            db.clientes.insert_one(dados_cliente)
            success_msg = f"Cliente '{nick}' salvo com sucesso! ID: CLI{novo_id_cliente_int}."
        
        # 9. Prepara os argumentos de redirecionamento
        redirect_kwargs = {'success': success_msg}

        if next_url == 'nova_venda':
            cliente_id_para_retorno = id_cliente_edicao if id_cliente_edicao else str(novo_id_cliente_int)
            redirect_kwargs['id_cliente_final'] = cliente_id_para_retorno
            if id_evento_retorno:
                redirect_kwargs['id_evento'] = id_evento_retorno
        
        return redirect(url_for(next_url, **redirect_kwargs))


    except ValueError as e:
        # Erros de validação
        view_redirect = 'alterar' if id_cliente_edicao else 'novo'
        return redirect(url_for('cadastro_cliente', error=f"Erro de Validação: {e}", view=view_redirect, next=next_url, id_evento=id_evento_retorno))
        
    except Exception as e:
        # Erros gerais (DB, Geração de ID)
        print(f"ERRO CRÍTICO na gravação/atualização de cliente: {e}")
        view_redirect = 'alterar' if id_cliente_edicao else 'novo'
        return redirect(url_for('cadastro_cliente', error="Erro interno ao gravar/atualizar cliente.", view=view_redirect, next=next_url, id_evento=id_evento_retorno))



@app.route('/cliente/excluir/<int:id_cliente>', methods=['POST'])
@login_required
def excluir_cliente(id_cliente):
    db = g.db
    
    if not g.db_status:
        return redirect(url_for('cadastro_cliente', error="DB Offline. Exclusão Falhou.", view='listar'))

    try:
        # 1. Tenta excluir
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
    db = g.db
    db_status = g.db_status
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    id_evento_edicao = request.args.get('id_evento', None)
    
    evento_edicao = None 
    eventos_lista = []
    total_eventos = 0
    
    error = request.args.get('error')
    success = request.args.get('success')

    if db_status:
        try:
            total_eventos = db.eventos.count_documents({})
            
            # LÓGICA DE BUSCA DO EVENTO PARA EDIÇÃO
            if active_view == 'alterar' and id_evento_edicao:
                 try:
                     id_evento_int = int(id_evento_edicao)
                     evento_edicao = db.eventos.find_one({'id_evento': id_evento_int})
                     
                     if evento_edicao:
                         if '_id' in evento_edicao: evento_edicao['_id'] = str(evento_edicao['_id'])
                         # Converte todos os Decimal128 para float para o Jinja
                         for key in evento_edicao:
                             if isinstance(evento_edicao[key], Decimal128):
                                 evento_edicao[key] = safe_float(evento_edicao[key])
                     else:
                          error = f"Evento ID {id_evento_int} não encontrado para edição."
                          active_view = 'listar'
                          
                 except (ValueError, TypeError):
                     error = "ID de Evento inválido para edição."
                     active_view = 'listar'

            # Lógica de Consulta/Listagem
            if active_view == 'listar':
                # Ordena pela data do evento mais próxima (assumindo que a data está em formato yyyy-mm-dd)
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

    # Conversão de Decimal128 para float para todos os eventos na lista
    for evento in eventos_lista:
        if '_id' in evento: evento['_id'] = str(evento['_id'])
        for key in evento:
            if isinstance(evento[key], Decimal128):
                evento[key] = safe_float(evento[key])

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
    db = g.db
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido para Gravação."))

    # Verifica se é uma inserção (Novo) ou uma atualização (Alterar)
    id_evento_edicao = request.form.get('id_evento_edicao') 
    
    # --- FUNÇÃO AUXILIAR DE LIMPEZA DE FLOAT ---
    def clean_float_input(form_key, default_value='0'):
        """Trata a entrada do formulário, convertendo '' para default_value e trocando ',' por '.'"""
        value_raw = request.form.get(form_key, default_value)
        if not value_raw or value_raw.strip() == '':
            value_raw = str(default_value)
        
        # Converte para float (trocando a vírgula decimal)
        return float(value_raw.replace(',', '.'))
    # -------------------------------------------

    try:
        # 1. Coleta e Limpeza de Dados
        data_evento_str = request.form.get('data_evento') # Recebe YYYY-MM-DD do input[type=date]
        hora_evento = request.form.get('hora_evento')
        descricao = format_title_case(request.form.get('descricao'))
        unidade_de_venda = int(request.form.get('unidade_de_venda', 1))
        
        # Usando a nova função de limpeza:
        valor_de_venda = clean_float_input('valor_de_venda')
        premio_quadra = clean_float_input('premio_quadra')
        premio_linha = clean_float_input('premio_linha')
        premio_bingo = clean_float_input('premio_bingo')
        premio_segundobingo = clean_float_input('premio_segundobingo', default_value='0')
        premio_acumulado = clean_float_input('premio_acumulado', default_value='0')
        minimo_de_venda = clean_float_input('minimo_de_venda', default_value='0') # Captura o valor (desabilitado, mas bom ter o dado limpo)

        # Campos INT que podem vir vazios (usamos default_value na coleta)
        numero_inicial = int(request.form.get('numero_inicial', 1))
        numero_maximo = int(request.form.get('numero_maximo', 72000))
        quantidade_de_linhas = int(request.form.get('quantidade_de_linhas', 1))
        bola_tope_acumulado = int(request.form.get('bola_tope_acumulado', 0)) # 0 se desativado/vazio
        
        
        # 2. Validação Mínima e de Formato
        if not all([data_evento_str, hora_evento, descricao, unidade_de_venda, valor_de_venda]):
             raise ValueError("Preencha todos os campos obrigatórios (*).")
        
        if not (1 <= unidade_de_venda <= 6):
             raise ValueError("Unidade de venda deve ser entre 1 e 6.")

        if not (1 <= quantidade_de_linhas <= 3):
             raise ValueError("Quantidade de linhas deve ser entre 1 e 3.")

        # Converte data: data_evento_str JÁ VEM EM YYYY-MM-DD. 
        try:
             # Tenta converter para objeto datetime usando o formato HTML (YYYY-MM-DD)
             data_obj = datetime.strptime(data_evento_str, '%Y-%m-%d')
             
             # CRÍTICO: CRIA A NOVA STRING NO FORMATO DD/MM/YYYY PARA GRAVAÇÃO
             data_evento_str_gravar = data_obj.strftime('%d/%m/%Y')
             
        except ValueError:
             raise ValueError("Formato de data inválido. Use AAAA-MM-DD.")
        
        # CRÍTICO: CRIA O CAMPO DATA_HORA_EVENTO COMO OBJETO DATETIME NATIVO
        data_hora_evento_str = f"{data_evento_str} {hora_evento}" # Ex: '2025-11-06 20:00'
        data_hora_evento_dt = datetime.strptime(data_hora_evento_str, '%Y-%m-%d %H:%M')
        
        # 3. Cálculo do Prêmio Total
        premio_total = premio_quadra + (premio_linha * quantidade_de_linhas) + premio_bingo + premio_segundobingo + premio_acumulado
        
        # 4. Montagem do Documento
        dados_evento = {
            "data_evento": data_evento_str_gravar, # AGORA: DD/MM/YYYY
            "hora_evento": hora_evento, # Mantido para edição do usuário (HH:MM)
            "data_hora_evento": data_hora_evento_dt, # NOVO CAMPO DATETIME PARA ORDENAÇÃO
            "descricao": descricao,
            "unidade_de_venda": unidade_de_venda,
            "valor_de_venda": Decimal128(str(valor_de_venda)),
            "numero_inicial": numero_inicial,
            "numero_maximo": numero_maximo,
            "premio_quadra": Decimal128(str(premio_quadra)),
            "quantidade_de_linhas": quantidade_de_linhas,
            "premio_linha": Decimal128(str(premio_linha)),
            "premio_bingo": Decimal128(str(premio_bingo)),
            "premio_segundobingo": Decimal128(str(premio_segundobingo)),
            "premio_total": Decimal128(str(premio_total)), # Valor calculado
            "premio_acumulado": Decimal128(str(premio_acumulado)),
            "bola_tope_acumulado": bola_tope_acumulado,
            "minimo_de_venda": Decimal128(str(minimo_de_venda)),
            "id_colaborador": session.get('id_colaborador', 'N/A'),
        }
        
        # 5. Lógica de Inserção/Atualização
        novo_id_evento_int = None
        
        if id_evento_edicao:
            # --- Modo ATUALIZAÇÃO (UPDATE) ---
            id_evento_int = int(id_evento_edicao)
            
            # Remove o status e data_ativado do set para não sobrescrever se não houver lógica de controle externa
            if 'status' in dados_evento:
                 del dados_evento['status']
            if 'data_ativado' in dados_evento:
                 del dados_evento['data_ativado']
                 
            db.eventos.update_one({'id_evento': id_evento_int}, {'$set': dados_evento})
            success_msg = f"Evento ID: {id_evento_int} atualizado com sucesso!"
            
        else:
            # --- Modo INSERÇÃO (INSERT) ---
            try:
                global get_next_evento_sequence 
                novo_id_evento_int = get_next_evento_sequence(db)
            except NameError:
                novo_id_evento_int = None 

            if novo_id_evento_int is None:
                raise Exception("Falha ao gerar ID sequencial do evento.")

            dados_evento.update({
                "id_evento": novo_id_evento_int, 
                "status": "paralizado", # Status inicial
                "data_ativado": None, # Data de ativação das vendas (definida ao mudar status para 'ativo')
                "data_cadastro": datetime.utcnow()
            })
            
            db.eventos.insert_one(dados_evento)
            success_msg = f"Evento '{dados_evento['descricao']}' salvo com sucesso! ID: {novo_id_evento_int}."
        
        # 6. Redirecionamento de Sucesso
        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))


    except ValueError as e:
        # Erros de validação (Conversão ou Range de Valores)
        view_redirect = 'alterar' if id_evento_edicao else 'novo'
        return redirect(url_for('cadastro_evento', error=f"Erro de Validação: {e}", view=view_redirect))
        
    except Exception as e:
        # Erros gerais (DB, Geração de ID)
        print(f"ERRO CRÍTICO na gravação/atualização de evento: {e}")
        view_redirect = 'alterar' if id_evento_edicao else 'novo'
        return redirect(url_for('cadastro_evento', error="Erro interno ao gravar/atualizar evento.", view=view_redirect))




@app.route('/excluir_evento/<int:id_evento>', methods=['POST'])
@login_required
def excluir_evento(id_evento):
    db = g.db
    
    try:
        # 1. Tenta excluir
        result = db.eventos.delete_one({'id_evento': id_evento})
        
        if result.deleted_count == 1:
            success_msg = f"Evento ID: {id_evento} excluído com sucesso."
        else:
            success_msg = f"Evento ID: {id_evento} não encontrado para exclusão."

        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO CRÍTICO na exclusão de evento ID {id_evento}: {e}")
        return redirect(url_for('cadastro_evento', error=f"Erro interno ao excluir evento.", view='listar'))


if __name__ == '__main__':
    # Para desenvolvimento local apenas
    # Em produção, use Gunicorn via Dockerfile
    # Comando: gunicorn -w 4 -b 0.0.0.0:8080 app:app

    # Verifica se NÃO está em produção
    if os.environ.get('FLASK_ENV') != 'production':
        app.run(debug=True, host='0.0.0.0', port=5001)
    else:
        print("⚠️  AVISO: Em produção, use Gunicorn. Não execute app.py diretamente!")