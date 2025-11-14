# app.py (Versão Final com Rotas de Colaborador, Cliente e Eventos)

import threading
import pymongo
from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify
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
import html # <-- Importado para a nova rota
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
    
    # Configuração Padrão (fallback)
    default_config_cadastro = {
        "nome_cliente": True, "nick": True, "telefone": True,
        "cpf": False, "cidade": True, "chave_pix": True, "senha": True
    }
    
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
                    'tipo_cadastro_cliente': params_doc.get('tipo_cadastro_cliente', default_config_cadastro),
                    'comissao_padrao': params_doc.get('comissao_padrao', 20), # 20% como fallback
                }
            else:
                 g.parametros_globais = {
                     'tipo_cadastro_cliente': default_config_cadastro,
                     'comissao_padrao': 20
                 }
        except Exception as e:
            print(f"🚨 ERRO ao carregar Parâmetros Globais: {e}")
            g.parametros_globais = {
                'tipo_cadastro_cliente': default_config_cadastro,
                'comissao_padrao': 20
            }
    elif not g.parametros_globais:
        # Fallback se o DB estiver offline
        g.parametros_globais = {
            'tipo_cadastro_cliente': default_config_cadastro,
            'comissao_padrao': 20
        }


# --- ROTAS DE NAVEGAÇÃO E AUTENTICAÇÃO ---

@app.route('/menu')
@login_required
def menu_operacoes():
    nivel = session.get('nivel', 1) 
    nome_logado = session.get('nick', 'Colaborador')
    db_status = g.db_status 
    return render_template('menu.html', nivel=nivel, logado=nome_logado, db_status=db_status)

@app.route('/login', methods=['POST'])
def login():
    nome_usuario = format_title_case(request.form.get('nome'))
    senha = format_title_case(request.form.get('senha'))
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


@app.route('/dashboard_cliente')
@login_required
def dashboard_cliente():
    """Exibe o dashboard (menu) para o cliente logado."""
    
    # Verificação de segurança: Garante que é um cliente (Nível 0)
    if session.get('nivel', 1) != 0:
        session.clear() # Limpa a sessão se um colaborador tentar acessar
        return redirect(url_for('login_page', error="Tipo de acesso inválido."))

    # Pega o nick da sessão (definido na função login)
    nick_cliente = session.get('nick', 'Cliente')
    
    # Renderiza o template HTML
    return render_template('dashboard_cliente.html', nick_cliente=nick_cliente, g=g)


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
    
    # --- NOVO: Captura mensagens de sucesso/erro da sessão ---
    error = session.pop('error_message', None)
    success = session.pop('success_message', None)
    
    if not g.db_status:
        # Passa o 'error' do DB para o template
        return render_template('consulta_status_eventos.html', error="DB Offline. Status indisponível.", eventos_status=[], g=g, success=success)

    eventos_status = []
    
    # Captura o modo de visualização. 'detailed' é o padrão.
    view_mode = request.args.get('mode', 'detailed') 
    
    # Funções auxiliares (pode manter as suas)
    def format_currency(value):
        if value is None: return "R$ 0,00"
        return f"R$ {safe_float(value):.2f}".replace('.', ',')

    try:
        # ... (Toda a sua lógica de busca e formatação de 'eventos_status' continua igual) ...
        
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
            # ... (Toda a sua lógica de agregação de vendas e numeração) ...
            
            # --- Bloco de agregação (mantido como estava) ---
            colecao_vendas = f"vendas{id_evento_int}"
            if db[colecao_vendas].count_documents({}) > 0:
                # Use .next() com segurança, verificando se há resultados
                vendas_data_list = list(db[colecao_vendas].aggregate([
                    {'$group': {'_id': None, 'total_unidades': {'$sum': '$quantidade_unidades'}, 'total_valor': {'$sum': '$valor_total'}}}
                ]))
                vendas_data = vendas_data_list[0] if vendas_data_list else None
            else:
                vendas_data = None
            total_unidades = vendas_data.get('total_unidades', 0) if vendas_data else 0
            total_valor = vendas_data.get('total_valor', 0) if vendas_data else 0
            controle = db.controle_venda.find_one({'id_evento': id_evento_int})
            num_atual = controle.get('inicial_proxima_venda', evento.get('numero_inicial', 1)) if controle else evento.get('numero_inicial', 1)
            
            # --- Bloco de formatação (mantido como estava) ---
            data_ativado = evento.get('data_ativado')
            if isinstance(data_ativado, str):
                try:
                    data_ativado_dt = datetime.strptime(data_ativado.strip(), '%Y-%m-%d')
                    data_ativado_formatada = data_ativado_dt.strftime("%d/%m/%Y") 
                except ValueError: data_ativado_formatada = data_ativado 
            elif isinstance(data_ativado, datetime):
                data_ativado_formatada = data_ativado.strftime("%d/%m/%Y %H:%M:%S")
            else: data_ativado_formatada = 'N/A'
            
            evento_info = {
                'id_evento': evento.get('id_evento'),
                'descricao': evento.get('descricao'),
                'data_hora': f"{evento.get('data_evento', 'N/A')} às {evento.get('hora_evento', 'N/A')}",
                'status': evento.get('status').lower(), # <-- Garante minúsculas
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
        # Passa o 'error' para o template
        return render_template('consulta_status_eventos.html', error=f"Erro interno ao carregar status: {e}", eventos_status=[], g=g, success=success, mode=view_mode)

    # Passa 'success' e 'error' para o template
    return render_template('consulta_status_eventos.html', eventos_status=eventos_status, g=g, mode=view_mode, error=error, success=success)


@app.route('/evento/mudar_status', methods=['POST'])
@login_required
def evento_mudar_status():
    """Altera o status de um evento (Ativo, Paralizado, Finalizado)."""
    
    # 1. Segurança: Somente Nível 3 pode mudar status
    if session.get('nivel', 0) < 3:
        session['error_message'] = "Acesso Negado. Nível 3 Requerido."
        return redirect(url_for('consulta_status_eventos'))
        
    db = g.db
    
    # 2. Coleta de dados do formulário
    try:
        id_evento_int = int(request.form.get('id_evento_int'))
        novo_status = request.form.get('novo_status').lower() # Garante minúsculas
        current_mode = request.form.get('current_mode', 'detailed')
    except Exception as e:
        session['error_message'] = f"Dados inválidos: {e}"
        return redirect(url_for('consulta_status_eventos'))
        
    # 3. Validação
    if novo_status not in ['ativo', 'paralizado', 'finalizado']:
        session['error_message'] = "Status inválido."
        return redirect(url_for('consulta_status_eventos', mode=current_mode))

    try:
        # 4. Lógica de Atualização
        update_data = {'status': novo_status}
        
        # --- Lógica Inteligente de Ativação ---
        # Se está mudando PARA 'ativo', verifica se a data de ativação já foi setada.
        if novo_status == 'ativo':
            evento = db.eventos.find_one({'id_evento': id_evento_int}, {'data_ativado': 1})
            # Se o evento existe E a data de ativação ainda é Nula, seta ela agora.
            if evento and evento.get('data_ativado') is None:
                update_data['data_ativado'] = datetime.utcnow()
        
        # 5. Executa a atualização no DB
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
    db = g.db
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))
        
    db_status = g.db_status
    
    # --- INÍCIO DA CORREÇÃO (Lógica de Erro) ---
    # 1. Tenta pegar dados de um erro anterior.
    form_data_erro = session.pop('form_data', None)
    # --- FIM DA CORREÇÃO ---
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    
    id_colaborador_edicao = request.args.get('id_colaborador', None) 
    
    colaborador_edicao = None 
    colaboradores_lista = []
    total_colaboradores = 0
    
    error = request.args.get('error')
    success = request.args.get('success')

    # --- INÍCIO DA CORREÇÃO (Lógica de Preenchimento) ---
    if form_data_erro:
        # 2. Se 'form_data_erro' existe, um erro acabou de ocorrer.
        #    Usamos esses dados para preencher o formulário.
        colaborador_edicao = form_data_erro
        
        # Garante que a view ('novo' or 'alterar') esteja correta
        if 'id_colaborador_edicao' in form_data_erro and form_data_erro['id_colaborador_edicao']:
             active_view = 'alterar'
             # Passa o ID de volta para o 'context'
             id_colaborador_edicao = form_data_erro['id_colaborador_edicao']
        else:
             active_view = 'novo'

    elif active_view == 'alterar' and id_colaborador_edicao and db_status:
         # 3. Se NÃO há 'form_data_erro', é um carregamento normal.
         #    Buscamos no DB como na sua lógica original.
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
            
    # --- FIM DA CORREÇÃO ---

    if db_status:
        try:
            total_colaboradores = db.colaboradores.count_documents({})
            
            # A lógica de 'alterar' já foi movida para cima

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
        
    # --- NOVO: Pega a comissão padrão ---
    # (Usa 20 como fallback final se 'g' não tiver o valor)
    default_comissao = g.parametros_globais.get('comissao_padrao', 20)
    # --- FIM DA ALTERAÇÃO ---

    context = {
        'total_colaboradores': total_colaboradores,
        'colaboradores_lista': colaboradores_lista,
        'active_view': active_view,
        'query': search_term, 
        'colaborador_edicao': colaborador_edicao,
        'error': error,
        'success': success,
        'g': g,
        'default_comissao': default_comissao # <-- ADICIONADO AO CONTEXTO
    }
    
    return render_template('cadastro_colaborador.html', **context)


