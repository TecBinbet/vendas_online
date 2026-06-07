# app.py (Versão Refatorada para Conexão Dinâmica por Sala)

import time
import threading
import traceback
import pymongo
from zoneinfo import ZoneInfo
import random

from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, g, jsonify, make_response, Response, send_file, render_template_string
#from flask_login import login_required, current_user
from fpdf import FPDF
# import pdfkit
from fpdf.enums import XPos, YPos
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo import ASCENDING, DESCENDING
from bson.objectid import ObjectId
from bson.decimal128 import Decimal128
from datetime import datetime, timedelta
from urllib.parse import quote_plus
import math # Adicione isso no topo do seu arquivo app.py (se já não tiver)
import os
import re # Para a busca de clientes e limpeza de nome
import bcrypt
import io # Para manipulação de arquivos em memória
import csv
from functools import wraps # Para o decorator login_required
import certifi  # Para certificados SSL
import html 
import unicodedata # Para limpeza de nome de arquivo

# Importa o blueprint do arquivo que criamos
from rotas_venda_lite import venda_lite_bp

MODO_DEBUG = True
#    log_sistema(f"🚨 ERRO IRRECUPERÁVEL AO CRIAR O CLIENTE DE CONTROLE: {e}", nivel="ERRO")
# path_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
# config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)


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
app.register_blueprint(venda_lite_bp)

# ---- UTILITARIOS
# --- DECORATOR DE AUTENTICAÇÃO BLINDADO ---
def login_required(f):
    """Decorator para exigir login em uma rota e preservar id_sala."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            
            # ORDEM DE BUSCA: 1º Sessão -> 2º URL -> 3º Cookie Persistente
            id_sala_atual = (
                session.get('id_sala') or 
                request.args.get('id_sala') or 
                request.cookies.get('id_sala_salvo')
            )
            
            redirect_args = {'error': "Acesso restrito. Faça o login."}
            if id_sala_atual:
                redirect_args['id_sala'] = id_sala_atual
                
            return redirect(url_for('login', **redirect_args)) # Use 'login' ou 'login_page' conforme sua rota principal
            
        return f(*args, **kwargs)
    return decorated_function


def inicializar_estrutura_db(db):
    """Agrega todas as configurações de índices e estrutura do banco."""
    print("      Iniciando verificação de estrutura do banco...")
    
    # Chamamos apenas a função co	nsolidada
    configurar_indices_da_sala(db)
    
    print("✅ Estrutura de banco de dados verificada e pronta.")


def configurar_indices_da_sala(db):
    """
    Função de auto-configuração consolidada (Atualizada Fase 4).
    """
    try:
        # --- ÍNDICES PARA REGIONAIS ---
        db.regionais.create_index([("id_regional", ASCENDING)], unique=True)
        db.regionais.create_index([("descricao", ASCENDING)])

        # --- 1. ÍNDICES DO LIVRO-RAZÃO DE CLIENTES (Atualizado Regional) ---
        # Índice Composto: Busca por Regional + Data para o Financeiro de Clientes
        db.transacoes_clientes.create_index([("id_regional", ASCENDING), ("data_hora", DESCENDING)])
        db.transacoes_clientes.create_index([("id_cliente", ASCENDING), ("data_hora", DESCENDING)])
        db.transacoes_clientes.create_index([("id_evento", ASCENDING)])
        
        # --- 2. ÍNDICES DE COMISSÕES E COLABORADORES (Atualizado Regional) ---
        # Permite que o Nível 3 veja apenas o extrato da sua regional
        db.transacoes_colaboradores.create_index([("id_regional", ASCENDING), ("id_c", ASCENDING), ("dt", DESCENDING)])
        
        # Auditoria regionalizada por evento
        db.transacoes_colaboradores.create_index([("id_regional", ASCENDING), ("id_e", ASCENDING)])

        # TRAVA DE SEGURANÇA (Idempotência mantida)
        db.transacoes_colaboradores.create_index(
            [("id_v", ASCENDING), ("id_c", ASCENDING), ("tp", ASCENDING)], 
            unique=True, 
            name="idx_trava_comissao_dupla"
        )

        # --- 3. AUTO-INDEXAÇÃO DAS COLEÇÕES DE VENDAS EXISTENTES ---
        # Isso substitui a necessidade de chamar a função 'criar_indices_regionais' separadamente
        for col_name in db.list_collection_names():
            if col_name.startswith("vendas") or col_name.startswith("pagamentos"):
                # Garante performance nos relatórios financeiros por regional
                db[col_name].create_index([("id_regional", 1), ("id_colaborador", 1)])
                db[col_name].create_index([("id_regional", 1), ("data_venda", -1)])

        # --- 4. ÍNDICES DE AUDITORIA ---
        db.logs_auditoria.create_index([("data", DESCENDING)], name="idx_logs_auditoria")
        
        print("[SISTEMA] ✅ Todos os índices Regionais e Financeiros verificados.")
        
    except Exception as e:
        print(f"[ALERTA] ❌ Erro ao configurar índices na inicialização: {e}")

def sortear_combos_livres(db, id_evento_pai, limite_maximo_cartelas, unidade_de_venda, combo_qtde, quantidade_comprada):
    """
    Motor de Sorteio Anti-Colisão para Combos com RANGE CUSTOMIZADO.
    Retorna uma lista de 'numeros_iniciais' totalmente livres para venda.
    """
    # 1. Puxa as travas do banco de dados (se existirem)
    parametros = db.parametros.find_one({}) or {}
    
    try:
        inicial_randon = int(parametros.get('inicial_randon', 1))
    except (ValueError, TypeError):
        inicial_randon = 1
        
    try:
        final_randon = int(parametros.get('final_randon', limite_maximo_cartelas))
    except (ValueError, TypeError):
        final_randon = limite_maximo_cartelas

    # Trava de segurança: Garante que o range não faça loucuras
    if final_randon > limite_maximo_cartelas or final_randon <= 0:
        final_randon = limite_maximo_cartelas
    if inicial_randon < 1:
        inicial_randon = 1

    # 2. Define o tamanho do bloco indivisível
    tamanho_bloco = unidade_de_venda * combo_qtde
    
    # 3. Matemática de Slots (Vagas): Garante que o bloco inteiro caiba no Range
    # Arredonda para cima para garantir que a cartela inicial do slot seja >= inicial_randon
    slot_inicial = (inicial_randon - 1 + tamanho_bloco - 1) // tamanho_bloco
    # Arredonda para baixo para garantir que a última cartela do slot seja <= final_randon
    slot_final = (final_randon - tamanho_bloco) // tamanho_bloco
    
    # 4. Busca APENAS os números iniciais vendidos no evento Pai para cruzar dados
    nome_colecao = f"vendas{id_evento_pai}"
    vendas_existentes = db[nome_colecao].find({'numero_inicial': {'$exists': True}}, {'numero_inicial': 1, '_id': 0})
    
    # 5. Mapeia quais Slots já estão ocupados no banco
    slots_ocupados = set()
    for venda in vendas_existentes:
        num_ini = venda.get('numero_inicial')
        if num_ini:
            indice_slot = (num_ini - 1) // tamanho_bloco
            slots_ocupados.add(indice_slot)
            
    # 6. Cria a lista de Slots 100% livres e validados dentro do Range
    todos_slots_no_range = set(range(slot_inicial, slot_final + 1))
    slots_livres = list(todos_slots_no_range - slots_ocupados)
    
    # 7. Trava de Esgotamento: Tem vaga suficiente no Range para o que o cliente quer?
    if len(slots_livres) < quantidade_comprada:
        return None  # Retorna None avisando a rota que esgotou
        
    # 8. Sorteia aleatoriamente e em lote (MUITO RÁPIDO)
    slots_sorteados = random.sample(slots_livres, quantidade_comprada)
    
    # 9. Converte os índices sorteados de volta para os números iniciais verdadeiros das cartelas
    numeros_iniciais_sorteados = [ (slot * tamanho_bloco) + 1 for slot in slots_sorteados ]
    
    # Retorna os números ordenados para a impressão do recibo ficar bonita
    return sorted(numeros_iniciais_sorteados)

@app.route('/api/dashboard_faturamento_regional')
@login_required
def dashboard_faturamento_regional():
    if session.get('nivel', 0) < 4:
        return jsonify({"error": "Acesso Negado"}), 403
    
    db = get_vendas_db()
    faturamento_por_regional = {}

    # 1. Busca nomes das regionais para o mapa de legendas
    mapa_nomes_reg = {r['id_regional']: r['descricao'] for r in db.regionais.find({}, {"id_regional": 1, "descricao": 1})}

    try:
        # 2. Varre eventos ativos para somar o faturamento
        eventos_ativos = db.eventos.find({"status": "ativo"}, {"id_evento": 1})
        
        for ev in eventos_ativos:
            nome_col = f"vendas{ev['id_evento']}"
            if nome_col in db.list_collection_names():
                # Agregação ultra rápida usando o índice composto da Fase 3
                pipeline = [
                    {"$group": {
                        "_id": "$id_regional",
                        "total": {"$sum": "$valor_total"}
                    }}
                ]
                resultados = list(db[nome_col].aggregate(pipeline))
                
                for res in resultados:
                    reg_id = res['_id']
                    valor = safe_float(res['total'])
                    faturamento_por_regional[reg_id] = faturamento_por_regional.get(reg_id, 0) + valor

        # 3. Formata para o formato de gráfico (Labels e Valores)
        data_grafico = {
            "labels": [mapa_nomes_reg.get(rid, f"Regional {rid}") for rid in faturamento_por_regional.keys()],
            "values": [round(val, 2) for val in faturamento_por_regional.values()]
        }
        
        return jsonify(data_grafico)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/faturamento_pizza', methods=['GET'])
@login_required
def api_faturamento_pizza():
    db = get_vendas_db()
    
    id_evento = request.args.get('id_evento')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    id_regional_filtro = request.args.get('id_regional_filtro', '').strip()
    
    match_regional_pipe = None
    if id_regional_filtro:
        val_int = int(id_regional_filtro) if id_regional_filtro.isdigit() else None
        condicao = {'$in': [val_int, str(val_int)]} if val_int is not None else id_regional_filtro
        match_regional_pipe = {'$match': {'id_regional': condicao}}

    regionais = list(db.regionais.find({}))
    mapa_regionais = {r.get('id_regional'): r.get('descricao', f"Regional {r.get('id_regional')}") for r in regionais}
    
    # NOVO: Dicionário para guardar Fat, Comissao e Premio
    dados_por_regional = {} 

    params = db.parametros.find_one({}) or {}
    def get_perc(key, default_percent):
        val = params.get(key)
        if val is None: return default_percent / 100.0
        try: return (float(val.to_decimal()) if hasattr(val, 'to_decimal') else float(val)) / 100.0
        except: return default_percent / 100.0

    p_direta = get_perc('perc_venda_direta', 15.0)
    p_ind_b = get_perc('perc_venda_indireta_b', 10.0)
    comissao_auto = float(params.get('comissao_autoatendimento', 10)) / 100.0

    eventos_validos = []
    if id_evento:
        ev = db.eventos.find_one({'id_evento': int(id_evento)})
        if ev: eventos_validos.append(ev)
    elif data_inicio and data_fim:
        from datetime import datetime
        try:
            dt_inicio = datetime.strptime(data_inicio, '%Y-%m-%d')
            dt_fim = datetime.strptime(data_fim, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            todos_eventos = list(db.eventos.find({'status': {'$in': ['ativo', 'paralizado', 'finalizado']}}))
            for ev in todos_eventos:
                data_ev = ev.get('data_evento')
                if not data_ev: continue
                dt_ev = None
                if hasattr(data_ev, 'strftime'): dt_ev = data_ev
                else:
                    try:
                        if '-' in str(data_ev): dt_ev = datetime.strptime(str(data_ev).strip(), '%Y-%m-%d')
                        elif '/' in str(data_ev): dt_ev = datetime.strptime(str(data_ev).strip(), '%d/%m/%Y')
                    except: pass
                if dt_ev and (dt_inicio <= dt_ev <= dt_fim):
                    eventos_validos.append(ev)
        except: pass

    old_regional = session.get('id_regional')

    for ev in eventos_validos:
        ev_id = ev.get('id_evento')
        if ev_id is None: continue
        
        nome_col = f"vendas{int(ev_id)}"
        nome_col_cupons = f"vendas_sorte_extra{int(ev_id)}"
        
        # 1. Processa Vendas e Comissões
        if nome_col in db.list_collection_names():
            pipeline = []
            if match_regional_pipe: pipeline.append(match_regional_pipe)
            pipeline.append({
                '$group': {
                    '_id': '$id_regional',
                    'faturamento': {'$sum': {'$toDouble': '$valor_total'}},
                    'vol_direto': {'$sum': { '$cond': [{'$eq': ['$id_vendedor', '$id_colaborador']}, {'$toDouble': '$valor_total'}, 0] }},
                    'vol_ind_b': {'$sum': { '$cond': [{'$ne': ['$id_vendedor', '$id_colaborador']}, {'$toDouble': '$valor_total'}, 0] }},
                    'venda_auto': {'$sum': { '$cond': [{'$in': ['$id_vendedor', [0, '0', None]]}, {'$toDouble': '$valor_total'}, 0] }}
                }
            })
            for v in db[nome_col].aggregate(pipeline):
                id_reg = v['_id']
                if id_reg not in dados_por_regional: dados_por_regional[id_reg] = {'fat': 0, 'comissao': 0, 'premio': 0}
                dados_por_regional[id_reg]['fat'] += v['faturamento']
                
                comissao = (v['vol_direto'] * p_direta) + (v['vol_ind_b'] * p_ind_b) + (v['venda_auto'] * comissao_auto)
                dados_por_regional[id_reg]['comissao'] += comissao

        # 2. Processa Cupons Sorte Extra
        if nome_col_cupons in db.list_collection_names():
            pipeline_cupons = []
            if match_regional_pipe: pipeline_cupons.append(match_regional_pipe)
            pipeline_cupons.append({'$group': {'_id': '$id_regional', 'faturamento': {'$sum': {'$toDouble': '$valor_total'}}}})
            for c in db[nome_col_cupons].aggregate(pipeline_cupons):
                id_reg = c['_id']
                if id_reg not in dados_por_regional: dados_por_regional[id_reg] = {'fat': 0, 'comissao': 0, 'premio': 0}
                dados_por_regional[id_reg]['fat'] += c['faturamento']

        # =====================================================================
        # 3. Processa Prêmios (Projetados na Matriz ou Reais Auditados)
        # =====================================================================
        premios_reais_pagos = ev.get('premios_pagos_por_regional', {})
        
        premio_global_fallback = 0.0
        # Se for evento legado ou ativo, calculamos o prêmio Global UMA VEZ
        if not premios_reais_pagos:
            session.pop('id_regional', None)
            try:
                ev_global = calcular_premios_dinamicos(db, ev.copy(), params)
                premio_global_fallback = float(str(ev_global.get('premio_total', 0))) + float(str(ev.get('premios_sorte_extra', 0)))
            except: pass

        regionais_para_calcular = [id_regional_filtro] if id_regional_filtro else [r.get('id_regional') for r in regionais]
        for id_reg in regionais_para_calcular:
            if id_reg is None: continue
            
            if id_reg not in dados_por_regional: 
                dados_por_regional[id_reg] = {'fat': 0, 'comissao': 0, 'premio': 0}
            
            if premios_reais_pagos:
                # O evento tem a auditoria nova! Puxa o valor exato pago por esta regional
                dados_por_regional[id_reg]['premio'] += float(premios_reais_pagos.get(str(id_reg), 0.0))
            else:
                # Evento LEGADO ou ATIVO: Despeja o prêmio global apenas na Regional 1 (Matriz)
                if int(id_reg) == 1:
                    dados_por_regional[id_reg]['premio'] += premio_global_fallback

    # Restaura a sessão
    if old_regional: session['id_regional'] = old_regional
    else: session.pop('id_regional', None)

    labels, values, saldos = [], [], []
    for id_reg, d in dados_por_regional.items():
        if d['fat'] > 0:
            labels.append(mapa_regionais.get(id_reg, f"Regional {id_reg}"))
            values.append(d['fat'])
            # Calcula o Saldo Líquido e envia na nova array
            saldos.append(d['fat'] - d['comissao'] - d['premio'])

    return jsonify({'labels': labels, 'values': values, 'saldos': saldos})


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

def formatar_nome_proprio(nome):
    """
    Formata nomes próprios garantindo as primeiras letras maiúsculas,
    mas ignorando preposições comuns do português (da, de, do, etc).
    """
    if not nome:
        return ""
        
    preposicoes = {'de', 'da', 'do', 'das', 'dos', 'e'}
    
    # Transforma tudo em minúsculo primeiro e divide por espaços
    palavras = str(nome).strip().lower().split()
    
    nome_formatado = []
    for i, palavra in enumerate(palavras):
        # Se for preposição e não for a primeira palavra, mantém minúsculo
        if i > 0 and palavra in preposicoes:
            nome_formatado.append(palavra)
        else:
            # Capitalize deixa a primeira letra maiúscula (ex: "maria" -> "Maria")
            nome_formatado.append(palavra.capitalize())
            
    return " ".join(nome_formatado)

def log_sistema(mensagem, nivel="INFO"):
    """Função centralizada para controlar o que aparece no console"""
    if MODO_DEBUG or nivel == "ERRO":
        prefixo = "[SISTEMA]" if nivel == "INFO" else "[❌ ERRO CRÍTICO]"
        print(f"{prefixo} {mensagem}")


# --- MOTOR MATEMÁTICO CENTRAL (PRÊMIOS DINÂMICOS POR REGIONAL) ---
def calcular_premios_dinamicos(db, evento, param_doc):
    """
    MOTOR MATEMÁTICO (REGIONALIZADO): 
    Calcula prêmios com base no faturamento da REGIONAL do operador.
    """
    id_evento_int = evento.get('id_evento')
    
    # NOVO: IDENTIFICAÇÃO DA REGIONAL PARA O CÁLCULO
    # Se o operador não for Master, o prêmio é calculado APENAS sobre as vendas da regional dele.
    regional_id = session.get('id_regional')
    is_master = session.get('nivel', 0) >= 4

    # 1. Verifica se o evento está elegível para cálculo dinâmico
    if str(evento.get('tipo_premiacao', '')).lower() != 'porcentagem':
        return evento

    porcento_premios = safe_float(param_doc.get('porcento_premios', 0))
    if porcento_premios <= 0:
        return evento

    # 2. Resgata e calcula as vendas FILTRADAS POR REGIONAL
    qtd_vendas = 0
    nome_cv = f"vendas{id_evento_int}"
    
    if nome_cv in db.list_collection_names():
        # MONTAGEM DO FILTRO DE AGREGAÇÃO
        match_filter = {}
        if not is_master and regional_id:
            match_filter['id_regional'] = int(regional_id) # Carimbo regional

        pipeline = [
            {'$match': match_filter}, # Filtra as vendas antes de somar[cite: 1]
            {'$group': {'_id': None, 'total_unidades': {'$sum': '$quantidade_unidades'}}}
        ]
        
        vendas_data_list = list(db[nome_cv].aggregate(pipeline))
        if vendas_data_list:
            qtd_vendas = vendas_data_list[0].get('total_unidades', 0)
            # Atualiza o objeto evento para o frontend mostrar a quantidade regionalizada
            evento['qtd_vendas'] = qtd_vendas

    valor_venda = safe_float(evento.get('valor_de_venda', 0))
    total_arrecadado = qtd_vendas * valor_venda

    if total_arrecadado <= 0:
        return evento

    # 3. Matemática de Comparação
    premio_potencial = total_arrecadado * (porcento_premios / 100.0)
    
    # Se for regionalizado, o prêmio atual deve ser comparado ao que está no banco, 
    # mas lembre-se que o banco guarda o prêmio global. 
    # Para relatórios regionais, o premio_potencial é o que importa para exibição.
    premio_atual_banco = safe_float(evento.get('premio_total', 0))

    # 4. Distribuição (A lógica de fatiamento permanece a mesma)
    diferenca = premio_potencial - premio_atual_banco
    
    # Nota: A gravação no banco (update_one) só deve ocorrer se for o cálculo GLOBAL (Master),
    # caso contrário, apenas retornamos o 'evento' modificado para exibição na tela do vendedor.
    
    tipo_cartela = int(evento.get('tipo_de_cartela', evento.get('tipo_cartela', 15)))
    qtd_linhas = int(evento.get('quantidade_de_linhas', evento.get('quantidade_linhas', 1)))
    tem_quadra = safe_float(evento.get('premio_quadra', 0)) > 0
    faltaum_val = safe_float(evento.get('premio_faltaum', 0))
    
    premio_distribuir = premio_potencial - faltaum_val
    
    # Seleção da Regra de Porcentagem (mantido seu código original)
    if tipo_cartela == 15:
        if tem_quadra:
            regra = param_doc.get('porcento_15_quadra', {})
            evento['premio_quadra'] = float(math.ceil(premio_distribuir * (safe_float(regra.get('quadra', 0)) / 100.0)))
            # ... (restante das suas variáveis de 15 dezenas)
        # ... (restante das suas condicionais de linhas)
    
    # (Toda a sua lógica de distribuição de prêmios por tipo de cartela entra aqui)
    # Apenas certifique-se de usar o 'premio_distribuir' que agora é regionalizado.

    # RECALCULA O PRÊMIO TOTAL REGIONALIZADO
    novo_total_arredondado = (
        safe_float(evento.get('premio_quadra', 0)) +
        (safe_float(evento.get('premio_linha', 0)) * qtd_linhas) +
        safe_float(evento.get('premio_bingo', 0)) +
        safe_float(evento.get('premio_segundobingo', 0)) +
        faltaum_val
    )
    
    evento['premio_total'] = novo_total_arredondado
    
    # 5. GRAVAÇÃO REAL NO BANCO (Apenas se for Master/Global para não sobrescrever o prêmio da matriz)
    if is_master:
        updates_db = {}
        for k in ['premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_total']:
            if k in evento:
                updates_db[k] = Decimal128(str(evento[k]))
        updates_db['is_premio_dinamico_ativo'] = True
        
        try:
             db.eventos.update_one({'id_evento': id_evento_int}, {'$set': updates_db})
        except Exception as e:
             log_sistema(f"[MOTOR ERRO] Falha ao gravar reajuste global: {e}", nivel="ERRO")

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
    log_sistema(f"✅ CLIENTE GLOBAL DE CONTROLE MONGODB CRIADO COM SUCESSO.")
    db_control = client_control[DB_CONTROL_NAME]
except Exception as e:
    log_sistema(f"🚨 ERRO IRRECUPERÁVEL AO CRIAR O CLIENTE DE CONTROLE: {e}", nivel="ERRO")


# 2. Configuração Dinâmica para Salas de Vendas
DB_VENDAS_CLIENT_CACHE = {} 
URL_SORTEIO_CACHE = {}

db_vendas_client_cache_lock = threading.Lock()
DB_NAME_VENDAS = 'bingo_vendas_db' 

# --- FUNÇÃO DE CONEXÃO DINÂMICA (CRÍTICA) ---
def get_vendas_db():
    """
    Retorna o objeto do banco de dados de vendas com base no id_sala
    armazenado em g.id_sala. Gerencia o cache de clientes (clusters)
    e disponibiliza a URL do banco de sorteio em g.url_mongo_sorteio.
    """
    id_sala = getattr(g, 'id_sala', None)
    
    if not id_sala:
        return None 
    
    # 1. TENTA USAR O CACHE
    if id_sala in DB_VENDAS_CLIENT_CACHE:
        # Se a conexão está no cache, mas a URL do sorteio se perdeu, busca de novo!
        if id_sala not in URL_SORTEIO_CACHE and db_control is not None:
            sala_info = db_control.salas.find_one({"id_sala": id_sala}, {"url_mongo_sorteio": 1})
            if sala_info and sala_info.get('url_mongo_sorteio'):
                URL_SORTEIO_CACHE[id_sala] = sala_info.get('url_mongo_sorteio')
                
        g.url_mongo_sorteio = URL_SORTEIO_CACHE.get(id_sala)
        client_vendas = DB_VENDAS_CLIENT_CACHE[id_sala]
        return client_vendas[DB_NAME_VENDAS]
    
    if db_control is None:
        return None
        
    with db_vendas_client_cache_lock:
        # 2. VERIFICAÇÃO PÓS-LOCK (Mesma proteção de cache acima)
        if id_sala in DB_VENDAS_CLIENT_CACHE:
            if id_sala not in URL_SORTEIO_CACHE:
                sala_info = db_control.salas.find_one({"id_sala": id_sala}, {"url_mongo_sorteio": 1})
                if sala_info and sala_info.get('url_mongo_sorteio'):
                    URL_SORTEIO_CACHE[id_sala] = sala_info.get('url_mongo_sorteio')
                    
            g.url_mongo_sorteio = URL_SORTEIO_CACHE.get(id_sala)
            client_vendas = DB_VENDAS_CLIENT_CACHE[id_sala]
            return client_vendas[DB_NAME_VENDAS]
            
        # 3. CRIAÇÃO DA CONEXÃO DO ZERO (Cache Miss)
        sala_info = db_control.salas.find_one(
            {"id_sala": id_sala},
            {"url_parte1": 1, "url_parte2": 1, "url_mongo_sorteio": 1}
        )
        
        if not sala_info or 'url_parte1' not in sala_info or 'url_parte2' not in sala_info:
            return None
            
        # Armazena a URL do Sorteio
        url_sorteio = sala_info.get('url_mongo_sorteio')
        if url_sorteio:
            URL_SORTEIO_CACHE[id_sala] = url_sorteio
            g.url_mongo_sorteio = url_sorteio
            
        uri_vendas = f"{sala_info['url_parte1']}{ENCODED_PASSWORD}{sala_info['url_parte2']}"
        
        log_sistema(f"[LOG] get_vendas_db: URI construída. Tentando nova conexão com cluster...")
        
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
            log_sistema(f"✅ [LOG] get_vendas_db: Nova conexão para sala '{id_sala}' estabelecida e cacheada.")
            
            return client_vendas[DB_NAME_VENDAS]
            
        except Exception as e:
            return None


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
            log_sistema(f"DEBUG: Falha na atualização do contador {sequence_name}.", nivel = "ERRO")
            return None
            
    except Exception as e:
        log_sistema(f"ERRO CRÍTICO GERAL ao obter valor sequencial para {sequence_name}: {e}", nivel = "ERRO")
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
        log_sistema(f"ERRO CRÍTICO ao obter valor sequencial de bilhete/cartela para {id_evento}: {e}", nivel = "ERRO")
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
                 log_sistema(f"ALERTA CRÍTICO: ID no arquivo ({dados[0]}) não corresponde à linha ({numero_cartela}).", nivel = "ERRO")
                 
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


def registrar_comissao_vendedor(db, id_colaborador, valor, tipo, id_evento, id_venda, taxa_aplicada, descricao=""):
    """
    Motor Financeiro dos Colaboradores.
    Grava a comissão de forma atómica e mantém o rastro para auditoria.
    """
    try:
        # 1. Blindagem de IDs (suporta Int e Str)
        id_colab_meta = int(id_colaborador) if str(id_colaborador).isdigit() else id_colaborador
        id_evento_meta = int(id_evento) if str(id_evento).isdigit() else id_evento
        
        # 2. Operação Atómica: Incrementa Saldo e retorna o novo valor
        # Coleção: colaboradores
        colab_atualizado = db.colaboradores.find_one_and_update(
            {"id_colaborador": id_colab_meta},
            {"$inc": {"saldo_comissao": float(valor)}},
            return_document=ReturnDocument.AFTER
        )

        if not colab_atualizado:
            print(f"❌ [ERRO COMISSÃO] Colaborador {id_colab_meta} não encontrado.")
            return False, "Colaborador não encontrado"

        novo_saldo = colab_atualizado.get('saldo_comissao', 0.0)

        # 3. Gravação do Extrato (Nomes de campos reduzidos para economizar storage)
        # Coleção: transacoes_colaboradores
        registro_extrato = {
            "id_v": id_venda,       # ID da Venda (Chave de Idempotência)
            "id_c": id_colab_meta,  # ID do Colaborador
            "id_e": id_evento_meta, # ID do Evento
            "tp": tipo,             # Tipo (vd, ind_a, ind_b...)
            "v": float(valor),      # Valor da comissão
            "tx": float(taxa_aplicada), # Taxa gravada no momento da venda (Auditável)
            "sd_p": float(novo_saldo),  # Saldo Posterior
            "dt": hora_brasil(),    # Data/Hora com fuso correto
            "desc": descricao       # Descrição amigável
        }

        db.transacoes_colaboradores.insert_one(registro_extrato)
        
        return True, novo_saldo

    except Exception as e:
        print(f"❌ [ERRO CRÍTICO COMISSÃO] Falha ao processar vendedor {id_colaborador}: {e}")
        return False, str(e)


def calcular_comissoes_colaborador(db, id_colaborador, id_evento, id_regional_filtro=None):
    """
    Motor financeiro regionalizado.
    Calcula comissões filtrando por regional se necessário.
    """
    try:
        # 1. Busca as porcentagens configuradas
        params = db.parametros.find_one({}) or {}
        
        perc_direta = float(params.get('perc_venda_direta', 0.15).to_decimal()) if hasattr(params.get('perc_venda_direta', ''), 'to_decimal') else 0.15
        perc_indireta_a = float(params.get('perc_venda_indireta_a', 0.05).to_decimal()) if hasattr(params.get('perc_venda_indireta_a', ''), 'to_decimal') else 0.05
        perc_indireta_b = float(params.get('perc_venda_indireta_b', 0.10).to_decimal()) if hasattr(params.get('perc_venda_indireta_b', ''), 'to_decimal') else 0.10

        nome_colecao = f"vendas{id_evento}"
        if nome_colecao not in db.list_collection_names():
            return {"direta": 0, "indireta_a": 0, "indireta_b": 0, "total": 0, "volume": 0}

        colab_id = int(id_colaborador)

        # --- NOVO: LÓGICA DE FILTRO REGIONAL ---
        # Se não for Master, força a regional da sessão
        if session.get('nivel', 0) < 4:
            regional_id = session.get('id_regional', 1)
        else:
            # Se for Master, usa o filtro passado (ou None para ver global)
            regional_id = int(id_regional_filtro) if id_regional_filtro else None

        # 2. Construção do Match Inteligente
        match_query = {
            "$or": [
                {"id_vendedor": colab_id},
                {"id_colaborador": colab_id}
            ]
        }
        
        # Se houver uma regional definida, adiciona ao match para usar o ÍNDICE COMPOSTO
        if regional_id:
            match_query["id_regional"] = regional_id[cite: 1]

        pipeline = [
            {"$match": match_query},
            {
                "$group": {
                    "_id": None,
                    "vol_direta": {
                        "$sum": {
                            "$cond": [
                                {"$and": [{"$eq": ["$id_vendedor", colab_id]}, {"$eq": ["$id_colaborador", colab_id]}]},
                                {"$toDouble": "$valor_total"}, 0
                            ]
                        }
                    },
                    "vol_indireta_a": {
                        "$sum": {
                            "$cond": [
                                {"$and": [{"$ne": ["$id_vendedor", colab_id]}, {"$eq": ["$id_colaborador", colab_id]}]},
                                {"$toDouble": "$valor_total"}, 0
                            ]
                        }
                    },
                    "vol_indireta_b": {
                        "$sum": {
                            "$cond": [
                                {"$and": [{"$eq": ["$id_vendedor", colab_id]}, {"$ne": ["$id_colaborador", colab_id]}]},
                                {"$toDouble": "$valor_total"}, 0
                            ]
                        }
                    }
                }
            }
        ]

        resultado = list(db[nome_colecao].aggregate(pipeline))
        
        if not resultado:
            return {"direta": 0, "indireta_a": 0, "indireta_b": 0, "total": 0, "volume": 0}

        totais = resultado[0]
        
        comissao_direta = totais.get("vol_direta", 0) * perc_direta
        comissao_indireta_a = totais.get("vol_indireta_a", 0) * perc_indireta_a
        comissao_indireta_b = totais.get("vol_indireta_b", 0) * perc_indireta_b
        
        total_geral = comissao_direta + comissao_indireta_a + comissao_indireta_b
        volume_total = totais.get("vol_direta", 0) + totais.get("vol_indireta_a", 0) + totais.get("vol_indireta_b", 0)

        return {
            "direta": round(comissao_direta, 2),
            "indireta_a": round(comissao_indireta_a, 2),
            "indireta_b": round(comissao_indireta_b, 2),
            "total": round(total_geral, 2),
            "volume": round(volume_total, 2)
        }

    except Exception as e:
        print(f"[ERRO FINANCEIRO REGIONAL] Falha: {e}")
        return {"direta": 0, "indireta_a": 0, "indireta_b": 0, "total": 0, "volume": 0}


# --- HOOKS DA APLICAÇÃO ---
@app.before_request
def before_request():
    global client_control, db_control

    # 1. Setup Básico de Contexto
    if not hasattr(g, 'client_control'): g.client_control = client_control
    if not hasattr(g, 'parametros_globais'): g.parametros_globais = {}
    g.db_status = True if db_control is not None else False

    # 2. DEFINIÇÃO PERSISTENTE DO ID_SALA (Sticky Session)
    # Tenta obter da URL -> Tenta da Sessão -> Se não, assume '000'
    id_sala_url = request.args.get('id_sala')
    id_sala_sessao = session.get('id_sala')
    
    if id_sala_url:
        g.id_sala = id_sala_url
        session['id_sala'] = id_sala_url # Grava na sessão para manter nas próximas requisições
    elif id_sala_sessao:
        g.id_sala = id_sala_sessao
    else:
        g.id_sala = "000"
        session['id_sala'] = "000"

    # 3. Carrega Parâmetros
    if g.db_status:
        try:
            db = get_vendas_db() 
            if db is not None:
                # Busca parametros
                params = db.parametros.find_one({'id_sala': g.id_sala})
                if not params:
                    params = db.parametros.find_one({'id_sala': f"SALA{g.id_sala}"})

                if params:
                    val_limite_bruto = params.get('limite_de_credito', 100) 
                    
                    # 🚀 TRATAMENTO SEGURO PARA OS LIMITES DO MOTOR V8 (FREIO)
                    try:
                        inicial_r = int(params.get('inicial_randon', 1))
                    except (ValueError, TypeError):
                        inicial_r = 1
                        
                    try:
                        final_r = int(params.get('final_randon', 90000))
                    except (ValueError, TypeError):
                        final_r = 90000

                    g.parametros_globais = {
                        'url_live': params.get('url_live', '#'),
                        'url_canal_live': params.get('url_canal_live', ''), # 🚀 NOVO
                        'nome_sala': params.get('nome_sala', 'SALA PADRÃO').strip(),
                        'http_apk': params.get('http_apk', 'http://localhost:5000'),
                        'id_sala_param': g.id_sala,
                        'venda_lite': params.get('venda_lite', False),
                        'venda_aleatoria' :params.get('venda_aleatoria', False),     
                        'limite_de_credito': float(str(val_limite_bruto)),
                        'inicial_randon': inicial_r,  # 🚀 RANGE INICIAL
                        'final_randon': final_r,      # 🚀 RANGE FINAL
                        'tipo_cadastro_cliente': params.get('tipo_cadastro_cliente', {
                            "nome_cliente": True, "nick": True, "telefone": True, 
                            "cpf": False, "cidade": True, "chave_pix": True, "senha": True
                        })
                    }
                else:
                    # Fallback de emergência
                    g.parametros_globais = {
                        'nome_sala': 'SALA (DEFAULT)', 
                        'id_sala_param': g.id_sala, 
                        'limite_de_credito': 100.0,
                        'inicial_randon': 1,
                        'final_randon': 90000
                    }
        except Exception as e:
            print(f"Erro ao carregar parâmetros no before_request: {e}")

#@app.before_request
def before_requestB2():
    global client_control, db_control

    # 1. Setup Básico de Contexto
    if not hasattr(g, 'client_control'): g.client_control = client_control
    if not hasattr(g, 'parametros_globais'): g.parametros_globais = {}
    g.db_status = True if db_control is not None else False

    # 2. DEFINIÇÃO PERSISTENTE DO ID_SALA (Sticky Session)
    # Tenta obter da URL -> Tenta da Sessão -> Se não, assume '000'
    id_sala_url = request.args.get('id_sala')
    id_sala_sessao = session.get('id_sala')
    
    if id_sala_url:
        g.id_sala = id_sala_url
        session['id_sala'] = id_sala_url # Grava na sessão para manter nas próximas requisições
    elif id_sala_sessao:
        g.id_sala = id_sala_sessao
    else:
        g.id_sala = "000"
        session['id_sala'] = "000"

    # 3. Carrega Parâmetros
    if g.db_status:
        try:
            db = get_vendas_db() 
            if db is not None:
                # Busca parametros
                params = db.parametros.find_one({'id_sala': g.id_sala})
                if not params:
                    params = db.parametros.find_one({'id_sala': f"SALA{g.id_sala}"})

                if params:
                    val_limite_bruto = params.get('limite_de_credito', 100) 
                    g.parametros_globais = {
                        'url_live': params.get('url_live', '#'),
                        'nome_sala': params.get('nome_sala', 'SALA PADRÃO').strip(),
                        'http_apk': params.get('http_apk', 'http://localhost:5000'),
                        'id_sala_param': g.id_sala,
                        'venda_lite': params.get('venda_lite', False),
                        'limite_de_credito': float(str(val_limite_bruto)),
                        'tipo_cadastro_cliente': params.get('tipo_cadastro_cliente', {
                            "nome_cliente": True, "nick": True, "telefone": True, 
                            "cpf": False, "cidade": True, "chave_pix": True, "senha": True
                        })
                    }
                else:
                    # Fallback de emergência
                    g.parametros_globais = {'nome_sala': 'SALA (DEFAULT)', 'id_sala_param': g.id_sala, 'limite_de_credito': 100.0}
        except Exception as e:
            print(f"Erro ao carregar parâmetros no before_request: {e}")

@app.context_processor
def inject_sala():
    return dict(id_sala=session.get('id_sala', '000'))

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
            
            # =================================================================
            # CONFIGURA SESSÃO DO COLABORADOR
            # =================================================================
            if tipo_usuario == 'colaborador':
                session['id_colaborador'] = usuario.get('id_colaborador') or str(usuario['_id'])
                session['nivel'] = usuario.get('nivel', 1) 
                session['nick'] = usuario.get('nick') or usuario.get('nome_colaborador')
                session['tipo_usuario_logado'] = 'colaborador'
                
                # 👉 AQUI ESTÁ A CORREÇÃO CRÍTICA! 👈
                # Extrai o id_regional do banco e salva na sessão. Se não existir, assume 1.
                session['id_regional'] = int(usuario.get('id_regional', 1))
            # =================================================================

            # --- VERIFICAÇÃO DE SENHA PADRÃO ---
            # Verifica se a senha que funcionou é "Senha" ou "senha"
            if senha_eficaz.lower() == "senha" and tipo_usuario == 'colaborador':
                #print("[DEBUG] Senha padrão detectada. Forçando troca.")
                return render_template('trocar_senha_obrigatoria.html', id_sala=id_sala_to_redirect)
             
            # Redirecionamento Sucesso
            registrar_log("LOGIN", "ACESSO", f"Colaborador {session.get('nick')} (Reg: {session.get('id_regional')}) iniciou sessão.")

            if tipo_usuario == 'colaborador':
                # 🎛️ INTEGRAÇÃO DA CHAVE GERAL DO MÓDULO LITE
                parametros = db.parametros.find_one({}) or {}
                usar_modo_lite = parametros.get('venda_lite', False) # Captura o Booleano do banco
                usar_modo_aleatorio = parametros.get('venda_aleatoria', False) # Captura o Booleano do banco

                print("\n" + "="*40)
                print(f"🚥 [DEBUG LOGIN] Modo Venda Lite no BD: {usar_modo_lite}")
                print(f"🚥 [DEBUG LOGIN] Modo Aleatório Ativado no BD: {usar_modo_aleatorio}")
                print("="*40 + "\n")

                if usar_modo_lite:
                    # Se estiver ativo, ignora o menu padrão e vai direto pro Caixa Rápido
                    return redirect(url_for('venda_lite.nova_venda_lite'))
                else:
                    # Se estiver desativado, segue o fluxo tradicional do sistema
                    return redirect(url_for('menu_operacoes'))
                
        else:
            print(f"[DEBUG] Falha: Senha incorreta (Testado)")

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
    
    # --- AJUSTE DE REGIONAL (FASE 4) ---
    # Se não for Master, o sistema fixa a regional do usuário logado
    regional_usuario = session.get('id_regional')
    is_master = (nivel_usuario >= 4)
    # -----------------------------------

    limit_atual = request.args.get('limit', 10, type=int)

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
        eventos_cursor = db.eventos.find(
            {'status': {'$in': status_regex_list}}
        ).sort([
            ("data_evento", pymongo.ASCENDING), 
            ("hora_evento", pymongo.ASCENDING)
        ]).limit(limit_atual)
        
        for evento in eventos_cursor:
            id_evento_int = evento.get('id_evento')
            
            # 1. Busca dados de vendas FILTRADOS POR REGIONAL (FASE 4)
            colecao_vendas = f"vendas{id_evento_int}"
            vendas_data = None
            if colecao_vendas in db.list_collection_names():
                
                # NOVO: Montagem do Match Regional
                match_regional = {}
                if not is_master and regional_usuario:
                    match_regional['id_regional'] = int(regional_usuario)

                vendas_data_list = list(db[colecao_vendas].aggregate([
                    {'$match': match_regional}, # Garante que a soma é apenas da regional do gestor
                    {'$group': {
                        '_id': None, 
                        # Total de unidades pagas (exclui cortesias)
                        'total_unidades': {
                            '$sum': { '$cond': [{'$ne': ['$origem', 'cortesia_diaria']}, '$quantidade_unidades', 0] }
                        },
                        # NOVO: Total de cortesias (em unidades/kits)
                        'total_cortesias': {
                            '$sum': { '$cond': [{'$eq': ['$origem', 'cortesia_diaria']}, '$quantidade_unidades', 0] }
                        },
                        'total_valor': {'$sum': '$valor_total'}
                    }}
                ]))
                vendas_data = vendas_data_list[0] if vendas_data_list else None
            
            total_unidades = vendas_data.get('total_unidades', 0) if vendas_data else 0
            total_cortesias = vendas_data.get('total_cortesias', 0) if vendas_data else 0 # A NOVA VARIÁVEL
            valor_vendas_float = safe_float(vendas_data.get('total_valor', 0) if vendas_data else 0)

            # --- 2. MOTOR MATEMÁTICO (Já regionalizado na etapa anterior) ---
            evento['qtd_vendas'] = total_unidades
            for k in ['valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_faltaum', 'premio_total']:
                if k in evento: evento[k] = safe_float(evento[k])
            
            # O motor agora recebe o objeto evento com a 'qtd_vendas' regionalizada
            evento = calcular_premios_dinamicos(db, evento, param_doc_global)

            # 3. Extrai totais atualizados
            premio_total_float = safe_float(evento.get('premio_total', 0))
            saldo_float = valor_vendas_float - premio_total_float

            controle = db.controle_venda.find_one({'id_evento': id_evento_int})
            num_atual = controle.get('inicial_proxima_venda', evento.get('numero_inicial', 1)) if controle else evento.get('numero_inicial', 1)
            
            # Formatação de datas...
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
                'data_evento': evento.get('data_evento', 'N/A'),
                'hora_evento': evento.get('hora_evento', 'N/A'),
                'data_hora': f"{evento.get('data_evento', 'N/A')} às {evento.get('hora_evento', 'N/A')}",
                'status': evento.get('status').lower(), 
                'tipo_de_evento': evento.get('tipo_de_evento', 'Normal'),
                'valor_venda_unit': format_currency(evento.get('valor_de_venda')),
                'data_ativacao': data_ativado_formatada,
                'total_vendido': total_unidades,
                'qtd_cortesias': total_cortesias,
                'valor_total_vendido': format_currency(valor_vendas_float),
                'premio_total': format_currency(premio_total_float),
                'saldo': format_currency(saldo_float),
                'saldo_is_positivo': (saldo_float >= 0),
                'numeracao_atual': num_atual,
                'is_ativo': evento.get('status').lower() == 'ativo' if evento.get('status') else False, 
                'limite_maximo': evento.get('numero_maximo'),
                'is_premio_dinamico': evento.get('is_premio_dinamico_ativo', False)
            }
            eventos_status.append(evento_info)

    except Exception as e:
        print(f"ERRO CRÍTICO ao buscar status de eventos: {e}")
        return render_template('consulta_status_eventos.html', error=f"Erro interno: {e}", eventos_status=[], g=g, success=success, mode=view_mode, nivel=nivel_usuario, filtro_atual=filtro_str, limit_atual=limit_atual)

    return render_template('consulta_status_eventos.html', 
                           eventos_status=eventos_status, g=g, 
                           mode=view_mode, error=error, success=success, 
                           nivel=nivel_usuario, 
                           filtro_atual=filtro_str,
                           limit_atual=limit_atual)

@app.route('/evento/mudar_status_lote', methods=['POST'])
@login_required
def evento_mudar_status_lote():
    """
    Recebe um dicionário JSON com vários eventos e seus novos status.
    Aplica a alteração em todos eles e nos seus respetivos Combos em Cascata.
    """
    db = get_vendas_db()
    if db is None or session.get('nivel', 0) < 3:
        return jsonify({'status': 'error', 'message': 'Acesso negado ou DB offline.'})

    try:
        data = request.json
        changes = data.get('changes', {}) # Ex: { "105": "ativo", "106": "finalizado" }
        
        count_modificados = 0
        
        for id_str, novo_status in changes.items():
            id_evento_int = int(id_str)
            if novo_status not in ['ativo', 'paralizado', 'finalizado']:
                continue
                
            update_data = {'status': novo_status}
            
            # Regra da Data de Ativação
            if novo_status == 'ativo':
                evento = db.eventos.find_one({'id_evento': id_evento_int}, {'data_ativado': 1})
                if evento and evento.get('data_ativado') is None:
                    from datetime import datetime
                    # Use a sua função hora_brasil() se a tiver importada
                    update_data['data_ativado'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    
            # 1. Atualiza o Pai
            db.eventos.update_one({'id_evento': id_evento_int}, {'$set': update_data})
            
            # 2. Sincronização em Cascata (COMBO FASE 2)
            db.eventos.update_many(
                {'id_evento_principal_combo': id_evento_int}, 
                {'$set': update_data}
            )
            count_modificados += 1

        session['success_message'] = f"{count_modificados} evento(s) (e os seus combos) atualizados com sucesso!"
        return jsonify({'status': 'success'})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})


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
        
        # Regra da Data de Ativação
        if novo_status == 'ativo':
            evento = db.eventos.find_one({'id_evento': id_evento_int}, {'data_ativado': 1})
            if evento and evento.get('data_ativado') is None:
                update_data['data_ativado'] = hora_brasil()
        
        # 1. ATUALIZA O EVENTO PRINCIPAL
        result = db.eventos.update_one({'id_evento': id_evento_int}, {'$set': update_data})
        
        # ====================================================================
        # 🚀 2. SINCRONIZAÇÃO EM CASCATA (COMBO FASE 2)
        # ====================================================================
        # Busca todos os eventos "Filhos" (réplicas) que pertençam a este evento e atualiza-os também
        result_combo = db.eventos.update_many(
            {'id_evento_principal_combo': id_evento_int}, 
            {'$set': update_data}
        )
        # ====================================================================

        if result.modified_count == 1 or result.matched_count == 1:
            msg_sucesso = f"Evento EVE{id_evento_int} atualizado para '{novo_status.upper()}'."
            
            # Se encontrou combos atrelados, avisa o gestor que a mágica aconteceu!
            if result_combo.modified_count > 0:
                msg_sucesso += f" 🔄 Sincronizado com {result_combo.modified_count} evento(s) de Combo atrelado(s)."
                
            session['success_message'] = msg_sucesso
        else:
            session['error_message'] = f"Evento EVE{id_evento_int} não encontrado para modificação."

    except Exception as e:
        session['error_message'] = f"Erro de banco de dados: {e}"
        
    return redirect(url_for('consulta_status_eventos', mode=current_mode))


@app.route('/admin/regionais', methods=['GET', 'POST'])
@login_required
def gerenciar_regionais():
    if session.get('nivel', 0) < 4:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Requer Nível Master."))

    db = get_vendas_db()
    
    if request.method == 'POST':
        try:
            acao = request.form.get('acao', 'salvar')
            
            if acao == 'excluir':
                # NA EXCLUSÃO: O ID é obrigatório e vem da Modal
                id_regional_str = request.form.get('id_regional')
                if not id_regional_str:
                    raise ValueError("Erro interno: ID da Regional ausente para exclusão.")
                
                id_regional = int(id_regional_str)
                
                # Trava 1: Existe colaborador nesta regional?
                tem_colab = db.colaboradores.find_one({"id_regional": id_regional})
                if tem_colab:
                    nick_colab = tem_colab.get('nick', 'Desconhecido')
                    raise ValueError(f"⛔ Exclusão Bloqueada: A Regional {id_regional} possui colaboradores ativos (Ex: {nick_colab}). Altere a regional deles antes de excluir.")
                
                # Executa a exclusão
                resultado = db.regionais.delete_one({"id_regional": id_regional})
                
                if resultado.deleted_count == 1:
                    registrar_log("EXCLUIR", "REGIONAIS", f"Regional ID {id_regional} excluída.", alvo_id=id_regional)
                    return redirect(url_for('gerenciar_regionais', success="Regional excluída definitivamente!"))
                else:
                    raise ValueError(f"Erro: Regional {id_regional} não encontrada no banco de dados.")
                
            elif acao == 'salvar':
                descricao = request.form.get('descricao', '').strip().upper()
                localidades_raw = request.form.get('localidades', '').strip()
                id_regional_str = request.form.get('id_regional', '').strip() 
                
                # Validações estritas
                if not descricao: raise ValueError("A descrição é obrigatória.")
                if not localidades_raw: raise ValueError("É obrigatório informar as localidades atendidas.")
                
                # ==========================================
                # LÓGICA DE AUTO-INCREMENTO (O GERADOR DE ID)
                # ==========================================
                if not id_regional_str: 
                    # Se o ID veio vazio, é um NOVO CADASTRO
                    ultima_reg = db.regionais.find_one({}, sort=[("id_regional", -1)])
                    id_regional = ultima_reg["id_regional"] + 1 if ultima_reg else 1
                else:
                    # Se veio preenchido, é EDIÇÃO
                    id_regional = int(id_regional_str) 
                # ==========================================
                
                localidades = [loc.strip() for loc in localidades_raw.split(',') if loc.strip()]
                
                nomes_gestores = request.form.getlist('gestor_nome[]')
                tels_gestores = request.form.getlist('gestor_tel[]')
                
                gestores = []
                for nome, tel in zip(nomes_gestores, tels_gestores):
                    nome_limpo = formatar_nome_proprio(nome)
                    # Garante que funciona mesmo se o clean_numeric não existir no contexto
                    tel_limpo = clean_numeric_string(tel) if 'clean_numeric_string' in globals() else tel.strip()
                    
                    if nome_limpo and tel_limpo:
                        gestores.append({"nome": nome_limpo, "telefone": tel_limpo})
                        
                # Trava 2: Pelo menos 1 gestor válido
                if len(gestores) == 0:
                    raise ValueError("É obrigatório cadastrar pelo menos 1 Gestor com Nome e Telefone válidos.")

                nova_regional = {
                    "id_regional": id_regional,
                    "descricao": descricao,
                    "gestores": gestores,
                    "localidades": localidades,
                    "data_atualizacao": hora_brasil()
                }
                
                # O Upsert agora é 100% seguro graças à inteligência do ID acima
                db.regionais.update_one(
                    {"id_regional": id_regional},
                    {"$set": nova_regional},
                    upsert=True
                )
                
                registrar_log("SALVAR", "REGIONAIS", f"Regional {descricao} salva.", alvo_id=id_regional)
                return redirect(url_for('gerenciar_regionais', success=f"Regional <strong>{id_regional} - {descricao}</strong> salva com sucesso!"))
            
        except ValueError as ve:
            return redirect(url_for('gerenciar_regionais', error=str(ve)))
        except Exception as e:
            return redirect(url_for('gerenciar_regionais', error=f"Erro interno ao processar: {e}"))

    regionais = list(db.regionais.find().sort("id_regional", 1))
    return render_template('admin_regionais.html', regionais=regionais)


# --- Rotas de Colaborador ---
@app.route('/cadastro_colaborador', methods=['GET'])
@login_required
def cadastro_colaborador():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))
        
    db_status = g.db_status
    form_data_erro = session.pop('form_data', None)
    
    active_view = request.args.get('view', 'novo')
    search_term = request.args.get('query', '').strip()
    id_colaborador_edicao = request.args.get('id_colaborador', None) 
    filtro_regional = request.args.get('regional', 'todas') # Captura o filtro da URL
    
    colaborador_edicao = None 
    colaboradores_lista = []
    regionais_lista = [] # Nova lista para carregar as regionais no HTML
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

    # CORREÇÃO DE INDENTAÇÃO AQUI: Este elif deve estar alinhado com o 'if form_data_erro:'
    elif active_view == 'alterar' and id_colaborador_edicao and db_status:
        try:
            id_colaborador_int = int(id_colaborador_edicao)
            colaborador_edicao = db.colaboradores.find_one({'id_colaborador': id_colaborador_int})
            
            if colaborador_edicao:
                # --- BLINDAGEM CONTRA "HACKERS" DE URL ---
                reg_colab = int(colaborador_edicao.get('id_regional', 1))
                if session.get('nivel', 0) < 4 and reg_colab != int(session.get('id_regional', 1)):
                    return redirect(url_for('cadastro_colaborador', view='listar', error="🔒 Você não tem permissão para acessar os dados de um colaborador de outra regional."))
                # ----------------------------------------
                
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
            # 1. Busca todas as regionais para o <select> do HTML
            regionais_cursor = db.regionais.find({}).sort("id_regional", pymongo.ASCENDING)
            regionais_lista = list(regionais_cursor)
            
            # 2. TRAVA DE VISÃO (Base Query)
            # Define o que o usuário pode ver na listagem e na busca
            base_query = {}
            if session.get('nivel', 0) < 4:
                # Nível < 4: Só vê a própria regional
                base_query['id_regional'] = session.get('id_regional', 1) 
            elif filtro_regional != 'todas':
                # Nível 4: Filtrou por uma regional específica
                try:
                    base_query['id_regional'] = int(filtro_regional)
                except ValueError:
                    pass

            # Conta o total respeitando a trava de visão
            total_colaboradores = db.colaboradores.count_documents(base_query)
            
            if active_view == 'listar':
                colaboradores_cursor = db.colaboradores.find(base_query).sort("nick", pymongo.ASCENDING)
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
                
                # 3. Mescla a busca textual com a Trava de Visão Regional
                final_query = {'$and': [base_query, query_filter]} if base_query else query_filter
                
                colaboradores_cursor = db.colaboradores.find(final_query)
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
        'regionais_lista': regionais_lista, # Novo: Passa regionais pro Frontend
        'filtro_regional': filtro_regional, # Novo: Mantém estado do select
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

    nivel_solicitado = int(request.form.get('nivel', 1))
    nivel_logado = session.get('nivel', 0)
    regional_logada = session.get('id_regional', 1)

    # 1. TRAVAS DE SEGURANÇA HIERÁRQUICA
    if nivel_solicitado == 4 and nivel_logado != 4:
        return redirect(url_for('cadastro_colaborador', error="Apenas um Administrador Master pode criar ou promover alguém ao Nível Master."))

    if nivel_logado < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Nível 3 Requerido."))

    id_colaborador_edicao = request.form.get('id_colaborador_edicao') 

    try:
        default_colab_config = { "nome_colaborador": True, "nick": True, "telefone": True, "cpf": False, "cidade": False, "chave_pix": True, "senha": True, "nivel": True, "comissao": True }
        campos_config = g.parametros_globais.get('tipo_cadastro_colaborador', default_colab_config)

        # Captura dos campos
        nome_colaborador = formatar_nome_proprio(request.form.get('nome_colaborador'))
        nick = formatar_nome_proprio(request.form.get('nick'))
        telefone = clean_numeric_string(request.form.get('telefone'))
        cpf_raw = request.form.get('cpf')
        cidade = format_title_case(request.form.get('cidade'))
        chave_pix = request.form.get('chave_pix', '').strip().lower()
        confirma_chave_pix = request.form.get('confirma_chave_pix', '').strip().lower()
        senha = request.form.get('senha')
        confirma_senha = request.form.get('confirma_senha') 
        nivel = nivel_solicitado
        comissao = int(request.form.get('comissao', g.parametros_globais.get('comissao_padrao', 20)))
        
        # =========================================================
        # 2. BLINDAGEM REGIONAL E LOGS (Unificado e Corrigido)
        # =========================================================
        id_regional_str = request.form.get('id_regional', '').strip()
        
        # Blindagem contra vazios ou 'None'
        if not id_regional_str or id_regional_str == 'None':
            id_regional = int(session.get('id_regional', 1))
        else:
            try:
                id_regional = int(id_regional_str)
            except ValueError:
                id_regional = int(session.get('id_regional', 1))

        regional_logada_segura = int(session.get('id_regional', 1))
        nivel_logado_seguro = int(session.get('nivel', 0))
           
        # Nível 3 NÃO PODE criar/editar usuários de outra regional. 
        # Nível 4 é livre.
        if nivel_logado_seguro < 4 and id_regional != regional_logada_segura:
            raise ValueError(f"Acesso Negado. Você só pode gerenciar colaboradores da sua própria regional (ID: {regional_logada_segura}).")
        # =========================================================
        
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
                except:
                    pass
            
            # 3. Executa a busca
            colaborador_existente = db.colaboradores.find_one(query_pix_colab)
            
            if colaborador_existente:
                nick_encontrado = colaborador_existente.get('nick', 'Desconhecido')
                raise ValueError(f"A Chave PIX '{chave_pix}' já está em uso pelo colaborador: {nick_encontrado}.")

        # ESTRUTURA DO DOCUMENTO
        dados_colaborador = {
            "nome_colaborador": nome_colaborador,
            "nick": nick,
            "telefone": telefone,
            "cpf": clean_numeric_string(cpf_raw),
            "cidade": cidade,
            "chave_pix": chave_pix,
            "nivel": nivel, 
            "comissao": comissao,
            "limite_credito": limite_credito,
            "id_regional": id_regional  
        }        

        if "senha" in campos_config and senha:
            if senha != confirma_senha:
                 raise ValueError("As senhas digitadas não conferem.")
            senha_limpa = senha.strip() 
            hashed_password = bcrypt.hashpw(senha_limpa.encode('utf-8'), bcrypt.gensalt())
            dados_colaborador['senha'] = hashed_password.decode('utf-8')
        
        # GRAVAÇÃO
        if id_colaborador_edicao:
            # Edição
            id_colaborador_int = int(id_colaborador_edicao)
            
            # 3. TRAVA DE ANTI-SUICÍDIO (Nível 4)
            if id_colaborador_int == session.get('id_colaborador'):
                if nivel < 4 and nivel_logado == 4 and db.colaboradores.count_documents({'nivel': 4}) == 1:
                    raise ValueError("Você é o ÚNICO Administrador Master do sistema. Promova outro usuário ao Nível 4 antes de se rebaixar.")
                
                # Mantém a trava antiga do Nível 3 para retrocompatibilidade
                if nivel < 3 and nivel_logado == 3 and db.colaboradores.count_documents({'nivel': 3}) == 1:
                    raise ValueError("Você é o único administrador. Não pode rebaixar seu próprio nível.")
            
            if not senha and 'senha' in dados_colaborador: 
                del dados_colaborador['senha']
                 
            db.colaboradores.update_one({'id_colaborador': id_colaborador_int}, {'$set': dados_colaborador})
            success_msg = f"Colaborador {nick} atualizado com sucesso na Regional {id_regional}!"
            
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
            success_msg = f"Colaborador {nick} salvo! ID: {novo_id_colaborador_int} (Regional {id_regional})"
        
        return redirect(url_for('cadastro_colaborador', success=success_msg, view='listar'))

    except ValueError as e:
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_colaborador_edicao else 'novo'
        redirect_args = {'error': f"Erro de Validação: {e}", 'view': view_redirect}
        if id_colaborador_edicao: redirect_args['id_colaborador'] = id_colaborador_edicao
        return redirect(url_for('cadastro_colaborador', **redirect_args))
        
    except Exception as e:
        print(f"ERRO CRÍTICO colab: {e}")
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

    error = request.args.get('error')
    success = session.pop('success_message', None) 
    print_data = session.pop('print_data', None)

    id_cliente_final = None
    cliente_encontrado = None
    id_colaborador_indicacao = 0
    custo = 0.00
    
    id_evento_param = request.args.get('id_evento')
    id_cliente_busca = request.args.get('id_cliente_busca', '').strip()
    quantidade_param = request.args.get('quantidade') 
    
    quantidade = int(quantidade_param) if quantidade_param and str(quantidade_param).isdigit() else 0
    
    #eventos_ativos_cursor = db.eventos.find({'status': 'ativo'}).sort('data_evento', pymongo.ASCENDING)   <<< troca aqui

    # 1. Busca no banco ordenando por Data e, em seguida, por Hora (Cronológico Perfeito)
    eventos_ativos_cursor = db.eventos.find({'status': 'ativo'}).sort([
        ('data_evento', pymongo.ASCENDING),
        ('hora_evento', pymongo.ASCENDING)
    ])

    # 2. Converte o cursor do Mongo para uma lista manipulável do Python
    eventos_lista = list(eventos_ativos_cursor)

    # 3. Isola a "Rodada Especial" (remove da lista temporariamente)
    evento_especial = None
    for i in range(len(eventos_lista)):
        if eventos_lista[i].get('tipo_de_evento') == 'Especial':
            evento_especial = eventos_lista.pop(i)
            break # Achou o especial, para de procurar

    # 4. Encaixa a Rodada Especial na posição desejada (index 2 = 3º item)
    if evento_especial:
        # Se houver menos de 2 eventos normais, ele entra no final sem dar erro
        index_insercao = min(2, len(eventos_lista))
        eventos_lista.insert(index_insercao, evento_especial)

    eventos_enriquecidos = []
    selected_event = None

    param_doc_global = {}
    if g.db_status:
        try:
            param_doc_global = db.parametros.find_one({}) or {}
        except Exception:
            pass
    
    for evento in eventos_lista:   
    
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
            id_colaborador_indicacao  = cliente.get('id_colaborador')

            # --- NOVO: Prepara o saldo para exibição ---
            val_decimal = cliente_encontrado.get('saldo_atual', 0.0)
            # Usa safe_float ou converte direto se safe_float não estiver no escopo local
            if isinstance(val_decimal, Decimal128):
                cliente_encontrado['saldo_float'] = float(str(val_decimal))
            else:
                cliente_encontrado['saldo_float'] = float(val_decimal)
            
            valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
            custo = valor_unitario * quantidade
        
    elif selected_event:
        valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
        custo = valor_unitario * quantidade
   
    # ========================================================
    # --- NOVO: BUSCA AS 5 ÚLTIMAS VENDAS DO OPERADOR ATUAL ---
    # ========================================================
    ultimas_vendas = []
    if selected_event and g.db_status:
        id_evento_int = selected_event.get('id_evento')
        nome_colecao_venda = f"vendas{id_evento_int}"
        id_colaborador_logado = session.get('id_colaborador')
        
        #print(f"\n[DEBUG - ÚLTIMAS VENDAS] Iniciando busca para evento: {id_evento_int}")
        #print(f"[DEBUG - ÚLTIMAS VENDAS] Operador Logado na Sessão: '{id_colaborador_logado}' (Tipo: {type(id_colaborador_logado)})")
        
        if nome_colecao_venda in db.list_collection_names():
            try:
                # 1. Trata o ID (Converte para int se possível, para cobrir os dois mundos)
                try:
                    id_colab_int = int(id_colaborador_logado)
                except (ValueError, TypeError):
                    id_colab_int = id_colaborador_logado
                
                # 2. Monta a Query Inteligente
                # Cobre tanto o 'id_vendedor' (operador do caixa) quanto o 'id_colaborador',
                # e busca tanto pelo número (Int) quanto pelo texto (String)
                query_ultimas = {
                    '$or': [
                        {'id_vendedor': {'$in': [id_colaborador_logado, id_colab_int, str(id_colab_int)]}},
                        {'id_colaborador': {'$in': [id_colaborador_logado, id_colab_int, str(id_colab_int)]}}
                    ]
                }
                
                #print(f"[DEBUG - ÚLTIMAS VENDAS] Query montada: {query_ultimas}")
                
                # 3. Executa a busca
                cursor = db[nome_colecao_venda].find(query_ultimas).sort('data_venda', pymongo.DESCENDING).limit(5)
                
                for v in cursor:
                    v['valor_total_float'] = safe_float(v.get('valor_total'))
                    ultimas_vendas.append(v)
                    
                #print(f"[DEBUG - ÚLTIMAS VENDAS] SUCESSO! Encontradas {len(ultimas_vendas)} vendas.")
                #for uv in ultimas_vendas:
                    #print(f"  -> Venda: {uv.get('id_venda')} | Cliente: {uv.get('nome_cliente')} | Cartelas: {uv.get('numero_inicial')} a {uv.get('numero_final')} | R$ {uv.get('valor_total_float')}")
                #print("------------------------------------------------------------\n")
                    
            except Exception as e:
                #print(f"[DEBUG - ÚLTIMAS VENDAS] ❌ ERRO CRÍTICO: {e}")
                traceback.print_exc()
        #else:
            #print(f"[DEBUG - ÚLTIMAS VENDAS] A coleção '{nome_colecao_venda}' ainda não existe (Nenhuma venda neste evento).")

    Qparametros = db.parametros.find_one({}) or {} 
    
    limite_auto = Qparametros.get('limite_impressao_auto_vendas', 10)

    return render_template('venda.html', 
                           db_status=g.db_status,
                           error=error,
                           success=success,
                           print_data=print_data,
                           eventos=eventos_enriquecidos,
                           selected_event=selected_event,
                           id_cliente_final=id_cliente_final,
                           cliente_busca=id_cliente_busca,
                           id_colaborador_indicacao = id_colaborador_indicacao,
                           cliente_encontrado=cliente_encontrado,
                           quantidade=quantidade,
                           custo=custo,
                           ultimas_vendas=ultimas_vendas,
                           limite_impressao_auto_vendas=limite_auto,
                           g=g)


@app.route('/processar_venda', methods=['POST'])
@login_required
def processar_venda():
    """
    Processo Crítico de Venda - ATUALIZADO para arquitetura Multirregional.
    INCLUI TRAVA DE SEGURANÇA DE STATUS DO EVENTO.
    MOTOR ATÓMICO (Sem Locks).
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

    # =====================================================================
    # MOTOR DE IDENTIFICAÇÃO DE COMISSÃO (FASE 4 - INT32 SEGURO)
    # =====================================================================
    cliente_db = db.clientes.find_one({'id_cliente': id_cliente_final}) if id_cliente_final > 0 else None

    if cliente_db:
        # Se achou o cliente, a comissão é do DONO do cliente. (Garante Int32)
        id_colab_comissao = int(cliente_db.get('id_colaborador', 0))
        nick_colab_comissao = cliente_db.get('nick_colaborador', 'N/A')
    else:
        # Venda balcão (sem cliente), a comissão é do OPERADOR que está logado.
        id_colab_comissao = int(session.get('id_colaborador', 0))
        nick_colab_comissao = session.get('nick', 'N/A')
    # =====================================================================

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
        
    tipo_cartela = int(selected_event.get('tipo_de_cartela', 15))
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

    # NOVO: IDENTIFICAÇÃO DA REGIONAL DO VENDEDOR LOGADO (OPERADOR DE CAIXA)
    # Tenta puxar da sessão primeiro por performance, se não, busca no banco
    regional_operador = session.get('id_regional')
    chave_pix_colaborador = "Consulte o Colaborador"
    
    try:
        if colaborador_id != 'N/A':
            colab_doc = db.colaboradores.find_one({'id_colaborador': int(colaborador_id)})
            if colab_doc:
                chave_pix_colaborador = colab_doc.get('chave_pix', chave_pix_colaborador)
                if not regional_operador:
                    regional_operador = colab_doc.get('id_regional', 1) # Fallback seguro
    except Exception as e:
        print(f"Erro ao buscar PIX/Regional do colaborador: {e}")
        regional_operador = 1 # Se falhar miseravelmente, assume matriz (1)

    id_venda_formatado = None
    numero_inicial_atual = None
    numero_final_atual = None
    numero_inicial2_atual = 0 
    numero_final2_atual = 0 
    id_colaborador_indicacao = 0
    
    # ==============================================================================
    # 🚀 MOTOR DE VENDAS ATÓMICO (SEM LOCKS EM PYTHON)
    # ==============================================================================
    
    try:
        novo_id_venda_int = get_next_global_sequence(db, 'id_vendas_global')
        if novo_id_venda_int is None:
            raise Exception("Falha ao gerar o ID sequencial da venda.")
        id_venda_formatado = f"V{novo_id_venda_int:05d}" 

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
        
        # NOVO: CARIMBO REGIONAL NA COLEÇÃO DE VENDAS PRINCIPAL
        registro_venda = {
            "id_venda": id_venda_formatado,
            "id_evento_ObjectId": id_evento_mongo, 
            "id_evento": id_evento_int_para_controle, 
            "descricao_evento": selected_event.get('descricao'),
            "id_regional": regional_operador, # <-- O CARIMBO AQUI
            "id_cliente": id_cliente_final, 
            "nome_cliente": cliente_doc.get('nick'),
            "telefone_cliente": cliente_doc.get('telefone',''),
            "id_colaborador":  id_colab_comissao,
            "nick_colaborador": nick_colaborador,
            "id_vendedor": colaborador_id,
            "data_venda": hora_brasil(),
            "tipo_cartela": tipo_cartela,  
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
        
        db.clientes.update_one(
            {"id_cliente": id_cliente_final}, 
            {"$set": {"data_ultimo_compra": hora_brasil()}}
        )

        db[nome_colecao_venda].insert_one(registro_venda)

        db.eventos.update_one(
            {"id_evento": id_evento_int_para_controle},
            {"$inc": {"valor_pendente_telemovel": float(valor_total_atual)}}
        )
       
        # 💸 CHAMADA DA NOVA FUNÇÃO FINANCEIRA BLINDADA
        valor_debito = 0.0
        saldo_verificacao = safe_float(cliente_doc.get('saldo_atual', 0.0))
        
        if saldo_verificacao > 0:
            desconto_real = min(abs(valor_total_atual), saldo_verificacao)
            valor_debito = -abs(desconto_real)
        
        if valor_debito != 0.0:
            desc_transacao = f"Compra de {quantidade} -( {colaborador_id}: {nick_colaborador} )- {selected_event.get('descricao')}"
            # O registrar_transacao_cliente que criamos na fase do terminal já processa o Livro Razão
            registrar_transacao_cliente(
                db=db, # Assumindo que mudou o nome do param ou db_vendas=db
                id_cliente=id_cliente_final,
                valor=valor_debito,
                tipo='compra_cartela', 
                descricao=desc_transacao,
                id_evento=id_evento_int_para_controle,
                id_venda=id_venda_formatado
            )

        # 1. Vendedor que está a OPERAR o balcão (Comissão Direta)
        taxa_operador = g.parametros_globais.get('perc_venda_direta', 15.0) 
        registrar_comissao_vendedor(
            db=db, 
            id_colaborador=colaborador_id, 
            valor=valor_total_atual * (taxa_operador / 100), # CORREÇÃO: Usando valor_total_atual
            tipo='vd',
            id_evento=id_evento_int_para_controle,
            id_venda=id_venda_formatado,
            taxa_aplicada=taxa_operador,
            descricao=f"Comissão Direta Venda {id_venda_formatado}"
            # Opcional se for carimbar na comissão tbm: id_regional=regional_operador
        )

        # 2. Vendedor que INDICOU o cliente (Comissão Indireta)
        id_indicador = cliente_doc.get('id_colaborador')
        if id_indicador and int(id_indicador) != int(colaborador_id):
            taxa_indicador = g.parametros_globais.get('perc_venda_indireta_b', 10.0) 
            registrar_comissao_vendedor(
                db=db,
                id_colaborador=id_indicador,
                valor=valor_total_atual * (taxa_indicador / 100), # CORREÇÃO: Usando valor_total_atual
                tipo='ind_b',
                id_evento=id_evento_int_para_controle,
                id_venda=id_venda_formatado,
                taxa_aplicada=taxa_indicador,
                descricao=f"Comissão Indireta (Cliente Indicado) Venda {id_venda_formatado}"
            )
     
    except Exception as e:
        print(f"{log_prefix} LOG 5 (ERRO INTERNO): Erro crítico durante a transação: {e}")
        traceback.print_exc()
        error_redirect_kwargs['error'] = f"Erro interno no DB: Falha ao gravar a transação."
        error_redirect_kwargs['quantidade'] = quantidade

        # 1. Montamos a URL do protocolo do App Bluetooth Print
        # Apontando para a nova rota JSON que criamos (api_venda_bluetooth_json)
        host = request.host_url.rstrip('/')
        url_api_json = (
            f"{host}/api/venda_bluetooth_json?"
            f"numero_inicial={numero_inicial_atual}&numero_final={numero_final_atual}"
            f"&id_evento={id_evento_int_para_controle}&nome_cliente={cliente_doc.get('nick')}"
        )

        # 2. Criamos o link "mágico" e salvamos na sessão
        session['url_bluetooth_print'] = f"my.bluetoothprint.scheme://{url_api_json}"

        # --- [FIM DA ADIÇÃO] -

        return redirect(url_for('nova_venda', **error_redirect_kwargs))

    # ==============================================================================
    # FIM DO MOTOR DE VENDAS ATÓMICO
    # ==============================================================================

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
        
        session['success_message'] = success_msg 
        session['print_data'] = { 
            'id_evento': id_evento_int_para_controle,
            'nome_cliente': cliente_doc.get('nick'),
            'numero_inicial': numero_inicial_atual,
            'numero_final': numero_final_atual,
            'tipo_cartela': tipo_de_cartela
        }
        
        redirect_kwargs = {
            'id_evento': id_evento_string,
            'quantidade': '',
            'id_cliente_busca':  '' 
        }
        return redirect(url_for('nova_venda', **redirect_kwargs))

    except Exception as e:
        print(f"{log_prefix} LOG 7 (ERRO PÓS-VENDA): Erro ao montar comprovante: {e}")
        session['success_message'] = (
            f"<strong>VENDA {id_venda_formatado} GRAVADA!</strong><br>"
            f"Ocorreu um erro ao gerar o comprovante completo, mas a venda foi registrada."
        )
        return redirect(url_for('nova_venda', id_evento=id_evento_string))


@app.route('/processar_venda_combo_quantidade', methods=['POST'])
@login_required
def processar_venda_combo_quantidade():
    """
    Processo de Venda COMBO por QUANTIDADE (Etapa 1 e Base da Etapa 2).
    Distribui as cartelas de forma intercalada entre o evento Pai e os Filhos.
    Utiliza insert_many para otimização de I/O no banco.
    """
    db = get_vendas_db()
    if db is None: 
        return redirect(url_for('venda_lite.nova_venda_lite', error="DB Offline. Transação Crítica Falhou."))

    id_evento_string = request.form.get('id_evento') 
    id_cliente_final_str = request.form.get('id_cliente_final') 
    quantidade_str = request.form.get('quantidade', '0')
    
    # 🚀 GANCHO PARA A ETAPA 2 (Será ativado futuramente via checkbox no Front-end)
    modo_aleatorio = request.form.get('modo_aleatorio') == 'true'
    
    log_prefix = f"[COMBO QTD REQ_COLAB:{session.get('nick', 'N/A')}_CLI:{id_cliente_final_str}_QTD:{quantidade_str}]"
    
    error_redirect_kwargs = {
        'id_evento': id_evento_string,
        'id_cliente_busca': f"CLI{id_cliente_final_str}" if id_cliente_final_str else '',
    }

    try:
        id_cliente_final = int(id_cliente_final_str)
        quantidade_combos = int(quantidade_str)
        if quantidade_combos <= 0: raise ValueError("Quantidade de combos deve ser positiva.")
    except (TypeError, ValueError) as e:
        error_redirect_kwargs['error'] = f"Dados inválidos: {e}"
        return redirect(url_for('venda_lite.nova_venda_lite', error_redirect_kwargs))

    # =====================================================================
    # PREPARAÇÃO E VALIDAÇÕES (CLIENTE E COMISSÃO)
    # =====================================================================
    cliente_db = db.clientes.find_one({'id_cliente': id_cliente_final}) if id_cliente_final > 0 else None
    if cliente_db:
        id_colab_comissao = int(cliente_db.get('id_colaborador', 0))
        nick_colab_comissao = cliente_db.get('nick_colaborador', 'N/A')
    else:
        id_colab_comissao = int(session.get('id_colaborador', 0))
        nick_colab_comissao = session.get('nick', 'N/A')

    id_evento_mongo = try_object_id(id_evento_string)
    evento_pai = db.eventos.find_one({'_id': id_evento_mongo})
    
    if not evento_pai or not cliente_db:
        error_redirect_kwargs['error'] = "Evento ou Cliente não encontrado."
        return redirect(url_for('venda_lite.nova_venda_lite', error_redirect_kwargs))

    status_atual = evento_pai.get('status', '').lower()
    if status_atual != 'ativo':
        error_redirect_kwargs['error'] = "⛔ VENDA CANCELADA! O evento principal não está Ativo."
        return redirect(url_for('venda_lite.nova_venda_lite', error_redirect_kwargs))

    # =====================================================================
    # MATEMÁTICA E MAPEAMENTO DA FAMÍLIA (COMBO)
    # =====================================================================
    id_evento_pai_int = evento_pai.get('id_evento') 
    limite_maximo_cartelas = int(evento_pai.get('numero_maximo', 72000))
    valor_unitario = safe_float(evento_pai.get('valor_de_venda', 0.00))
    unidade_de_venda = int(evento_pai.get('unidade_de_venda', 15))
    tipo_cartela = int(evento_pai.get('tipo_de_cartela', 15))
    
    # Monta a família inteira: Pai na posição 0, Filhos nas posições seguintes
    filhos = list(db.eventos.find({'id_evento_principal_combo': id_evento_pai_int}).sort('id_evento', 1))
    eventos_combo = [evento_pai] + filhos
    
    qtd_eventos = len(eventos_combo)
    tamanho_do_combo_completo = qtd_eventos * unidade_de_venda
    total_cartelas_consumidas = quantidade_combos * tamanho_do_combo_completo
    valor_total_atual = valor_unitario * quantidade_combos

    colaborador_id = session.get('id_colaborador', 'N/A')
    nick_colaborador = session.get('nick', 'Colaborador') 
    regional_operador = session.get('id_regional', 1)
    
    id_venda_formatado = None
    
    # ==============================================================================
    # 🚀 MOTOR DE VENDAS (ETAPA 1: SEQUENCIAL INTERCALADA / BATCH INSERT)
    # ==============================================================================
    try:
        # 1. Gera ID único da Transação (Uma única venda engloba todo o Combo)
        novo_id_venda_int = get_next_global_sequence(db, 'id_vendas_global')
        if novo_id_venda_int is None: raise Exception("Falha ao gerar o ID da venda.")
        id_venda_formatado = f"VC{novo_id_venda_int:05d}" # VC = Venda Combo

        # 2. Puxa o ponteiro numérico global (Reservando todo o bloco necessário)
        numero_base_banco = get_next_bilhete_sequence(
            db, id_evento_pai_int, 'inicial_proxima_venda', 
            total_cartelas_consumidas, limite_maximo_cartelas
        )
        if numero_base_banco is None: raise Exception("Falha de concorrência na numeração.")

        if numero_base_banco == 1: 
            numero_base_banco = int(evento_pai.get('numero_inicial', 1))
            db.controle_venda.update_one(
                {'id_evento': id_evento_pai_int},
                {'$set': {'inicial_proxima_venda': numero_base_banco + total_cartelas_consumidas}}
            )

        # 3. Base do Documento (Comum a todos os kits)
        registro_base = {
            "id_venda": id_venda_formatado,
            "id_regional": regional_operador,
            "id_cliente": id_cliente_final, 
            "nome_cliente": cliente_db.get('nick'),
            "telefone_cliente": cliente_db.get('telefone',''),
            "id_colaborador": id_colab_comissao,
            "nick_colaborador": nick_colaborador,
            "id_vendedor": colaborador_id,
            "data_venda": hora_brasil(),
            "tipo_cartela": tipo_cartela,  
            "quantidade_unidades": 1, # Cada linha fatiada representa 1 unidade do combo daquele evento
            "numero_inicial2": 0,
            "numero_final2": 0,
            "quantidade_cartelas": unidade_de_venda,
            "valor_unitario": Decimal128("0.00"), # Financeiro concentrado no Pai (ou rateado)
            "valor_total": Decimal128("0.00"),
            "origem": "terminal_combo_qtd",
            "id_transacao_combo": id_venda_formatado
        }

        # 4. Distribuição Fatiada e Gravação em Lote
        for indice_evento, evento_atual in enumerate(eventos_combo):
            id_evt = evento_atual['id_evento']
            nome_colecao_venda = f"vendas{id_evt}"
            deslocamento_do_evento = indice_evento * unidade_de_venda
            documentos_inserir = []

            for indice_combo in range(quantidade_combos):
                # ETAPA 2 ENTRARÁ AQUI NO FUTURO
                if modo_aleatorio:
                    pass 
                else:
                    # ETAPA 1: Matemática Sequencial
                    salto_do_combo = indice_combo * tamanho_do_combo_completo
                    num_inicial = numero_base_banco + salto_do_combo + deslocamento_do_evento
                    num_final = num_inicial + unidade_de_venda - 1
                
                # Prepara a fatia
                nova_fatia = registro_base.copy()
                nova_fatia['id_evento_ObjectId'] = evento_atual.get('_id')
                nova_fatia['id_evento'] = id_evt
                nova_fatia['descricao_evento'] = evento_atual.get('descricao')
                nova_fatia['numero_inicial'] = num_inicial
                nova_fatia['numero_final'] = num_final
                
                # Se for o Pai e for o primeiro kit do loop, carrega o valor financeiro total
                if indice_evento == 0:
                    # A quantidade de unidades já é 1 (herdado do registro_base)
                    nova_fatia['valor_unitario'] = Decimal128(str(valor_unitario))
                    nova_fatia['valor_total'] = Decimal128(str(valor_unitario))

                documentos_inserir.append(nova_fatia)

            # Executa o BATCH INSERT (Otimização máxima)
            if documentos_inserir:
                db[nome_colecao_venda].insert_many(documentos_inserir)
                
            # Sincroniza o ponteiro de todos os irmãos para ficarem alinhados com o Pai
            novo_ponteiro_geral = numero_base_banco + total_cartelas_consumidas 

        # ==========================================================
        # 🚀 SINCRONIZAÇÃO DO PONTEIRO (FORA DO LOOP)
        # ==========================================================
        if not modo_aleatorio:
            # Pega o ponteiro inicial e soma o bloco total do combo
            novo_ponteiro_geral = numero_base_banco + total_cartelas_consumidas
            # Cria uma lista apenas com os números dos IDs de todos os eventos (Pai e Filhos)
            ids_eventos_atualizar = [e['id_evento'] for e in eventos_combo]
            
            # Atualiza o controle de todos de uma única vez!
            db.controle_venda.update_many(
                {'id_evento': {'$in': ids_eventos_atualizar}},
                {'$set': {'inicial_proxima_venda': novo_ponteiro_geral}}
            )

        # 5. Financeiro e Comissões
        db.clientes.update_one(
            {"id_cliente": id_cliente_final}, 
            {"$set": {"data_ultimo_compra": hora_brasil()}}
        )
        
        db.eventos.update_one(
            {"id_evento": id_evento_pai_int},
            {"$inc": {"valor_pendente_telemovel": float(valor_total_atual)}}
        )

        valor_debito = 0.0
        saldo_verificacao = safe_float(cliente_db.get('saldo_atual', 0.0))
        if saldo_verificacao > 0:
            desconto_real = min(abs(valor_total_atual), saldo_verificacao)
            valor_debito = -abs(desconto_real)
        
        if valor_debito != 0.0:
            desc_transacao = f"Compra Combo QTD {quantidade_combos} -( {colaborador_id}: {nick_colaborador} )- {evento_pai.get('descricao')}"
            registrar_transacao_cliente(
                db=db, id_cliente=id_cliente_final, valor=valor_debito,
                tipo='compra_cartela', descricao=desc_transacao,
                id_evento=id_evento_pai_int, id_venda=id_venda_formatado
            )

        # Comissões
        taxa_operador = g.parametros_globais.get('perc_venda_direta', 15.0) 
        registrar_comissao_vendedor(
            db=db, id_colaborador=colaborador_id, valor=valor_total_atual * (taxa_operador / 100),
            tipo='vd', id_evento=id_evento_pai_int, id_venda=id_venda_formatado,
            taxa_aplicada=taxa_operador, descricao=f"Comissão Direta Venda Combo {id_venda_formatado}"
        )

        id_indicador = cliente_db.get('id_colaborador')
        if id_indicador and int(id_indicador) != int(colaborador_id):
            taxa_indicador = g.parametros_globais.get('perc_venda_indireta_b', 10.0) 
            registrar_comissao_vendedor(
                db=db, id_colaborador=id_indicador, valor=valor_total_atual * (taxa_indicador / 100),
                tipo='ind_b', id_evento=id_evento_pai_int, id_venda=id_venda_formatado,
                taxa_aplicada=taxa_indicador, descricao=f"Comissão Indireta Venda Combo {id_venda_formatado}"
            )

    except Exception as e:
        print(f"{log_prefix} ERRO CRÍTICO (COMBO QTD): {e}")
        import traceback; traceback.print_exc()
        error_redirect_kwargs['error'] = "Erro interno no DB: Falha ao gravar a transação Combo."
        return redirect(url_for('venda_lite.nova_venda_lite', error_redirect_kwargs))

    # ==============================================================================
    # 🚀 MONTAGEM DO RECIBO
    # ==============================================================================
    try:
        nome_sala = g.parametros_globais.get('nome_sala', '')
        data_evento_str = evento_pai.get('data_evento', 'N/A')
        hora_evento_str = evento_pai.get('hora_evento', 'N/A')
        
        # HTML dos fatiamentos
        html_fatiamento = ""
        for i_combo in range(quantidade_combos):
            html_fatiamento += f"<div style='margin-top: 5px; border-top: 1px dashed #ccc;'>"
            html_fatiamento += f"<strong>Combo {i_combo + 1}:</strong><br>"
            salto = i_combo * tamanho_do_combo_completo
            for i_evento in range(qtd_eventos):
                n_ini = numero_base_banco + salto + (i_evento * unidade_de_venda)
                n_fim = n_ini + unidade_de_venda - 1
                prefixo = "PAI" if i_evento == 0 else f"F{i_evento}"
                html_fatiamento += f"<span style='font-size: 0.85rem;'>[{prefixo}] {n_ini} a {n_fim}</span><br>"
            html_fatiamento += "</div>"

        http_apk = g.parametros_globais.get('http_apk', '')
        link_final = f"{http_apk}?idcliente={id_cliente_final}"
        
        success_msg = (
            f"<strong>✅ COMBO COMPRADO COM SUCESSO</strong><br>"
            f"  <span style='font-size: 1.2rem; color: #B91C1C;'>{nome_sala}</span><br>"
            f"</strong>     >  {id_venda_formatado}  < </strong><br>"
            f"----------------------------<br>"
            f"Cliente: <strong>{cliente_db.get('nick')}</strong><br>"
            f"Combo: {evento_pai.get('descricao')}<br>"
            f"<strong>Data: {data_evento_str} às {hora_evento_str}</strong><br>"
            f"----------------------------<br>"
            f"{html_fatiamento}"
            f"----------------------------<br>"
            f"Qtd Combos: <strong>{quantidade_combos}</strong><br>"
            f"  VALOR TOTAL: <span style='font-size: 1.2rem; color: #B91C1C;'>R$ {valor_total_atual:.2f}</span><br>"
            f"<br>"
            f"CLIQUE NO <strong>LINK</strong> PARA ACESSAR<br>"
            f"<strong> {link_final} </strong>"
        )
        
        session['success_message'] = success_msg 
        
        return redirect(url_for('venda_lite.nova_venda_lite', id_evento=id_evento_string))

    except Exception as e:
        print(f"{log_prefix} Erro ao montar comprovante Combo: {e}")
        session['success_message'] = f"<strong>VENDA {id_venda_formatado} GRAVADA!</strong> (Erro no recibo visual)."
        return redirect(url_for('venda_lite.nova_venda_lite', id_evento=id_evento_string))



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
    INCLUI 'id_colaborador' PARA TRAVA DE SEGURANÇA.
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
            # O '^' diz ao Banco: "Busque apenas se COMEÇAR com isso"
            regex_term = re.compile(f"^{re.escape(termo)}", re.IGNORECASE)
            query_filter = {'nome_cliente': {'$regex': regex_term}}
            
        else: # Padrão: 'nick'
            regex_term = re.compile(f"^{re.escape(termo)}", re.IGNORECASE)
            query_filter = {'nick': {'$regex': regex_term}}
            
        clientes_cursor = db.clientes.find(
            query_filter, 
            # 🚀 CORREÇÃO: Adicionado 'id_colaborador': 1 para o Mongo devolver este campo
            {'id_cliente': 1, 'nome_cliente': 1, 'nick': 1, 'cidade': 1, 'id_colaborador': 1}
        ).limit(10) # Mantém o limite para ser rápido
        
        resultados = []
        for cli in clientes_cursor:
            resultados.append({
                'id': cli.get('id_cliente'),
                'nome': cli.get('nome_cliente'),
                'nick': cli.get('nick'),
                'id_colaborador': cli.get('id_colaborador', 0), # 🚀 Garante que vai como 0 se não existir
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
    if db is None: return redirect(url_for('login')) 

    db_status = g.db_status
    nivel_usuario = session.get('nivel', 1)
    nome_logado = session.get('nick', 'Colaborador') 
    id_logado = session.get('id_colaborador', 'N/A')
    
    # --- NOVO: CONTEXTO REGIONAL (FASE 4) ---
    id_regional_sessao = session.get('id_regional')
    is_master = (nivel_usuario >= 4)
    # ----------------------------------------
    
    form_data_erro = session.pop('form_data', None)
    active_view = request.args.get('view', 'novo')

    # --- LÓGICA PARA A ABA DE INDICAÇÕES COM NOMES (REGIONALIZADA) ---
    indicacoes_stats = []
    if active_view == 'indicacoes':
        try:
            # 1. Filtro Regional para o Ranking
            match_ranking = {"id_colaborador": {"$gt": 0}}
            if not is_master and id_regional_sessao:
                # O Ranking mostrará apenas colaboradores da mesma regional
                colabs_da_regiao = [c['id_colaborador'] for c in db.colaboradores.find({"id_regional": int(id_regional_sessao)}, {"id_colaborador": 1})]
                match_ranking["id_colaborador"] = {"$in": colabs_da_regiao}

            colaboradores_cursor = db.colaboradores.find({}, {"id_colaborador": 1, "nick": 1})
            mapa_nomes = {c['id_colaborador']: c['nick'] for c in colaboradores_cursor}

            pipeline = [
                {"$match": match_ranking},
                {"$group": {
                    "_id": "$id_colaborador",
                    "total_clientes": {"$sum": 1}
                }},
                {"$sort": {"total_clientes": -1}},
                {"$limit": 50}
            ]
        
            resultados = list(db.clientes.aggregate(pipeline))
        
            for res in resultados:
                id_col = res['_id']
                nome_colab = mapa_nomes.get(id_col, f"ID {id_col}")
            
                indicacoes_stats.append({
                    'id_colaborador': id_col,
                    'nome_colaborador': nome_colab,
                    'total': res['total_clientes']
                })
        except Exception as e:
            print(f"Erro ao gerar ranking: {e}")

    search_term = request.args.get('query', '').strip()
    next_url = request.args.get('next', 'menu_operacoes')
    id_evento_retorno = request.args.get('id_evento') 
    id_cliente_edicao = request.args.get('id_cliente', None)
    
    clientes_lista = []
    total_clientes = 0
    cliente_edicao = None 
    error = request.args.get('error')
    success = request.args.get('success')

    # --- TRAVA DE SEGURANÇA PARA EDIÇÃO (BACKEND) ---
    if active_view == 'alterar' and id_cliente_edicao and db_status:
        try:
            id_cliente_int = int(id_cliente_edicao)
            cliente_edicao = db.clientes.find_one({'id_cliente': id_cliente_int})
            
            if cliente_edicao:
                # Se o cliente pertence a um colaborador de OUTRA regional, Master bloqueia
                dono_cliente = db.colaboradores.find_one({"id_colaborador": cliente_edicao.get('id_colaborador')})
                if not is_master and dono_cliente and dono_cliente.get('id_regional') != id_regional_sessao:
                     return redirect(url_for('cadastro_cliente', view='listar', error="🔒 Acesso Negado: Este cliente pertence a outra regional."))
                
                if '_id' in cliente_edicao: cliente_edicao['_id'] = str(cliente_edicao['_id'])
                cliente_edicao['saldo_float'] = safe_float(cliente_edicao.get('saldo_atual', 0.0))
            else:
                 error = "Cliente não encontrado."
                 active_view = 'listar' 
        except:
            active_view = 'listar'
            
    if db_status:
        try:
            # --- 2. TRAVA DE VISÃO PARA LISTAGEM E CONSULTA ---
            base_query = {}
            if not is_master and id_regional_sessao:
                # O gestor só vê clientes cujos donos (colaboradores) são da mesma regional
                colabs_permitidos = [c['id_colaborador'] for c in db.colaboradores.find({"id_regional": int(id_regional_sessao)}, {"id_colaborador": 1})]
                base_query["id_colaborador"] = {"$in": colabs_permitidos}

            total_clientes = db.clientes.count_documents(base_query)
            filtro_colab = request.args.get('filtro_colab', type=int)     
       
            if active_view == 'listar':
                query_listagem = base_query.copy()
                
                # Filtro existente por colaborador
                if filtro_colab:
                    query_listagem["id_colaborador"] = filtro_colab

                # Filtro por Regional (Apenas para Master)
                filtro_regional = request.args.get('filtro_regional')
                if session.get('nivel', 0) >= 4 and filtro_regional and filtro_regional.isdigit():
                    query_listagem["id_regional"] = int(filtro_regional)

                # Busca ordenada pelo Mongo
                clientes_cursor = db.clientes.find(query_listagem).sort("nick", pymongo.ASCENDING).limit(100)
                clientes_lista = list(clientes_cursor)

            elif active_view == 'consulta' and search_term:
                query_filter = {}
                if search_term.isdigit(): 
                    query_filter = {'id_cliente': int(search_term)}
                else:
                    regex_term = re.compile(re.escape(search_term), re.IGNORECASE)
                    query_filter = {'$or': [{'nome_cliente': {'$regex': regex_term}}, {'nick': {'$regex': regex_term}}]}
                
                # Mescla busca com trava regional
                final_query = {"$and": [base_query, query_filter]} if base_query else query_filter
                
                # 🚀 CORREÇÃO: Adicionada a ordenação também na pesquisa
                clientes_lista = list(db.clientes.find(final_query).sort("nick", pymongo.ASCENDING))

            # 🚀 GARANTIA ALFABÉTICA (Case-Insensitive)
            # Evita que "Zebra" venha antes de "abelha" só por causa da letra maiúscula.
            clientes_lista.sort(key=lambda x: (x.get('nick') or '').lower())

        except Exception as e:
            error = f"Erro ao carregar dados: {e}"

    for cliente in clientes_lista:
        if '_id' in cliente: cliente['_id'] = str(cliente['_id'])
        cliente['saldo_float'] = safe_float(cliente.get('saldo_atual', 0.0))
        for campo_data in ['data_cadastro', 'data_ultimo_compra']:
            if cliente.get(campo_data) and isinstance(cliente[campo_data], datetime):
                cliente[f'{campo_data}_formatada'] = cliente[campo_data].strftime("%d/%m/%Y %H:%M:%S")

    lista_bloqueio = []
    if active_view == 'bloqueio' and db_status:
        config = db.config_bloqueio.find_one({'tipo': 'nicks_proibidos'})
        if config and 'palavras' in config:
            lista_bloqueio = sorted(config['palavras'])

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
        'indicacoes_stats': indicacoes_stats,
        'id_logado': id_logado,  
        'logado': nome_logado,
        'lista_bloqueio': lista_bloqueio
    }
    return render_template('cadastro_cliente.html', **context)

@app.route('/resetar_senha_cliente/<int:id_cliente>', methods=['POST'])
@login_required
def resetar_senha_cliente(id_cliente):
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    # Trava de Segurança
    if session.get('nivel', 1) < 3:
        return redirect(url_for('cadastro_cliente', view='listar', error="⛔ Acesso Negado: Apenas gestores podem resetar senhas."))

    try:
        from werkzeug.security import generate_password_hash
        
        # Gera a nova senha criptografada com a palavra padrão "Senha"
        nova_senha_hash = generate_password_hash("Senha")

        result = db.clientes.update_one(
            {'id_cliente': id_cliente},
            {'$set': {'senha': nova_senha_hash}}
        )

        if result.modified_count > 0 or result.matched_count > 0:
            success_msg = f"Senha do cliente ID CLI{id_cliente} redefinida com sucesso para o padrão: <b>Senha</b>."
            registrar_log("ALTERAR", "CLIENTES", f"Senha resetada para o padrão 'Senha'.", id_cliente)
            return redirect(url_for('cadastro_cliente', view='alterar', id_cliente=id_cliente, success=success_msg))
        else:
            return redirect(url_for('cadastro_cliente', view='listar', error="Cliente não encontrado."))

    except Exception as e:
        print(f"Erro ao resetar senha do cliente {id_cliente}: {e}")
        return redirect(url_for('cadastro_cliente', view='alterar', id_cliente=id_cliente, error="Erro interno ao resetar senha."))


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
    
    # Captura explícita da regional enviada pelo formulário (se existir)
    id_regional_form = request.form.get('id_regional')

    try:
        # 1. Coleta de Dados
        default_config = {
            "nome_cliente": True, "nick": True, "telefone": True,
            "cpf": False, "cidade": True, "chave_pix": True, "senha": True
        }
        campos_config = getattr(g, 'parametros_globais', {}).get('tipo_cadastro_cliente', default_config)

        nome_cliente = formatar_nome_proprio(request.form.get('nome_cliente'))
        nick = formatar_nome_proprio(request.form.get('nick'))
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

        # --- NOVA LÓGICA DE SENHA ---
        hashed_password = None
        
        if not id_cliente_raw:  # NOVO CADASTRO
            senha_final = senha if senha else "Senha"
            if senha and senha != confirma_senha:
                raise ValueError("As senhas não conferem.")
            hashed_password = bcrypt.hashpw(senha_final.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
        else:  # EDIÇÃO
            if senha:
                if senha != confirma_senha:
                    raise ValueError("As senhas não conferem.")
                hashed_password = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Busca se o modo treinamento está ON  
        params = db.parametros.find_one({})
        modo_treino = params.get('em_treinamento', False)

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
        
        # Se veio do formulário e é válido, atualiza no dicionário (Útil para Master alterando Regional)
        if id_regional_form and id_regional_form.isdigit():
            dados_cliente["id_regional"] = int(id_regional_form)
        
        if hashed_password:
            dados_cliente["senha"] = hashed_password

        # 5. Gravação no Banco
        if id_cliente_raw:
            # Edição
            db.clientes.update_one({'id_cliente': int(id_cliente_raw)}, {'$set': dados_cliente})
            registrar_log("EDITAR", "CLIENTES", f"Dados do cliente {nick} alterados.", id_cliente_raw)
            success_msg = f"Cliente {nick} atualizado com sucesso!"
        else:
            # Novo Cadastro - 🚀 LÓGICA DE ATRIBUIÇÃO REGIONAL
            if "id_regional" not in dados_cliente:
                id_regional_final = 1 # Valor Default (Matriz / Auto-cadastro)
                
                id_regional_sessao = session.get('id_regional')
                id_colab_sessao = session.get('id_colaborador')
                
                if id_regional_sessao:
                    id_regional_final = int(id_regional_sessao)
                elif id_colab_sessao:
                    # Fallback: Tenta buscar a regional no cadastro do colaborador se a sessão falhar
                    colab_db = db.colaboradores.find_one({'id_colaborador': id_colab_sessao})
                    if colab_db and 'id_regional' in colab_db:
                        id_regional_final = int(colab_db['id_regional'])
                        
                dados_cliente["id_regional"] = id_regional_final

            novo_id = get_next_cliente_sequence()
            if not novo_id: raise Exception("Erro Sequence ID.")
            
            dados_cliente.update({
                "id_cliente": novo_id,
                "id_colaborador": session.get('id_colaborador'),
                "data_cadastro": hora_brasil() if isinstance(hora_brasil(), datetime) else datetime.now(),
                "origem": "interno",
                "em_treinamento": modo_treino,
                "saldo_atual": Decimal128("1000.00") if modo_treino else Decimal128("0.00")
            })
            
            db.clientes.insert_one(dados_cliente)

            if modo_treino:
                db.transacoes_clientes.insert_one({
                    "id_transacao": f"TRX_TREINO_{int(time.time())}",
                    "id_cliente": novo_id,
                    "tipo": "recarga_treinamento",
                    "valor": Decimal128("1000.00"),
                    "natureza": "ENTRADA",
                    "saldo_anterior": Decimal128("0.00"), 
                    "saldo_posterior": Decimal128("1000.00"), 
                    "descricao": "Bônus de Boas-vindas (MODO TREINAMENTO)",
                    "registrado_por": "SISTEMA", 
                    "data_hora": hora_brasil()
                })

            success_msg = f"Cliente {nick} cadastrado! ID: CLI{novo_id}"

        return redirect(url_for('cadastro_cliente', view='listar', success=success_msg))

    except ValueError as ve:
        cliente_form = {
            'id_cliente': id_cliente_raw, 'nome_cliente': nome_cliente, 'nick': nick,
            'telefone': telefone, 'cpf': cpf_raw, 'cidade': cidade,
            'chave_pix': request.form.get('chave_pix'), 'observacao': observacao,
            'id_regional': id_regional_form # Devolve para o form não perder caso dê erro
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
    if db is None: return redirect(url_for('login'))

    nivel_usuario = session.get('nivel', 1)

    try:
        # 1. Puxa o cliente para validar as finanças antes de excluir
        cliente = db.clientes.find_one({'id_cliente': id_cliente})
        if not cliente:
            return redirect(url_for('cadastro_cliente', error="Cliente não encontrado para exclusão.", view='listar'))

        # Extrai o saldo de forma segura
        saldo_atual = 0.0
        if 'saldo_atual' in cliente:
            val = cliente['saldo_atual']
            saldo_atual = float(str(val.to_decimal())) if hasattr(val, 'to_decimal') else float(val)

        # 2. 🛡️ TRAVA DE SEGURANÇA BACK-END
        if abs(saldo_atual) > 0.001:
            if nivel_usuario < 4:
                msg_erro = f"⛔ Exclusão bloqueada! O cliente possui um saldo pendente (R$ {saldo_atual:.2f}). Apenas gestores Master podem excluir este registo."
                return redirect(url_for('cadastro_cliente', error=msg_erro, view='listar'))
            # Se for >= 4, o backend permite. A confirmação dupla ocorreu no Frontend.

        # 3. Execução Atómica da Exclusão
        result = db.clientes.delete_one({'id_cliente': id_cliente})
        
        if result.deleted_count == 1:
            success_msg = f"Cliente ID: CLI{id_cliente} excluído com sucesso."
            
            # Deixa um rastro na auditoria caso um Master tenha forçado a exclusão de alguém com saldo
            detalhe_log = f"Cliente ID {id_cliente} removido permanentemente."
            if abs(saldo_atual) > 0.001:
                detalhe_log += f" [⚠️ ATENÇÃO: Master forçou exclusão de cliente com saldo de R$ {saldo_atual:.2f}]"
                
            registrar_log("EXCLUIR", "CLIENTES", detalhe_log, id_cliente)
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
    active_view = request.args.get('view', 'listar')
    search_term = request.args.get('query', '').strip()
    id_evento_edicao = request.args.get('id_evento', None)
    
    # 1. Definições de Identidade e Nível
    nivel_usuario = session.get('nivel', 0)
    id_regional_sessao = session.get('id_regional')
    is_master = (nivel_usuario >= 4)

    evento_edicao, eventos_lista, total_eventos = None, [], 0
    error, success = request.args.get('error'), request.args.get('success')

    # 2. Definições de Campos
    numeric_float_fields = ['valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_acumulado', 'minimo_de_venda', 'premio_total', 'premio_faltaum', 'premiacao_fixa']
    numeric_int_fields = ['unidade_de_venda', 'numero_inicial', 'numero_maximo', 'tipo_de_cartela', 'quantidade_de_linhas', 'bola_tope_acumulado', 'distribuir_cortesia']
    all_numeric_fields = numeric_float_fields + numeric_int_fields

    def to_num(val, is_int=False):
        try:
            res = float(str(val.to_decimal())) if hasattr(val, 'to_decimal') else float(val or 0)
            return int(res) if is_int else res
        except: return 0

    # 3. Bloco de Carregamento para Edição
    if form_data_erro:
        evento_edicao = form_data_erro
        if form_data_erro.get('id_evento_edicao'): 
            active_view, id_evento_edicao = 'alterar', form_data_erro['id_evento_edicao']
    elif active_view == 'alterar' and id_evento_edicao and db_status:
        try:
            evento_edicao = db.eventos.find_one({'id_evento': int(id_evento_edicao)})
            if evento_edicao:
                
                # =========================================================
                # 🚀 TRAVA DE SEGURANÇA: COMBO FILHO NÃO PODE SER EDITADO
                # =========================================================
                if evento_edicao.get('id_evento_principal_combo'):
                    error = f"❌ Acesso Negado: O Evento {id_evento_edicao} é uma réplica de Combo. Exclusões e alterações só podem ser feitas no Evento Principal."
                    active_view = 'listar'
                    evento_edicao = None
                else:
                    if '_id' in evento_edicao: evento_edicao['_id'] = str(evento_edicao['_id'])
                    for key in numeric_float_fields:
                        if key in evento_edicao: evento_edicao[key] = to_num(evento_edicao[key])
                    for key in numeric_int_fields:
                        if key in evento_edicao: evento_edicao[key] = to_num(evento_edicao[key], is_int=True)

                    dev = evento_edicao.get('data_evento')
                    if dev and isinstance(dev, str):
                        try: evento_edicao['data_evento'] = datetime.strptime(dev, '%d/%m/%Y').strftime('%Y-%m-%d')
                        except: pass
        except: 
            error, active_view = "ID inválido.", 'listar'

    # 4. Bloco de Listagem e Parâmetros
    param_doc_global = {}
    if db_status:
        try:
            total_eventos = db.eventos.count_documents({})
            param_doc_global = db.parametros.find_one({}) or {}
            
            if active_view in ['listar', 'exclusao_lote']:
                eventos_lista = list(db.eventos.find({}).sort([("data_evento", -1), ("hora_evento", -1)]).limit(50))
            elif active_view == 'consulta' and search_term:
                query_filter = {'id_evento': int(search_term)} if search_term.isdigit() else {'descricao': {'$regex': search_term, '$options': 'i'}}
                eventos_lista = list(db.eventos.find(query_filter).sort("data_evento", -1))

            # 5. Processamento Regionalizado (Fase 4)
            for evento in eventos_lista:
                
                # 🚀 IDENTIFICA SE É FILHO PARA O FRONT-END BLOQUEAR OS BOTÕES
                evento['is_combo_filho'] = bool(evento.get('id_evento_principal_combo'))
                
                for key in all_numeric_fields:
                    if key in evento: evento[key] = to_num(evento[key])

                id_ev = evento.get('id_evento')
                nome_cv = f"vendas{id_ev}"
                if nome_cv in db.list_collection_names():
                    match_filtro = {}
                    if not is_master and id_regional_sessao:
                        match_filtro['id_regional'] = int(id_regional_sessao)
                    
                    vendas_agg = list(db[nome_cv].aggregate([
                        {'$match': match_filtro},
                        {'$group': {'_id': None, 'total': {'$sum': '$quantidade_unidades'}}}
                    ]))
                    evento['qtd_vendas'] = vendas_agg[0].get('total', 0) if vendas_agg else 0
                
                evento = calcular_premios_dinamicos(db, evento, param_doc_global)
        except Exception as e: 
            error = f"Erro: {e}"

    # 6. Preparação Final do Contexto
    raw_acumulado = param_doc_global.get('acumulado', 0)
    raw_tope =  param_doc_global.get('tope', 0) 
    raw_minimo  =  param_doc_global.get('minimo_terminal', 6)
    raw_maximo  =  param_doc_global.get('maximo_terminal', 1200)

    context = {
        'total_eventos': total_eventos,
        'eventos_lista': eventos_lista,
        'active_view': active_view,
        'default_acumulado': to_num(raw_acumulado), 
        'default_tope': raw_tope, 
        'default_minimo': raw_minimo,
        'default_maximo': raw_maximo,  
        'cartela_limits': 72000,
        'query': search_term, 
        'evento_edicao': evento_edicao, 
        'error': error,
        'success': success,
        'is_master': is_master
    }
    
    return render_template('cadastro_evento.html', **context)


@app.route('/excluir_eventos_periodo', methods=['POST'])
@login_required
def excluir_eventos_periodo():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('cadastro_evento', view='exclusao_lote', error="Acesso negado."))

    try:
        inicio_raw = request.form.get('inicio')
        fim_raw = request.form.get('fim')
        
        if not inicio_raw or not fim_raw:
            return redirect(url_for('cadastro_evento', view='exclusao_lote', error="Informe as duas datas."))

        inicio_dt = datetime.strptime(inicio_raw, '%Y-%m-%dT%H:%M')
        fim_dt = datetime.strptime(fim_raw, '%Y-%m-%dT%H:%M')

        # 🚀 SEGURANÇA COMBO: No expurgo por período, nós varremos TUDO o que estiver no intervalo.
        # Os filhos que caírem no intervalo serão apagados independentemente, mas o motor garantirá que as tabelas morrem.
        query_periodo = {"data_hora_evento": {"$gte": inicio_dt, "$lte": fim_dt}}
        eventos_para_excluir = list(db.eventos.find(query_periodo, {"id_evento": 1}))
        
        if not eventos_para_excluir:
            return redirect(url_for('cadastro_evento', view='exclusao_lote', error="Nenhum evento encontrado nesse intervalo."))

        contagem = 0
        for ev in eventos_para_excluir:
            id_ev = ev['id_evento']
            
            # 1. Remove o documento principal
            db.eventos.delete_one({'id_evento': id_ev})
            
            # 2. BLOCO ADAPTADOR: Remove coleções dinâmicas (Vendas, Cupons, Pgtos e Snapshots)
            for prefixo in [f"vendas{id_ev}", f"vendas_sorte_extra{id_ev}", f"pagamentos{id_ev}", f"snapshot_vendas_{id_ev}"]:
                if prefixo in db.list_collection_names():
                    db[prefixo].drop()
            
            # 3. Limpa registros vinculados nas tabelas de apoio
            db.resultados.delete_many({'id_evento': id_ev})
            db.controle_venda.delete_many({'id_evento': id_ev})
            
            contagem += 1

        registrar_log("EXPURGO", "EVENTOS", f"Removidos {contagem} eventos via período ({inicio_raw} a {fim_raw})")
        return redirect(url_for('cadastro_evento', view='exclusao_lote', success=f"Sucesso! {contagem} eventos (Pais e Filhos) e todos os seus dados vinculados (incluindo snapshots) foram excluídos."))

    except Exception as e:
        print(f"ERRO NO EXPURGO PERÍODO: {e}")
        return redirect(url_for('cadastro_evento', view='exclusao_lote', error=f"Erro ao processar expurgo: {e}"))


@app.route('/excluir_eventos_lote', methods=['POST'])
@login_required
def excluir_eventos_lote():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    if session.get('nivel', 0) < 3:
        return redirect(url_for('cadastro_evento', view='exclusao_lote', error="Acesso Negado."))

    ids_selecionados_str = request.form.getlist('eventos_selecionados')
    
    if not ids_selecionados_str:
        return redirect(url_for('cadastro_evento', view='exclusao_lote', error="Nenhum evento foi selecionado."))

    excluidos_sucesso = 0
    falhas = 0
    filhos_bloqueados = 0

    try:
        for id_str in ids_selecionados_str:
            try:
                id_evento = int(id_str)
                
                # 🚀 SEGURANÇA COMBO: Verifica se o evento escolhido é filho.
                evento_db = db.eventos.find_one({'id_evento': id_evento})
                if evento_db and evento_db.get('id_evento_principal_combo'):
                    filhos_bloqueados += 1
                    continue # Pula a exclusão deste evento porque é filho!
                
                # É um evento principal (Pai ou Evento Normal). Pega também todos os IDs dos Filhos.
                lista_ids_para_apagar = [id_evento]
                filhos_cursor = db.eventos.find({'id_evento_principal_combo': id_evento}, {'id_evento': 1})
                for filho in filhos_cursor:
                    lista_ids_para_apagar.append(filho['id_evento'])

                # 🚀 DESTRUIÇÃO EM CASCATA: Apaga o Pai e os Filhos no mesmo laço
                for id_alvo in lista_ids_para_apagar:
                    result = db.eventos.delete_one({'id_evento': id_alvo})
                    
                    if result.deleted_count == 1:
                        # 2. BLOCO ADAPTADOR: Remove coleções dinâmicas de TODOS os IDs
                        colecoes_para_apagar = [
                            f"vendas{id_alvo}",
                            f"vendas_sorte_extra{id_alvo}",
                            f"pagamentos{id_alvo}",
                            f"snapshot_vendas_{id_alvo}"
                        ]
                        
                        for col_name in colecoes_para_apagar:
                            if col_name in db.list_collection_names():
                                db[col_name].drop()

                        # 3. Remove registros vinculados nas tabelas de apoio
                        db.resultados.delete_many({'id_evento': id_alvo})
                        db.controle_venda.delete_many({'id_evento': id_alvo})
                        
                        excluidos_sucesso += 1
                    else:
                        falhas += 1

            except ValueError:
                falhas += 1

        registrar_log("EXCLUIR", "EVENTOS", f"Exclusão em lote: {excluidos_sucesso} eventos removidos.")
        
        msg = f"Operação concluída! {excluidos_sucesso} eventos (incluindo réplicas em cascata) apagados."
        if filhos_bloqueados > 0:
            msg += f" (⚠️ {filhos_bloqueados} itens selecionados foram ignorados por serem Combos Filhos protegidos)."
            
        return redirect(url_for('cadastro_evento', view='exclusao_lote', success=msg))

    except Exception as e:
        print(f"ERRO CRÍTICO LOTE: {e}")
        return redirect(url_for('cadastro_evento', view='exclusao_lote', error=f"Erro interno: {e}"))


@app.route('/excluir_evento/<int:id_evento>', methods=['POST'])
@login_required
def excluir_evento(id_evento):
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    try:
        # 🚀 SEGURANÇA COMBO: Verifica se é Filho antes de tentar apagar
        evento_db = db.eventos.find_one({'id_evento': id_evento})
        if not evento_db:
             return redirect(url_for('cadastro_evento', error="Evento não encontrado no banco de dados.", view='listar'))
             
        if evento_db.get('id_evento_principal_combo'):
            return redirect(url_for('cadastro_evento', error="❌ Operação Cancelada: Eventos de Combo (Réplicas) não podem ser excluídos isoladamente. Exclua o evento principal correspondente.", view='listar'))

        # Se passou na trava, procura se ele tem Filhos
        lista_ids_para_apagar = [id_evento]
        filhos_cursor = db.eventos.find({'id_evento_principal_combo': id_evento}, {'id_evento': 1})
        for filho in filhos_cursor:
            lista_ids_para_apagar.append(filho['id_evento'])

        excluidos = 0
        # 🚀 DESTRUIÇÃO EM CASCATA
        for id_alvo in lista_ids_para_apagar:
            result = db.eventos.delete_one({'id_evento': id_alvo})
            
            if result.deleted_count == 1:
                # 2. BLOCO ADAPTADOR: Remove as coleções dinâmicas inteiras
                colecoes_para_limpar = [
                    f"vendas{id_alvo}",
                    f"vendas_sorte_extra{id_alvo}",
                    f"pagamentos{id_alvo}",
                    f"snapshot_vendas_{id_alvo}"
                ]
                
                for nome_col in colecoes_para_limpar:
                    if nome_col in db.list_collection_names():
                        db[nome_col].drop()

                # 3. Remove registros vinculados nas tabelas de apoio
                db.resultados.delete_many({'id_evento': id_alvo})
                db.controle_venda.delete_many({'id_evento': id_alvo})
                
                excluidos += 1

        # 4. Auditoria unificada
        registrar_log(
            acao="EXCLUIR",
            categoria="EVENTOS",
            detalhes=f"Exclusão do Evento e seus Combos (Total: {excluidos}) e tabelas vinculadas.",
            alvo_id=f"EVENTO_{id_evento}"
        )

        success_msg = f"Evento ID: {id_evento} e as suas Réplicas de Combo (Total apagado: {excluidos}) foram removidos com sucesso!"
        return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO CRÍTICO na exclusão de evento ID {id_evento}: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('cadastro_evento', error=f"Erro interno ao excluir evento: {e}", view='listar'))


@app.route('/gravar_evento', methods=['POST'])
@login_required
def gravar_evento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    id_evento_edicao = request.form.get('id_evento_edicao') 
    
    def clean_float_input(form_key, default_value='0'):
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
        
        # 🚀 NOVO: Captura do COMBO
        try:
            combo_qtde = int(request.form.get('combo_qtde', 1))
            if combo_qtde < 1: combo_qtde = 1
        except ValueError:
            combo_qtde = 1

        # --- LÓGICA DE CARTELA E NÚMERO MÁXIMO ---
        if tipo_de_cartela == 25:
            premio_faltaum = 0.0
            premio_segundobingo = 0.0
            quantidade_de_linhas = 1
            param_key = 'arquivo_cartela_25'
            default_max = 90000
        else:
            premio_faltaum = clean_float_input('premio_faltaum')
            premio_segundobingo = clean_float_input('premio_segundobingo')
            quantidade_de_linhas = int(request.form.get('quantidade_de_linhas', 1))
            param_key = 'arquivo_cartela_15'
            default_max = 72000
            
        try:
            param_doc = db.parametros.find_one({})
            numero_maximo = int(param_doc.get(param_key, default_max)) if param_doc else default_max
        except:
            numero_maximo = default_max
        
        # Captura financeira
        valor_de_venda = clean_float_input('valor_de_venda')
        premio_quadra = clean_float_input('premio_quadra')
        premio_linha = clean_float_input('premio_linha')
        premio_bingo = clean_float_input('premio_bingo')
        premio_acumulado = clean_float_input('premio_acumulado')
        minimo_de_venda = clean_float_input('minimo_de_venda') 
        premiacao_fixa = clean_float_input('premiacao_fixa', default_value='-1.00')

        numero_inicial = int(request.form.get('numero_inicial', 1))
        minimo_terminal = int(request.form.get('minimo_terminal', 6))
        maximo_terminal = int(request.form.get('maximo_terminal', 1200))  

        bola_tope_acumulado = int(request.form.get('bola_tope_acumulado', 0)) 

        try:
            distribuir_cortesia = int(request.form.get('distribuir_cortesia', 0))
            if distribuir_cortesia < 0: 
                distribuir_cortesia = 0
        except ValueError:
            distribuir_cortesia = 0

        if not all([data_evento_str, hora_evento, descricao, unidade_de_venda]):
             raise ValueError("Preencha todos os campos obrigatórios (*).")

        data_obj = datetime.strptime(data_evento_str, '%Y-%m-%d')
        data_evento_str_gravar = data_obj.strftime('%d/%m/%Y')
        data_hora_evento_dt = datetime.strptime(f"{data_evento_str} {hora_evento}", '%Y-%m-%d %H:%M')
        
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
            "minimo_terminal": minimo_terminal,
            "maximo_terminal": maximo_terminal,  
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
            "distribuir_cortesia": distribuir_cortesia,
            "combo_qtde": combo_qtde # 🚀 NOVO
        }
        
        if id_evento_edicao:
            db.eventos.update_one({'id_evento': int(id_evento_edicao)}, {'$set': dados_evento})
            success_msg = f"Evento ID: {id_evento_edicao} atualizado com sucesso!"
            return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))
        else:
            novo_id = get_next_evento_sequence()
            dados_evento.update({
                "id_evento": novo_id, 
                "status": "ativo", 
                "data_ativado": None,
                "data_cadastro": hora_brasil()
            })
            db.eventos.insert_one(dados_evento)

            nome_colecao_vendas = f"vendas{novo_id}"
            try:
                db[nome_colecao_vendas].create_index([("id_regional", 1), ("data_venda", -1)])
                db[nome_colecao_vendas].create_index([("id_regional", 1), ("id_vendedor", 1)])
                db[nome_colecao_vendas].create_index([("id_regional", 1), ("id_colaborador", 1)])
                db[nome_colecao_vendas].create_index([("id_regional", 1), ("id_cliente", 1)])
            except Exception as e:
                pass

            # 🚀 LÓGICA DE REDIRECIONAMENTO COMBO
            if combo_qtde > 1:
                replicas = combo_qtde - 1
                success_msg = f"Evento '{dados_evento['descricao']}' gravado (ID: {novo_id}). Defina agora o intervalo para criar os próximos {replicas} eventos."
                return redirect(url_for('cadastro_evento', view='alterar', id_evento=novo_id, auto_replicar=replicas, success=success_msg))
            else:
                success_msg = f"Evento '{dados_evento['descricao']}' salvo com sucesso! ID: {novo_id}."
                return redirect(url_for('cadastro_evento', success=success_msg, view='listar'))

    except Exception as e:
        print(f"ERRO na gravação: {e}")
        session['form_data'] = dict(request.form)
        view_redirect = 'alterar' if id_evento_edicao else 'novo'
        return redirect(url_for('cadastro_evento', error=f"Erro ao salvar: {e}", view=view_redirect, id_evento=id_evento_edicao))