@app.route('/gravar_colaborador', methods=['POST'])
@login_required
def gravar_colaborador():
    db = g.db
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido para Gravação."))

    id_colaborador_edicao = request.form.get('id_colaborador_edicao') 

    try:
        # --- ATENÇÃO: Carrega a configuração dinâmica de campos ---
        # (Se você não criou um 'tipo_cadastro_colaborador' nos parâmetros, ele usará este padrão)
        default_colab_config = {
            "nome_colaborador": True, "nick": True, "telefone": False,
            "cpf": True, "cidade": False, "chave_pix": True, "senha": True,
            "nivel": True, "comissao": True # <-- Adicionado comissao
        }
        campos_config = g.parametros_globais.get('tipo_cadastro_colaborador', default_colab_config)

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
            
        # VALIDAÇÃO CRÍTICA DE SENHA (Dinâmica)
        if "senha" in campos_config:
            if not id_colaborador_edicao and campos_config.get("senha") and (not senha or senha != confirma_senha):
                raise ValueError("Senha e Confirmação de Senha não conferem ou estão vazias.")
            elif id_colaborador_edicao and senha and (senha != confirma_senha):
                raise ValueError("Senha e Confirmação de Senha não conferem.")
                
        # VALIDAÇÃO CRÍTICA DO CPF (Dinâmica)
        cpf_limpo = clean_numeric_string(cpf_raw)
        if campos_config.get("cpf") == True: # Se CPF é OBRIGATÓRIO
            if not cpf_raw or not validate_cpf(cpf_limpo):
                raise ValueError("CPF é obrigatório e deve ser válido.")
        elif "cpf" in campos_config and cpf_raw and not validate_cpf(cpf_limpo):
            # Se CPF é OPCIONAL (false) mas foi digitado
            raise ValueError("O CPF inserido não é válido.")
        
        # 3. Verificação de unicidade (Nick e CPF)
        query_exist = {}
        if id_colaborador_edicao:
            query_exist['id_colaborador'] = {'$ne': int(id_colaborador_edicao)} 
        
        if "nick" in campos_config and nick and db.colaboradores.find_one({'$and': [query_exist, {'nick': nick}]}):
             raise ValueError("Nick já está em uso, por outro colaborador.")

        if "cpf" in campos_config and cpf_limpo and db.colaboradores.find_one({'$and': [query_exist, {'cpf': cpf_limpo}] }):
             raise ValueError("CPF já cadastrado para outro colaborador.")

        # 4. Montagem do Documento Dinâmico
        dados_colaborador = {
            "nivel": nivel, # Nível é sempre salvo
            "comissao": comissao # Comissão é sempre salva
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
        
        # Hash da Senha (Apenas se foi fornecida e o campo existe)
        if "senha" in campos_config and senha:
            senha = format_title_case(request.form.get('senha'))
            hashed_password = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
            dados_colaborador['senha'] = hashed_password.decode('utf-8')
        
        # 5. Lógica de Inserção/Atualização
        if id_colaborador_edicao:
            id_colaborador_int = int(id_colaborador_edicao)
            
            if id_colaborador_int == session.get('id_colaborador') and nivel < 3 and session.get('nivel') == 3 and db.colaboradores.count_documents({'nivel': 3}) == 1:
                raise ValueError("Você é o único administrador. Não pode rebaixar seu próprio nível.")
                 
            if not senha and 'senha' in dados_colaborador:
                 del dados_colaborador['senha']
                 
            db.colaboradores.update_one({'id_colaborador': id_colaborador_int}, {'$set': dados_colaborador})
            success_msg = f"Colaborador {nick} atualizado com sucesso!"
            
        else:
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
        
        # 1. Salva os dados que o usuário digitou na sessão
        session['form_data'] = dict(request.form)
        
        # 2. Prepara os argumentos para o redirect
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        redirect_args = {
            'error': f"Erro de Validação: {e}",
            'view': view_redirect
        }
        
        # 3. CRÍTICO: Se estávamos editando, passa o ID do colaborador de volta
        if id_colaborador_edicao:
            redirect_args['id_colaborador'] = id_colaborador_edicao
            
        return redirect(url_for('cadastro_colaborador', **redirect_args))
        
    except Exception as e:
        # Erros gerais (DB, Geração de ID)
        print(f"ERRO CRÍTICO na gravação/atualização de colaborador: {e}")
        
        # 1. Salva os dados que o usuário digitou na sessão
        session['form_data'] = dict(request.form)
        
        # 2. Prepara os argumentos para o redirect
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        redirect_args = {
            'error': "Erro interno ao gravar/atualizar colaborador.",
            'view': view_redirect
        }
        
        # 3. CRÍTICO: Se estávamos editando, passa o ID do colaborador de volta
        if id_colaborador_edicao:
            redirect_args['id_colaborador'] = id_colaborador_edicao

        return redirect(url_for('cadastro_colaborador', **redirect_args))


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
                    # Se a data já estiver em DD/MM/YYYY
                    if re.match(r'^\d{2}/\d{2}/\d{4}$', value.strip()):
                        return value.strip()
                    return value
            return value
        
        # O MongoDB salva data_evento como string 'YYYY-MM-DD' ou 'DD/MM/YYYY'.
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


# app.py

# ... (todas as outras rotas e imports) ...

@app.route('/processar_venda', methods=['POST'])
@login_required
def processar_venda():
    """
    Processo Crítico de Venda - ATUALIZADO para incluir todos os períodos
    do cliente no comprovante e no link final.
    """
    db = g.db
    
    # --- 1. LEITURA E VALIDAÇÃO INICIAL ---
    id_evento_string = request.form.get('id_evento') 
    id_cliente_final_str = request.form.get('id_cliente_final') 
    quantidade_str = request.form.get('quantidade', '0')
    
    log_prefix = f"[VENDA REQ_COLAB:{session.get('nick', 'N/A')}_CLI:{id_cliente_final_str}_QTD:{quantidade_str}]"
    
    if not g.db_status:
        # ... (código de erro de DB Offline) ...
        error_redirect_kwargs = {
            'id_evento': id_evento_string,
            'id_cliente_busca': f"CLI{id_cliente_final_str}" if id_cliente_final_str else '',
            'error': "DB Offline. Transação Crítica Falhou."
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    try:
        id_cliente_final = int(id_cliente_final_str)
        quantidade = int(quantidade_str)
        if quantidade <= 0: raise ValueError("Quantidade deve ser positiva")
    except (TypeError, ValueError) as e:
        # ... (código de erro de dados inválidos) ...
        error_redirect_kwargs = {
            'id_evento': id_evento_string, 
            'error': f"Dados inválidos: {e}",
            'id_cliente_busca': f"CLI{id_cliente_final_str}" if id_cliente_final_str else ''
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    id_evento_mongo = try_object_id(id_evento_string)
    if not id_evento_mongo:
        return redirect(url_for('nova_venda', error="Dados inválidos: Evento não selecionado."))
    
    # --- 2. Busca Evento e Cliente ---
    selected_event = db.eventos.find_one({'_id': id_evento_mongo})
    cliente_doc = db.clientes.find_one({"id_cliente": id_cliente_final})
    
    if not selected_event or not cliente_doc:
        # ... (código de erro de evento/cliente não encontrado) ...
        error_redirect_kwargs = {
            'id_evento': id_evento_string,
            'error': "Evento ou Cliente não encontrado no sistema.",
            'id_cliente_busca': f"CLI{id_cliente_final_str}"
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))
        
    # Extração de Dados Críticos
    id_evento_int_para_controle = selected_event.get('id_evento') 
    limite_maximo_cartelas = int(selected_event.get('numero_maximo', 72000))
    if not isinstance(id_evento_int_para_controle, int):
        error_redirect_kwargs = { 'error': "Erro: ID sequencial do evento (int) não encontrado." }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
    unidade_de_venda = int(selected_event.get('unidade_de_venda', 1))

    # Cálculo da Venda Atual
    valor_total_atual = valor_unitario * quantidade
    quantidade_cartelas_atual = quantidade * unidade_de_venda
    colaborador_id = session.get('id_colaborador', 'N/A')
    nick_colaborador = session.get('nick', 'Colaborador') 
    nome_colecao_venda = f"vendas{str(id_evento_int_para_controle).strip()}"

    # --- 3. ETAPA CRÍTICA: LOCK E TRANSAÇÃO ---
    
    # Variáveis que serão preenchidas dentro do lock
    id_venda_formatado = None
    numero_inicial_atual = None
    numero_final_atual = None
    numero_inicial2_atual = 0 # Default 0
    numero_final2_atual = 0 # Default 0
    
    print(f"{log_prefix} LOG 2: Tentando adquirir 'venda_lock' (timeout=8s)...")
    
    if venda_lock.acquire(timeout=8): 
        print(f"{log_prefix} LOG 3: 'venda_lock' ADQUIRIDO.")
        try:
            # 3a. Geração Atômica do ID da Venda
            print(f"{log_prefix} LOG 3A: Gerando ID da Venda...")
            novo_id_venda_int = get_next_global_sequence(db, 'id_vendas_global')
            if novo_id_venda_int is None:
                raise Exception("Falha ao gerar o ID sequencial da venda.")
            id_venda_formatado = f"V{novo_id_venda_int:05d}" # Salva na variável externa

            # 3b. Geração Atômica dos Números de Bilhetes/Cartelas
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
            
            # 3c. Lógica de Rollover
            if numero_final_atual > limite_maximo_cartelas:
                numero_inicial2_atual = 1
                numero_final2_atual = numero_final_atual - limite_maximo_cartelas
                numero_final_atual = limite_maximo_cartelas
            
            print(f"{log_prefix} ... IDs Bilhete gerados: {numero_inicial_atual}-{numero_final_atual}...")

            # 4. Montagem do Registro de Venda (Apenas a venda ATUAL)
            registro_venda = {
                "id_venda": id_venda_formatado,
                "id_evento_ObjectId": id_evento_mongo, 
                "id_evento": id_evento_int_para_controle, 
                "descricao_evento": selected_event.get('descricao'),
                "id_cliente": id_cliente_final, 
                "nome_cliente": cliente_doc.get('nome_cliente'),
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
            
            # 5. Atualiza data da última compra do cliente
            print(f"{log_prefix} LOG 3C: Atualizando cliente {id_cliente_final}...")
            db.clientes.update_one(
                {"id_cliente": id_cliente_final}, 
                {"$set": {"data_ultimo_compra": datetime.utcnow()}}
            )

            # 6. Inserção no Banco de Dados
            print(f"{log_prefix} LOG 3D: Inserindo venda na coleção '{nome_colecao_venda}'...")
            db[nome_colecao_venda].insert_one(registro_venda)
            print(f"{log_prefix} ... Venda inserida.")
            
        except Exception as e:
            # --- Se algo falhar DENTRO do lock, libera e retorna o erro ---
            venda_lock.release()
            print(f"{log_prefix} LOG 5 (ERRO INTERNO): Erro crítico durante a transação: {e}")
            error_redirect_kwargs = {
                'id_evento': id_evento_string,
                'error': f"Erro interno no DB: Falha ao gravar a transação.",
                'id_cliente_busca': f"CLI{id_cliente_final_str}",
                'quantidade': quantidade
            }
            return redirect(url_for('nova_venda', **error_redirect_kwargs))
            
        finally:
            # Garante que o lock seja liberado
            if venda_lock.locked():
                 print(f"{log_prefix} LOG FIM (LOCK): Liberando 'venda_lock'.")
                 venda_lock.release()
            
    else:
        # --- Se o lock NÃO FOI ADQUIRIDO (Timeout) ---
        print(f"{log_prefix} LOG 6 (TIMEOUT): 'venda_lock' não adquirido após 8s. (Sistema ocupado)")
        error_redirect_kwargs = {
            'id_evento': id_evento_string,
            'error': "Sistema muito ocupado. Por favor, tente novamente em alguns segundos.",
            'id_cliente_busca': f"CLI{id_cliente_final_str}",
            'quantidade': quantidade
        }
        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    # --- FIM DO BLOCO DE LOCK ---

    # --- 7. PÓS-VENDA (FORA DO LOCK): Montagem do Comprovante Completo ---
    # Se chegamos aqui, a venda foi gravada e o lock foi liberado.
    
    print(f"{log_prefix} LOG 4: Venda gravada. Montando comprovante completo...")
    
    try:
        # 7a. Busca TODOS os períodos deste cliente para este evento
        vendas_cliente_cursor = db[nome_colecao_venda].find(
            {'id_cliente': id_cliente_final}
        ).sort('data_venda', pymongo.ASCENDING) # Ordena do mais antigo para o mais novo
        
        lista_periodos_antigos_html = []
        periodo_atual_html = ""
        link_periodos_completos = "" # Para o link
        
        total_unidades_cliente = 0
        total_cartelas_cliente = 0
        total_valor_cliente = 0.0

        for venda in vendas_cliente_cursor:
            # 7b. Soma os totais do cliente
            total_unidades_cliente += venda['quantidade_unidades']
            total_cartelas_cliente += venda['quantidade_cartelas']
            total_valor_cliente += safe_float(venda['valor_total'])
            
            # 7c. Constrói o link (para TODOS os períodos)
            link_periodos_completos += f"&periodo={venda['numero_inicial']},{venda['numero_final']}"
            if venda.get('numero_inicial2', 0) > 0:
                link_periodos_completos += f"&periodo={venda['numero_inicial2']},{venda['numero_final2']}"
            
            # 7d. Constrói o HTML do recibo
            periodo_str = f" > {venda['numero_inicial']} a {venda['numero_final']}<br>"
            if venda.get('numero_inicial2', 0) > 0:
                periodo_str += f" > {venda['numero_inicial2']} a {venda['numero_final2']}<br>"

            # Compara se esta venda é a que acabamos de fazer
            if venda['id_venda'] == id_venda_formatado:
                # É a venda atual: destaca
                periodo_atual_html = (
                    f"<strong> > PERÍODO ATUAL (Qtd: {quantidade}) <strong><br>"
                    f"<span style='font-size: 1.4rem; color: #0047AB;'><strong>{periodo_str}</strong></span>"
                )
            else:
                # É uma venda antiga: fonte menor
                lista_periodos_antigos_html.append(
                    f"<span style='font-size: 0.9rem; color: #555;'>{periodo_str}</span>"
                )

        periodos_anteriores_html = "".join(lista_periodos_antigos_html)

        # 7e. Monta o Link Final
        #if link_periodos_completos:
            # Troca o primeiro '&' por '?'
            #link_periodos_completos = link_periodos_completos.replace('&', '?', 1) 
        
        http_apk = g.parametros_globais.get('http_apk', '')
        link_final_limpo = f"{http_apk}?idrodada={id_evento_int_para_controle}{link_periodos_completos}"

        # 7f. Monta o success_msg final
        nome_sala = g.parametros_globais.get('nome_sala', '')
        data_evento_str = selected_event.get('data_evento', 'N/A')
        hora_evento_str = selected_event.get('hora_evento', 'N/A')
        data_evento_formatada = data_evento_str.replace('/', '-') if data_evento_str else 'N/A'
        
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
        
        # 8. Redirecionamento de Sucesso
        session['success_message'] = success_msg 
        redirect_kwargs = {
            'id_evento': id_evento_string,
            'quantidade': 1 
        }
        return redirect(url_for('nova_venda', **redirect_kwargs))

    except Exception as e:
        # Se algo falhar FORA do lock (na montagem do recibo)
        print(f"{log_prefix} LOG 7 (ERRO PÓS-VENDA): Erro ao montar comprovante: {e}")
        # A venda foi salva, mas o comprovante falhou. Envia um sucesso genérico.
        session['success_message'] = (
            f"<strong>VENDA {id_venda_formatado} GRAVADA!</strong><br>"
            f"Ocorreu um erro ao gerar o comprovante completo, mas a venda foi registrada."
        )
        return redirect(url_for('nova_venda', id_evento=id_evento_string))


# --- ROTAS DE CADASTRO DE CLIENTE ---
@app.route('/cadastro_cliente', methods=['GET'])
@login_required
def cadastro_cliente():
    db = g.db
    db_status = g.db_status

    # --- NOVO: Captura o nível da sessão ---
    nivel_usuario = session.get('nivel', 1)
    nome_logado = session.get('nick', 'Colaborador') 
    id_logado = session.get('id_colaborador', 'N/A')
    
    # --- INÍCIO DA CORREÇÃO (Lógica de Erro) ---
    # 1. Tenta pegar dados de um erro anterior. 
    form_data_erro = session.pop('form_data', None)
    # --- FIM DA CORREÇÃO ---
    
    # 1. Variáveis de Estado (Inicialização Garantida)
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    next_url = request.args.get('next', 'menu_operacoes')
    id_evento_retorno = request.args.get('id_evento') # Captura, mas pode ser None
    id_cliente_edicao = request.args.get('id_cliente', None)
    
    clientes_lista = []
    total_clientes = 0
    cliente_edicao = None # <-- Importante começar como None
    
    error = request.args.get('error')
    success = request.args.get('success')

    # --- INÍCIO DA CORREÇÃO (Lógica de Preenchimento) ---
    
    if form_data_erro:
        # 2. Se 'form_data_erro' existe, um erro acabou de ocorrer.
        #    Usamos esses dados para preencher o formulário.
        #    O HTML (Jinja) já usa a variável 'cliente_edicao' para preencher os campos.
        cliente_edicao = form_data_erro
        
        # Garante que a view ('novo' or 'alterar') esteja correta
        if 'id_cliente_edicao' in form_data_erro and form_data_erro['id_cliente_edicao']:
             active_view = 'alterar'
             # Passa o ID de volta para o 'context'
             id_cliente_edicao = form_data_erro['id_cliente_edicao']
        else:
             active_view = 'novo'
            
    elif active_view == 'alterar' and id_cliente_edicao and db_status:
        # 3. Se NÃO há 'form_data_erro', é um carregamento normal.
        #    Buscamos no DB como na sua lógica original.
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
            
    # --- FIM DA CORREÇÃO ---
            
    if db_status:
        try:
            total_clientes = db.clientes.count_documents({})
            
            # A lógica de 'alterar' já foi movida para cima
            
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
        'cliente_edicao': cliente_edicao, # <-- AQUI ESTÁ A MÁGICA
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
        # --- 1. Carregar a configuração de campos ---
        default_config = {} # Um padrão vazio caso 'g' falhe
        if hasattr(g, 'parametros_globais'):
             default_config = g.parametros_globais.get('tipo_cadastro_cliente', {})
        
        campos_config = g.parametros_globais.get('tipo_cadastro_cliente', default_config)


        # --- 2. Coleta e Limpeza de Dados ---
        nome_cliente = format_title_case(request.form.get('nome_cliente'))
        nick = format_title_case(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip()
        confirma_chave_pix = request.form.get('confirma_chave_pix', '').strip()
        senha = format_title_case(request.form.get('senha'))
        confirma_senha = format_title_case(request.form.get('confirma_senha'))

        # --- 3. VALIDAÇÃO DINÂMICA (A CORREÇÃO) ---
        if campos_config.get("nome_cliente") and not nome_cliente:
            raise ValueError("O campo Nome Completo é obrigatório.")
        
        if campos_config.get("nick") and not nick:
            raise ValueError("O campo Nick/Apelido é obrigatório.")
        
        if campos_config.get("cidade") and not cidade:
            raise ValueError("O campo Cidade é obrigatório.")
        
        if campos_config.get("chave_pix") and not chave_pix:
            raise ValueError("O campo Chave PIX é obrigatório.")
            
        # Validação de CPF (agora dinâmica)
        cpf_limpo = clean_numeric_string(cpf_raw)
        if campos_config.get("cpf") == True: # Se CPF é OBRIGATÓRIO
            if not cpf_raw or not validate_cpf(cpf_limpo):
                raise ValueError("CPF é obrigatório e deve ser válido.")
        elif "cpf" in campos_config and cpf_raw and not validate_cpf(cpf_limpo):
            # Se CPF é OPCIONAL (false) mas foi digitado E é inválido
            raise ValueError("O CPF inserido não é válido.")

        # Validações de PIX e Senha (só se os campos existirem na config)
        if "chave_pix" in campos_config and chave_pix != confirma_chave_pix:
            raise ValueError("As chaves PIX não conferem.")
        
        if "senha" in campos_config:
            # Se for NOVO cadastro E a senha for obrigatória E (senha vazia OU não confere)
            if not id_cliente_edicao and campos_config.get("senha") and (not senha or senha != confirma_senha):
                raise ValueError("Senha e Confirmação de Senha não conferem ou estão vazias.")
            # Se for ALTERAÇÃO E a senha foi digitada E não confere
            elif id_cliente_edicao and senha and (senha != confirma_senha):
                raise ValueError("Senha e Confirmação de Senha não conferem.")
        
        # --- 4. LÓGICA DA SENHA (Padrão = Nick) ---
        senha_final_raw = None
        if "senha" in campos_config:
            if senha:
                senha_final_raw = senha
            elif not id_cliente_edicao: 
                # Se for NOVO cadastro e a senha estiver vazia, usa o Nick
                # (A validação anterior já pegou se era 'required' e veio vazia)
                if not campos_config.get("senha"): # Se a senha for opcional e vazia
                    senha_final_raw = nick 
                elif senha == "": # Se for required, já deu erro. Se for opcional e vazia...
                     senha_final_raw = nick # fallback
            # else: (Alteração com senha vazia) senha_final_raw continua None (correto)
            
        # --- 5. Montagem Dinâmica do Documento ---
        dados_cliente = {
            "id_colaborador": session.get('id_colaborador', 'N/A'),
        }
        
        # Adiciona campos ao documento SOMENTE se eles estiverem na configuração
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
        
        # --- 6. Adiciona a senha apenas se ela foi definida ---
        if senha_final_raw: # (Já passou pela lógica do "senha" in campos_config)
            senha_formatada = senha_final_raw.capitalize()
            hashed_password = bcrypt.hashpw(senha_formatada.encode('utf-8'), bcrypt.gensalt())
            dados_cliente['senha'] = hashed_password.decode('utf-8')

        
        # --- 7. Lógica de Inserção/Atualização ---
        novo_id_cliente_int = None
        
        if id_cliente_edicao:
            # --- Modo ATUALIZAÇÃO (UPDATE) ---
            id_cliente_int = int(id_cliente_edicao)
            
            # (O 'dados_cliente' já contém apenas os campos permitidos)
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
        
        # --- 8. Prepara os argumentos de redirecionamento ---
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
        # Erros de validação
        session['form_data'] = dict(request.form) # Salva dados na sessão
        view_redirect = 'alterar' if id_cliente_edicao else 'novo'
        
        redirect_args = {
            'error': f"Erro de Validação: {e}",
            'view': view_redirect,
            'next': next_url,
            'id_evento': id_evento_retorno
        }
        if id_cliente_edicao:
            redirect_args['id_cliente'] = id_cliente_edicao
            
        return redirect(url_for('cadastro_cliente', **redirect_args))
        
    except Exception as e:
        # Erros gerais (DB, Geração de ID)
        print(f"ERRO CRÍTICO na gravação/atualização de cliente: {e}")
        session['form_data'] = dict(request.form) # Salva dados na sessão
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
    
    # --- INÍCIO DA CORREÇÃO (Lógica de Erro) ---
    # 1. Tenta pegar dados de um erro anterior. 
    form_data_erro = session.pop('form_data', None)
    # --- FIM DA CORREÇÃO ---
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    id_evento_edicao = request.args.get('id_evento', None)
    
    evento_edicao = None 
    eventos_lista = []
    total_eventos = 0
    
    error = request.args.get('error')
    success = request.args.get('success')

    # --- INÍCIO DA CORREÇÃO (Lógica de Preenchimento) ---
    if form_data_erro:
        # 2. Se 'form_data_erro' existe, um erro acabou de ocorrer.
        #    Usamos esses dados para preencher o formulário.
        #    O HTML (Jinja) já usa a variável 'evento_edicao'.
        evento_edicao = form_data_erro
        
        # Garante que a view ('novo' or 'alterar') esteja correta
        if 'id_evento_edicao' in form_data_erro and form_data_erro['id_evento_edicao']:
             active_view = 'alterar'
             # Passa o ID de volta para o 'context'
             id_evento_edicao = form_data_erro['id_evento_edicao']
        else:
             active_view = 'novo'
             
    elif active_view == 'alterar' and id_evento_edicao and db_status:
        # 3. Se NÃO há 'form_data_erro', é um carregamento normal.
        #    Buscamos no DB como na sua lógica original.
        try:
            id_evento_int = int(id_evento_edicao)
            evento_edicao = db.eventos.find_one({'id_evento': id_evento_int})
            
            if evento_edicao:
                if '_id' in evento_edicao: evento_edicao['_id'] = str(evento_edicao['_id'])

                # --- CORREÇÃO DA DATA (para formulário) ---
                data_evento_db = evento_edicao.get('data_evento') # Ex: "10/11/2025"
                if data_evento_db and isinstance(data_evento_db, str):
                    try:
                        # Converte de DD/MM/YYYY para um objeto datetime
                        dt_obj = datetime.strptime(data_evento_db, '%d/%m/%Y')
                        # Formata de volta para YYYY-MM-DD para o input HTML
                        evento_edicao['data_evento'] = dt_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        pass # Deixa como está se já for YYYY-MM-DD
                # --- FIM DA CORREÇÃO DA DATA ---

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
            
    # --- FIM DA LÓGICA DE PREENCHIMENTO ---

    if db_status:
        try:
            total_eventos = db.eventos.count_documents({})
            
            # A lógica de 'alterar' já foi movida para cima
            
            # Lógica de Consulta/Listagem
            if active_view == 'listar':
                # Ordena pela data do evento mais próxima
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

    # Conversão de Decimal128 para float (para a LISTA de eventos)
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
        'evento_edicao': evento_edicao, # <-- Esta variável agora contém os dados do erro ou do DB
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

    id_evento_edicao = request.form.get('id_evento_edicao') 
    
    # --- FUNÇÃO AUXILIAR DE LIMPEZA DE FLOAT ---
    def clean_float_input(form_key, default_value='0'):
        value_raw = request.form.get(form_key, default_value)
        if not value_raw or value_raw.strip() == '':
            value_raw = str(default_value)
        return float(value_raw.replace(',', '.'))
    # -------------------------------------------

    try:
        # 1. Coleta e Limpeza de Dados
        data_evento_str = request.form.get('data_evento') # YYYY-MM-DD
        hora_evento = request.form.get('hora_evento')
        descricao = format_title_case(request.form.get('descricao'))
        unidade_de_venda = int(request.form.get('unidade_de_venda', 1))
        
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
        
        
        # 2. Validação Mínima e de Formato
        if not all([data_evento_str, hora_evento, descricao, unidade_de_venda, valor_de_venda]):
             raise ValueError("Preencha todos os campos obrigatórios (*).")
        
        if not (1 <= unidade_de_venda <= 6):
             raise ValueError("Unidade de venda deve ser entre 1 e 6.")

        if not (1 <= quantidade_de_linhas <= 3):
             raise ValueError("Quantidade de linhas deve ser entre 1 e 3.")

        try:
             data_obj = datetime.strptime(data_evento_str, '%Y-%m-%d')
             data_evento_str_gravar = data_obj.strftime('%d/%m/%Y')
        except ValueError:
             raise ValueError("Formato de data inválido. Use AAAA-MM-DD.")
        
        data_hora_evento_str = f"{data_evento_str} {hora_evento}" # Ex: '2025-11-06 20:00'
        data_hora_evento_dt = datetime.strptime(data_hora_evento_str, '%Y-%m-%d %H:%M')
        
        # 3. Cálculo do Prêmio Total
        premio_total = premio_quadra + (premio_linha * quantidade_de_linhas) + premio_bingo + premio_segundobingo + premio_acumulado
        
        # 4. Montagem do Documento
        dados_evento = {
            "data_evento": data_evento_str_gravar, # DD/MM/YYYY
            "hora_evento": hora_evento, # HH:MM
            "data_hora_evento": data_hora_evento_dt, # Datetime Object
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
            "premio_total": Decimal128(str(premio_total)), 
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
                "data_ativado": None,
                "data_cadastro": datetime.utcnow()
            })
            
            db.eventos.insert_one(dados_evento)
            success_msg = f"Evento '{dados_evento['descricao']}' salvo com sucesso! ID: {novo_id_evento_int}."
        
        # 6. Redirecionamento de Sucesso
        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))


    except ValueError as e:
        # --- INÍCIO DA CORREÇÃO ---
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_evento_edicao else 'novo'
        redirect_args = {
            'error': f"Erro de Validação: {e}",
            'view': view_redirect
        }
        if id_evento_edicao:
            redirect_args['id_evento'] = id_evento_edicao
        return redirect(url_for('cadastro_evento', **redirect_args))
        # --- FIM DA CORREÇÃO ---
        
    except Exception as e:
        # --- INÍCIO DA CORREÇÃO ---
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
        # --- FIM DA CORREÇÃO ---


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

# --- Rota de Consulta de Vendas (com cálculo de comissão) ---
@app.route('/consulta_vendas', methods=['GET'])
@login_required
def consulta_vendas():
    """
    Página principal de consulta de vendas.
    (Com cálculo de comissão)
    """
    db = g.db
    if not g.db_status:
        return render_template('consulta_vendas.html', error="DB Offline.", g=g)

    # Captura mensagens da sessão
    error_from_session = session.pop('error_message', None)
    success = session.pop('success_message', None)

    # 1. Obter Nível de Acesso
    nivel_usuario = session.get('nivel', 1)
    id_colaborador_logado = session.get('id_colaborador', 'N/A')
    
    # 2. Obter Parâmetros da URL
    id_evento_param = request.args.get('id_evento')
    id_colaborador_param = request.args.get('id_colaborador')

    # 3. Variáveis de Contexto
    eventos_ativos = []
    colaboradores_lista = []
    selected_event = None
    resultados_agregados = []
    resumo_geral = None 
    error = error_from_session
    selected_colab_id_str = None
    
    # --- NOVO: Pega comissão padrão e cria mapa ---
    default_comissao = g.parametros_globais.get('comissao_padrao', 0)
    comissao_map = {} # Mapa para guardar {id_colab: taxa}

    try:
        # --- Helper Interno para limpar eventos ---
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

        # 4. Lógica de Carregamento
        if not id_evento_param:
            # Etapa A: Seleção de Evento
            eventos_ativos_cursor = db.eventos.find({'status': 'ativo'}).sort('data_evento', pymongo.ASCENDING)
            for evento in eventos_ativos_cursor:
                eventos_ativos.append(clean_event_numerics(evento))
        
        else:
            # Etapa B: Evento Selecionado
            evento_oid = try_object_id(id_evento_param)
            selected_event_raw = db.eventos.find_one({'_id': evento_oid})
            selected_event = clean_event_numerics(selected_event_raw)
            
            if not selected_event:
                error = "Evento não encontrado."
                return render_template('consulta_vendas.html', error=error, g=g)

            # 4.2. (Se Nível 3) Busca lista de colaboradores
            if nivel_usuario == 3:
                colaboradores_lista.append({'nick': 'TODOS', 'id_colaborador': 'ALL'})
                # --- Otimização: Busca comissões de TODOS ---
                colabs_cursor = db.colaboradores.find({}, {'nick': 1, 'id_colaborador': 1, 'comissao': 1}).sort('nick', pymongo.ASCENDING)
                for colab in colabs_cursor:
                    colaboradores_lista.append(colab)
                    # Preenche o mapa de comissões
                    taxa = colab.get('comissao')
                    if isinstance(taxa, (int, float)):
                        comissao_map[colab['id_colaborador']] = taxa
            
            # 4.3. Define o filtro do colaborador
            filtro_colaborador_query = {} 
            
            if nivel_usuario < 3:
                filtro_colaborador_query = {'id_colaborador': id_colaborador_logado}
                selected_colab_id_str = str(id_colaborador_logado)
                # Busca a comissão do usuário logado
                colab_doc = db.colaboradores.find_one({'id_colaborador': id_colaborador_logado}, {'comissao': 1})
                if colab_doc:
                    taxa = colab_doc.get('comissao')
                    if isinstance(taxa, (int, float)):
                         comissao_map[id_colaborador_logado] = taxa
            
            elif nivel_usuario == 3:
                if id_colaborador_param and id_colaborador_param != 'ALL':
                    filtro_colaborador_query = {'id_colaborador': int(id_colaborador_param)}
                    selected_colab_id_str = id_colaborador_param
                    # (comissão já foi pega no loop 'TODOS' acima)
                elif id_colaborador_param == 'ALL':
                    selected_colab_id_str = 'ALL'

            # 5. Execução da Consulta (Aggregation Pipeline)
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
            
            # 6. Formata os resultados e CALCULA COMISSÃO
            for res in resultados_cursor:
                res['total_valor_float'] = safe_float(res['total_valor'])
                
                # --- Cálculo da Comissão ---
                colab_id = res['_id'] # ID do colaborador
                taxa_aplicada = comissao_map.get(colab_id, default_comissao) # Pega do mapa ou usa o padrão
                
                res['taxa_comissao_aplicada'] = taxa_aplicada
                res['valor_comissao_float'] = (res['total_valor_float'] * taxa_aplicada) / 100.0
                # --- Fim do Cálculo ---
                
                resultados_agregados.append(res)
                
            # --- CÁLCULO DO RESUMO GERAL (com comissão) ---
            if selected_colab_id_str == 'ALL' and resultados_agregados:
                total_kits_geral = sum(r['total_kits'] for r in resultados_agregados)
                total_cartelas_geral = sum(r['total_cartelas'] for r in resultados_agregados)
                total_valor_geral = sum(r['total_valor_float'] for r in resultados_agregados)
                total_vendas_geral = sum(r['total_vendas'] for r in resultados_agregados)
                total_comissao_geral = sum(r['valor_comissao_float'] for r in resultados_agregados) # <-- NOVO
                data_inicial_geral = min(r['data_inicial'] for r in resultados_agregados)
                data_final_geral = max(r['data_final'] for r in resultados_agregados)
                
                resumo_geral = {
                    'nick_colaborador': '⭐ Resumo Geral (TODOS)',
                    '_id': 'ALL',
                    'total_kits': total_kits_geral,
                    'total_cartelas': total_cartelas_geral,
                    'total_valor_float': total_valor_geral,
                    'total_vendas': total_vendas_geral,
                    'valor_comissao_float': total_comissao_geral, # <-- NOVO
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
    db = g.db
    if not g.db_status:
        return render_template('consulta_vendas_detalhes.html', error="DB Offline.", g=g)

    # 1. Obter Nível de Acesso e Parâmetros
    nivel_usuario = session.get('nivel', 1)
    id_colaborador_logado = session.get('id_colaborador', 'N/A')
    
    id_evento_param = request.args.get('id_evento')
    id_colaborador_param = request.args.get('id_colaborador') # Vem como string

    vendas_detalhadas = []
    error = None
    info_evento_nome = None
    info_evento_id = None # <-- VARIÁVEL ADICIONADA
    info_colaborador = "N/A"
    
    # --- NOVO: Pega comissão padrão e cria mapa ---
    default_comissao = g.parametros_globais.get('comissao_padrao', 0)
    comissao_map = {} # Mapa para guardar {id_colab: taxa}

    try:
        # 2. Validação e Busca de Infos
        evento_oid = try_object_id(id_evento_param)
        selected_event = db.eventos.find_one({'_id': evento_oid})
        
        if not selected_event:
            error = "Evento não encontrado."
            return render_template('consulta_vendas_detalhes.html', error=error, g=g, vendas=[])

        id_evento_int = selected_event.get('id_evento')
        info_evento_nome = selected_event.get('descricao')
        info_evento_id = id_evento_int # <-- VALOR ATRIBUÍDO
        nome_colecao_venda = f"vendas{id_evento_int}"
        
        # 3. Construção do Filtro (Query)
        query_filter = {'id_evento': id_evento_int}
        colab_ids_para_buscar_comissao = []

        # Segurança: Nível < 3 só pode ver seus próprios detalhes
        if nivel_usuario < 3:
            query_filter['id_colaborador'] = id_colaborador_logado
            info_colaborador = session.get('nick', 'N/A')
            if isinstance(id_colaborador_logado, int):
                 colab_ids_para_buscar_comissao.append(id_colaborador_logado)
        
        elif nivel_usuario == 3:
            # Nível 3 pode ver "TODOS" ou um ID específico
            if id_colaborador_param and id_colaborador_param != 'ALL':
                id_colab_int = int(id_colaborador_param)
                query_filter['id_colaborador'] = id_colab_int
                colab_ids_para_buscar_comissao.append(id_colab_int)
                colab_doc = db.colaboradores.find_one({'id_colaborador': id_colab_int}, {'nick': 1})
                info_colaborador = colab_doc.get('nick') if colab_doc else f"ID {id_colab_int}"
                
            elif id_colaborador_param == 'ALL':
                # Filtro "TODOS", não adiciona filtro de colaborador
                info_colaborador = "TODOS"
                # --- Otimização: Busca comissões de TODOS ---
                todos_colabs = db.colaboradores.find({}, {'id_colaborador': 1, 'comissao': 1})
                for c in todos_colabs:
                    taxa = c.get('comissao')
                    if isinstance(taxa, (int, float)):
                        comissao_map[c['id_colaborador']] = taxa
            
        # 4. Otimização: Busca comissões (se não for "TODOS")
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
                 
        # 5. Execução da Consulta (Find)
        vendas_cursor = db[nome_colecao_venda].find(query_filter).sort('data_venda', pymongo.DESCENDING)
        
        for venda in vendas_cursor:
            # --- Cálculo da Comissão (DETALHADO) ---
            venda['valor_total_float'] = safe_float(venda.get('valor_total'))
            colab_id = venda.get('id_colaborador')
            taxa_comissao = comissao_map.get(colab_id, default_comissao) # Pega do mapa ou usa o padrão
            venda['valor_comissao_float'] = (venda['valor_total_float'] * taxa_comissao) / 100.0
            # --- Fim do Cálculo ---
            vendas_detalhadas.append(venda)
            
        if not vendas_detalhadas:
            error = "Nenhuma venda detalhada encontrada."

    except Exception as e:
        print(f"Erro em consulta_vendas_detalhes: {e}")
        error = f"Erro interno: {e}"

    return render_template('consulta_vendas_detalhes.html',
                           g=g,
                           error=error,
                           vendas=vendas_detalhadas,
                           info_evento=info_evento_nome, # Nome do evento
                           info_evento_id=info_evento_id, # <-- ID DO EVENTO ADICIONADO
                           info_colaborador=info_colaborador)


# --- ROTA DE REIMPRESSÃO (TXT) ---
@app.route('/reimprimir_comprovante_txt', methods=['POST'])
@login_required
def reimprimir_comprovante_txt():
    """
    Gera o texto (TXT) de um comprovante para "Venda Única" ou "Vendas Cliente"
    e retorna como JSON para ser copiado pela área de transferência.
    """
    db = g.db
    if not g.db_status:
        return jsonify({'status': 'error', 'message': 'DB Offline'})

    try:
        # 1. Coletar dados da requisição AJAX
        data = request.json
        tipo_reimpressao = data.get('tipo_reimpressao') # 'unica' ou 'cliente'
        id_venda_str = data.get('id_venda')           # Ex: "V00123"
        id_evento_int = int(data.get('id_evento'))
        id_cliente_int = int(data.get('id_cliente'))
        
        # 2. Buscar dados globais (do evento e parâmetros)
        evento = db.eventos.find_one({'id_evento': id_evento_int})
        if not evento:
            return jsonify({'status': 'error', 'message': 'Evento não encontrado'})

        http_apk = g.parametros_globais.get('http_apk', '')
        nome_sala = g.parametros_globais.get('nome_sala', '')
        data_evento_str = evento.get('data_evento', 'N/A')
        hora_evento_str = evento.get('hora_evento', 'N/A')
        data_evento_formatada = data_evento_str.replace('/', '-') if data_evento_str else 'N/A'
        
        nome_colecao_venda = f"vendas{id_evento_int}"
        
        # 3. Preparar variáveis
        receipt_html = "" # O comprovante formatado
        link_periodos = "" # O string de períodos para o link
        
        # --- LÓGICA PARA VENDA ÚNICA ---
        if tipo_reimpressao == 'unica':
            venda = db[nome_colecao_venda].find_one({'id_venda': id_venda_str})
            if not venda:
                return jsonify({'status': 'error', 'message': 'Venda não encontrada'})
            
            # Formata os períodos (Usamos tags <br> e <strong> que serão limpas depois)
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

        # --- LÓGICA PARA VENDAS DO CLIENTE ---
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
        
        # 4. Montar o Link Final
        #if link_periodos:
            # Substitui o PRIMEIRO '&' por '?'
            #link_periodos = link_periodos.replace('&', '?', 1) 
        
        # O 'http_apk' não deve ter '<strong>' no link final
        link_final_limpo = f"{http_apk}?idrodada={id_evento_int}{link_periodos}"
        receipt_html += f"<br><strong> {link_final_limpo} </strong>"

        # --- 6. VERSÃO TXT (A ÚNICA QUE SERÁ ENVIADA) ---
        def clean_html_to_txt(html_str):
            # Substitui <br> por quebra de linha
            txt = re.sub(r'<br\s*/?>', '\n', html_str, flags=re.IGNORECASE)
            # Remove todas as outras tags HTML
            txt = re.sub(r'<[^>]+>', '', txt)
            # Decodifica entidades HTML (como &gt;)
            txt = html.unescape(txt)
            # Remove espaços extras no início/fim de cada linha
            txt_limpo = '\n'.join([linha.strip() for linha in txt.split('\n')])
            return txt_limpo.strip()

        receipt_text = clean_html_to_txt(receipt_html)

        return jsonify({
            'status': 'success',
            'receipt_text': receipt_text # Envia a versão TXT limpa
        })

    except Exception as e:
        print(f"Erro ao reimprimir comprovante: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Erro interno: {e}'})

# --- FIM DA NOVA ROTA ---


# --- ROTA GERAR LISTA (DOWNLOAD TXT) ---
@app.route('/gerar_lista_vendas')
@login_required
def gerar_lista_vendas():
    """
    Gera um arquivo TXT em memória (com cabeçalho e dados de cliente)
    e o envia para download.
    """
    
    # 1. Segurança (Só Nível 3 pode gerar)
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    db = g.db
    id_evento_param = request.args.get('id_evento')
    
    # URL de Redirecionamento Padrão (em caso de falha)
    redirect_url = url_for('consulta_vendas', 
                           id_evento=id_evento_param, 
                           id_colaborador='ALL')
    
    if not id_evento_param:
        session['error_message'] = "Erro: ID do Evento não fornecido."
        return redirect(url_for('consulta_vendas'))

    try:
        # 2. Validar Evento e Buscar Dados do Cabeçalho
        evento_oid = try_object_id(id_evento_param)
        
        # Busca todos os campos necessários para o cabeçalho
        selected_event = db.eventos.find_one(
            {'_id': evento_oid},
            { # Projeção dos campos do evento
                'id_evento': 1, 'unidade_de_venda': 1, 'numero_maximo': 1,
                'valor_de_venda': 1, 'descricao': 1, 'premio_quadra': 1,
                'quantidade_de_linhas': 1, 'premio_linha': 1, 'premio_bingo': 1,
                'premio_segundobingo': 1, 'premio_acumulado': 1, 'bola_tope_acumulado': 1
            }
        )
        
        if not selected_event:
            session['error_message'] = "Erro: Evento não encontrado."
            return redirect(redirect_url)
            
        id_evento_int = selected_event.get('id_evento')
        nome_colecao_venda = f"vendas{id_evento_int}"
        
        # 3. Definir Nome do Arquivo (Ex: periodo.101)
        file_name = f"periodo.{id_evento_int}"

        # --- 4. Geração do Arquivo em Memória ---
        io_buffer = io.StringIO()
        
        # --- NOVO: Escreve a Linha 1 (Cabeçalho do Evento) ---
        header_line = (
            f"{selected_event.get('unidade_de_venda', 0)}!"
            f"{selected_event.get('numero_maximo', 0)}!"
            f"{safe_float(selected_event.get('valor_de_venda', 0))}!"
            f"{selected_event.get('descricao', 'N/A')}!"
            f"{safe_float(selected_event.get('premio_quadra', 0))}!"
            f"{selected_event.get('quantidade_de_linhas', 0)}!"
            f"{safe_float(selected_event.get('premio_linha', 0))}!"
            f"{safe_float(selected_event.get('premio_bingo', 0))}!"
            f"{safe_float(selected_event.get('premio_segundobingo', 0))}!"
            f"{safe_float(selected_event.get('premio_acumulado', 0))}!"
            f"{selected_event.get('bola_tope_acumulado', 0)}\n"
        )
        io_buffer.write(header_line)
        # --- FIM DO CABEÇALHO ---

        # 5. Query no DB (Pega todas as vendas do evento)
        vendas_cursor = db[nome_colecao_venda].find(
            {'id_evento': id_evento_int},
            { # Projeção: pega só os campos necessários
                'numero_inicial': 1, 'numero_final': 1, 'numero_inicial2': 1,
                'numero_final2': 1, 'id_cliente': 1, 'nome_cliente': 1,
                'id_colaborador': 1, 'nick_colaborador': 1
            }
        ).sort('numero_inicial', pymongo.ASCENDING)
        
        lista_vendas = list(vendas_cursor) # Converte o cursor para lista
        
        if not lista_vendas:
            session['error_message'] = "Não há nenhuma venda neste evento para gerar o arquivo."
            return redirect(redirect_url)

        # --- 6. Otimização (Abordagem "Map") ---
        cliente_ids_set = {v.get('id_cliente') for v in lista_vendas if v.get('id_cliente')}
        
        clientes_cursor = db.clientes.find(
            {'id_cliente': {'$in': list(cliente_ids_set)}},
            {'id_cliente': 1, 'telefone': 1, 'cidade': 1} # Pega só os campos extras
        )
        
        clientes_map = {c['id_cliente']: c for c in clientes_cursor}
        # --- Fim da Otimização ---

        # 7. Escreve as Linhas de Venda
        contagem_linhas = 0
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
                f"{cliente_info.get('cidade', 'N/A')}\n"
            )
            io_buffer.write(line_venda)
            contagem_linhas += 1
        
        output_text = io_buffer.getvalue()
        
        # 8. Enviar a Resposta de Download
        return Response(
            output_text,
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment;filename={file_name}"}
        )

    except Exception as e:
        print(f"ERRO GERAL ao gerar lista: {e}")
        session['error_message'] = f"Erro inesperado ao gerar arquivo: {e}"
        return redirect(redirect_url)


if __name__ == '__main__':
    # Para desenvolvimento local apenas
    if os.environ.get('FLASK_ENV') != 'production':
        app.run(debug=True, host='0.0.0.0', port=5001)
    else:
        print("⚠️  AVISO: Em produção, use Gunicorn. Não execute app.py diretamente!")