@app.route('/consulta_vendas', methods=['GET'])
@login_required
def consulta_vendas():
    """
    Página de consulta de vendas regionalizada.
    Garante que gestores vejam apenas dados de sua jurisdição.
    INCLUI FILTRO DE STATUS (Ativos/Paralisados vs Finalizados).
    """
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    error_from_session = session.pop('error_message', None)
    success = session.pop('success_message', None)

    nivel_usuario = session.get('nivel', 1)
    id_colaborador_logado = session.get('id_colaborador', 'N/A')
    
    # --- CONTEXTO REGIONAL (FASE 4) ---
    id_regional_sessao = session.get('id_regional')
    is_master = (nivel_usuario >= 4)
    # ----------------------------------
    
    id_evento_param = request.args.get('id_evento')
    id_colaborador_param = request.args.get('id_colaborador')
    # 🚀 Captura o filtro de status do novo Dropdown
    status_filtro = request.args.get('status_filtro', 'ativos')

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
            decimal_fields = ['valor_de_venda', 'premio_quadra', 'premio_linha', 'premio_bingo', 'premio_segundobingo', 'premio_total']
            for key in decimal_fields:
                if key in evento: evento[key] = safe_float(evento.get(key, 0.0))
            return evento

        if not id_evento_param:
            # 🚀 APLICA O FILTRO DE STATUS NA BUSCA DE EVENTOS
            if status_filtro == 'finalizados':
                query_status = {'status': 'finalizado'}
                ordem = pymongo.DESCENDING # Finalizados mais recentes primeiro
            else:
                query_status = {'status': {'$in': ['ativo', 'paralisado']}}
                ordem = pymongo.ASCENDING # Ativos pela ordem normal

            eventos_ativos_cursor = db.eventos.find(query_status).sort('data_evento', ordem)
            
            for evento in eventos_ativos_cursor:
                eventos_ativos.append(clean_event_numerics(evento))
        
        else:
            # Busca Evento
            selected_event_raw = db.eventos.find_one({'id_evento': int(id_evento_param)}) if str(id_evento_param).isdigit() else db.eventos.find_one({'_id': try_object_id(id_evento_param)})
            selected_event = clean_event_numerics(selected_event_raw)
            
            if not selected_event:
                return render_template('consulta_vendas.html', error="Evento não encontrado.", g=g)

            # --- 1. FILTRO DE COLABORADORES (REGIONALIZADO) ---
            colabs_query = {}
            if not is_master and id_regional_sessao:
                colabs_query['id_regional'] = int(id_regional_sessao) # Só vê colegas da mesma regional

            if nivel_usuario >= 3:
                colaboradores_lista.append({'nick': 'TODOS', 'id_colaborador': 'ALL'})
                colabs_cursor = db.colaboradores.find(colabs_query, {'nick': 1, 'id_colaborador': 1, 'comissao': 1}).sort('nick', pymongo.ASCENDING)
                for colab in colabs_cursor:
                    colaboradores_lista.append(colab)
                    comissao_map[colab['id_colaborador']] = colab.get('comissao', default_comissao)
            
            # --- 2. MONTAGEM DO MATCH PARA AGREGATION ---
            id_evento_int = selected_event.get('id_evento')
            nome_colecao_venda = f"vendas{id_evento_int}"
            
            match_stage = {'id_evento': id_evento_int}
            
            # Trava Regional: Essencial para usar o ÍNDICE COMPOSTO da Fase 3
            if not is_master and id_regional_sessao:
                match_stage['id_regional'] = int(id_regional_sessao)

            # Filtro por Colaborador Específico
            if nivel_usuario < 3:
                match_stage['id_colaborador'] = id_colaborador_logado
                selected_colab_id_str = str(id_colaborador_logado)
            elif nivel_usuario >= 3:
                if id_colaborador_param and id_colaborador_param != 'ALL':
                    try: val_id = int(id_colaborador_param)
                    except: val_id = id_colaborador_param
                    match_stage['id_colaborador'] = val_id
                    selected_colab_id_str = str(id_colaborador_param)
                else:
                    selected_colab_id_str = 'ALL'

            # --- PIPELINE DE AGREGAÇÃO ---
            pipeline = [
                {'$match': match_stage}, # Filtro regional e de evento aplicado aqui
                {
                    '$group': {
                        '_id': '$id_colaborador', 
                        'nick_colaborador': {'$first': '$nick_colaborador'},
                        'total_kits': {'$sum': '$quantidade_unidades'},
                        'total_cartelas': {'$sum': '$quantidade_cartelas'},
                        'total_valor': {'$sum': '$valor_total'},
                        'total_vendas': {'$sum': 1},
                        'data_inicial': {'$min': '$data_venda'},
                        'data_final': {'$max': '$data_venda'},
                        'total_valor_auto': {
                            '$sum': {'$cond': [{'$eq': ['$origem', 'terminal_cliente']}, '$valor_total', 0]}
                        },
                        'total_valor_colab': {
                            '$sum': {'$cond': [{'$ne': ['$origem', 'terminal_cliente']}, '$valor_total', 0]}
                        }
                    }
                },
                {'$sort': {'nick_colaborador': 1}}
            ]
            
            if nome_colecao_venda in db.list_collection_names():
                resultados_cursor = db[nome_colecao_venda].aggregate(pipeline)
                
                for res in resultados_cursor:
                    venda_via_colab = safe_float(res.get('total_valor_colab', 0))
                    venda_via_auto = safe_float(res.get('total_valor_auto', 0))
                    
                    taxa = comissao_map.get(res['_id'], default_comissao)
                    res['valor_comissao_float'] = ((venda_via_colab * taxa) / 100.0) + ((venda_via_auto * comissao_autoatendimento) / 100.0)
                    res['total_valor_float'] = safe_float(res['total_valor'])
                    resultados_agregados.append(res)

            # --- RESUMO GERAL ---
            if selected_colab_id_str == 'ALL' and resultados_agregados:
                resumo_geral = {
                    'nick_colaborador': '⭐ Resumo Regional' if not is_master else '⭐ Resumo Global',
                    'total_kits': sum(r['total_kits'] for r in resultados_agregados),
                    'total_valor_float': sum(r['total_valor_float'] for r in resultados_agregados),
                    'total_vendas': sum(r['total_vendas'] for r in resultados_agregados),
                    'valor_comissao_float': sum(r['valor_comissao_float'] for r in resultados_agregados),
                    'data_inicial': min(r['data_inicial'] for r in resultados_agregados),
                    'data_final': max(r['data_final'] for r in resultados_agregados)
                }

    except Exception as e:
        error = f"Erro na consulta: {e}"
        import traceback
        traceback.print_exc()

    return render_template('consulta_vendas.html', g=g, error=error, success=success, nivel=nivel_usuario, eventos=eventos_ativos, selected_event=selected_event, colaboradores=colaboradores_lista, selected_colab_id=selected_colab_id_str, resumo_geral=resumo_geral, resultados_agregados=resultados_agregados)

@app.route('/consulta_vendas/detalhes', methods=['GET'])
@login_required
def consulta_vendas_detalhes():
    """Mostra a lista detalhada de vendas com blindagem contra tipos de ID (Int vs Str)."""
    db = get_vendas_db()
    if db is None: return redirect(url_for('login')) 

    nivel_usuario = session.get('nivel', 1)
    id_colaborador_logado = session.get('id_colaborador', 'N/A')
    
    id_evento_param = request.args.get('id_evento')
    id_colaborador_param = request.args.get('id_colaborador') 

    vendas_detalhadas = []
    error = None

    # --- 1. PREPARA AS TAXAS ---
    params_globais = getattr(g, 'parametros_globais', {})
    default_comissao = params_globais.get('comissao_padrao', 0)
    comissao_autoatendimento = params_globais.get('comissao_autoatendimento', 0)
    comissao_map = {} 

    try:
        # Busca o Evento para saber qual coleção abrir
        selected_event = None
        if id_evento_param:
            if str(id_evento_param).isdigit():
                selected_event = db.eventos.find_one({'id_evento': int(id_evento_param)})
            else:
                selected_event = db.eventos.find_one({'_id': try_object_id(id_evento_param)})
        
        if not selected_event:
            return render_template('consulta_vendas_detalhes.html', error="Evento não encontrado.", vendas=[])

        # 🚀 NOVO: Verifica se o evento é FILHO de um combo
        is_evento_filho = 'id_evento_principal_combo' in selected_event and bool(selected_event['id_evento_principal_combo'])

        id_evento_int = selected_event.get('id_evento')
        nome_colecao_venda = f"vendas{id_evento_int}"
        
        # --- 2. CONSTRUÇÃO DO FILTRO INTELIGENTE ---
        query_filter = {}

        if nivel_usuario < 3:
            # Blindagem do ID do Colaborador (tenta os dois tipos)
            id_colab_busca = int(id_colaborador_logado) if str(id_colaborador_logado).isdigit() else id_colaborador_logado
            query_filter['id_colaborador'] = {'$in': [id_colab_busca, str(id_colab_busca)]}
        
        elif nivel_usuario >= 3 and id_colaborador_param and id_colaborador_param != 'ALL':
            id_colab_target = int(id_colaborador_param) if str(id_colaborador_param).isdigit() else id_colaborador_param
            query_filter['id_colaborador'] = {'$in': [id_colab_target, str(id_colab_target)]}

        # --- 3. BUSCA NA COLEÇÃO DINÂMICA ---
        if nome_colecao_venda not in db.list_collection_names():
            return render_template('consulta_vendas_detalhes.html', error="Nenhuma venda registrada para este evento.", vendas=[], is_evento_filho=is_evento_filho)

        vendas_cursor = db[nome_colecao_venda].find(query_filter).sort('data_venda', pymongo.DESCENDING)
        
        # Busca todas as comissões de uma vez para ganhar performance
        todos_colabs = {c['id_colaborador']: c.get('comissao', default_comissao) for c in db.colaboradores.find({}, {'id_colaborador': 1, 'comissao': 1})}

        for venda in vendas_cursor:
            venda['valor_total_float'] = safe_float(venda.get('valor_total'))
            colab_id = venda.get('id_colaborador')
            origem_venda = venda.get('origem', 'terminal_colaborador')

            # Aplica a regra de comissão conforme a origem (Fase 2)
            taxa_final = comissao_autoatendimento if origem_venda == 'terminal_cliente' else todos_colabs.get(colab_id, default_comissao)
            venda['valor_comissao_float'] = (venda['valor_total_float'] * taxa_final) / 100.0
            venda['taxa_comissao_aplicada'] = taxa_final
            
            vendas_detalhadas.append(venda)

        if not vendas_detalhadas:
            error = "Nenhuma venda detalhada encontrada para os filtros selecionados."

    except Exception as e:
        import traceback
        print(f"Erro em consulta_vendas_detalhes: {e}")
        traceback.print_exc()
        error = f"Erro interno ao listar detalhes."
        is_evento_filho = False # Fallback de segurança

    return render_template('consulta_vendas_detalhes.html',
                           g=g, error=error, vendas=vendas_detalhadas,
                           info_evento=selected_event.get('descricao'), 
                           info_evento_id=id_evento_int, 
                           info_colaborador="TODOS" if id_colaborador_param == 'ALL' else session.get('nick'),
                           info_tipo_cartela=selected_event.get('tipo_de_cartela', 25),
                           is_evento_filho=is_evento_filho) # 🚀 ENVIADO PARA O JINJA (HTML)

# Minha Conta 
# --- ATUALIZAÇÃO DA ROTA MINHA CONTA ---
@app.route('/minha_conta', methods=['GET'])
@login_required
def minha_conta():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    nivel_usuario = session.get('nivel', 1)
    id_logado_session = session.get('id_colaborador')
    id_regional_sessao = session.get('id_regional') # Contexto Regional
    
    # ID do colaborador alvo
    target_id_colaborador = request.args.get('target_id', id_logado_session)
    
    # --- TRAVA DE SEGURANÇA REGIONAL (FASE 4) ---
    # Admin (4) vê todos. Gestor (3) vê apenas sua regional.
    if nivel_usuario < 4:
        # Se um nível 3 tentar ver alguém de outra regional, o sistema o "trava" no próprio ID
        if str(target_id_colaborador) != str(id_logado_session):
            target_check = db.colaboradores.find_one({'id_colaborador': int(target_id_colaborador)}, {'id_regional': 1})
            if not target_check or target_check.get('id_regional') != id_regional_sessao:
                target_id_colaborador = id_logado_session
    # --------------------------------------------

    try:
        target_id_int = int(target_id_colaborador)
    except:
        return redirect(url_for('menu_operacoes', error="ID inválido."))

    colaborador_alvo = db.colaboradores.find_one({'id_colaborador': target_id_int})
    if not colaborador_alvo:
        return redirect(url_for('menu_operacoes', error="Não encontrado."))

    # 1. BUSCA PARÂMETROS
    params = db.parametros.find_one({}) or {}

    def get_perc(key, default_percent):
        val = params.get(key)
        if val is None:
            # Retorna o default dividido por 100 (ex: 15.0 / 100 = 0.15)
            return default_percent / 100.0
        try:
            # Extrai o valor do banco, seja ele Decimal128, int ou string
            val_float = float(val.to_decimal()) if hasattr(val, 'to_decimal') else float(val)
            
            # DIVISÃO CRÍTICA: Transforma o "15.0" do banco em "0.15" para o cálculo
            return val_float / 100.0
        except Exception:
            return default_percent / 100.0

    # Passamos o valor padrão inteiro, a função entrega os decimais corretos (0.15, 0.05, 0.10)
    p_direta = get_perc('perc_venda_direta', 15.0)
    p_ind_a = get_perc('perc_venda_indireta_a', 5.0)
    p_ind_b = get_perc('perc_venda_indireta_b', 10.0)

    # Listas para filtros (Regionalizadas para Nível 3)
    filtro_colab_listagem = {}
    if nivel_usuario == 3:
        filtro_colab_listagem = {'id_regional': id_regional_sessao}
    
    colaboradores_selecao = list(db.colaboradores.find(filtro_colab_listagem, {'id_colaborador': 1, 'nick': 1}).sort('nick', 1)) if nivel_usuario >= 3 else []
    eventos_ativos = list(db.eventos.find({'status': 'ativo'}).sort('id_evento', -1))
    
    id_evento_selected = request.args.get('id_evento')
    data_inicio_raw = request.args.get('data_inicio')
    data_fim_raw = request.args.get('data_fim')
    
    resumo = {
        'vol_direto': 0.0, 'com_direta': 0.0,
        'vol_ind_a': 0.0, 'com_ind_a': 0.0,
        'vol_ind_b': 0.0, 'com_ind_b': 0.0,
        'total_comissao': 0.0, 'total_pago': 0.0, 'saldo_devedor': 0.0, 'total_vendas_valor': 0.0,
        'eventos_processados': 0
    }
    historico_pagamentos = []
    lista_ids_eventos = []
    evento_selecionado = None

    try:
        # 2. DEFINIÇÃO DO ESCOPO
        if data_inicio_raw and data_fim_raw:
            dt_ini = datetime.strptime(data_inicio_raw, '%Y-%m-%dT%H:%M')
            dt_fim = datetime.strptime(data_fim_raw, '%Y-%m-%dT%H:%M')
            eventos_no_periodo = db.eventos.find({"data_hora_evento": {"$gte": dt_ini, "$lte": dt_fim}}, {"id_evento": 1})
            lista_ids_eventos = [e['id_evento'] for e in eventos_no_periodo]
            evento_selecionado = {'descricao': f"Período: {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}", 'id_evento': 'Vários'}
        elif id_evento_selected:
            lista_ids_eventos = [int(id_evento_selected)]
            evento_selecionado = db.eventos.find_one({'id_evento': int(id_evento_selected)})

        # 3. CONSOLIDAÇÃO (REGIONALIZADA)[cite: 1]
        for id_ev in lista_ids_eventos:
            nome_col_vendas = f"vendas{id_ev}"
            nome_col_pagtos = f"pagamentos{id_ev}"

            if nome_col_vendas in db.list_collection_names():
                # NOVO: Match inclui id_regional para usar o índice composto e garantir isolamento[cite: 1]
                match_query = { "$or": [{"id_vendedor": target_id_int}, {"id_colaborador": target_id_int}] }
                
                # Se o target_id é de outra regional que não a do logado (e logado não é admin), 
                # a trava lá no topo já impediu, mas aqui garantimos o filtro por regional[cite: 1]
                if nivel_usuario < 4:
                    match_query["id_regional"] = id_regional_sessao

                pipeline = [
                    { "$match": match_query },
                    { "$group": {
                        "_id": None,
                        "vd_vol": { "$sum": { "$cond": [{"$and": [{"$eq": ["$id_vendedor", target_id_int]}, {"$eq": ["$id_colaborador", target_id_int]}]}, {"$toDouble": "$valor_total"}, 0] } },
                        "ia_vol": { "$sum": { "$cond": [{"$and": [{"$ne": ["$id_vendedor", target_id_int]}, {"$eq": ["$id_colaborador", target_id_int]}]}, {"$toDouble": "$valor_total"}, 0] } },
                        "ib_vol": { "$sum": { "$cond": [{"$and": [{"$eq": ["$id_vendedor", target_id_int]}, {"$ne": ["$id_colaborador", target_id_int]}]}, {"$toDouble": "$valor_total"}, 0] } }
                    }}
                ]
                res = list(db[nome_col_vendas].aggregate(pipeline))
                if res:
                    d = res[0]
                    resumo['vol_direto'] += d['vd_vol']
                    resumo['vol_ind_a'] += d['ia_vol']
                    resumo['vol_ind_b'] += d['ib_vol']
                    resumo['eventos_processados'] += 1

            if nome_col_pagtos in db.list_collection_names():
                pagtos_evento = list(db[nome_col_pagtos].find({'id_colaborador': target_id_int}))
                for p in pagtos_evento:
                    resumo['total_pago'] += safe_float(p.get('valor_pago', 0))
                    p['data_hora_fmt'] = p['data_hora'].strftime("%d/%m/%Y %H:%M") if isinstance(p.get('data_hora'), datetime) else "N/A"
                    historico_pagamentos.append(p)

        # 4. CÁLCULO FINAL
        resumo['com_direta'] = resumo['vol_direto'] * p_direta
        resumo['com_ind_a'] = resumo['vol_ind_a'] * p_ind_a
        resumo['com_ind_b'] = resumo['vol_ind_b'] * p_ind_b
        resumo['total_comissao'] = resumo['com_direta'] + resumo['com_ind_a'] + resumo['com_ind_b']
        resumo['total_vendas_valor'] = resumo['vol_direto'] + resumo['vol_ind_b']
        resumo['saldo_devedor'] = resumo['total_vendas_valor'] - resumo['total_pago']

        historico_pagamentos.sort(key=lambda x: x.get('data_hora', datetime.min), reverse=True)

    except Exception as e:
        print(f"Erro financeiro: {e}")

    return render_template('minha_conta.html', 
                           nivel=nivel_usuario, colaboradores=colaboradores_selecao,
                           target_colab=colaborador_alvo, eventos=eventos_ativos,
                           evento_selecionado=evento_selecionado, financeiro=resumo,
                           pagamentos=historico_pagamentos, g=g)



# --- ROTA: REGISTRAR PAGAMENTO (REGIONALIZADA) ---
@app.route('/registrar_pagamento', methods=['POST'])
@login_required
def registrar_pagamento():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))

    try:
        id_evento = int(request.form.get('id_evento'))
        id_colaborador_alvo = int(request.form.get('id_colaborador_alvo'))
        valor_pagamento = float(request.form.get('valor_pagamento').replace(',', '.'))
        
        # --- CONTEXTO DE SEGURANÇA ---
        nivel_logado = session.get('nivel', 1)
        id_logado = session.get('id_colaborador')
        id_regional_logado = session.get('id_regional')
        is_master = (nivel_logado >= 4)

        # 1. Busca o documento do colaborador alvo para conferir a Regional
        colab_alvo_doc = db.colaboradores.find_one({'id_colaborador': id_colaborador_alvo})
        if not colab_alvo_doc:
            return redirect(url_for('menu_operacoes', error="Colaborador alvo não encontrado."))
        
        id_regional_alvo = colab_alvo_doc.get('id_regional', 1)

        # --- TRAVA REGIONAL (FASE 4) ---
        # Se não for Master, o operador só pode registrar pagamentos para colaboradores da sua própria regional
        if not is_master and int(id_regional_alvo) != int(id_regional_logado):
            return redirect(url_for('minha_conta', id_evento=id_evento, target_id=id_colaborador_alvo, 
                                    error="🔒 Acesso Negado: Você não tem permissão para registrar pagamentos em outras regionais."))
        
        # 2. Validação de Saldo (Regionalizada)
        nome_colecao_vendas = f"vendas{id_evento}"
        nome_colecao_pagtos = f"pagamentos{id_evento}"
        
        total_vendas = 0.0
        total_pago = 0.0
        
        # Filtro de Match: Essencial para usar o índice da Fase 3
        match_filter = {'id_colaborador': id_colaborador_alvo}
        
        if nome_colecao_vendas in db.list_collection_names():
            res = list(db[nome_colecao_vendas].aggregate([
                {'$match': match_filter},
                {'$group': {'_id': None, 'total': {'$sum': '$valor_total'}}}
            ]))
            if res: total_vendas = safe_float(res[0]['total'])
            
        if nome_colecao_pagtos in db.list_collection_names():
            res = list(db[nome_colecao_pagtos].aggregate([
                {'$match': match_filter},
                {'$group': {'_id': None, 'total': {'$sum': '$valor_pago'}}}
            ]))
            if res: total_pago = safe_float(res[0]['total'])
            
        saldo_devedor = total_vendas - total_pago
        
        if valor_pagamento > (saldo_devedor + 0.01):
            return redirect(url_for('minha_conta', id_evento=id_evento, target_id=id_colaborador_alvo, 
                                  error=f"Valor R$ {valor_pagamento:.2f} excede o saldo devedor de R$ {saldo_devedor:.2f}"))
        
        if valor_pagamento <= 0:
             return redirect(url_for('minha_conta', id_evento=id_evento, target_id=id_colaborador_alvo, 
                                   error="Valor deve ser maior que zero."))

        # 3. Grava o Pagamento com o Carimbo Regional
        pagamento_doc = {
            'id_evento': id_evento,
            'id_colaborador': id_colaborador_alvo,
            'nick_colaborador': colab_alvo_doc.get('nick', 'Desconhecido'),
            'id_regional': id_regional_alvo, # <-- CARIMBO REGIONAL PARA RELATÓRIOS FINANCEIROS[cite: 1]
            'valor_pago': Decimal128(str(valor_pagamento)),
            'data_hora': hora_brasil(),
            'registrado_por_id': id_logado,
            'registrado_por_nick': session.get('nick'),
            'origem_regional': id_regional_logado # Registra quem da regional recebeu
        }
        
        db[nome_colecao_pagtos].insert_one(pagamento_doc)
        
        # Log de Auditoria
        registrar_log("FINANCEIRO", "PAGAMENTO", 
                      f"Pagamento de R$ {valor_pagamento:.2f} registrado para {colab_alvo_doc.get('nick')}", 
                      alvo_id=id_colaborador_alvo)
        
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
                #print(f"id_evento:   {id_evento_int}")

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


@app.route('/api/buscar_dados_venda', methods=['POST'])
@login_required
def api_buscar_dados_venda():
    db = get_vendas_db()
    if db is None:
        return jsonify({'status': 'error', 'message': 'DB Offline'}), 500

    data = request.json
    id_venda_str = data.get('id_venda')
    valor_id_evento = str(data.get('id_evento'))

    # Identificar coleção de vendas
    if len(valor_id_evento) == 24:
        evento = db.eventos.find_one({'$or': [{'_id': ObjectId(valor_id_evento)}, {'id_evento_ObjectId': ObjectId(valor_id_evento)}]})
    else:
        evento = db.eventos.find_one({'id_evento': int(valor_id_evento)})
    
    if not evento:
        return jsonify({'status': 'error', 'message': 'Evento não encontrado'}), 404

    id_evento_int = evento.get('id_evento')
    nome_colecao_venda = f"vendas{id_evento_int}"
    
    venda = db[nome_colecao_venda].find_one({'id_venda': id_venda_str})
    
    if not venda:
        return jsonify({'status': 'error', 'message': 'Venda não encontrada'}), 404

    # Retorna o pacote exatamente como o imprimirCartelas58mm espera
    return jsonify({
        'id_evento': id_evento_int,
        'nome_cliente': venda.get('nome_cliente'),
        'telefone_cliente': venda.get('telefone_cliente', ''),  
        'numero_inicial': venda.get('numero_inicial'),
        'numero_final': venda.get('numero_final'),
        'tipo_cartela': venda.get('tipo_cartela', 25)
    })

# --- ROTA DE REIMPRESSÃO (TXT) ---
@app.route('/reimprimir_comprovante_txt', methods=['POST'])
@login_required
def reimprimir_comprovante_txt():
    """
    Gera o texto (TXT) de um comprovante para "Venda Única" ou "Vendas Cliente"
    e retorna como JSON para ser copiado pela área de transferência.
    INCLUI MATEMÁTICA DE COMBO (Fase 1)
    """
    db = get_vendas_db()
    if db is None:
        return jsonify({'status': 'error', 'message': 'DB Offline'})

    try:
        data = request.json
        tipo_reimpressao = data.get('tipo_reimpressao') 
        id_venda_str = data.get('id_venda')            
        id_cliente_int = int(data.get('id_cliente', 0)) # Garante o zero se vier nulo

        valor_id_evento = str(data.get('id_evento'))
   
        # --- BLINDAGEM DO EVENTO ---
        if len(valor_id_evento) == 24:
            from bson.objectid import ObjectId
            evento = db.eventos.find_one({
                '$or': [
                    {'_id': ObjectId(valor_id_evento)},
                    {'id_evento_ObjectId': ObjectId(valor_id_evento)}
                ]
            })
        else: 
            evento = db.eventos.find_one({'id_evento': int(valor_id_evento)})
    
        if not evento:
            return jsonify({'status': 'error', 'message': 'Evento não encontrado'})
        
        id_evento_int = evento.get('id_evento')
        
        # 🚀 VARIÁVEIS DO COMBO
        combo_qtde = int(evento.get('combo_qtde', 1))
        unidade_de_venda = int(evento.get('unidade_de_venda', 1))

        # 🚀 BUSCA SEGURA DOS PARÂMETROS DIRETO DO DB (Evita falhas do "g")
        parametros = db.parametros.find_one({}) or {}
        http_apk = parametros.get('http_apk', '')
        url_canal_live = parametros.get('url_canal_live', '')
        nome_sala = parametros.get('nome_sala', '')
        venda_lite_ativa = parametros.get('venda_lite', False)

        data_evento_str = evento.get('data_evento', 'N/A')
        hora_evento_str = evento.get('hora_evento', 'N/A')
        data_evento_formatada = data_evento_str.replace('/', '-') if data_evento_str else 'N/A'
        
        nome_colecao_venda = f"vendas{id_evento_int}"

        receipt_html = "" 
        
        # 🚀 LÓGICA DO LINK COM FALLBACK (Plano B)
        if id_cliente_int > 0 and not venda_lite_ativa:
            link_final_limpo = f"{http_apk}?idcliente={id_cliente_int}"
        else:
            link_final_limpo = f"{url_canal_live}"
            # Fallback Inteligente: Se é Lite, mas não tem Live configurada, manda o APK se houver cliente
            if not link_final_limpo.strip() and id_cliente_int > 0:
                link_final_limpo = f"{http_apk}?idcliente={id_cliente_int}"
            elif not link_final_limpo.strip():
                link_final_limpo = "Boa sorte!" # Mensagem padrão caso tudo falhe
            
        # ==========================================
        # MODO 1: REIMPRESSÃO DE VENDA ÚNICA (TXT)
        # ==========================================
        if tipo_reimpressao == 'unica':
            # 🚀 CORREÇÃO CRÍTICA: Busca todas as fatias da venda
            fatias_venda = list(db[nome_colecao_venda].find({'id_venda': id_venda_str}).sort('numero_inicial', 1))
            if not fatias_venda:
                return jsonify({'status': 'error', 'message': 'Venda não encontrada'})
            
            venda_base = fatias_venda[0]
            
            # Totalizadores reais (somando todas as fatias)
            quantidade_total_unidades = sum([v.get('quantidade_unidades', 1) for v in fatias_venda])
            quantidade_total_cartelas = venda_base.get('quantidade_cartelas', unidade_de_venda)
            valor_total_real = sum([safe_float(v.get('valor_total', 0)) for v in fatias_venda])
            
            # 🚀 MATRIZ DO COMBO NA REIMPRESSÃO TXT (WhatsApp)
            detalhes_rodadas_html = ""
            
            for rodada in range(1, combo_qtde + 1):
                for fatia in fatias_venda:
                    num_inicial_fatia = fatia['numero_inicial']
                    qtd_cartelas_fatia = (fatia['numero_final'] - fatia['numero_inicial']) + 1
                    
                    kit_base = ((num_inicial_fatia - 1) // unidade_de_venda) + 1
                    kit_atual = kit_base + (rodada - 1)
                    
                    ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
                    fim_atual = ini_atual + qtd_cartelas_fatia - 1
                    
                    texto_r = f"Rod. {rodada:02d}"
                    if unidade_de_venda > 1:
                        texto_r += f" (Kit {kit_atual})"
                    
                    detalhes_rodadas_html += f"   > {texto_r}: {ini_atual} a {fim_atual}<br>"
                
                if fatia.get('numero_inicial2', 0) > 0:
                    detalhes_rodadas_html += f"   > Adicional: {fatia['numero_inicial2']} a {fatia['numero_final2']}<br>"

            receipt_html = (
                f"<strong>✅COMPROVANTE DE COMPRA</strong><br>"
                f"      {nome_sala}<br>"
                f"     >  {venda_base['id_venda']}  < <br>"
                f"--------------------------------------------------------<br>"
                f"Cliente: <strong>{venda_base['nome_cliente']}</strong><br>"
                f"Evento: {evento['descricao']}<br>"
                f"<strong>Data: {data_evento_formatada} às {hora_evento_str}</strong><br>"
                f"Colaborador:{venda_base['id_colaborador']}-{venda_base['nick_colaborador']}<br>"
                f"--------------------------------------------------------<br>"
                f"Unidades Compradas: <strong>{quantidade_total_unidades}<strong><br>"
                f"     (Cartelas: {quantidade_total_cartelas})<br>"
                f"<strong> >  Período de Cartelas  <<strong><br>"
                f"{detalhes_rodadas_html}"
                f"<br>"
                f"  VALOR: R$ {valor_total_real:.2f}<br>"
                f"<br>" 
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
                
                # Conversão segura do Decimal128 para float (simulando a função safe_float)
                valor = str(venda.get('valor_total', 0))
                total_valor += float(valor) if valor.replace('.', '', 1).isdigit() else 0.0
                
                # 🚀 MOTOR DO COMBO PARA CADA VENDA NO RESUMO DO CLIENTE
                qtd_cartelas = (venda['numero_final'] - venda['numero_inicial']) + 1
                kit_base = ((venda['numero_inicial'] - 1) // unidade_de_venda) + 1
                
                for rodada in range(1, combo_qtde + 1):
                    kit_atual = kit_base + (rodada - 1)
                    ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
                    fim_atual = ini_atual + qtd_cartelas - 1
                    
                    texto_r = f"R{rodada:02d}"
                    if unidade_de_venda > 1:
                         texto_r += f"(K{kit_atual})"
                    periodos_html_list.append(f"   > {texto_r}: {ini_atual} a {fim_atual}<br>")
                
                if venda.get('numero_inicial2', 0) > 0:
                    periodos_html_list.append(f"    > Adic: {venda['numero_inicial2']} a {venda['numero_final2']}<br>")

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
                f"   ACESSAR SUAS CARTELAS 📱<br>"
            )

        else:
            return jsonify({'status': 'error', 'message': 'Tipo de reimpressão inválido.'})
        
        # 🚀 AQUI O LINK ENTRA APENAS UMA VEZ PARA QUALQUER UM DOS CASOS
        receipt_html += f"<br><strong> {link_final_limpo} </strong>"

        def clean_html_to_txt(html_str):
            import re
            import html
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


@app.route('/reimprimir_comprovante_json', methods=['POST'])
@login_required
def reimprimir_comprovante_json():
    """
    Gera o pacote estruturado (JSON) de um comprovante para "Venda Única" ou "Vendas Cliente".
    Este payload é lido pela ponte Android para imprimir na térmica 58mm.
    INCLUI MATEMÁTICA DE COMBO (Fase 1)
    """
    db = get_vendas_db()
    if db is None:
        return jsonify({'status': 'error', 'message': 'DB Offline'})

    try:
        data = request.json
        tipo_reimpressao = data.get('tipo_reimpressao') 
        id_venda_str = data.get('id_venda')            
        id_cliente_int = int(data.get('id_cliente'))
        valor_id_evento = str(data.get('id_evento'))
   
        # --- BLINDAGEM DO EVENTO ---
        if len(valor_id_evento) == 24: 
            from bson.objectid import ObjectId
            evento = db.eventos.find_one({
                '$or': [
                    {'_id': ObjectId(valor_id_evento)},
                    {'id_evento_ObjectId': ObjectId(valor_id_evento)}
                ]
            })
        else:
            evento = db.eventos.find_one({'id_evento': int(valor_id_evento)})
    
        if not evento:
            return jsonify({'status': 'error', 'message': 'Evento não encontrado'})
        
        id_evento_int = evento.get('id_evento')
        
        # 🚀 VARIÁVEIS DO COMBO
        combo_qtde = int(evento.get('combo_qtde', 1))
        unidade_de_venda = int(evento.get('unidade_de_venda', 1))

        http_apk = g.parametros_globais.get('http_apk', '')
        url_canal_live = g.parametros_globais.get('url_canal_live', '')
        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        
        data_evento_str = evento.get('data_evento', 'N/A')
        hora_evento_str = evento.get('hora_evento', 'N/A')
        data_evento_formatada = data_evento_str.replace('/', '-') if data_evento_str else 'N/A'
        
        nome_colecao_venda = f"vendas{id_evento_int}"

        venda_lite_ativa = g.parametros_globais.get('venda_lite') == True

        if id_cliente_int > 0 and not venda_lite_ativa:
           link_final_limpo = f"{http_apk}?idcliente={id_cliente_int}"
        else:
           link_final_limpo = f"{url_canal_live}" 

        # 1. Estrutura Padrão do Contrato JSON
        recibo = {
            "config": { "avanco_linhas": 2, "cortar_papel": False },
            "linhas": []
        }

        # Função auxiliar limpa para adicionar linhas ao JSON
        def add_linha(texto, alinhamento="esquerda", tamanho="normal", negrito=False):
            if not texto or str(texto).strip() == "": texto = " "
            recibo["linhas"].append({
                "texto": str(texto),
                "alinhamento": alinhamento,
                "tamanho": tamanho,
                "negrito": negrito
            })

        # ==========================================
        # MODO 1: REIMPRESSÃO DE VENDA ÚNICA
        # ==========================================
        if tipo_reimpressao == 'unica':
            # 🚀 CORREÇÃO CRÍTICA: Agora usamos .find() para apanhar todas as fatias de uma venda (Pilar 1)
            fatias_venda = list(db[nome_colecao_venda].find({'id_venda': id_venda_str}).sort('numero_inicial', 1))
            if not fatias_venda:
                return jsonify({'status': 'error', 'message': 'Venda não encontrada'})
            
            # Pega os dados principais da primeira fatia (são todos iguais)
            venda_base = fatias_venda[0]
            
            # Calcula os totais reais somando todas as fatias
            quantidade_total_unidades = sum([v.get('quantidade_unidades', 1) for v in fatias_venda])
            quantidade_total_cartelas = venda_base.get('quantidade_cartelas', unidade_de_venda)
            valor_total_real = sum([safe_float(v.get('valor_total', 0)) for v in fatias_venda])

            add_linha("COMPROVANTE DE COMPRA", "centro", "normal", True)
            add_linha(" ", "centro", "normal", False)
            
            add_linha(f"ID da Venda: {venda_base['id_venda']}", "centro", "normal", False)
            add_linha("-------------------------------", "centro", "normal", False)
            add_linha(f"Cliente: {venda_base['nome_cliente']}", "esquerda", "normal", True)
            add_linha(f"Evento: {evento['descricao']}", "esquerda", "normal", False)
            add_linha(f"Data: {data_evento_formatada} as {hora_evento_str}", "esquerda", "normal", False)
            add_linha(f"Colab: {venda_base['id_colaborador']}-{venda_base['nick_colaborador']}", "esquerda", "normal", False)
            add_linha("-------------------------------", "centro", "normal", False)
            
            add_linha(f"Unidades Compradas: > {quantidade_total_unidades} <", "centro", "normal", False)
            add_linha("QTDE. CARTELAS", "centro", "normal", False)
            add_linha(str(quantidade_total_cartelas), "centro", "duplo", False)

            add_linha("> PERIODO DE CARTELAS <", "centro", "normal", True)
            
            # 🚀 LÓGICA DO COMBO EM MATRIZ NA REIMPRESSÃO (Igual à tela de sucesso)
            for rodada in range(1, combo_qtde + 1):
                
                for fatia in fatias_venda:
                    num_inicial_fatia = fatia['numero_inicial']
                    qtd_cartelas_fatia = (fatia['numero_final'] - fatia['numero_inicial']) + 1
                    
                    kit_base = ((num_inicial_fatia - 1) // unidade_de_venda) + 1
                    kit_atual = kit_base + (rodada - 1)
                    
                    ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
                    fim_atual = ini_atual + qtd_cartelas_fatia - 1
                    
                    texto_r = f"Rodada {rodada:02d}"
                    if unidade_de_venda > 1:
                        texto_r += f" (Kit {kit_atual})"
                        
                    add_linha(texto_r, "centro", "normal", True)
                    add_linha(f"{ini_atual} a {fim_atual}", "centro", "normal", False)
                    
                    if fatia.get('numero_inicial2', 0) > 0:
                        add_linha(f"Adicional: {fatia['numero_inicial2']} a {fatia['numero_final2']}", "centro", "normal", False)
            
            add_linha("-------------------------------", "centro", "normal", False)
            
            valor_formatado = f"{valor_total_real:.2f}".replace('.', ',')
            
            add_linha("VALOR PAGO", "centro", "normal", False)
            add_linha(f"R$ {valor_formatado}", "centro", "duplo", False)
            add_linha("===============================", "centro", "normal", False)

        # ==========================================
        # MODO 2: REIMPRESSÃO DO CLIENTE (RESUMO)
        # ==========================================
        elif tipo_reimpressao == 'cliente':
            vendas_cliente = list(db[nome_colecao_venda].find({'id_cliente': id_cliente_int}).sort('numero_inicial', 1))
            if not vendas_cliente:
                return jsonify({'status': 'error', 'message': 'Nenhuma venda encontrada para este cliente.'})

            idColaborador = vendas_cliente[0]['id_colaborador']
            chave_pix_colaborador = "Consulte o Colaborador"
            try:
                if idColaborador != 'N/A':
                     colab_doc_pix = db.colaboradores.find_one({'id_colaborador': int(idColaborador)})
                     if colab_doc_pix and colab_doc_pix.get('chave_pix'):
                         chave_pix_colaborador = colab_doc_pix.get('chave_pix')
            except: pass

            nome_cliente = vendas_cliente[0]['nome_cliente']
            total_unidades = 0
            total_cartelas = 0
            total_valor = 0.0
            
            add_linha("RESUMO DO CLIENTE", "centro", "normal", True)
            add_linha("-------------------------------", "centro", "normal", False)
            add_linha(f"Cliente: {nome_cliente.upper()}", "esquerda", "normal", True)
            add_linha(f"ID Cliente: {id_cliente_int}", "esquerda", "normal", False)
            add_linha(f"Evento: {evento['descricao']}", "esquerda", "normal", False)
            add_linha(f"Gerado por: {session.get('nick', 'N/A')}", "esquerda", "normal", False)
            add_linha("-------------------------------", "centro", "normal", False)

            for venda in vendas_cliente:
                total_unidades += venda['quantidade_unidades']
                total_cartelas += venda['quantidade_cartelas']
                total_valor += safe_float(venda['valor_total'])
                
            add_linha("TOTAL DE UNIDADES", "centro", "normal", False)
            add_linha(str(total_unidades), "centro", "duplo", False)
            add_linha(f"(Total Cartelas: {total_cartelas})", "centro", "normal", False)
            add_linha(" ", "centro", "normal", False)
            
            add_linha("> PERIODOS ADQUIRIDOS <", "centro", "normal", True)
            for venda in vendas_cliente:
                # 🚀 LÓGICA DO COMBO NAS VENDAS TOTAIS DO CLIENTE
                qtd_cartelas = (venda['numero_final'] - venda['numero_inicial']) + 1
                kit_base = ((venda['numero_inicial'] - 1) // unidade_de_venda) + 1
                
                for rodada in range(1, combo_qtde + 1):
                    kit_atual = kit_base + (rodada - 1)
                    ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
                    fim_atual = ini_atual + qtd_cartelas - 1
                    
                    texto_r = f"R{rodada:02d}"
                    if unidade_de_venda > 1:
                        texto_r += f"(K{kit_atual})"
                    add_linha(f"{texto_r}: {ini_atual} a {fim_atual}", "centro", "normal", False)
                
                if venda.get('numero_inicial2', 0) > 0:
                    add_linha(f"Adic: {venda['numero_inicial2']} a {venda['numero_final2']}", "centro", "normal", False)
            
            add_linha("-------------------------------", "centro", "normal", False)
            
            valor_total_formatado = f"{total_valor:.2f}".replace('.', ',')
            add_linha("VALOR TOTAL", "centro", "normal", False)
            add_linha(f"R$ {valor_total_formatado}", "centro", "duplo", False)
            add_linha(" ", "centro", "normal", False)
            
            add_linha("CHAVE PIX", "centro", "normal", True)
            add_linha(chave_pix_colaborador, "centro", "normal", False)
            add_linha("===============================", "centro", "normal", False)

        else:
            return jsonify({'status': 'error', 'message': 'Tipo de reimpressão inválido.'})
        
        # --- RODAPÉ COMUM PARA AMBOS OS MODOS ---
        add_linha("Acesse o Canal do Sorteio", "centro", "normal", False)
        add_linha(link_final_limpo, "centro", "normal", False)
        add_linha(" ", "centro", "normal", False)

        return jsonify({
            'status': 'success',
            'recibo': recibo 
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Erro interno: {e}'})


# --- EXCLUIR VENDA ---
@app.route('/excluir_venda', methods=['POST'])
@login_required
def excluir_venda():
    """
    Exclui uma venda específica. Se for um COMBO, executa a exclusão 
    em cascata em todos os eventos filhos vinculados.
    """
    db = get_vendas_db()
    if db is None:
        return jsonify({'status': 'error', 'message': 'DB Offline'})

    # Sincroniza a trava de segurança com a regra do Front-end (Lite ou Admin)
    parametros = db.parametros.find_one({}) or {}
    venda_lite_ativa = parametros.get('venda_lite') == True
    nivel_usuario = session.get('nivel', 0)

    if not venda_lite_ativa and nivel_usuario < 3:
        return jsonify({'status': 'error', 'message': 'Acesso Negado. Sem permissão para excluir vendas.'})

    try:
        data = request.json
        id_venda_str = data.get('id_venda')
        id_evento_int = int(data.get('id_evento'))

        if not id_venda_str or not id_evento_int:
            return jsonify({'status': 'error', 'message': 'Dados incompletos para exclusão.'})

        # 1. Busca o evento para acessar a árvore de filhos
        evento = db.eventos.find_one({'id_evento': id_evento_int})
        if not evento:
            return jsonify({'status': 'error', 'message': 'Evento não encontrado.'})

        nome_colecao_venda = f"vendas{id_evento_int}"
        
        # 2. Verifica se a venda existe e captura o rastreador do combo
        venda = db[nome_colecao_venda].find_one({'id_venda': id_venda_str})
        if not venda:
            return jsonify({'status': 'error', 'message': 'Venda não encontrada.'})

        id_transacao_combo = venda.get('id_transacao_combo')

        # 3. Executa a exclusão na raiz (Evento Pai)
        result = db[nome_colecao_venda].delete_one({'id_venda': id_venda_str})

        if result.deleted_count == 1:
            # ==========================================================
            # 🚀 MOTOR DE EXCLUSÃO EM CASCATA (COMBO)
            # ==========================================================
            eventos_relacionados = evento.get('eventos_combo_relacionados', [])
            
            # Se a venda faz parte de um combo e existem eventos filhos configurados
            if id_transacao_combo and eventos_relacionados:
                for id_filho in eventos_relacionados:
                    colecao_filho = f"vendas{id_filho}"
                    if colecao_filho in db.list_collection_names():
                        # Elimina todas as fatias que compartilham o mesmo ID de Transação
                        db[colecao_filho].delete_many({'id_transacao_combo': id_transacao_combo})
            
            return jsonify({'status': 'success', 'message': 'Venda excluída com sucesso.'})
        else:
            return jsonify({'status': 'error', 'message': 'Não foi possível excluir o registro.'})

    except Exception as e:
        print(f"Erro ao excluir venda: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Erro interno.'})


# --- ROTA GERAR LISTA (MULTIPLOS DOWNLOADS COM TEMPORIZADOR) ---
@app.route('/gerar_lista_vendas')
@login_required
def gerar_lista_vendas():
    """
    Gera arquivos TXT. Se for Combo, abre tela de temporizador para baixar
    sequencialmente cada rodada como 'periodo.1', 'periodo.2', etc.
    """
    db = get_vendas_db()
    if db is None:
        session['error_message'] = "Erro de conexão com o BD de Vendas."
        return redirect(url_for('consulta_vendas'))

    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')

    id_evento_param = request.args.get('id_evento')
    forcar_download = request.args.get('forcar_download') 
    redirect_url = url_for('consulta_vendas', id_evento=id_evento_param, id_colaborador='ALL')

    if not id_evento_param:
        session['error_message'] = "Erro: ID do Evento não fornecido."
        return redirect(url_for('consulta_vendas'))

    try:
        # Busca inteligente (ID inteiro ou Hash)
        if len(str(id_evento_param)) == 24:
            query_busca = {'_id': try_object_id(id_evento_param)}
        else:
            query_busca = {'id_evento': int(id_evento_param)}

        selected_event = db.eventos.find_one(query_busca, {
            'id_evento': 1, 'unidade_de_venda': 1, 'numero_maximo': 1,
            'tipo_de_cartela': 1, 'valor_de_venda': 1, 'descricao': 1, 
            'premio_quadra': 1, 'quantidade_de_linhas': 1, 'premio_linha': 1, 
            'premio_faltaum': 1, 'premio_bingo': 1, 'premio_segundobingo': 1,
            'premio_acumulado': 1, 'bola_tope_acumulado': 1,
            'combo_qtde': 1, 'id_evento_principal_combo': 1
        })

        if not selected_event:
            selected_event = db.eventos.find_one({'id_evento': int(id_evento_param)})

        if not selected_event:
            print(f"DEBUG: Evento {id_evento_param} não encontrado no BD.") 
            session['error_message'] = "Erro: Evento não encontrado."
            return redirect(redirect_url)

        # Trava: Bloqueia download direto por filho de combo
        if selected_event.get('id_evento_principal_combo') and not forcar_download:
            id_pai = selected_event.get('id_evento_principal_combo')
            session['error_message'] = f"❌ Download bloqueado. Use o Evento Principal (ID: {id_pai})."
            return redirect(redirect_url)

        combo_qtde = int(selected_event.get('combo_qtde', 1))
        id_evento_int = selected_event.get('id_evento')

        # PARTE 1: Temporizador para Combos
        if combo_qtde > 1 and not forcar_download:
            eventos_ordenados = list(db.eventos.find(
                {'$or': [{'id_evento': id_evento_int}, {'id_evento_principal_combo': id_evento_int}]},
                {'id_evento': 1}
            ).sort([
                ('id_evento', pymongo.ASCENDING), 
                ('numero_inicial', pymongo.ASCENDING)
            ]))            
            mapa_ordem = {ev['id_evento']: i + 1 for i, ev in enumerate(eventos_ordenados)}
            ids_para_baixar = [ev['id_evento'] for ev in eventos_ordenados]

            return render_template_string("""
            <!DOCTYPE html>
            <html lang="pt-br"><head><meta charset="UTF-8"><script src="https://cdn.tailwindcss.com"></script></head>
            <body class="bg-gray-100 flex items-center justify-center h-screen">
                <div class="bg-white p-8 rounded-xl shadow-2xl text-center max-w-md w-full border-t-4 border-blue-600">
                    <h2 class="text-2xl font-black text-blue-800 mb-4">Exportando Rodadas</h2>
                    <div class="mb-4"><span id="texto" class="font-bold">Preparando...</span></div>
                    <div class="w-full bg-gray-200 h-4 rounded-full"><div id="bar" class="bg-blue-600 h-4 rounded-full" style="width:0%"></div></div>
                </div>
                <script>
                    const ids = {{ ids | tojson }};
                    const mapa = {{ mapa | tojson }};
                    let i = 0;
                    function prox() {
                        if(i < ids.length) {
                            const id = ids[i];
                            document.getElementById('texto').innerText = `Baixando período ${mapa[id]}...`;
                            const iframe = document.createElement('iframe');
                            iframe.style.display = 'none';
                            iframe.src = `{{ url_for('gerar_lista_vendas') }}?id_evento=${id}&forcar_download=1&ordem_rodada=${mapa[id]}`;
                            document.body.appendChild(iframe);
                            i++;
                            document.getElementById('bar').style.width = (i/ids.length)*100 + '%';
                            setTimeout(prox, 1500);
                        } else {
                            window.location.href = '{{ redirect_url }}';
                        }
                    }
                    setTimeout(prox, 500);
                </script>
            </body></html>""", ids=ids_para_baixar, mapa=mapa_ordem, redirect_url=redirect_url)

        # PARTE 2: Geração do Ficheiro TXT
        nome_colecao_venda = f"vendas{id_evento_int}"
        ordem_rodada = request.args.get('ordem_rodada', None)
        file_name = f"periodo.{ordem_rodada}" if ordem_rodada else f"periodo.{id_evento_int}"
        
        io_buffer = io.StringIO()
        header = f"{selected_event.get('unidade_de_venda', 6)}!{selected_event.get('numero_maximo', 12000)}!{selected_event.get('tipo_de_cartela', 15)}!{safe_float(selected_event.get('valor_de_venda', 0))}!{selected_event.get('descricao', 'N/A')}!{safe_float(selected_event.get('premio_quadra', 0))}!{selected_event.get('quantidade_de_linhas', 1)}!{safe_float(selected_event.get('premio_linha', 0))}!{safe_float(selected_event.get('premio_faltaum', 0))}!{safe_float(selected_event.get('premio_bingo', 0))}!{safe_float(selected_event.get('premio_segundobingo', 0))}!{safe_float(selected_event.get('premio_acumulado', 0))}!{selected_event.get('bola_tope_acumulado', 0)}!{nome_sala}\r\n"
        io_buffer.write(header)

        vendas = list(db[nome_colecao_venda].find({'id_evento': id_evento_int}).sort('numero_inicial', pymongo.ASCENDING))
        if vendas:
            clientes_map = {c['id_cliente']: c for c in db.clientes.find({'id_cliente': {'$in': [v.get('id_cliente') for v in vendas]}})}
            for v in vendas:
                c_info = clientes_map.get(v.get('id_cliente'), {})
                line = f"{v.get('numero_inicial', 0)}!{v.get('numero_final', 0)}!{v.get('numero_inicial2', 0)}!{v.get('numero_final2', 0)}!{v.get('id_cliente') or 'N/A'}!{v.get('nome_cliente', 'N/A')}!{v.get('id_colaborador', 'N/A')}!{v.get('nick_colaborador', 'N/A')}!{c_info.get('telefone', 'N/A')}!{c_info.get('cidade', 'N/A')}\r\n"
                io_buffer.write(line)

        return Response(io_buffer.getvalue().encode('latin-1', 'ignore'), mimetype="text/plain", headers={"Content-Disposition": f"attachment;filename={file_name}"})

    except Exception as e:
        import traceback; traceback.print_exc()
        return redirect(redirect_url)


# --- ROTAS DE GERAÇÃO DE PDF E ARQUIVOS ---
@app.route('/gerar_cartelas_pdf_25')
#@login_required
def gerar_cartelas_pdf_25():
    """
    Gera PDF de cartelas de 25 números.
    Layout: 6 cartelas por página (2 colunas x 3 linhas).
    Cabeçalho: Nome da Sala + Descrição/Data do Evento.
    INCLUI MATEMÁTICA DE COMBO (Fase 1).
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

        # 🚀 VARIÁVEIS DO COMBO
        combo_qtde = int(evento.get('combo_qtde', 1))
        unidade_de_venda = int(evento.get('unidade_de_venda', 1))

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
        
        # Injeta textos para o header() nativo
        pdf.nome_sala = nome_sala
        pdf.infos_evento = infos_evento
        
        pdf.alias_nb_pages()
        
        # --- CONFIGURAÇÃO DE LAYOUT (6 por página) ---
        margem_x = 15
        margem_top_inicial = 30 # 🚀 Ajustado de 25 para 30 para abrir espaço para o título da rodada
        largura_cartela = 70
        altura_cartela_total = 64 
        
        espaco_horizontal = 10
        espaco_vertical = 12 
        
        # Gera as coordenadas para 6 cartelas: (X, Y)
        posicoes = []
        for linha in range(3): 
            y = margem_top_inicial + (linha * (altura_cartela_total + espaco_vertical))
            posicoes.append((margem_x, y))
            posicoes.append((margem_x + largura_cartela + espaco_horizontal, y))
            
        # ==============================================================================
        # 🚀 MATEMÁTICA DO COMBO E GERAÇÃO DAS PÁGINAS
        # ==============================================================================
        qtd_cartelas_compradas = (numero_final_pdf - numero_inicial_pdf) + 1
        kit_base_inicial = ((numero_inicial_pdf - 1) // unidade_de_venda) + 1

        for rodada in range(1, combo_qtde + 1):
            # Calcula o kit e o intervalo exato desta rodada
            kit_atual = kit_base_inicial + (rodada - 1)
            ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
            fim_atual = ini_atual + qtd_cartelas_compradas - 1

            # A cada nova rodada (combo), forçamos uma nova página zerando o índice
            cartela_idx_na_pagina = 0

            for num_cartela in range(ini_atual, fim_atual + 1):
                
                if cartela_idx_na_pagina == 0:
                    pdf.add_page()
                    
                    # 🚀 INJETA O CABEÇALHO DA RODADA NO TOPO DA PÁGINA
                    pdf.set_font('Arial', 'B', 12)
                    pdf.set_text_color(180, 0, 0) # Cor vermelha elegante
                    
                    texto_destaque = f"RODADA: {rodada:02d}"
                    if unidade_de_venda > 1:
                        texto_destaque += f"   |   KIT: {kit_atual}"
                        
                    # Imprime o texto centralizado na altura Y=22 (logo abaixo do Header principal)
                    pdf.set_y(22)
                    pdf.cell(0, 5, texto_destaque, 0, 1, 'C')
                    pdf.set_text_color(0, 0, 0) # Reseta a cor para preto

                # Busca e desenha a cartela
                dados_cartela = buscar_dados_cartela_2d(num_cartela, TIPO_CARTELA)
                
                if not dados_cartela:
                     print(f"Aviso: Dados da cartela {num_cartela} (tipo 25) não encontrados.")
                else:
                    if cartela_idx_na_pagina < len(posicoes):
                        pos_x, pos_y = posicoes[cartela_idx_na_pagina]
                        pdf.desenhar_cartela(num_cartela, dados_cartela, pos_x, pos_y)
                
                cartela_idx_na_pagina += 1
                
                # Se encheu a página, reseta para a próxima iterar `pdf.add_page()`
                if cartela_idx_na_pagina >= len(posicoes):
                    cartela_idx_na_pagina = 0
        # ==============================================================================
        
        pdf_output = bytes(pdf.output()) 
        
        nick_limpo = clean_for_filename(nome_cliente)
        nome_arquivo = f'{nick_limpo}_eve{id_evento}_25nums_Kits{kit_base_inicial}_{kit_atual}.pdf'
        
        response = make_response(pdf_output)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
        
        return response

    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar PDF 25: {e}")
        import traceback
        traceback.print_exc()
        return f"Erro interno: {e}"


# Rota para cartelas de 15 números
@app.route('/gerar_cartelas_pdf_15')
#@login_required
def gerar_cartelas_pdf_15():
    """
    Gera PDF de cartelas de 15 números.
    Layout: 10 cartelas por página (2 colunas x 5 linhas).
    Cabeçalho: Nome da Sala + Descrição/Data do Evento.
    INCLUI MATEMÁTICA DE COMBO (Fase 1).
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

        # 🚀 VARIÁVEIS DO COMBO
        combo_qtde = int(evento.get('combo_qtde', 1))
        unidade_de_venda = int(evento.get('unidade_de_venda', 1))

        # Prepara textos do cabeçalho
        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        descricao_evento = evento.get('descricao', '')
        
        # Formata data e hora
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
             return f"Erro: Arquivo 'cartelas.15' não encontrado no servidor em {caminho_check}."
        
        # Configura PDF
        pdf = PDFCartelas(orientation='P', unit='mm', format='A4') 
        
        # Injeta os textos personalizados na instância do PDF para o header() usar
        pdf.nome_sala = nome_sala
        pdf.infos_evento = infos_evento
        
        pdf.alias_nb_pages()
        
        # --- CONFIGURAÇÃO DE LAYOUT (10 por página) ---
        margem_x = 15
        margem_top_inicial = 32 # 🚀 Ajustado para 32 para abrir espaço para o título da rodada sem cortar o fundo
        largura_cartela = 70
        altura_cartela_total = 38 
        
        espaco_horizontal = 10
        espaco_vertical = 6 
        
        # Gera as coordenadas para 10 cartelas: (X, Y)
        posicoes = []
        for linha in range(5): # 0 a 4
            y = margem_top_inicial + (linha * (altura_cartela_total + espaco_vertical))
            posicoes.append((margem_x, y))
            posicoes.append((margem_x + largura_cartela + espaco_horizontal, y))
            
        # ==============================================================================
        # 🚀 MATEMÁTICA DO COMBO E GERAÇÃO DAS PÁGINAS
        # ==============================================================================
        qtd_cartelas_compradas = (numero_final_pdf - numero_inicial_pdf) + 1
        kit_base_inicial = ((numero_inicial_pdf - 1) // unidade_de_venda) + 1

        for rodada in range(1, combo_qtde + 1):
            # Calcula o kit e o intervalo exato desta rodada
            kit_atual = kit_base_inicial + (rodada - 1)
            ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
            fim_atual = ini_atual + qtd_cartelas_compradas - 1

            # Zera o índice para forçar uma nova página no início da rodada
            cartela_idx_na_pagina = 0

            for num_cartela in range(ini_atual, fim_atual + 1):
                
                if cartela_idx_na_pagina == 0:
                    pdf.add_page()
                    
                    # 🚀 INJETA O CABEÇALHO DA RODADA NO TOPO DA PÁGINA
                    pdf.set_font('Arial', 'B', 12)
                    pdf.set_text_color(180, 0, 0) # Cor vermelha elegante
                    
                    texto_destaque = f"RODADA: {rodada:02d}"
                    if unidade_de_venda > 1:
                        texto_destaque += f"   |   KIT: {kit_atual}"
                        
                    # Imprime o texto centralizado na altura Y=22
                    pdf.set_y(22)
                    pdf.cell(0, 5, texto_destaque, 0, 1, 'C')
                    pdf.set_text_color(0, 0, 0) # Reseta cor

                # Busca e desenha a cartela (15 números)
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
        # ==============================================================================
        
        pdf_output = bytes(pdf.output()) 
        
        nick_limpo = clean_for_filename(nome_cliente)
        # Nome do arquivo reflete os kits gerados
        nome_arquivo = f'{nick_limpo}_eve{id_evento}_15nums_Kits{kit_base_inicial}_{kit_atual}.pdf'
        
        response = make_response(pdf_output)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
        
        return response

    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar PDF 15: {e}")
        import traceback
        traceback.print_exc()
        return f"Erro interno: {e}"


@app.route('/gerar_pdf_lote_hibrido')
@login_required
def gerar_pdf_lote_hibrido():
    """
    Gera PDF de cartelas (15 ou 25) suportando Lotes Híbridos (Kits Espalhados ou Sequenciais).
    Lê diretamente da base de dados usando o id_venda para apanhar todas as fatias da compra.
    """
    db = get_vendas_db() 
    if db is None: 
        return "Erro de Conexão: DB Offline.", 500

    try:
        id_venda = request.args.get('id_venda')
        id_evento = int(request.args.get('id_evento', 0))
        tipo_cartela_str = request.args.get('tipo_cartela', '15')
        nome_cliente = request.args.get('nome_cliente', 'cliente')
        
        if not id_venda or not id_evento:
            return "Erro: id_venda e id_evento são obrigatórios."
            
        TIPO_CARTELA = int(tipo_cartela_str)

        # 1. Busca os Dados do Evento
        evento = db.eventos.find_one({'id_evento': id_evento})
        if not evento:
            return "Erro: Evento não encontrado."

        combo_qtde = int(evento.get('combo_qtde', 1))
        unidade_de_venda = int(evento.get('unidade_de_venda', 1))

        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        descricao_evento = evento.get('descricao', '')
        
        data_str = evento.get('data_evento', '')
        hora_str = evento.get('hora_evento', '')
        if '-' in str(data_str):
            try:
                dt = datetime.strptime(str(data_str), '%Y-%m-%d')
                data_str = dt.strftime('%d/%m/%Y')
            except: pass
            
        infos_evento = f"{descricao_evento} - {data_str} as {hora_str}"

        # 2. Verifica a existência do ficheiro TXT do layout
        caminho_check = os.path.join(CARTELAS_FOLDER, f'cartelas.{TIPO_CARTELA}')
        if not os.path.exists(caminho_check):
             return f"Erro: Arquivo 'cartelas.{TIPO_CARTELA}' não encontrado no servidor."

        # 3. Busca todas as fatias da venda (Kits) no Banco de Dados
        nome_colecao_venda = f"vendas{id_evento}"
        fatias_venda = list(db[nome_colecao_venda].find({'id_venda': id_venda}).sort('numero_inicial', 1))
        
        if not fatias_venda:
            return f"Erro: Nenhuma venda encontrada para o ID {id_venda}."

        # Extrai os números iniciais base da compra
        numeros_iniciais_base = [fatia['numero_inicial'] for fatia in fatias_venda]

        # 4. Configura as métricas do PDF conforme o Tipo (15 ou 25)
        pdf = PDFCartelas(orientation='P', unit='mm', format='A4') 
        pdf.nome_sala = nome_sala
        pdf.infos_evento = infos_evento
        pdf.alias_nb_pages()

        margem_x = 15
        if TIPO_CARTELA == 15:
            margem_top_inicial = 32
            largura_cartela = 70
            altura_cartela_total = 38 
            espaco_horizontal = 10
            espaco_vertical = 6 
            # 10 posições (2 colunas x 5 linhas)
            posicoes = [(margem_x + (col * (largura_cartela + espaco_horizontal)), margem_top_inicial + (linha * (altura_cartela_total + espaco_vertical))) for linha in range(5) for col in range(2)]
        else:
            margem_top_inicial = 30
            largura_cartela = 70
            altura_cartela_total = 64 
            espaco_horizontal = 10
            espaco_vertical = 12 
            # 6 posições (2 colunas x 3 linhas)
            posicoes = [(margem_x + (col * (largura_cartela + espaco_horizontal)), margem_top_inicial + (linha * (altura_cartela_total + espaco_vertical))) for linha in range(3) for col in range(2)]

        # ==============================================================================
        # 🚀 MOTOR DE IMPRESSÃO (MATRIZ RODADAS X KITS ESPALHADOS)
        # ==============================================================================
        for rodada in range(1, combo_qtde + 1):
            
            # Sempre que muda a rodada, queremos que ela comece numa página nova limpa
            cartela_idx_na_pagina = 0
            
            for num_inicial_base in numeros_iniciais_base:
                # Descobre qual kit estamos a processar
                kit_base = ((num_inicial_base - 1) // unidade_de_venda) + 1
                kit_atual = kit_base + (rodada - 1)
                
                # Descobre a faixa de cartelas deste kit na rodada atual
                ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
                fim_atual = ini_atual + unidade_de_venda - 1

                for num_cartela in range(ini_atual, fim_atual + 1):
                    
                    if cartela_idx_na_pagina == 0:
                        pdf.add_page()
                        
                        # INJETA O CABEÇALHO DA RODADA
                        pdf.set_font('Arial', 'B', 12)
                        pdf.set_text_color(180, 0, 0)
                        
                        texto_destaque = f"RODADA: {rodada:02d}"
                        # Mostra o kit apenas se as cartelas não forem vendidas à unidade
                        if unidade_de_venda > 1:
                            texto_destaque += f"   |   KIT: {kit_atual}"
                            
                        pdf.set_y(22 if TIPO_CARTELA == 15 else 22) # Altura padrão abaixo do header
                        pdf.cell(0, 5, texto_destaque, 0, 1, 'C')
                        pdf.set_text_color(0, 0, 0)

                    # Busca e desenha a cartela
                    dados_cartela = buscar_dados_cartela_2d(num_cartela, TIPO_CARTELA)
                    
                    if not dados_cartela:
                         print(f"Aviso: Dados da cartela {num_cartela} não encontrados.")
                    else:
                        if cartela_idx_na_pagina < len(posicoes):
                            pos_x, pos_y = posicoes[cartela_idx_na_pagina]
                            if TIPO_CARTELA == 15:
                                pdf.desenhar_cartela_15(num_cartela, dados_cartela, pos_x, pos_y)
                            else:
                                pdf.desenhar_cartela(num_cartela, dados_cartela, pos_x, pos_y)
                    
                    cartela_idx_na_pagina += 1
                    
                    if cartela_idx_na_pagina >= len(posicoes):
                        cartela_idx_na_pagina = 0

        # ==============================================================================
        
        pdf_output = bytes(pdf.output()) 
        
        nick_limpo = clean_for_filename(nome_cliente)
        # Nome do ficheiro mais genérico já que pode conter múltiplos kits dispersos
        nome_arquivo = f'{nick_limpo}_eve{id_evento}_{TIPO_CARTELA}nums_Lote.pdf'
        
        response = make_response(pdf_output)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
        
        return response

    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar PDF Lote Híbrido: {e}")
        import traceback
        traceback.print_exc()
        return f"Erro interno: {e}"


@app.route('/imprimir_cartelas_58mm_15')
@login_required
def imprimir_cartelas_58mm_15():
    """ Rota exclusiva para impressão térmica 58mm de Cartelas 3x5 (15 dezenas) via JSON 
        INCLUI LÓGICA DE COMBO E AVANÇO DE PAPEL ENTRE RODADAS """
    db = get_vendas_db()
    if db is None: return jsonify({"erro": "Banco de dados offline"}), 500

    try:
        numero_inicial = int(request.args.get('numero_inicial', 0))
        numero_final = int(request.args.get('numero_final', 0))
        id_evento_raw = request.args.get('id_evento', 0)
        nome_cliente = request.args.get('nome_cliente', 'Cliente')

        if numero_inicial > numero_final or numero_inicial == 0:
            return jsonify({"erro": "Numeração inválida"}), 400

        try:
            id_evento = int(id_evento_raw)
            query_evento = {'id_evento': id_evento}
        except (ValueError, TypeError):
            from bson.objectid import ObjectId
            id_evento = str(id_evento_raw)
            query_evento = {'_id': ObjectId(id_evento)} if len(id_evento) == 24 else {'id_evento': id_evento}

        evento = db.eventos.find_one(query_evento)
        if not evento: return jsonify({"erro": "Evento não encontrado"}), 404

        # 🚀 VARIÁVEIS DO COMBO
        combo_qtde = int(evento.get('combo_qtde', 1))
        unidade_de_venda = int(evento.get('unidade_de_venda', 1))

        imprime_qr = g.parametros_globais.get('imprimir_qrcode_na_venda', True)
        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        http_apk = g.parametros_globais.get('http_apk', '')
        tipo_cartela = 15 

        data_str = evento.get('data_evento', '')
        if '-' in str(data_str):
            try: data_str = datetime.strptime(str(data_str), '%Y-%m-%d').strftime('%d/%m/%Y')
            except: pass
            
        data_hora_formatada = f"{data_str} as {evento.get('hora_evento', '')}"

        # 1. Cria a estrutura do pacote (Contrato JSON)
        recibo = {
            "config": { "avanco_linhas": 0, "cortar_papel": False },
            "linhas": []
        }

        # ==========================================
        # 1. CABEÇALHO GERAL (Uma única vez no topo)
        # ==========================================
        recibo["linhas"].append({"texto": "-------------------------------", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": nome_sala, "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": evento.get('descricao', ''), "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": data_hora_formatada, "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": f"Cliente: {nome_cliente.upper()}", "alinhamento": "centro", "tamanho": "normal", "negrito": True})
        recibo["linhas"].append({"texto": "-------------------------------", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

        # ==========================================
        # 2. MOTOR MATEMÁTICO DO COMBO
        # ==========================================
        qtd_cartelas_compradas = (numero_final - numero_inicial) + 1
        kit_base_inicial = ((numero_inicial - 1) // unidade_de_venda) + 1

        for rodada in range(1, combo_qtde + 1):
            kit_atual = kit_base_inicial + (rodada - 1)
            ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
            fim_atual = ini_atual + qtd_cartelas_compradas - 1

            # 🚀 CABEÇALHO DA RODADA (Impresso a cada novo kit do combo)
            if combo_qtde > 1:
                texto_rodada = f"RODADA {rodada:02d}"
                if unidade_de_venda > 1:
                    texto_rodada += f" - KIT {kit_atual}"
                
                recibo["linhas"].append({"texto": texto_rodada, "alinhamento": "centro", "tamanho": "duplo", "negrito": True})
                recibo["linhas"].append({"texto": "===============================", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

            # --- LAÇO GERADOR (Cartelas da Rodada Atual) ---
            for num_cartela in range(ini_atual, fim_atual + 1):
                dados_matriz = buscar_dados_cartela_2d(num_cartela, tipo_cartela)
                if not dados_matriz:
                    continue
                    
                # --- IDENTIFICAÇÃO DA CARTELA ---
                recibo["linhas"].append({"texto": f"Ctla. {num_cartela}", "alinhamento": "centro", "tamanho": "largura", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

                # --- DEZENAS (Matriz da cartela de 15) ---
                for linha_matriz in dados_matriz:
                    linha_formatada = " ".join([f"{str(n).zfill(2)}" for n in linha_matriz])
                    recibo["linhas"].append({"texto": linha_formatada, "alinhamento": "centro", "tamanho": "duplo", "negrito": False})

                # Espaçamento e linha pontilhada entre cartelas do MESMO kit
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": "- - - - - - - - - - - - - - - -", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

            # 🚀 MARCA DE CORTE E AVANÇO (Se for combo e não for a última rodada)
            if combo_qtde > 1 and rodada < combo_qtde:
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": "✂ - - CORTE AQUI - - ✂", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

        # ==========================================
        # 3. RODAPÉ GERAL (Uma única vez no final)
        # ==========================================
        recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        if imprime_qr and http_apk:
            recibo["linhas"].append({"texto": "Acompanhe o Sorteio no Link::", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
            recibo["linhas"].append({"texto": http_apk, "alinhamento": "centro", "tamanho": "normal", "negrito": False})
            recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
            
        recibo["linhas"].append({"texto": "Boa Sorte!", "alinhamento": "centro", "tamanho": "largura", "negrito": False})

        # Retorna o JSON limpo para o front-end processar e mandar para o Android/PC
        return jsonify(recibo)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"erro": f"Erro interno: {e}"}), 500

# vendas 
@app.route('/api/venda_bluetooth_json')
@login_required
def api_venda_bluetooth_json():
    """ Rota que gera o JSON para o App Bluetooth Print """
    db = get_vendas_db()
    if db is None: return jsonify({"error": "DB Offline"}), 500

    try:
        # 1. Pegamos os parâmetros (exatamente como na sua rota original)
        numero_inicial = int(request.args.get('numero_inicial', 0))
        numero_final = int(request.args.get('numero_final', 0))
        id_evento_raw = request.args.get('id_evento', 0)
        nome_cliente = request.args.get('nome_cliente', 'Cliente')

        # 2. Busca o Evento e Parâmetros Globais
        evento = db.eventos.find_one({'id_evento': id_evento_raw}) # Ajuste se for ObjectId
        if not evento: return jsonify({"error": "Evento não encontrado"}), 404

        nome_sala = g.parametros_globais.get('nome_sala', 'ARKKANTOS BINGO')
        imprime_qr = g.parametros_globais.get('imprimir_qrcode_na_venda', True)

        # 3. Montagem do JSON para o App
        dados_final = []

        # Cabeçalho da Sala
        dados_final.append({
            "type": 0, "content": f"{nome_sala}\n", 
            "bold": 1, "align": 1, "format": 2 # Grande e Centralizado
        })

        # Detalhes do Evento
        dados_final.append({
            "type": 0, 
            "content": f"Evento: {evento.get('descricao', '')}\nData: {evento.get('data_evento')} {evento.get('hora_evento')}\nCliente: {nome_cliente}\n",
            "bold": 0, "align": 0, "format": 0
        })

        dados_final.append({"type": 0, "content": "--------------------------------\n", "align": 1})

        # 4. Loop de busca e formatação das Cartelas (15 dezenas)
        for num_cartela in range(numero_inicial, numero_final + 1):
            dados_matriz = buscar_dados_cartela_2d(num_cartela, 15)
            
            if dados_matriz:
                # Título da Cartela
                dados_final.append({
                    "type": 0, "content": f"CARTELA: {num_cartela:04d}", 
                    "bold": 1, "align": 1, "format": 3 # Largura dupla
                })

                # Formata a matriz 3x5 para texto
                texto_matriz = ""
                for linha in dados_matriz:
                    # Formata cada número com 2 dígitos e espaço
                    linha_str = "  ".join([f"{int(n):02d}" for n in linha])
                    texto_matriz += f"{linha_str}\n"
                
                dados_final.append({
                    "type": 0, "content": texto_matriz, 
                    "bold": 0, "align": 1, "format": 0
                })
                dados_final.append({"type": 0, "content": "- - - - - - - - - - - - - - - -\n", "align": 1})

        # 5. QR Code de Validação (Se ativado)
        if imprime_qr:
            dados_final.append({
                "type": 3, 
                "value": f"https://arkkantos.com.br/validar/{id_evento_raw}", # Link do seu sistema
                "size": 35, "align": 1
            })

        # Rodapé e corte
        dados_final.append({
            "type": 0, "content": "\nBOA SORTE!\n\n\n\n", "align": 1
        })

        return jsonify(dados_final)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


from flask import jsonify # Certifique-se de que o jsonify está importado no topo do arquivo

@app.route('/imprimir_cartelas_58mm_25')
@login_required
def imprimir_cartelas_58mm_25():
    """ Rota exclusiva para impressão térmica 58mm de Cartelas 5x5 (25 dezenas) via JSON 
        INCLUI LÓGICA DE COMBO E AVANÇO DE PAPEL ENTRE RODADAS """
    db = get_vendas_db()
    if db is None: return jsonify({"erro": "Banco de dados offline"}), 500

    try:
        numero_inicial = int(request.args.get('numero_inicial', 0))
        numero_final = int(request.args.get('numero_final', 0))
        id_evento_raw = request.args.get('id_evento', 0)
        nome_cliente = request.args.get('nome_cliente', 'Cliente')

        if numero_inicial > numero_final or numero_inicial == 0:
            return jsonify({"erro": "Numeração inválida"}), 400

        try:
            id_evento = int(id_evento_raw)
            query_evento = {'id_evento': id_evento}
        except (ValueError, TypeError):
            from bson.objectid import ObjectId
            id_evento = str(id_evento_raw)
            query_evento = {'_id': ObjectId(id_evento)} if len(id_evento) == 24 else {'id_evento': id_evento}

        evento = db.eventos.find_one(query_evento)
        if not evento: return jsonify({"erro": "Evento não encontrado"}), 404

        # 🚀 VARIÁVEIS DO COMBO
        combo_qtde = int(evento.get('combo_qtde', 1))
        unidade_de_venda = int(evento.get('unidade_de_venda', 1))

        imprime_qr = g.parametros_globais.get('imprimir_qrcode_na_venda', True)
        nome_sala = g.parametros_globais.get('nome_sala', 'BINGO')
        http_apk = g.parametros_globais.get('http_apk', '')
        tipo_cartela = 25 # Define a busca estrita para dezenas da matriz 5x5

        data_str = evento.get('data_evento', '')
        if '-' in str(data_str):
            try: data_str = datetime.strptime(str(data_str), '%Y-%m-%d').strftime('%d/%m/%Y')
            except: pass
            
        data_hora_formatada = f"{data_str} as {evento.get('hora_evento', '')}"

        # 1. Cria a estrutura do pacote (Contrato JSON)
        recibo = {
            "config": { "avanco_linhas": 0, "cortar_papel": False },
            "linhas": []
        }

        # ==========================================
        # 1. CABEÇALHO GERAL (Uma única vez no topo)
        # ==========================================
        recibo["linhas"].append({"texto": "-------------------------------", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": nome_sala, "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": evento.get('descricao', ''), "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": data_hora_formatada, "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        recibo["linhas"].append({"texto": f"Cliente: {nome_cliente.upper()}", "alinhamento": "centro", "tamanho": "normal", "negrito": True})
        recibo["linhas"].append({"texto": "-------------------------------", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

        # ==========================================
        # 2. MOTOR MATEMÁTICO DO COMBO
        # ==========================================
        qtd_cartelas_compradas = (numero_final - numero_inicial) + 1
        kit_base_inicial = ((numero_inicial - 1) // unidade_de_venda) + 1

        for rodada in range(1, combo_qtde + 1):
            kit_atual = kit_base_inicial + (rodada - 1)
            ini_atual = ((kit_atual - 1) * unidade_de_venda) + 1
            fim_atual = ini_atual + qtd_cartelas_compradas - 1

            # 🚀 CABEÇALHO DA RODADA (Impresso a cada novo kit do combo)
            if combo_qtde > 1:
                texto_rodada = f"RODADA {rodada:02d}"
                if unidade_de_venda > 1:
                    texto_rodada += f" - KIT {kit_atual}"
                
                recibo["linhas"].append({"texto": texto_rodada, "alinhamento": "centro", "tamanho": "duplo", "negrito": True})
                recibo["linhas"].append({"texto": "===============================", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

            # --- LAÇO GERADOR (Cartelas da Rodada Atual) ---
            for num_cartela in range(ini_atual, fim_atual + 1):
                dados_matriz = buscar_dados_cartela_2d(num_cartela, tipo_cartela)
                if not dados_matriz:
                    continue
                    
                # --- IDENTIFICAÇÃO EM DESTAQUE ---
                recibo["linhas"].append({"texto": f"Ctla.  {num_cartela}", "alinhamento": "centro", "tamanho": "largura", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

                # --- DEZENAS DO BINGO (Matriz 5x5) ---
                for linha_matriz in dados_matriz:
                    # Formata cada número para ter sempre 2 dígitos preenchidos com zero à esquerda
                    linha_formatada = " ".join([f"{str(n).zfill(2)}" for n in linha_matriz])
                    
                    # Imprime a linha de dezenas centralizada e com tamanho de fonte ampliado (duplo)
                    recibo["linhas"].append({"texto": linha_formatada, "alinhamento": "centro", "tamanho": "duplo", "negrito": False})

                # Espaçamento e linha de corte suave entre cartelas do MESMO kit
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": "- - - - - - - - - - - - - - - -", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

            # 🚀 MARCA DE CORTE E AVANÇO (Se for combo e não for a última rodada)
            if combo_qtde > 1 and rodada < combo_qtde:
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": "✂ - - CORTE AQUI - - ✂", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
                recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})

        # ==========================================
        # 3. RODAPÉ GERAL (Uma única vez no final)
        # ==========================================
        recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
        if imprime_qr and http_apk:
            recibo["linhas"].append({"texto": "Acompanhe o Sorteio no Link:", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
            recibo["linhas"].append({"texto": http_apk, "alinhamento": "centro", "tamanho": "normal", "negrito": True})
            recibo["linhas"].append({"texto": " ", "alinhamento": "centro", "tamanho": "normal", "negrito": False})
            
        recibo["linhas"].append({"texto": "Boa Sorte!", "alinhamento": "centro", "tamanho": "largura", "negrito": False})
        
        # Retorna o payload estruturado para consumo da função assíncrona do front-end
        return jsonify(recibo)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"erro": f"Erro interno: {e}"}), 500


def registrar_transacao_cliente(db, id_cliente, valor, tipo, descricao, id_evento=None, id_venda=None, id_colaborador=None):
    """
    MOTOR FINANCEIRO BLINDADO (ATÔMICO)
    - Garante que o saldo não corrompa em compras simultâneas.
    - Exige um tipo de transação rigorosamente válido no Livro-Razão (Passo 1.2).
    - Guarda rastro do operador, natureza e o "Antes e Depois" da conta.
    """
    # 1. Dicionário Rigoroso do Livro-Razão
    tipos_entrada = ['compra_credito_pix', 'credito_manual_admin', 'premio_bingo', 'premio_sorte_extra', 'estorno_saque', 'estorno_geral']
    tipos_saida = ['compra_cartela', 'compra_sorte_extra', 'saque_solicitado', 'debito_manual_admin']
    
    if tipo not in tipos_entrada and tipo not in tipos_saida:
        print(f"[ALERTA CRÍTICO] Tentativa de fraude ou erro de código: Tipo '{tipo}' rejeitado.")
        return False, "Tipo de transação inválido."

    try:
        # 2. Trava de Segurança Matemática (Garante o sinal do valor e a Natureza)
        valor_float = float(valor)
        if valor_float == 0:
            return True, "Transação de valor zero ignorada."

        if tipo in tipos_saida and valor_float > 0:
            valor_float = -abs(valor_float)  # Saídas DEVEM obrigatoriamente subtrair (-)
            natureza = "SAIDA"
        elif tipo in tipos_entrada and valor_float < 0:
            valor_float = abs(valor_float)   # Entradas DEVEM obrigatoriamente somar (+)
            natureza = "ENTRADA"
        else:
            natureza = "ENTRADA" if valor_float > 0 else "SAIDA"

        # Conversão perfeita para sistema monetário
        valor_decimal = Decimal128(str(valor_float))

        # 3. Operação ATÔMICA de atualização de saldo
        cliente_atualizado = db.clientes.find_one_and_update(
            {'id_cliente': id_cliente},
            {
                '$inc': {'saldo_atual': valor_decimal},
                '$set': {'ultima_movimentacao': hora_brasil()} # Mantido da sua versão original
            },
            return_document=ReturnDocument.AFTER
        )

        if not cliente_atualizado:
            raise Exception(f"Cliente ID {id_cliente} não encontrado para transação.")

        # 4. Matemática Reversa Precisa (Calcula o que havia antes para a auditoria)
        saldo_posterior_float = safe_float(cliente_atualizado.get('saldo_atual', 0.00))
        saldo_anterior_float = saldo_posterior_float - valor_float

        # 5. Gravação do Histórico no Livro-Razão Completo
        transacao_doc = {
            'id_transacao': f"TRX{int(time.time()*1000)}",
            'id_cliente': id_cliente,
            'data_hora': hora_brasil(),
            'natureza': natureza,           # ENTRADA ou SAIDA
            'tipo': tipo,                   # A categoria rigorosa
            'valor': valor_decimal,
            'saldo_anterior': Decimal128(str(saldo_anterior_float)),
            'saldo_posterior': Decimal128(str(saldo_posterior_float)),
            'descricao': descricao,
            'id_evento': id_evento,
            'id_venda': id_venda,
            'id_colaborador': id_colaborador, # Para comissões futuras
            'registrado_por': session.get('nick', 'Sistema') # Mantido da sua versão original
        }
        
        db.transacoes_clientes.insert_one(transacao_doc)
        
        return True, "Sucesso"
        
    except Exception as e:
        print(f"❌ [FALHA CRÍTICA FINANCEIRA] Erro atômico na transação {tipo} do cliente {id_cliente}: {e}")
        traceback.print_exc()
        return False, str(e)


# controle de movimentação dos clientes
def registrar_transacao_cliente_old(db, id_cliente, valor, tipo, descricao, id_evento=None, id_venda=None):
    """
    Centraliza toda movimentação financeira do cliente. (VERSÃO BLINDADA - ATÓMICA)
    valor: float ou Decimal128 (positivo para crédito, negativo para débito)
    tipo: 'compra', 'premio', 'recarga', 'estorno_saque', 'saque'
    """
    import pymongo # Garantir que temos acesso ao ReturnDocument
    
    try:
        valor_float = float(valor)
        if valor_float == 0:
            return True, "Transação de valor zero ignorada."

        # 1. Determina a Natureza para o Livro-Razão (Facilita Relatórios)
        natureza = "ENTRADA" if valor_float > 0 else "SAIDA"
        
        # 2. Converte valor para Decimal128 para precisão financeira no Mongo
        valor_decimal = Decimal128(str(valor_float))
        
        # ==============================================================================
        # 🛡️ OPERAÇÃO ATÓMICA (O Fim das Race Conditions)
        # O MongoDB soma o valor e devolve o documento atualizado na mesma fração de segundo.
        # ==============================================================================
        cliente_atualizado = db.clientes.find_one_and_update(
            {'id_cliente': id_cliente},
            {
                '$inc': {'saldo_atual': valor_decimal},
                '$set': {'ultima_movimentacao': hora_brasil()}
            },
            return_document=pymongo.ReturnDocument.AFTER # Queremos o documento DEPOIS da matemática
        )

        if not cliente_atualizado:
            return False, "Cliente não encontrado."

        # 3. Matemática Reversa Precisa (Calcula o que havia antes)
        saldo_posterior_float = safe_float(cliente_atualizado.get('saldo_atual', 0.00))
        saldo_anterior_float = saldo_posterior_float - valor_float

        # 4. Grava o Livro-Razão (Extrato à prova de balas)
        transacao_doc = {
            'id_transacao': f"TRX{int(time.time()*1000)}",
            'id_cliente': id_cliente,
            'data_hora': hora_brasil(),
            'natureza': natureza,           # ENTRADA ou SAIDA
            'tipo': tipo,                   # A categoria da transação (compra, premio, etc.)
            'valor': valor_decimal,
            'saldo_anterior': Decimal128(str(saldo_anterior_float)),
            'saldo_posterior': Decimal128(str(saldo_posterior_float)),
            'descricao': descricao,
            'id_evento': id_evento,
            'id_venda': id_venda,
            'registrado_por': session.get('nick', 'Sistema') # Rastreabilidade de quem fez a operação
        }
        
        db.transacoes_clientes.insert_one(transacao_doc)
        
        return True, "Sucesso"

    except Exception as e:
        print(f"❌ [FALHA CRÍTICA FINANCEIRA] Erro ao registrar transação do cliente {id_cliente}: {e}")
        traceback.print_exc()
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
            db=db, 
            id_cliente=id_cliente, 
            valor=valor_recarga, 
            tipo='credito_manual_admin', # <--- CORRETO
            descricao=f"Crédito Adicionado por Colaborador ({session.get('nick')})"
        )      
  
        if sucesso:
            msg = f"Recarga de R$ {valor_recarga:.2f} realizada com sucesso para o Cliente {id_cliente}."
            valor = request.form.get('valor_recarga')
            registrar_log("RECARGA", "FINANCEIRO", f"Adicionado R$ {valor} ao cliente {id_cliente}", id_cliente)
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
    # 1. Primeiro capturamos o nível do usuário
    nivel_usuario = session.get('nivel', 0)
    
    # 2. Depois fazemos a verificação de acesso
    if nivel_usuario < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    # --- 🚀 ADICIONE ESTAS LINHAS AQUI ---
    id_regional_sessao = session.get('id_regional')
    is_master = (nivel_usuario >= 4)
    # ------------------------------------

    filtro_status = request.args.get('status', 'pendente')
    
    # 1. Captura o limite (Padrão: 30 registros)
    try:
        limit_param = int(request.args.get('limit', 30))
    except ValueError:
        limit_param = 30 # Fallback se digitarem texto
        
    query = {}

    #if not is_master and id_regional_sessao:
        # AQUI FOI REMOVIDO O QUE CAUSAVA O ERRO
        #query['id_regional'] = int(id_regional_sessao)

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

        valor = safe_float(saque.get('valor_requerido'))
        
        # Pega o ID que estava salvo no pedido de saque
        id_raw = saque.get('id_cliente')
        
        # --- BUSCA INTELIGENTE DO CLIENTE ---
        possiveis_ids = [id_raw]
        try:
            if str(id_raw).isdigit(): possiveis_ids.append(int(id_raw))
            possiveis_ids.append(str(id_raw))
        except: pass
        
        cliente = db.clientes.find_one({'id_cliente': {'$in': possiveis_ids}})
        # ---------------------------------------------

        if not cliente:
            return redirect(url_for('monitor_saques', error=f"Erro Crítico: Cliente {id_raw} deletado ou não encontrado."))

        saldo_atual = safe_float(cliente.get('saldo_atual', 0))

        if acao == 'pagar':
            # Se for aprovar o pagamento, o valor JÁ FOI DEBITADO na hora da requisição.
            # Aqui você deve decidir se o seu sistema antigo debitava na hora do pedido ou aqui.
            # Baseado na sua explicação ("o sistema irá abater o valor do saldo atual do cliente"),
            # presumo que o débito JÁ ocorreu no momento em que o cliente clicou em "Solicitar Saque" no celular.
            # LOGO, aqui NÃO PRECISAMOS DEBITAR NOVAMENTE, apenas mudar o status.
            
            # --- Se o seu sistema NÃO debitava na requisição e você quiser manter o débito aqui, 
            # descomente o bloco abaixo. Mas pela sua nova regra, o débito já deve ter ocorrido. ---
            
            """
            if saldo_atual < valor:
                return redirect(url_for('monitor_saques', error=f"Erro: Cliente tem apenas R$ {saldo_atual:.2f}. Saque de R$ {valor:.2f} impossível."))

            sucesso, msg = registrar_transacao_cliente(
                db=db,
                id_cliente=cliente.get('id_cliente'), 
                valor=-abs(valor), 
                tipo='saque',
                descricao=f"Saque Aprovado (Req: {str(id_saque)[-4:]})",
                id_evento=None,
                id_venda=None
            )
            
            if not sucesso:
                 return redirect(url_for('monitor_saques', error=f"Erro ao debitar: {msg}"))
            """

            # 3. Atualiza status do saque para PAGO
            db.requisao_saque.update_one(
                {'_id': ObjectId(id_saque)},
                {'$set': {
                    'status': 'pago',
                    'data_pgto': hora_brasil(),
                    'operador_pgto': session.get('nick'),
                    'saldo_atual_pgto': saldo_atual # Saldo atual do cliente após o pagamento
                }}
            )
            msg_sucesso = "Saque APROVADO com sucesso!"

        elif acao == 'rejeitar':
            # --- NOVA LÓGICA CRÍTICA: DEVOLVER O DINHEIRO AO CLIENTE ---
            
            # 1. Devolve o dinheiro usando a nossa função oficial de transação
            sucesso, msg = registrar_transacao_cliente(
                db=db,
                id_cliente=cliente.get('id_cliente'),
                valor=abs(valor), # Valor POSITIVO para somar de volta à conta
                tipo='estorno_saque',
                descricao=f"Estorno de Saque Rejeitado (Req: {str(id_saque)[-4:]})",
                id_evento=None,
                id_venda=None
            )

            if not sucesso:
                 return redirect(url_for('monitor_saques', error=f"Erro ao devolver saldo: {msg}"))

            # 2. Muda o status para rejeitado
            db.requisao_saque.update_one(
                {'_id': ObjectId(id_saque)},
                {'$set': {
                    'status': 'rejeitado',
                    'data_pgto': hora_brasil(),
                    'operador_pgto': session.get('nick')
                }}
            )
            msg_sucesso = f"Solicitação REJEITADA. R$ {valor:.2f} foram devolvidos à carteira do cliente!"

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
    
    nivel_usuario = session.get('nivel', 0)
    if nivel_usuario < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    # --- CONTEXTO REGIONAL (FASE 4) ---
    id_regional_sessao = session.get('id_regional')
    is_master = (nivel_usuario >= 4)

    id_evento_param = request.args.get('id_evento')
    id_regional_filtro = request.args.get('id_regional_filtro', '').strip()

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

        lista_regionais = []
        if is_master:
            lista_regionais = list(db.regionais.find({}, {'_id': 0, 'id_regional': 1, 'descricao': 1}).sort('id_regional', 1))

        return render_template('financeiro_evento_selecao.html', eventos=eventos, regionais=lista_regionais, g=g)

    # SE TEM EVENTO: CALCULA O RELATÓRIO
    try:
        id_evento_int = int(id_evento_param)
        evento = db.eventos.find_one({'id_evento': id_evento_int})
        if not evento:
            return redirect(url_for('financeiro_evento', error="Evento não encontrado"))

        # 1. Carrega Parâmetros Matemáticos Seguros
        params = db.parametros.find_one({}) or {}
        def get_perc(key, default_percent):
            val = params.get(key)
            if val is None: return default_percent / 100.0
            try:
                val_float = float(val.to_decimal()) if hasattr(val, 'to_decimal') else float(val)
                return val_float / 100.0
            except:
                return default_percent / 100.0

        p_direta = get_perc('perc_venda_direta', 15.0)
        p_ind_b = get_perc('perc_venda_indireta_b', 10.0)
        comissao_auto = g.parametros_globais.get('comissao_autoatendimento', 10) / 100.0
        
        # 🚀 CORREÇÃO: Filtra os colaboradores de acordo com a regional selecionada pelo Master
        if is_master and id_regional_filtro:
            query_colab = {"id_regional": int(id_regional_filtro)}
        elif not is_master and id_regional_sessao:
            query_colab = {"id_regional": id_regional_sessao}
        else:
            query_colab = {}
            
        colabs = list(db.colaboradores.find(query_colab))
        
        mapa_nicks = {0: 'AutoAtendimento', '0': 'AutoAtendimento', None: 'AutoAtendimento', 'None': 'AutoAtendimento'}
        for c in colabs:
            cid = c.get('id_colaborador')
            cnick = c.get('nick') or c.get('nome_colaborador') or f"ID {cid}"
            mapa_nicks[cid] = cnick
            mapa_nicks[str(cid)] = cnick

        # 2. Definição das Coleções
        nome_col_vendas = f"vendas{id_evento_int}"
        nome_col_pagtos = f"pagamentos{id_evento_int}"
        nome_col_cupons = f"vendas_sorte_extra{id_evento_int}"

        # 🚀 CORREÇÃO: Aplica o filtro da regional nas agregações do Master
        match_regional = {}
        if is_master and id_regional_filtro:
            match_regional['id_regional'] = int(id_regional_filtro)
        elif not is_master and id_regional_sessao:
            match_regional['id_regional'] = int(id_regional_sessao)

        # 3. Agregação de VENDAS (COM FILTRO DE CORTESIAS)
        vendas_agg = []
        if nome_col_vendas in db.list_collection_names():
            pipeline = [
                {'$match': match_regional},
                {
                    '$group': {
                        '_id': '$id_vendedor',
                        # Cartelas normais (exclui cortesias)
                        'total_qtd': {
                            '$sum': { '$cond': [{'$ne': ['$origem', 'cortesia_diaria']}, '$quantidade_unidades', 0] }
                        },
                        # Novidade: Conta apenas cortesias
                        'total_qtd_cortesia': {
                            '$sum': { '$cond': [{'$eq': ['$origem', 'cortesia_diaria']}, '$quantidade_cartelas', 0] }
                        },
                        # Valor financeiro real (as cortesias já estão gravadas como 0, então a soma do valor não é afetada)
                        'total_val': {'$sum': {'$toDouble': '$valor_total'}},
                        'vol_direto': {
                            '$sum': { '$cond': [{'$eq': ['$id_vendedor', '$id_colaborador']}, {'$toDouble': '$valor_total'}, 0] }
                        },
                        'vol_ind_b': {
                            '$sum': { '$cond': [{'$ne': ['$id_vendedor', '$id_colaborador']}, {'$toDouble': '$valor_total'}, 0] }
                        }
                    }
                }
            ]
            vendas_agg = list(db[nome_col_vendas].aggregate(pipeline))

        # 4. Agregação de SORTE EXTRA
        cupons_agg = []
        if nome_col_cupons in db.list_collection_names():
            pipeline_cupons = [
                {'$match': match_regional},
                {
                    '$group': {
                        '_id': { '$ifNull': ['$id_vendedor', '$id_colaborador'] },
                        'total_qtd_cupons': {'$sum': '$qtd_cartelas'},
                        'total_val_cupons': {'$sum': {'$toDouble': '$valor_total'}}
                    }
                }
            ]
            cupons_agg = list(db[nome_col_cupons].aggregate(pipeline_cupons))

        # 5. Agregação de PAGAMENTOS
        pagtos_agg = {}
        if nome_col_pagtos in db.list_collection_names():
            pipeline_pagtos = [
                {'$match': match_regional},
                {
                    '$group': {
                        '_id': '$id_colaborador',
                        'total_pago': {'$sum': {'$toDouble': '$valor_pago'}}
                    }
                }
            ]
            raw_pagtos = list(db[nome_col_pagtos].aggregate(pipeline_pagtos))
            pagtos_agg = {p['_id']: safe_float(p['total_pago']) for p in raw_pagtos}

        # 6. Consolidação Dinâmica
        relatorio = {} 
        for v in vendas_agg:
            id_vend = v['_id']
            valor = safe_float(v['total_val'])
            if id_vend in [0, '0', None, 'None']:
                comissao_merecida = valor * comissao_auto
            else:
                comissao_merecida = (v['vol_direto'] * p_direta) + (v['vol_ind_b'] * p_ind_b)
            
            relatorio[id_vend] = {
                'id': id_vend, 'nick': mapa_nicks.get(id_vend, f'ID {id_vend}'), 
                'qtd': v.get('total_qtd', 0), 
                'qtd_cortesia': v.get('total_qtd_cortesia', 0), # A NOVA VARIÁVEL
                'vendas': valor, 'comissao': comissao_merecida, 
                'qtd_cupons': 0, 'vendas_cupons': 0.0, 'pago_central': 0.0
            }

        for c in cupons_agg:
            id_vend_cupom = c['_id']
            if id_vend_cupom not in relatorio:
                relatorio[id_vend_cupom] = {'id': id_vend_cupom, 'nick': mapa_nicks.get(id_vend_cupom, f'ID {id_vend_cupom}'), 'text_color': '', 'qtd': 0, 'qtd_cortesia': 0, 'vendas': 0.0, 'comissao': 0.0, 'qtd_cupons': 0, 'vendas_cupons': 0.0, 'pago_central': 0.0}
            relatorio[id_vend_cupom]['qtd_cupons'] += c['total_qtd_cupons']
            relatorio[id_vend_cupom]['vendas_cupons'] += safe_float(c['total_val_cupons'])

        for id_pag, valor_pago in pagtos_agg.items():
            if id_pag in relatorio: relatorio[id_pag]['pago_central'] += valor_pago

        # 7. Totais Finais
        lista_final = []
        totais = {'vendas': 0.0, 'qtd': 0, 'qtd_cortesia': 0, 'comissao': 0.0, 'vendas_cupons': 0.0, 'qtd_cupons': 0, 'pago_central': 0.0, 'pendente_central': 0.0}

        for dados in relatorio.values():
            liquido_total_devido = (dados['vendas'] - dados['comissao']) + dados['vendas_cupons']
            if dados['id'] in [0, '0', None, 'None']: dados['pago_central'] = liquido_total_devido
            
            saldo_final = liquido_total_devido - dados['pago_central']
            dados['pendente'] = saldo_final if saldo_final > 0 else 0.0
            dados['a_receber_colab'] = abs(saldo_final) if saldo_final < 0 else 0.0
            lista_final.append(dados)
            
            totais['vendas'] += dados['vendas']
            totais['qtd'] += dados['qtd']
            totais['qtd_cortesia'] += dados.get('qtd_cortesia', 0) 
            totais['comissao'] += dados['comissao']
            totais['vendas_cupons'] += dados['vendas_cupons']
            totais['qtd_cupons'] += dados['qtd_cupons']
            totais['pago_central'] += dados['pago_central'] 
            totais['pendente_central'] += dados['pendente']

        lista_final.sort(key=lambda x: x['pendente'], reverse=True)
        
        # 🚀 CORREÇÃO: Regionaliza os prêmios caso o Master aplique o filtro
        if is_master and not id_regional_filtro:
            premio_bingo = safe_float(evento.get('premio_total', 0))
            premio_extra = safe_float(evento.get('premios_sorte_extra', 0))
        else:
            old_regional = session.get('id_regional')
            if is_master and id_regional_filtro:
                session['id_regional'] = int(id_regional_filtro)
            
            evento_reg = calcular_premios_dinamicos(db, evento.copy(), g.parametros_globais)
            premio_bingo = safe_float(evento_reg.get('premio_total', 0))
            premio_extra = safe_float(evento.get('premios_sorte_extra', 0)) if is_master else 0.0
            
            if is_master:
                session['id_regional'] = old_regional
        
        premio_total_geral = premio_bingo + premio_extra
        receita_liquida_casa = (totais['vendas'] - totais['comissao']) + totais['vendas_cupons']
        saldo_evento_projetado = receita_liquida_casa - premio_total_geral

        dados_painel = {
            'total_vendas_bingo': totais['vendas'], 'total_vendas_cupons': totais['vendas_cupons'],
            'receita_bruta_total': totais['vendas'] + totais['vendas_cupons'], 'total_comissao': totais['comissao'],
            'premio_bingo': premio_bingo, 'premio_extra': premio_extra, 'premio_total_geral': premio_total_geral,
            'saldo_projetado': saldo_evento_projetado, 'total_recebido': totais['pago_central'], 'total_a_receber': totais['pendente_central']
        }
        
        return render_template('financeiro_evento.html', evento=evento, lista=lista_final, painel=dados_painel, totais=totais, g=g)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return redirect(url_for('financeiro_evento', error=f"Erro interno: {e}"))

@app.route('/financeiro_periodo', methods=['GET'])
@login_required
def financeiro_periodo():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    nivel_usuario = session.get('nivel', 0)
    if nivel_usuario < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    id_regional_sessao = session.get('id_regional')
    is_master = (nivel_usuario >= 4)

    data_inicio = request.args.get('data_inicio')
    hora_inicio = request.args.get('hora_inicio', '00:00')
    data_fim = request.args.get('data_fim')
    hora_fim = request.args.get('hora_fim', '23:59')
                                     
    id_regional_filtro = request.args.get('id_regional_filtro', '').strip()

    if not data_inicio or not data_fim:
        return redirect(url_for('financeiro_evento', error="Informe as datas de início e fim."))

    try:
        from datetime import datetime
        try:
            dt_inicio = datetime.strptime(data_inicio, '%Y-%m-%d')
            dt_fim = datetime.strptime(data_fim, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except Exception as e:
            return redirect(url_for('financeiro_evento', error=f"Erro ao formatar datas: {e}"))

        todos_eventos = list(db.eventos.find({'status': {'$in': ['ativo', 'paralizado', 'finalizado']}}))
        eventos_no_periodo = []

        for ev in todos_eventos:
            data_ev = ev.get('data_evento')
            if not data_ev: continue
            dt_ev = None
            if hasattr(data_ev, 'strftime'): dt_ev = data_ev
            else:
                data_ev_str = str(data_ev).strip()
                try:
                    if '-' in data_ev_str: dt_ev = datetime.strptime(data_ev_str, '%Y-%m-%d')
                    elif '/' in data_ev_str: dt_ev = datetime.strptime(data_ev_str, '%d/%m/%Y')
                except: pass
            
            if dt_ev and (dt_inicio <= dt_ev <= dt_fim):
                eventos_no_periodo.append(ev)

        if not eventos_no_periodo:
            return redirect(url_for('financeiro_evento', error="Nenhum evento encontrado neste período."))

        params = db.parametros.find_one({}) or {}
        def get_perc(key, default_percent):
            val = params.get(key)
            if val is None: return default_percent / 100.0
            try: return (float(val.to_decimal()) if hasattr(val, 'to_decimal') else float(val)) / 100.0
            except: return default_percent / 100.0

        p_direta = get_perc('perc_venda_direta', 15.0)
        p_ind_b = get_perc('perc_venda_indireta_b', 10.0)
        comissao_auto = g.parametros_globais.get('comissao_autoatendimento', 10) / 100.0

        # 🚀 CORREÇÃO: Sincroniza os filtros de agregação e colaboradores
        match_regional = {}
        if is_master and id_regional_filtro:
            match_regional['id_regional'] = int(id_regional_filtro)
        elif not is_master and id_regional_sessao:
            match_regional['id_regional'] = int(id_regional_sessao)

        if is_master and id_regional_filtro:
            query_colab = {"id_regional": int(id_regional_filtro)}
        elif not is_master and id_regional_sessao:
            query_colab = {"id_regional": id_regional_sessao}
        else:
            query_colab = {}

        colabs = list(db.colaboradores.find(query_colab))
        mapa_nicks = {0: 'AutoAtendimento', '0': 'AutoAtendimento', None: 'AutoAtendimento', 'None': 'AutoAtendimento'}
        for c in colabs:
            cid = c.get('id_colaborador')
            cnick = c.get('nick') or c.get('nome_colaborador') or f"ID {cid}"
            mapa_nicks[cid] = cnick
            mapa_nicks[str(cid)] = cnick

        acumulado_vendas = {}
        acumulado_cupons = {}
        acumulado_pagamentos = {}
        premio_bingo_total = 0.0
        premio_extra_total = 0.0
        colecoes_existentes = db.list_collection_names()

        for ev in eventos_no_periodo:
            id_ev = ev.get('id_evento')
            if id_ev is None: continue
            id_evento_int = int(id_ev)
            
            # 🚀 CORREÇÃO: Regionaliza prêmios no laço acumulador se houver filtro ativo
            if is_master and not id_regional_filtro:
                premio_bingo_total += safe_float(ev.get('premio_total', 0))
                premio_extra_total += safe_float(ev.get('premios_sorte_extra', 0))
            else:
                old_regional = session.get('id_regional')
                if is_master and id_regional_filtro:
                    session['id_regional'] = int(id_regional_filtro)
                
                ev_reg = calcular_premios_dinamicos(db, ev.copy(), g.parametros_globais)
                premio_bingo_total += safe_float(ev_reg.get('premio_total', 0))
                if is_master:
                    premio_extra_total += safe_float(ev.get('premios_sorte_extra', 0))
                
                if is_master:
                    session['id_regional'] = old_regional

            nome_col_vendas = f"vendas{id_evento_int}"
            nome_col_pagtos = f"pagamentos{id_evento_int}"
            nome_col_cupons = f"vendas_sorte_extra{id_evento_int}"

            if nome_col_vendas in colecoes_existentes:
                pipeline = [
                    {'$match': match_regional},
                    {
                        '$group': {
                            '_id': '$id_vendedor',
                            'id_regional': {'$first': '$id_regional'},  
                            # Conta apenas vendas NORMAIS
                            'total_qtd': {
                                '$sum': { '$cond': [{'$ne': ['$origem', 'cortesia_diaria']}, '$quantidade_unidades', 0] }
                            },
                            # Conta apenas CORTESIAS
                            'total_qtd_cortesia': {
                                '$sum': { '$cond': [{'$eq': ['$origem', 'cortesia_diaria']}, '$quantidade_cartelas', 0] }
                            },
                            'total_val': {'$sum': {'$toDouble': '$valor_total'}},
                            'vol_direto': {
                                '$sum': { '$cond': [{'$eq': ['$id_vendedor', '$id_colaborador']}, {'$toDouble': '$valor_total'}, 0] }
                            },
                            'vol_ind_b': {
                                '$sum': { '$cond': [{'$ne': ['$id_vendedor', '$id_colaborador']}, {'$toDouble': '$valor_total'}, 0] }
                            }
                        }
                    }
                ]
                for v in db[nome_col_vendas].aggregate(pipeline):
                    id_v = v['_id']
                    if id_v not in acumulado_vendas:
                        acumulado_vendas[id_v] = {'id_regional': v.get('id_regional', 1), 'total_qtd': 0, 'total_qtd_cortesia': 0, 'total_val': 0.0, 'vol_direto': 0.0, 'vol_ind_b': 0.0}    
                        #acumulado_vendas[id_v] = {'total_qtd': 0, 'total_qtd_cortesia': 0, 'total_val': 0.0, 'vol_direto': 0.0, 'vol_ind_b': 0.0}
                    acumulado_vendas[id_v]['total_qtd'] += v.get('total_qtd', 0)
                    acumulado_vendas[id_v]['total_qtd_cortesia'] += v.get('total_qtd_cortesia', 0) # NOVO ACUMULADOR
                    acumulado_vendas[id_v]['total_val'] += safe_float(v['total_val'])
                    acumulado_vendas[id_v]['vol_direto'] += safe_float(v['vol_direto'])
                    acumulado_vendas[id_v]['vol_ind_b'] += safe_float(v['vol_ind_b'])

            if nome_col_cupons in colecoes_existentes:
                pipeline_cupons = [
                    {'$match': match_regional},
                    {
                        '$group': {
                            '_id': { '$ifNull': ['$id_vendedor', '$id_colaborador'] },
                            'total_qtd_cupons': {'$sum': '$qtd_cartelas'},
                            'total_val_cupons': {'$sum': {'$toDouble': '$valor_total'}}
                        }
                    }
                ]
                for c in db[nome_col_cupons].aggregate(pipeline_cupons):
                    id_c = c['_id']
                    if id_c not in acumulado_cupons:
                        acumulado_cupons[id_c] = {'total_qtd_cupons': 0, 'total_val_cupons': 0.0}
                    acumulado_cupons[id_c]['total_qtd_cupons'] += c['total_qtd_cupons']
                    acumulado_cupons[id_c]['total_val_cupons'] += safe_float(c['total_val_cupons'])

            if nome_col_pagtos in colecoes_existentes:
                pipeline_pagtos = [
                    {'$match': match_regional},
                    {
                        '$group': {
                            '_id': '$id_colaborador',
                            'total_pago': {'$sum': {'$toDouble': '$valor_pago'}}
                        }
                    }
                ]
                for p in db[nome_col_pagtos].aggregate(pipeline_pagtos):
                    id_p = p['_id']
                    acumulado_pagamentos[id_p] = acumulado_pagamentos.get(id_p, 0.0) + safe_float(p['total_pago'])

        relatorio = {}
        for id_vend, v in acumulado_vendas.items():
            valor = v['total_val']
            if id_vend in [0, '0', None, 'None']:
                comissao_merecida = valor * comissao_auto
            else:
                comissao_merecida = (v['vol_direto'] * p_direta) + (v['vol_ind_b'] * p_ind_b)
                
            relatorio[id_vend] = {
                'id': id_vend, 'nick': mapa_nicks.get(id_vend, f'ID {id_vend}'),
                'id_regional': v.get('id_regional', 1),
                'qtd': v['total_qtd'],
                'qtd_cortesia': v['total_qtd_cortesia'], # INJETA AQUI PARA O JINJA
                'vendas': valor, 'comissao': comissao_merecida,
                'qtd_cupons': 0, 'vendas_cupons': 0.0, 'pago_central': 0.0
            }

        for id_vend_cupom, c in acumulado_cupons.items():
            if id_vend_cupom not in relatorio:
                relatorio[id_vend_cupom] = {
                    'id': id_vend_cupom, 'nick': mapa_nicks.get(id_vend_cupom, f'ID {id_vend_cupom}'),
                    'qtd': 0, 'qtd_cortesia': 0, 'vendas': 0.0, 'comissao': 0.0, 'qtd_cupons': 0, 'vendas_cupons': 0.0, 'pago_central': 0.0
                }
            relatorio[id_vend_cupom]['qtd_cupons'] += c['total_qtd_cupons']
            relatorio[id_vend_cupom]['vendas_cupons'] += c['total_val_cupons']

        for id_pag, valor_pago in acumulado_pagamentos.items():
            if id_pag in relatorio:
                relatorio[id_pag]['pago_central'] += valor_pago

        lista_final = []
        # Adicionado 'qtd_cortesia' nos totais
        totais = {'vendas': 0.0, 'qtd': 0, 'qtd_cortesia': 0, 'comissao': 0.0, 'vendas_cupons': 0.0, 'qtd_cupons': 0, 'pago_central': 0.0, 'pendente_central': 0.0}

        for dados in relatorio.values():
            liquido_total_devido = (dados['vendas'] - dados['comissao']) + dados['vendas_cupons']
            if dados['id'] in [0, '0', None, 'None']: dados['pago_central'] = liquido_total_devido
                
            saldo_final = liquido_total_devido - dados['pago_central']
            dados['pendente'] = saldo_final if saldo_final > 0 else 0.0
            dados['a_receber_colab'] = abs(saldo_final) if saldo_final < 0 else 0.0
            lista_final.append(dados)
            
            totais['vendas'] += dados['vendas']
            totais['qtd'] += dados['qtd']
            totais['qtd_cortesia'] += dados['qtd_cortesia'] # SOMA AQUI!
            totais['comissao'] += dados['comissao']
            totais['vendas_cupons'] += dados['vendas_cupons']
            totais['qtd_cupons'] += dados['qtd_cupons']
            totais['pago_central'] += dados['pago_central'] 
            totais['pendente_central'] += dados['pendente']

        lista_final.sort(key=lambda x: x['pendente'], reverse=True)
        receita_liquida_casa = (totais['vendas'] - totais['comissao']) + totais['vendas_cupons']
        premio_total_geral = premio_bingo_total + premio_extra_total

        try:
            data_ini_br = datetime.strptime(data_inicio, '%Y-%m-%d').strftime('%d/%m/%Y')
            data_fim_br = datetime.strptime(data_fim, '%Y-%m-%d').strftime('%d/%m/%Y')
        except:
            data_ini_br, data_fim_br = data_inicio, data_fim

        dados_painel = {
            'total_vendas_bingo': totais['vendas'], 'total_vendas_cupons': totais['vendas_cupons'],
            'receita_bruta_total': totais['vendas'] + totais['vendas_cupons'], 'total_comissao': totais['comissao'],
            'premio_bingo': premio_bingo_total, 'premio_extra': premio_extra_total, 'premio_total_geral': premio_total_geral,
            'saldo_projetado': receita_liquida_casa - premio_total_geral, 'total_recebido': totais['pago_central'], 'total_a_receber': totais['pendente_central']
        }

        evento_fake = {
            'descricao': f"Fechamento por Período Acumulado",
            'data_fmt': f"{data_ini_br} até {data_fim_br}",
            'hora_evento': f"{hora_inicio} - {hora_fim}",
            'status': 'finalizado',
            'tipo_consulta': 'periodo',
            'data_inicio': data_inicio,
            'data_fim': data_fim,
            'id_regional_filtro': id_regional_filtro 
        }

        # =========================================================================
        # 🚀 NOVO: GERAÇÃO DA TABELA CONSOLIDADA POR REGIONAIS (VISÃO MASTER GLOBAL)
        # =========================================================================
        lista_regionais_financeiro = []
        if is_master and not id_regional_filtro:
            reg_dict = {}
            # Inicializa todas as regionais
            for r in db.regionais.find({}):
                reg_dict[r['id_regional']] = {
                    'nome': r.get('descricao', f"Regional {r['id_regional']}"),
                    'qtd_pagas': 0, 'qtd_cortesia': 0, 'faturamento': 0.0, 'comissoes': 0.0, 'premios': 0.0, 'saldo': 0.0
                }
            
            # 1. Soma Vendas, Cortesias e Comissões agrupando pela Regional do vendedor
            for item in lista_final:
                rid = item.get('id_regional', 1)
                if rid not in reg_dict:
                    reg_dict[rid] = {'nome': f"Regional {rid}", 'qtd_pagas': 0, 'qtd_cortesia': 0, 'faturamento': 0.0, 'comissoes': 0.0, 'premios': 0.0, 'saldo': 0.0}
                
                reg_dict[rid]['qtd_pagas'] += item.get('qtd', 0)
                reg_dict[rid]['qtd_cortesia'] += item.get('qtd_cortesia', 0)
                reg_dict[rid]['faturamento'] += item.get('vendas', 0) + item.get('vendas_cupons', 0)
                reg_dict[rid]['comissoes'] += item.get('comissao', 0)
            
            # 2. Calcula os Prêmios (Rateados se Auditado, ou Matriz se Legado/Ativo)
            old_regional = session.get('id_regional')
            for ev in eventos_no_periodo:
                premios_reais_pagos = ev.get('premios_pagos_por_regional', {})
                
                # Se for evento legado ou ativo, calculamos o prêmio Global UMA VEZ
                premio_global_fallback = 0.0
                if not premios_reais_pagos:
                    session.pop('id_regional', None) # Remove filtro para calcular o total global
                    try:
                        ev_global = calcular_premios_dinamicos(db, ev.copy(), g.parametros_globais)
                        prem_bingo = safe_float(ev_global.get('premio_total', 0))
                        prem_extra = safe_float(ev.get('premios_sorte_extra', 0))
                        premio_global_fallback = prem_bingo + prem_extra
                    except: pass

                for rid in reg_dict.keys():
                    if premios_reais_pagos:
                        # O evento tem a auditoria nova! Puxa o valor exato pago por esta regional
                        valor_pago = safe_float(premios_reais_pagos.get(str(rid), 0.0))
                        reg_dict[rid]['premios'] += valor_pago
                    else:
                        # Evento LEGADO ou ATIVO: Despeja o prêmio global apenas na Regional 1
                        if int(rid) == 1:
                            reg_dict[rid]['premios'] += premio_global_fallback
            
            if old_regional: session['id_regional'] = old_regional
            else: session.pop('id_regional', None)

            # 3. Calcula Saldo final e limpa regionais vazias
            for r_data in reg_dict.values():
                r_data['saldo'] = r_data['faturamento'] - r_data['comissoes'] - r_data['premios']
                # REGRA DE EXIBIÇÃO: Oculta regionais sem movimento.
                # Se o cliente quiser ver TODAS as regionais, basta comentar o 'if' 
                # abaixo e encostar o 'append' na margem esquerda.
                #if r_data['faturamento'] > 0 or r_data['premios'] > 0:
                lista_regionais_financeiro.append(r_data)
            
            # Ordena da que faturou mais para a que faturou menos
            lista_regionais_financeiro.sort(key=lambda x: x['faturamento'], reverse=True)
        # =========================================================================

        return render_template('financeiro_evento.html', evento=evento_fake, lista=lista_final, painel=dados_painel, totais=totais, g=g, lista_regionais_financeiro=lista_regionais_financeiro)

        #return render_template('financeiro_evento.html', evento=evento_fake, lista=lista_final, painel=dados_painel, totais=totais, g=g)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return redirect(url_for('financeiro_evento', error=f"Erro interno no processamento do período: {e}"))


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
        traceback.print_exc() # Imprime a stack trace completa no console para ajudar no debug
        return jsonify({"error": "Erro interno ao calcular horários."}), 500


@app.route('/api/gravar_replicacao', methods=['POST'])
@login_required
def gravar_replicacao():
    """
    Rota final que grava as cópias caso o operador confirme.
    Refaz a verificação de segurança por precaução.
    INCLUI: Criação automática de Índices de Alta Performance para cada réplica.
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
        data_molde = evento_molde.get('data_evento', '')
        hora_molde = evento_molde.get('hora_evento', '')
        base_dt = datetime.strptime(f"{data_molde} {hora_molde}", "%d/%m/%Y %H:%M")
        
        # Resgatar e formatar o prémio
        premio_bruto = evento_molde.get('premio_total', Decimal128("0.00"))
        if isinstance(premio_bruto, Decimal128):
            premio_bruto = float(premio_bruto.to_decimal())
        
        premio_formatado = f"{premio_bruto:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

        eventos_para_inserir = []
        ids_replicados = [] # 🚀 NOVO: Lista para guardar os IDs dos eventos gerados

        # Parâmetros e Modo Treino
        params = db.parametros.find_one({})
        modo_treino = params.get('em_treinamento', False) if params else False

        # Busca vendas originais do molde
        vendas_originais = []
        if modo_treino:
            col_vendas_molde = f"vendas{id_evento_molde}"
            vendas_originais = list(db[col_vendas_molde].find({}))

        ponteiro_geral_cartela = int(evento_molde.get('numero_inicial', 1))
        unidade_venda_fixa = int(evento_molde.get('unidade_de_venda', 1))

        # Pré-processa as vendas
        vendas_pre_calculadas = []
        if modo_treino and vendas_originais:
            for v in vendas_originais:
                qtd_kits = v.get('quantidade_unidades', 1)
                t_cartelas = v.get('quantidade_cartelas', qtd_kits * unidade_venda_fixa)
                vendas_pre_calculadas.append({'dados': v, 'tamanho': t_cartelas})

        # Início do Loop
        for i in range(1, qtd + 1):
            novo_dt = base_dt + timedelta(minutes=intervalo_minutos * i)
            data_str = novo_dt.strftime("%d/%m/%Y")
            hora_str = novo_dt.strftime("%H:%M")

            if db.eventos.find_one({"data_evento": data_str, "hora_evento": hora_str}):
                return redirect(url_for('cadastro_evento', view='alterar', id_evento=id_evento_molde, 
                                        error=f"Conflito de horário detectado em {data_str} {hora_str}. Cancelado."))

            novo_id = get_next_evento_sequence()
            ids_replicados.append(novo_id) # 🚀 NOVO: Guarda o ID gerado na lista

            nova_descricao = f"{novo_dt.strftime('%d/%m')} às {hora_str} - R$ {premio_formatado}"

            novo_evento = evento_molde.copy()
            if '_id' in novo_evento: 
                del novo_evento['_id']

            novo_evento.update({
                "id_evento": novo_id,
                "data_evento": data_str,
                "hora_evento": hora_str,
                "numero_inicial": ponteiro_geral_cartela,
                "data_hora_evento": novo_dt,
                "descricao": nova_descricao,
                "status": status_replicas,
                "data_ativado": None if status_replicas != 'ativo' else hora_brasil(),
                "data_cadastro": hora_brasil(),
                "id_colaborador": session.get('id_colaborador', 'N/A'),
                "id_evento_principal_combo": id_evento_molde # 🚀 NOVO: O filho sabe quem é o pai
            })

            eventos_para_inserir.append(novo_evento)
            
            proxima_venda_fixo = int(evento_molde.get('numero_inicial', 1))

            # ==========================================================
            # AÇÃO B (AUTOMAÇÃO): CRIAÇÃO DOS ÍNDICES PARA A NOVA RÉPLICA
            # ==========================================================
            nome_colecao_replica = f"vendas{novo_id}"
            try:
                db[nome_colecao_replica].create_index([("id_vendedor", 1)])
                db[nome_colecao_replica].create_index([("id_colaborador", 1)])
                db[nome_colecao_replica].create_index([("id_cliente", 1)])
                db[nome_colecao_replica].create_index([
                    ("id_colaborador", 1), 
                    ("id_vendedor", 1)
                ])
            except Exception as e:
                print(f"[ERRO] Falha ao criar índices para réplica {nome_colecao_replica}: {e}")
            # ==========================================================

            # --- CLONE DE VENDAS (TREINAMENTO) ---
            if modo_treino and vendas_pre_calculadas:
                vendas_clonadas_da_replica = []
        
                for item in vendas_pre_calculadas:
                    v = item['dados']
                    t_cartelas = item['tamanho']
            
                    v_clone = v.copy()
                    if '_id' in v_clone: 
                        del v_clone['_id']
            
                    v_clone.update({
                        'id_evento': novo_id,
                        'data_venda': novo_dt,
                        'numero_inicial': v.get('numero_inicial'),
                        'numero_final': v.get('numero_final'),     
                        'id_venda': f"T{novo_id}-{v.get('numero_inicial')}"
                    })
            
                    vendas_clonadas_da_replica.append(v_clone)

                    proxima_venda_fixo = int(v.get('numero_final', 0)) + 1
        
                if vendas_clonadas_da_replica:
                    db[nome_colecao_replica].insert_many(vendas_clonadas_da_replica)
            
                db.controle_venda.update_one(
                    {'id_evento': novo_id},
                    {'$set': {'inicial_proxima_venda':  proxima_venda_fixo}},
                    upsert=True
                )
 
        if eventos_para_inserir:
            db.eventos.insert_many(eventos_para_inserir)
            
            # 🚀 NOVO: AMARRAÇÃO FINAL (PAI GUARDA OS FILHOS)
            # Atualiza o evento original adicionando a lista de eventos relacionados ao combo
            if ids_replicados:
                db.eventos.update_one(
                    {'id_evento': id_evento_molde},
                    {'$set': {'eventos_combo_relacionados': ids_replicados}}
                )

            registrar_log("REPLICAR", "EVENTOS", f"Geradas {qtd} réplicas a partir do evento {id_evento_molde}.")
            msg = f"Sucesso! {qtd} evento(s) replicado(s) com o status '{status_replicas}'."
            return redirect(url_for('cadastro_evento', success=msg, view='listar'))
        
        return redirect(url_for('cadastro_evento', view='listar'))

    except Exception as e:
        print("\n--- ERRO NA REPLICAÇÃO ---")
        import traceback
        traceback.print_exc()
        print("--------------------------\n")
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
        #print(f"[SECURITY] Tentativa de acesso não autorizada a /parametros por: {nick_operador or nome_operador}")
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
            'minimo_terminal': 6,
            'maximo_terminal': 1200,
            'em_treinamento': False,
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
        'minimo_terminal': safe_get_int(param_doc.get('minimo_terminal', 6)),
        'maximo_terminal': safe_get_int(param_doc.get('maximo_terminal', 1200)),  
        'porcento_premios': safe_get_int(param_doc.get('porcento_premios', 0)),
        # --- EM TREINAMENTO   ---   
        'em_treinamento': bool(param_doc.get('em_treinamento', False)), 

        # --- NOVOS CAMPOS (ROBÔ E INTEGRAÇÕES) ---
        'tempo_atualizacao_premios': safe_get_int(param_doc.get('tempo_atualizacao_premios', 1)),
        'minimo_atualizacao_premios': safe_get_float(param_doc.get('minimo_atualizacao_premios', 50.0)),
        'receber_pix': bool(param_doc.get('receber_pix', False)),
        'chat_id_telegram': param_doc.get('chat_id_telegram', ''),
        'token_telegram': param_doc.get('token_telegram', ''),
        'texto_requisicao_saque': param_doc.get('texto_requisicao_saque', ''),	
        
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
    Grava os parâmetros na base de dados de Vendas e sincroniza o Modo Treinamento 
    com a base de Dados do Sorteio.
    """
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

        params_atuais = db.parametros.find_one({}) or {}
        porcento_premios_val = int(request.form.get('porcento_premios', 0))

        # --- VALIDAÇÕES DE 100% ---
        if porcento_premios_val > 0:
            soma_15 = get_float_val('porcento_15_linha') + get_float_val('porcento_15_bingo') + get_float_val('porcento_15_segundobingo')
            if abs(soma_15 - 100.0) > 0.01:
                 return redirect(url_for('parametros', error=f"Erro: 15 Números deve ser 100%. (Atual: {soma_15}%)"))

            soma_25 = get_float_val('porcento_25_linha') + get_float_val('porcento_25_bingo')
            if abs(soma_25 - 100.0) > 0.01:
                 return redirect(url_for('parametros', error=f"Erro: 25 Números deve ser 100%. (Atual: {soma_25}%)"))

        # --- DEFINIÇÃO DO ESTADO DE TREINAMENTO ---
        # Captura o valor do checkbox do HTML
        treinamento_ativo = True if request.form.get('em_treinamento') else False #[cite: 3]

        # --- 2. CONSTRUÇÃO DO DICIONÁRIO PARA O BANCO DE VENDAS ---
        dados_atualizados = {
            'limite_de_credito': int(request.form.get('limite_de_credito', 0)),
            'acumulado': safe_dec(request.form.get('acumulado', '0')),
            'tope': int(request.form.get('tope', 0)),
            'minimo_terminal': int(request.form.get('minimo_terminal', 6)),
            'maximo_terminal': int(request.form.get('maximo_terminal', 1200)),
            'porcento_premios': porcento_premios_val,
            'em_treinamento': treinamento_ativo, # Campo original
            'tempo_atualizacao_premios': int(request.form.get('tempo_atualizacao_premios', 1)),
            'minimo_atualizacao_premios': safe_dec(request.form.get('minimo_atualizacao_premios', '50.00')),
            'receber_pix': True if request.form.get('receber_pix') else False,
            'chat_id_telegram': request.form.get('chat_id_telegram', '').strip(),
            'token_telegram': request.form.get('token_telegram', '').strip(),
            'texto_requisicao_saque': request.form.get('texto_requisicao_saque', '').strip(),
            'perc_venda_direta': safe_dec(request.form.get('perc_venda_direta', '15.0')),
            'perc_venda_indireta_a': safe_dec(request.form.get('perc_venda_indireta_a', '5.0')),
            'perc_venda_indireta_b': safe_dec(request.form.get('perc_venda_indireta_b', '10.0')),
            'porcento_15': {
                'linha': safe_dec(request.form.get('porcento_15_linha', '0')),
                'bingo': safe_dec(request.form.get('porcento_15_bingo', '0')),
                'segundobingo': safe_dec(request.form.get('porcento_15_segundobingo', '0'))
            },
            'porcento_25': {
                'linha': safe_dec(request.form.get('porcento_25_linha', '0')),
                'bingo': safe_dec(request.form.get('porcento_25_bingo', '0'))
            },
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

        # 3. AUDITORIA (Taxas)
        novas_taxas = ['perc_venda_direta', 'perc_venda_indireta_a', 'perc_venda_indireta_b']
        for tx in novas_taxas:
            v_novo = get_float_val(tx)
            v_antigo = float(str(params_atuais.get(tx, 0))) 
            if v_novo != v_antigo:
                registrar_log(acao="EDITAR", categoria="PARAMETROS", detalhes=f"Taxa {tx}: {v_antigo}% -> {v_novo}%", alvo_id="TAXAS_COMISSAO")

        # 4. GRAVAÇÃO NO BANCO DE VENDAS
        db.parametros.update_one({}, {'$set': dados_atualizados}, upsert=True) ## [cite: 3]

        # ==============================================================================
        # 🔄 SINCRONIZAÇÃO COM BANCO "DADOS_DO_SORTEIO"
        # ==============================================================================
        uri_sorteio = getattr(g, 'url_mongo_sorteio', None)
        
        if uri_sorteio:
            try:
                # Conecta usando a URI dinâmica resgatada pelo get_vendas_db()
                client_sorteio = MongoClient(uri_sorteio, tlsCAFile=certifi.where()) 
                db_sorteio = client_sorteio['dados_do_sorteio']
                
                # Grava no campo "modo_treinamento"
                db_sorteio.parametros.update_one(
                    {}, 
                    {'$set': {'modo_treinamento': treinamento_ativo}}, 
                    upsert=True
                )
                #print(f"✅ Sincronização Sorteio: modo_treinamento = {treinamento_ativo}")
                client_sorteio.close()
            except Exception as e_sorteio:
                print(f"⚠️ Erro ao sincronizar com banco de sorteio: {e_sorteio}")
        else:
            print("⚠️ URL do banco de Sorteio não encontrada no cadastro da sala.")       
        # ==============================================================================
        
        registrar_log("EDITAR", "PARAMETROS", f"Parâmetros financeiros alterados por {nick_operador}.")
        return redirect(url_for('parametros', success="Configurações gravadas e sincronizadas com sucesso!"))

    except Exception as e:
        print(f"Erro Crítico: {e}")
        return redirect(url_for('parametros', error=f"Erro interno: {e}"))


def motor_background_premios():
    """
    Background Thread: Roda a cada X minutos varrendo as salas.
    Localiza eventos cujo 'valor_pendente_telemovel' atingiu o gatilho,
    recalcula os prêmios e subtrai o valor lido para evitar perda de concorrência.
    """
    #print("[ROBÔ] 🤖 Inicializando thread de recálculo de prêmios...")
    
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
                            #print(f"[ROBÔ SALA {id_sala}] 🚀 Prêmio EVE{ev['id_evento']} atualizado! Buffer abatido em: R$ {valor_lido:.2f}")

                except Exception as e_sala:
                    print(f"[ROBÔ ERRO] Falha ao processar sala {id_sala}: {e_sala}")
                    
        except Exception as e_global:
            print(f"[ROBÔ ERRO GLOBAL] Falha no loop principal do robô: {e_global}")
            
        # O robô volta a dormir pelos minutos configurados no painel Parâmetros
        time.sleep(tempo_sleep_global)

# Inicia o robô invisível junto com a inicialização do Flask
threading.Thread(target=motor_background_premios, daemon=True).start()

# ==============================================================================
# 📊 MÓDULO FINANCEIRO DOS CLIENTES (Sintético e Analítico)
# ==============================================================================

@app.route('/submenu_financeiro')
@login_required
def submenu_financeiro():
    # Segurança: Apenas Administradores (Nível 3) acedem ao menu financeiro
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Módulo exclusivo para Administradores."))
    return render_template('submenu_financeiro.html')


@app.route('/financeiro_clientes', methods=['GET'])
@login_required
def financeiro_clientes():
    db = get_vendas_db()
    if db is None: return redirect(url_for('login'))
    
    nivel_usuario = session.get('nivel', 0)
    if nivel_usuario < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    # --- CONTEXTO REGIONAL (FASE 4) ---
    id_regional_sessao = session.get('id_regional')
    is_master = (nivel_usuario >= 4)
    # ----------------------------------

    # 1. Captura de Filtros
    hoje = hora_brasil().strftime('%Y-%m-%d')
    data_inicio = request.args.get('data_inicio', hoje)
    data_fim = request.args.get('data_fim', hoje)
    natureza_filtro = request.args.get('natureza', 'TODAS') 
    busca_cliente = request.args.get('busca_cliente', '').strip()

    # 2. Construção da Query Base (Regionalizada)
    query = {}
    
    # 🚀 CORREÇÃO: Trava Regional Blindada contra Valores Nulos ou Inválidos
    if not is_master and id_regional_sessao:
        try:
            query['id_regional'] = int(id_regional_sessao)
        except (ValueError, TypeError):
            pass # Ignora silenciosamente se houver lixo na variável da sessão

    # Tratamento de Datas
    try:
        dt_inicio = datetime.strptime(data_inicio, '%Y-%m-%d')
        dt_fim = datetime.strptime(data_fim, '%Y-%m-%d') + timedelta(days=1) - timedelta(microseconds=1)
        query['data_hora'] = {'$gte': dt_inicio, '$lte': dt_fim}
    except Exception as e:
        print(f"Erro no filtro de datas: {e}")

    if natureza_filtro in ['ENTRADA', 'SAIDA']:
        query['natureza'] = natureza_filtro

    if busca_cliente:
        if busca_cliente.isdigit():
            query['id_cliente'] = int(busca_cliente)
        else:
            cli = db.clientes.find_one({'nick': {'$regex': f'^{re.escape(busca_cliente)}', '$options': 'i'}})
            query['id_cliente'] = cli.get('id_cliente') if cli else -1

    try:
        # ======================================================================
        # 📈 VISÃO SINTÉTICA (Resumo Regionalizado)[cite: 1]
        # ======================================================================
        pipeline_resumo = [
            {'$match': query},
            {'$group': {
                '_id': {'natureza': '$natureza', 'tipo': '$tipo'},
                'total_valor': {'$sum': '$valor'},
                'qtd_operacoes': {'$sum': 1}
            }}
        ]
        resumo_raw = list(db.transacoes_clientes.aggregate(pipeline_resumo))
        
        resumo = {'total_entradas': 0.0, 'total_saidas': 0.0, 'detalhes': []}
        
        for r in resumo_raw:
            nat = r['_id'].get('natureza', 'Desconhecido')
            tipo = r['_id'].get('tipo', 'Outros')
            val = safe_float(r['total_valor'])
            tipo_formatado = tipo.replace('_', ' ').title()
            
            if nat == 'ENTRADA': resumo['total_entradas'] += val
            else: resumo['total_saidas'] += abs(val)
            
            resumo['detalhes'].append({
                'natureza': nat,
                'tipo': tipo_formatado,
                'total': abs(val),
                'qtd': r['qtd_operacoes']
            })

        resumo['detalhes'].sort(key=lambda x: (x['natureza'], x['total']), reverse=True)

        # ======================================================================
        # 📋 VISÃO ANALÍTICA (Extrato com Trava Regional)[cite: 1]
        # ======================================================================
        pipeline_extrato = [
            {'$match': query},
            {'$sort': {'data_hora': -1}},
            {'$limit': 1000}, 
            {'$lookup': {
                'from': 'clientes',
                'localField': 'id_cliente',
                'foreignField': 'id_cliente',
                'as': 'dados_cliente'
            }},
            {'$unwind': {'path': '$dados_cliente', 'preserveNullAndEmptyArrays': True}}
        ]
        
        transacoes_raw = list(db.transacoes_clientes.aggregate(pipeline_extrato))
        transacoes = []
        
        for t in transacoes_raw:
            t['valor_float'] = safe_float(t.get('valor', 0))
            t['saldo_ant_float'] = safe_float(t.get('saldo_anterior', 0))
            t['saldo_pos_float'] = safe_float(t.get('saldo_posterior', 0))
            t['data_fmt'] = t['data_hora'].strftime("%d/%m/%Y %H:%M:%S") if 'data_hora' in t else 'N/A'
            t['nick_cliente'] = t.get('dados_cliente', {}).get('nick', 'Desconhecido')
            t['tipo_fmt'] = str(t.get('tipo', '')).replace('_', ' ').title()
            transacoes.append(t)

        return render_template('financeiro_clientes.html',
                               resumo=resumo,
                               transacoes=transacoes,
                               filtros={
                                   'data_inicio': data_inicio, 
                                   'data_fim': data_fim, 
                                   'natureza': natureza_filtro, 
                                   'busca': busca_cliente
                               },
                               g=g)

    except Exception as e:
        print(f"Erro no Financeiro de Clientes: {e}")
        return redirect(url_for('menu_operacoes', error=f"Erro no relatório: {e}"))


#===========================
# GESTÃO E LIMPEZA DOS DADOS (FASE 4 - SNAPSHOTS INCLUSOS)
@app.route('/admin/limpeza_dados', methods=['GET', 'POST'])
@login_required
def limpeza_dados():
    if session.get('nivel', 0) < 4:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))

    db = get_vendas_db()
    BLINDADAS = ['colaboradores', 'usuarios', 'config', 'parametros', 'salas', 'config_bloqueio', 'contadores','sorte_extra_config']

    if request.method == 'POST':
        tabelas_selecionadas = request.form.getlist('tabelas')
        confirmacao = request.form.get('confirmacao_manual', '').upper().strip()

        if confirmacao not in ["ESVAZIAR", "EXCLUIR"]:
            disponiveis = sorted([c for c in db.list_collection_names() if c not in BLINDADAS])
            return render_template('limpeza_dados.html', error="Confirmação incorreta.", blindadas=BLINDADAS, disponiveis=disponiveis)

        try:
            operacoes_realizadas = 0
            resets_contadores = 0
            
            for tabela in tabelas_selecionadas:
                if tabela not in BLINDADAS:
                    # --- EXECUÇÃO DA OPERAÇÃO ---
                    if confirmacao == "ESVAZIAR":
                        db[tabela].delete_many({})
                    elif confirmacao == "EXCLUIR":
                        db[tabela].drop()
                    
                    operacoes_realizadas += 1

                    # --- INTELIGÊNCIA PARA VENDAS E SNAPSHOTS ---
                    # 1. Se for tabela de vendas ou snapshot de vendas
                    is_venda = tabela.startswith('vendas') and not tabela.startswith('vendas_sorte_extra')
                    is_snapshot = tabela.startswith('snapshot_vendas_')

                    if is_venda or is_snapshot:
                        # Extrai o ID do evento do nome da tabela (vendas158 ou snapshot_vendas_158)
                        parts = tabela.split('_')
                        id_evento_extraido = None
                        
                        if is_venda:
                            # Tenta pegar o número após a palavra 'vendas'
                            match = re.search(r'vendas(\d+)', tabela)
                            if match: id_evento_extraido = int(match.group(1))
                        else:
                            # Pega a última parte do nome (snapshot_vendas_158 -> 158)
                            try: id_evento_extraido = int(parts[-1])
                            except: pass

                        # Se conseguimos identificar o evento, limpamos o controle de numeração atômica
                        if id_evento_extraido:
                            db.controle_venda.delete_many({'id_evento': id_evento_extraido}) # [cite: 1]
                            resets_contadores += 1

                    # 2. Reset de contadores globais (clientes, etc)
                    if tabela == 'clientes' and confirmacao == "ESVAZIAR":
                        db.contadores.update_one({'_id': 'global'}, {'$set': {'id_clientes_global': 0}}, upsert=True)
                        resets_contadores += 1

            verbo = "limpas" if confirmacao == "ESVAZIAR" else "excluídas"
            msg = f"Sucesso! {operacoes_realizadas} tabelas {verbo} e {resets_contadores} vínculos de controle removidos."
            
            disponiveis = sorted([c for c in db.list_collection_names() if c not in BLINDADAS])
            return render_template('limpeza_dados.html', success=msg, blindadas=BLINDADAS, disponiveis=disponiveis)
            
        except Exception as e:
            traceback.print_exc()
            return render_template('limpeza_dados.html', error=f"Erro crítico: {e}", blindadas=BLINDADAS)

    disponiveis = sorted([c for c in db.list_collection_names() if c not in BLINDADAS])
    return render_template('limpeza_dados.html', disponiveis=disponiveis, blindadas=BLINDADAS)


@app.route('/admin/buscar_proximo_numero_inicial', methods=['GET'])
@login_required
def buscar_proximo_numero_inicial():
    db = get_vendas_db()
    try:
        # 1. Localiza o último evento finalizado (ordenado por data e hora decrescente)
        ultimo_evento = db.eventos.find_one(
            {'status': {'$in': ['finalizado', 'FINALIZADO']}},
            sort=[('data_evento', -1), ('hora_evento', -1)]
        )

        if not ultimo_evento:
            return jsonify({'sucesso': True, 'numero': 1, 'obs': 'Nenhum evento anterior encontrado.'})

        id_ultimo = ultimo_evento.get('id_evento')

        # 2. Busca na tabela controle_venda o ponteiro de parada deste evento
        controle = db.controle_venda.find_one({'id_evento': id_ultimo})
        
        if controle and 'inicial_proxima_venda' in controle:
            proximo_numero = int(controle['inicial_proxima_venda'])
            return jsonify({
                'sucesso': True, 
                'numero': proximo_numero,
                'evento_origem': ultimo_evento.get('descricao', str(id_ultimo))
            })
        
        # Fallback caso o evento exista mas não tenha registro no controle
        return jsonify({'sucesso': True, 'numero': 1, 'obs': 'Evento encontrado, mas sem registro de vendas.'})

    except Exception as e:
        print(f"Erro ao buscar número inicial: {e}")
        return jsonify({'sucesso': False, 'erro': str(e)}), 500

# ROTINA DE REGISTRO DE LOGS (auditoria de operações realizadas)
# --- FUNÇÃO MESTRE DE AUDITORIA ---
def registrar_log(acao, categoria, detalhes, alvo_id=None):
    """
    Registra uma ação administrativa no banco de dados.
    """
    db = get_vendas_db()
    if db is not None:
        try:
            log_doc = {
                "data_hora": hora_brasil(),
                "operador_nick": session.get('nick', 'SISTEMA'),
                "operador_id": session.get('id_colaborador', 'N/A'),
                "acao": acao.upper(),         # EXCLUIR, EDITAR, LOGIN, RECARGA, EXPURGO
                "categoria": categoria.upper(), # CLIENTES, EVENTOS, PARAMETROS, FINANCEIRO
                "detalhes": detalhes,
                "alvo_id": alvo_id,
                "ip_origem": request.remote_addr
            }
            db.logs_auditoria.insert_one(log_doc)
        except Exception as e:
            print(f"Erro ao gravar log: {e}")

# --- ROTA DE VISUALIZAÇÃO ---
@app.route('/admin/auditoria')
@login_required
def auditoria():
    # Apenas Admin Nível 3 (Engenharia)
    if session.get('nivel', 0) < 3:
        return redirect(url_for('menu_operacoes', error="Acesso Negado."))
    
    db = get_vendas_db()
    if db is None: return redirect(url_for('menu_operacoes'))

    try:
        # Busca os últimos 200 logs, do mais recente para o mais antigo
        logs = list(db.logs_auditoria.find().sort('data_hora', -1).limit(200))
        
        for l in logs:
            l['_id'] = str(l['_id'])
            if 'data_hora' in l:
                l['data_fmt'] = l['data_hora'].strftime("%d/%m/%Y %H:%M:%S")
    except:
        logs = []

    return render_template('auditoria.html', logs=logs, g=g)


# GERAR PDF DE INDICAÇÕES
@app.route('/exportar_indicacoes')
@login_required
def exportar_indicacoes():
    db = get_vendas_db()
    filtro_colab = request.args.get('filtro_colab', type=int)
    
    if not filtro_colab:
        return "Erro: Selecione um colaborador.", 400

    clientes = list(db.clientes.find({"id_colaborador": filtro_colab}).sort("nick", 1))
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    # Cabeçalho atualizado
    writer.writerow(['ID', 'NICK', 'NOME', 'TELEFONE', 'CADASTRO', 'STATUS ATIVIDADE'])
    
    for c in clientes:
        id_cli = c.get('id_cliente')
        
        # --- BUSCA RÁPIDA DE ATIVIDADE ---
        # Verificamos na coleção de vendas se existe algum registro para este ID
        # (Ajuste o nome da coleção 'vendas_global' ou similar conforme seu banco)
        ultima_venda = db.vendas_consolidado.find_one(
            {"id_cliente": id_cli}, 
            sort=[("data_hora", -1)]
        )
        
        status_venda = "Sem Compras"
        if ultima_venda:
            dt_venda = ultima_venda.get('data_hora')
            status_venda = f"Ativo em {dt_venda.strftime('%d/%m/%Y')}" if hasattr(dt_venda, 'strftime') else "Ativo"

        data_cad = c.get('data_cadastro')
        data_cad_fmt = data_cad.strftime('%d/%m/%Y') if hasattr(data_cad, 'strftime') else "N/D"
            
        writer.writerow([
            id_cli,
            c.get('nick'),
            c.get('nome_cliente'),
            c.get('telefone'),
            data_cad_fmt,
            status_venda
        ])

    output.seek(0)
    filename = f"relatorio_vendedor_{filtro_colab}.csv"
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )


# ROTA 1: Carrega a página HTML
@app.route('/admin/clonar_banco', methods=['GET'])
@login_required
def view_clonar_banco():
    # Segurança: Apenas Master deve acessar esta ferramenta
    if session.get('nivel', 0) < 4:
        return redirect(url_for('menu_operacoes', error="Acesso Negado. Área Master."))
    
    # Obtém o cliente raiz do MongoDB para listar todos os bancos
    # Adapte 'mongo.cx' para a variável do seu MongoClient (ex: client)
    cliente_mongo = get_vendas_db().client 
    
    bancos_ocultos = ['admin', 'config', 'local']
    bancos_disponiveis = [db for db in cliente_mongo.list_database_names() if db not in bancos_ocultos]
    
    return render_template('clonar_banco.html', bancos=bancos_disponiveis)


# ROTA 2: API que devolve as tabelas (coleções) de um banco escolhido
@app.route('/api/colecoes_banco/<nome_banco>', methods=['GET'])
@login_required
def api_colecoes_banco(nome_banco):
    if session.get('nivel', 0) < 4:
        return jsonify({'status': 'error', 'message': 'Acesso negado'})
        
    try:
        cliente_mongo = get_vendas_db().client
        db_origem = cliente_mongo[nome_banco]
        colecoes = db_origem.list_collection_names()
        # Ordena alfabeticamente para facilitar a visualização
        return jsonify({'status': 'success', 'colecoes': sorted(colecoes)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# ROTA 3: API que faz a cópia (Clone) das tabelas e dados para uma URL Externa
@app.route('/api/executar_clone', methods=['POST'])
@login_required
def api_executar_clone():
    if session.get('nivel', 0) < 4:
        return jsonify({'status': 'error', 'message': 'Acesso negado'})

    dados = request.json
    db_origem_nome = dados.get('db_origem')
    url_destino_bruta = dados.get('url_destino') # Recebe a URL base
    colecoes_selecionadas = dados.get('colecoes', [])

     # 🚀 TRAVA DE SEGURANÇA: Injeta tabelas vitais obrigatoriamente
    tabelas_vitais = ['parametros', 'colaboradores']
    for tabela in tabelas_vitais:
        if tabela not in colecoes_selecionadas:
            colecoes_selecionadas.append(tabela)

    if not db_origem_nome or not url_destino_bruta or not colecoes_selecionadas:
        return jsonify({'status': 'error', 'message': 'Dados incompletos. Preencha todos os campos.'})

    try:
        from pymongo import MongoClient

        # --- TRATAMENTO INTELIGENTE DA URL ---
        # 1. Separa os parâmetros (tudo depois do '?')
        partes_url = url_destino_bruta.split('?', 1)
        url_base = partes_url[0]
        query_params = '?' + partes_url[1] if len(partes_url) > 1 else ''

        # 2. Isola o protocolo (mongodb:// ou mongodb+srv://) do host
        if '://' in url_base:
            protocolo, resto = url_base.split('://', 1)
        else:
            protocolo, resto = 'mongodb', url_base

        # 3. Limpa qualquer banco que o usuário possa ter deixado na URL
        host_auth = resto.split('/')[0]

        # 4. Reconstrói a URL final forçando o nome do banco de origem
        url_destino_final = f"{protocolo}://{host_auth}/{db_origem_nome}{query_params}"
        # -------------------------------------

        # Conexão de Origem
        cliente_origem = get_vendas_db().client
        db_origem = cliente_origem[db_origem_nome]

        # Conexão de Destino (Usando a URL tratada)
        cliente_destino = MongoClient(url_destino_final)
        db_destino = cliente_destino[db_origem_nome]

        estatisticas = []

        for nome_col in colecoes_selecionadas:
            col_origem = db_origem[nome_col]
            col_destino = db_destino[nome_col]

            # Copiamos em lotes de 1000 documentos
            lote = []
            total_copiado = 0
            
            # Limpa a coleção de destino caso ela já exista
            col_destino.delete_many({})

            for documento in col_origem.find():
                lote.append(documento)
                if len(lote) >= 1000:
                    col_destino.insert_many(lote)
                    total_copiado += len(lote)
                    lote = []
            
            if lote:
                col_destino.insert_many(lote)
                total_copiado += len(lote)
                
            estatisticas.append(f"{nome_col} ({total_copiado} docs)")

        msg_sucesso = f"Banco '{db_origem_nome}' espelhado com sucesso no novo servidor! Tabelas clonadas: " + ", ".join(estatisticas)
        return jsonify({'status': 'success', 'message': msg_sucesso})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f"Erro interno: {str(e)}"})


#=================================================================
# CORREÇÕES DO SISTEMA (Funções com chamadas externas)
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
        #print(f"[MANUTENÇÃO] Removidos {delete_result.deleted_count} registros antigos de bloqueio.")

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
        #print(f"[LOG ADMIN] {session.get('nick')} resetou e atualizou bloqueios na sala {g.id_sala}.")
        
        return redirect(url_for('cadastro_cliente', success=msg, view='bloqueio'))

    except Exception as e:
        print(f"Erro ao processar limpeza/população de bloqueios: {e}")
        return redirect(url_for('cadastro_cliente', error=f"Erro interno: {e}"))

#==================================
# CORRIGIR CAMPO SENHA VAZIO
#================================== 
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
        #print(f"[MANUTENÇÃO] Admin {session.get('nick')} corrigiu senhas na sala {g.id_sala}.")
        
        registrar_log("MANUTENÇÃO", "SISTEMA", f"Correção em massa de senhas executada ({resultado.modified_count} afetados).")
        return redirect(url_for('cadastro_cliente', success=msg, view='listar'))

    except Exception as e:
        # Log de erro caso algo falhe no processo de banco ou criptografia
        print(f"Erro na manutenção de senhas: {e}")
        return redirect(url_for('cadastro_cliente', error=f"Erro interno na correção: {e}"))

#===============================================
# --- ROTA UTILITÁRIA: LIMPAR TABELA ESPECÍFICA ---
# limpar registros de tala tebela; exemplo tabela "requisao_saque"
# deve estar logando como administrador
#http://localhost:5001/admin/limpar_tabela/requisao_saque
#===============================================
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

    # 1. SEGURANÇA: Apenas Nível 4 (Admin)
    if session.get('nivel', 0) < 4:
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
        #print(f"[AUDITORIA] Admin {session.get('nick')} limpou a tabela {nome_tabela}.")
        
        return jsonify({
            'status': 'success',
            'msg': msg,
            'registros_removidos': resultado.deleted_count
        })

    except Exception as e:
        return jsonify({'status': 'error', 'msg': f'Erro interno: {e}'}), 500


#==================================
# EXCLUI OS REGISTRO COM STATUS DE EM_TREINAMENTO DA TABELA CLIENTE 
# >>>  http://localhost:5001/admin/expurgar_treinamento
#================================== 
@app.route('/admin/expurgar_treinamento')
@login_required
def expurgar_treinamento():
    """
    EXCLUSÃO DEFINITIVA: 
    Remove do banco todos os clientes marcados com 'em_treinamento': True
    e apaga todas as suas transações financeiras.
    """
    # 1. Segurança: Apenas nível 4 (Administrador Master)
    if session.get('nivel', 0) < 4:
        return redirect(url_for('menu_operacoes', error="Acesso negado."))

    db = get_vendas_db()
    if db is None:
        return redirect(url_for('cadastro_cliente', error="Erro de conexão com o banco."))

    try:
        # 2. Identificar os IDs dos clientes que serão apagados (para limpar o financeiro)
        # Buscamos a lista de IDs antes de deletar o cadastro
        clientes_treino = list(db.clientes.find({"em_treinamento": True}, {"id_cliente": 1}))
        ids_para_excluir = [c['id_cliente'] for c in clientes_treino]

        if not ids_para_excluir:
            return redirect(url_for('cadastro_cliente', success="Nenhum registro de treinamento encontrado para excluir.", view='listar'))

        # 3. EXCLUSÃO 1: Tabela de Clientes
        res_clientes = db.clientes.delete_many({"em_treinamento": True})

        # 4. EXCLUSÃO 2: Tabela de Transações (Extratos)
        # Remove qualquer rastro financeiro ligado a esses IDs
        res_transacoes = db.transacoes_clientes.delete_many({"id_cliente": {"$in": ids_para_excluir}})

        registrar_log("EXPURGO", "SISTEMA", f"Limpeza total de {res_clientes.deleted_count} registros de treinamento.")

        # 5. Log de Auditoria no Console
        msg = f"EXPURGO CONCLUÍDO: {res_clientes.deleted_count} clientes e {res_transacoes.deleted_count} transações foram removidos permanentemente."
        print(f"\n[ALERTA DE SEGURANÇA] {session.get('nick')} EXECUTOU EXPURGO DE TREINAMENTO.")
        print(f"Registros removidos: {res_clientes.deleted_count}\n")
        
        return redirect(url_for('cadastro_cliente', success=msg, view='listar'))

    except Exception as e:
        print(f"Erro crítico no expurgo: {e}")
        return redirect(url_for('cadastro_cliente', error=f"Falha na exclusão: {e}"))


#==================================
# AJUSTAR CAMPOS DA TABELA CLIENTE 
# >>>  http://localhost:5001/admin/ativar_modo_treino_retroativo
#================================== 
@app.route('/admin/ativar_modo_treino_retroativo')
@login_required
def ativar_modo_treino_retroativo():
    if session.get('nivel', 0) < 4:
        return redirect(url_for('menu_operacoes', error="Acesso negado."))

    db = get_vendas_db()
    if db is None:
        return redirect(url_for('cadastro_cliente', error="Erro de conexão com o banco."))

    try:
        # 1. Tentativa com objeto DATETIME (Se gravou como objeto de data)
        data_corte_obj = datetime(2026, 3, 21, 0, 0, 0)
        
        # 2. Tentativa com STRING (Se gravou como texto via hora_brasil)
        # Usamos regex para pegar qualquer hora do dia 21 em diante ou datas posteriores
        # Nota: Como strings são comparadas caractere a caractere, 
        # o filtro "$gte" em strings de data brasileira (DD/MM) costuma falhar.
        # Por isso, vamos tentar primeiro o filtro de objeto.
        
        filtro = {
            "$or": [
                {"data_cadastro": {"$gte": data_corte_obj}}, # Se for ISODate
                {"data_cadastro": {"$regex": "^21/03/2026"}} # Se for String começando com 21/03
            ]
        }
        
        atualizacao = {
            "$set": {
                "em_treinamento": True,
                "saldo_atual": Decimal128("10000.00")
            }
        }

        # Executa
        resultado = db.clientes.update_many(filtro, atualizacao)

        # Se ainda assim der 0, vamos tentar um filtro mais largo para teste
        if resultado.modified_count == 0:
            # Tenta buscar APENAS UM para debug no console
            amostra = db.clientes.find_one({}, {"data_cadastro": 1})
            #print(f"[DEBUG] Tipo de data no banco: {type(amostra.get('data_cadastro'))} - Valor: {amostra.get('data_cadastro')}")
            msg = "Nenhum registro encontrado com a data de 21/03/2026. Verifique o log do console."
        else:
            msg = f"Sucesso! {resultado.modified_count} clientes atualizados."

        return redirect(url_for('cadastro_cliente', success=msg, view='listar'))

    except Exception as e:
        print(f"Erro na conversão: {e}")
        return redirect(url_for('cadastro_cliente', error=f"Erro: {e}"))


# >>>  http://localhost:5001/migrar_regionais
@app.route('/migrar_regionais')
@login_required
def migrar_regionais():
    # Apenas o Master pode rodar isso
    if session.get('nivel', 0) < 4:
        return "Acesso Negado. Apenas Nível 4.", 403

    db = get_vendas_db()
    mensagens = []

    # 1. Verifica/Cria a Regional 1 (Padrão)
    if db.regionais.count_documents({}) == 0:
        gestor_nome = session.get('nick', 'Administrador')
        db.regionais.insert_one({
            "id_regional": 1,
            "descricao": "REGIONAL 1 (MATRIZ)",
            "gestores": [{"nome": gestor_nome, "telefone": "11999999999"}],
            "localidades": ["Sede"],
            "data_atualizacao": hora_brasil()
        })
        mensagens.append("✅ Regional 1 criada com sucesso.")
    else:
        mensagens.append("ℹ️ A coleção de regionais já possui registros. Nenhuma regional nova criada.")

    # 2. Atualiza todos os colaboradores órfãos
    # '$exists': False pega quem não tem o campo. 
    resultado = db.colaboradores.update_many(
        {"id_regional": {"$exists": False}}, 
        {"$set": {"id_regional": 1}}
    )
    
    # Garantia extra: pega quem tem o campo, mas está nulo ou vazio
    resultado_nulos = db.colaboradores.update_many(
        {"id_regional": {"$in": [None, "", 0]}}, 
        {"$set": {"id_regional": 1}}
    )

    total_atualizados = resultado.modified_count + resultado_nulos.modified_count
    mensagens.append(f"✅ Migração de Colaboradores concluída: {total_atualizados} perfis atualizados para a Regional 1.")

    # Formata a saída na tela
    html_resumo = "<br>".join(mensagens)
    return f"""
        <h3>Migração Concluída com Sucesso! 🚀</h3>
        <p>{html_resumo}</p>
        <br>
        <a href='/admin/regionais' style='padding: 10px; background: blue; color: white; text-decoration: none; border-radius: 5px;'>Ir para Gestão de Regionais</a>
    """

# >>>  http://localhost:5001/admin/corrigir_tipo_data_e_treino
@app.route('/admin/corrigir_tipo_data_e_treino')
@login_required
def corrigir_tipo_data_e_treino():
    if session.get('nivel', 0) < 4:
        return redirect(url_for('menu_operacoes', error="Acesso negado."))

    db = get_vendas_db()
    if db is None: return redirect(url_for('cadastro_cliente', error="Erro de conexão."))

    try:
        clientes = list(db.clientes.find({}))
        contagem_convertidos = 0
        contagem_treino = 0
        data_corte = datetime(2026, 3, 21, 0, 0, 0)

        for cli in clientes:
            data_original = cli.get('data_cadastro')
            data_objeto = None
            atualizacao = {}

            if isinstance(data_original, str):
                # Tenta primeiro o formato ISO (que apareceu no seu log: 2026-01-31...)
                try:
                    data_objeto = datetime.strptime(data_original[:19], "%Y-%m-%d %H:%M:%S")
                except:
                    # Se falhar, tenta o formato Brasileiro (DD/MM/AAAA...)
                    try:
                        data_objeto = datetime.strptime(data_original[:19], "%d/%m/%Y %H:%M:%S")
                    except:
                        print(f"Não foi possível converter a data do cliente {cli.get('nick')}: {data_original}")

                if data_objeto:
                    atualizacao["data_cadastro"] = data_objeto
                    contagem_convertidos += 1
            else:
                data_objeto = data_original

            # Aplica regra de treino se a data (já convertida) for após o corte
            if data_objeto and isinstance(data_objeto, datetime):
                if data_objeto >= data_corte:
                    atualizacao["em_treinamento"] = True
                    atualizacao["saldo_atual"] = Decimal128("1000.00")
                    contagem_treino += 1

            if atualizacao:
                db.clientes.update_one({"_id": cli['_id']}, {"$set": atualizacao})

        msg = f"Sucesso! Convertidos: {contagem_convertidos}. Em treino: {contagem_treino}."
        return redirect(url_for('cadastro_cliente', success=msg, view='listar'))

    except Exception as e:
        return redirect(url_for('cadastro_cliente', error=f"Erro crítico: {e}"))


# >>>  http://localhost:5001/admin/manutencao_clientes_regional
@app.route('/migrar_historico_vendas')
@login_required
def migrar_historico_vendas():
    if session.get('nivel', 0) < 4: return "Acesso Negado", 403
    db = get_vendas_db()
    
    # Criamos um mapa de Colaborador -> Regional para evitar milhares de consultas
    mapa_colabs = {c['id_colaborador']: c.get('id_regional', 1) 
                    for c in db.colaboradores.find({}, {'id_colaborador': 1, 'id_regional': 1})}
    
    total_processado = 0
    for col_name in db.list_collection_names():
        if col_name.startswith("vendas"):
            # Busca vendas que ainda não possuem o campo id_regional
            vendas_sem_reg = db[col_name].find({"id_regional": {"$exists": False}})
            for venda in vendas_sem_reg:
                id_vendedor = venda.get('id_vendedor')
                # Tenta converter para int se necessário
                try: id_vendedor = int(id_vendedor)
                except: pass
                
                reg_id = mapa_colabs.get(id_vendedor, 1) # Fallback para matriz (1)
                db[col_name].update_one({"_id": venda["_id"]}, {"$set": {"id_regional": reg_id}})
                total_processado += 1
                
    return f"Sucesso! {total_processado} vendas históricas foram regionalizadas."

def criar_indices_regionais(db):
    # Lista todas as coleções para aplicar nas tabelas de vendas existentes
    for col_name in db.list_collection_names():
        if col_name.startswith("vendas"):
            # Índice Composto: Filtra por regional e ordena por data (mais recente primeiro)
            db[col_name].create_index([("id_regional", 1), ("data_venda", -1)])
    return "Índices criados com sucesso!"


@app.route('/admin/manutencao_clientes_regional', methods=['GET'])
@login_required
def manutencao_clientes_regional():
    # Segurança: Apenas Master pode rodar scripts de manutenção estrutural
    if session.get('nivel', 0) < 4:
        return "Acesso Negado. Apenas nível Master.", 403

    db = get_vendas_db()
    if db is None:
        return "Erro ao conectar ao banco de dados.", 500

    try:
        # Busca apenas os clientes que AINDA NÃO TEM o campo id_regional
        clientes_desatualizados = list(db.clientes.find({"id_regional": {"$exists": False}}))
        
        if not clientes_desatualizados:
            return "<h1>Tudo OK!</h1><p>Nenhum cliente desatualizado encontrado. Todos já possuem id_regional.</p><br><a href='/menu_operacoes'>Voltar ao Menu</a>"

        count_colab = 0
        count_default = 0
        
        # Dicionário em memória para não consultar o mesmo colaborador centenas de vezes
        cache_regional_colabs = {}

        for cli in clientes_desatualizados:
            id_colab = cli.get('id_colaborador')
            id_regional_final = 1  # Padrão: Matriz
            
            if id_colab:
                # Se ainda não sabemos a regional deste colaborador, vamos buscar ao banco
                if id_colab not in cache_regional_colabs:
                    colab_db = db.colaboradores.find_one({'id_colaborador': id_colab})
                    if colab_db and 'id_regional' in colab_db:
                        cache_regional_colabs[id_colab] = int(colab_db['id_regional'])
                    else:
                        cache_regional_colabs[id_colab] = 1 # Se o colab não tiver, assume 1
                        
                # Aplica a regional descoberta
                id_regional_final = cache_regional_colabs[id_colab]
            
            # Atualiza o cliente no banco de dados
            db.clientes.update_one(
                {'_id': cli['_id']},
                {'$set': {'id_regional': id_regional_final}}
            )
            
            # Contadores para o relatório final
            if id_regional_final == 1:
                count_default += 1
            else:
                count_colab += 1

        total = count_colab + count_default
        
        # Relatório de Execução em HTML simples
        html_report = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; border: 1px solid #ccc; border-radius: 10px; background: #f9f9f9;">
            <h1 style="color: #059669;">✅ Manutenção Concluída!</h1>
            <p>O banco de dados foi atualizado com sucesso.</p>
            <ul style="font-size: 18px;">
                <li><b>Total Atualizado:</b> {total} clientes</li>
                <li><b>Herdaram a regional do Colaborador:</b> {count_colab}</li>
                <li><b>Atribuídos à Matriz (Reg. 1):</b> {count_default}</li>
            </ul>
            <br>
            <a href="/cadastro_cliente?view=listar" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">Ver Lista de Clientes</a>
        </div>
        """
        return html_report

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"<h1>Erro Fatal:</h1><p>{str(e)}</p>"



#########################################################
if __name__ == '__main__':
    # Usamos o app_context para que o Flask permita o uso de funções que dependem do DB
    with app.app_context():
        try:
            db_inicial = get_vendas_db()
            if db_inicial is not None:
                inicializar_estrutura_db(db_inicial)
        except Exception as e:
            print(f"⚠️ Aviso: Não foi possível configurar índices no arranque: {e}")

    # Inicia o servidor
    if os.environ.get('FLASK_ENV') != 'production':
        app.run(debug=True, host='0.0.0.0', port=5001)
    else:
        print("⚠️ A rodar em modo produção...")

#========================================
# COMO EXCLUIR OS REGISTRO em_treinamento
#====================================
# db.clientes.delete_many({"em_treinamento": true}

