from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session, g
from bson.decimal128 import Decimal128
import re
import traceback

venda_lite_bp = Blueprint('venda_lite', __name__)

# ==============================================================================
# 🧮 FUNÇÕES MATEMÁTICAS E DE VALIDAÇÃO
# ==============================================================================
def converter_intervalo_kits_para_cartelas(kit_inicial, kit_final, unidade_de_venda):
    """
    Converte um intervalo de kits nos limites exatos de cartelas.
    Ex: Kit Inicial 301, Kit Final 302 (com 6 cartelas por kit)
    Resulta em: Cartela Inicial 1801, Cartela Final 1812
    """
    if kit_inicial < 1 or kit_final < kit_inicial:
        raise ValueError("Intervalo de kits inválido.")

    cartela_inicial = ((kit_inicial - 1) * unidade_de_venda) + 1
    cartela_final = kit_final * unidade_de_venda

    return cartela_inicial, cartela_final


def checar_conflito_venda(db, inicial, final, id_evento):
    """
    Retorna o documento da venda que conflita ou None se estiver livre.
    """
    colecao = db[f"vendas{id_evento}"]
    # Busca qualquer venda que intercepte o intervalo solicitado
    conflito = colecao.find_one({
        "$and": [
            {"numero_inicial": {"$lte": final}},
            {"numero_final": {"$gte": inicial}}
        ]
    })
    return conflito

# ==============================================================================
# 🌐 ROTAS DA VENDA LITE
# ==============================================================================

# 1. API de Autocomplete (Chamada pelo JavaScript)
@venda_lite_bp.route('/api/clientes/autocomplete', methods=['GET'])
def autocomplete_clientes():
    # IMPORTAÇÃO LOCAL PARA EVITAR CIRCULAR IMPORT
    from app import get_vendas_db
    
    db = get_vendas_db()
    termo = request.args.get('q', '').strip()
    if not termo or db is None:
        return jsonify([])

    regex = re.compile(termo, re.IGNORECASE)
    # Busca clientes por nick ou nome
    clientes_cursor = db.clientes.find({
        '$or': [{'nick': regex}, {'nome': regex}]
    }, {'_id': 0, 'nick': 1, 'nome': 1, 'id_colaborador': 1}).limit(10)

    resultados = []
    for c in clientes_cursor:
        resultados.append({
            "nick": c.get('nick') or c.get('nome', 'S/N'),
            "colaborador": c.get('id_colaborador', 'S/C')
        })
    return jsonify(resultados)


# 2. Rota de Interface (Carrega o HTML)
@venda_lite_bp.route('/venda-lite', methods=['GET'])
def nova_venda_lite():
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))

    # Importamos também o safe_float
    from app import get_vendas_db, try_object_id, safe_float
    
    db = get_vendas_db()
    if db is None: 
        return "Erro: Banco de Dados Offline."

    # Busca Parâmetros
    parametros = db.parametros.find_one({}) or {}
    padrao_venda = parametros.get('padrao_registro_vendas', 'quantidade') 
    print(f"🛠️ [DEBUG TELA LITE] Padrão de formulário capturado: '{padrao_venda}'")

    # Busca Lista de Eventos Ativos para o Modal
    eventos_cursor = db.eventos.find({'status': 'ativo'}).sort('data_evento', 1)
    
    # 👉 TRATAMENTO DOS DADOS PARA O JINJA (CRIANDO O FLOAT)
    eventos = []
    for evt in eventos_cursor:
        evt['valor_de_venda_float'] = safe_float(evt.get('valor_de_venda', 0.0))
        eventos.append(evt)

    # Identifica Evento Selecionado
    id_evento_str = request.args.get('id_evento')
    selected_event = None
    if id_evento_str:
        selected_event = db.eventos.find_one({'_id': try_object_id(id_evento_str)})
        if selected_event:
            # Tratamento também no evento selecionado
            selected_event['valor_de_venda_float'] = safe_float(selected_event.get('valor_de_venda', 0.0))
            
            # Como herdamos o HTML, ele procura esse campo para exibir. Se não existir, criamos um substituto.
            if 'numeracao_atual_display' not in selected_event:
                selected_event['numeracao_atual_display'] = "Calculada na Gravação"

    # Puxa o histórico do operador logado
    colaborador_id = session.get('id_colaborador', 'N/A')
    ultimas_vendas = []
    if selected_event and colaborador_id != 'N/A':
        id_evento_int = selected_event.get('id_evento')
        nome_colecao = f"vendas{str(id_evento_int).strip()}"
        
        if nome_colecao in db.list_collection_names():
            vendas_cruas = db[nome_colecao].find(
                {'id_vendedor': colaborador_id}
            ).sort('data_venda', -1).limit(5)
            
            # 👉 TRATAMENTO DOS DADOS: Criando o float para o HTML ler sem quebrar
            for v in vendas_cruas:
                v['valor_total_float'] = safe_float(v.get('valor_total', 0.0))
                ultimas_vendas.append(v)

    # Resgata mensagens de sucesso/impressão da sessão
    success = session.pop('success_message', None)
    print_data = session.pop('print_data', None)
    error = request.args.get('error')

    return render_template(
        'venda_lite.html', 
        padrao_venda=padrao_venda,
        eventos=eventos,
        selected_event=selected_event,
        ultimas_vendas=ultimas_vendas,
        error=error,
        success=success,
        print_data=print_data
    )


# 3. Rota de Processamento Atômico (Grava no Banco)
@venda_lite_bp.route('/processar_venda_lite', methods=['POST'])
def processar_venda_lite():
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))

    """
    print("REQUISIÇÃO CHEGOU NO SERVIDOR! (lite)")

    Processo de Venda Lite (Balcão Rápido).
    Mantém travas atômicas e coleções dinâmicas, ignora saldo de cliente.
    """
    # IMPORTAÇÃO LOCAL PARA EVITAR CIRCULAR IMPORT
    from app import get_vendas_db, hora_brasil, safe_float, try_object_id, get_next_bilhete_sequence, get_next_global_sequence, registrar_comissao_vendedor
    
    db = get_vendas_db()
    if db is None: 
        return redirect(url_for('venda_lite.nova_venda_lite', error="DB Offline."))

    id_evento_string = request.form.get('id_evento')
    nick_cliente_lite = request.form.get('nick_cliente_lite', '').strip() 
    
    error_redirect_kwargs = {'id_evento': id_evento_string}

    # Trava Backend: Nome obrigatório
    if not nick_cliente_lite:
        error_redirect_kwargs['error'] = "O Nome do Cliente é obrigatório."
        return redirect(url_for('venda_lite.nova_venda_lite', **error_redirect_kwargs))

    # Validação do Evento e Status
    id_evento_mongo = try_object_id(id_evento_string)
    selected_event = db.eventos.find_one({'_id': id_evento_mongo})
    
    if not selected_event:
        return redirect(url_for('venda_lite.nova_venda_lite', error="Evento não encontrado."))

    if selected_event.get('status', '').lower() != 'ativo':
        error_redirect_kwargs['error'] = "⛔ VENDA CANCELADA! O evento não está mais Ativo."
        return redirect(url_for('venda_lite.nova_venda_lite', **error_redirect_kwargs))

    # Carregar Parâmetros Globais
    parametros = db.parametros.find_one({}) or {}
    padrao_venda = parametros.get('padrao_registro_vendas', 'quantidade')
    #cartelas_por_kit = parametros.get('unidade_de_venda', 6)

    tipo_cartela = int(selected_event.get('tipo_de_cartela', 15))
    id_evento_int_para_controle = selected_event.get('id_evento')
    limite_maximo_cartelas = int(selected_event.get('numero_maximo', 72000))
    valor_unitario = safe_float(selected_event.get('valor_de_venda', 0.00))
    unidade_de_venda = int(selected_event.get('unidade_de_venda', 1))
    
    colaborador_id = session.get('id_colaborador', 'N/A')
    nick_colaborador_sessao = session.get('nick', 'Operador') 
    regional_operador = session.get('id_regional', 1)
    nome_colecao_venda = f"vendas{str(id_evento_int_para_controle).strip()}"

    quantidade_kits = 0
    numero_inicial_atual = None
    numero_final_atual = None

    try:
        # CHAVEAMENTO DE REGRA
        if padrao_venda == 'numeracao':
            numero_kit_inicial = int(request.form.get('numero_kit_inicial', 0))
            numero_kit_final_str = request.form.get('numero_kit_final', '')

            if numero_kit_inicial < 1: 
                raise ValueError("Kit inicial inválido.")
            
            # Se não preencheu o final, considera igual ao inicial (1 kit)
            if not numero_kit_final_str.strip():
                numero_kit_final = numero_kit_inicial
            else:
                numero_kit_final = int(numero_kit_final_str)

            # =================================================================
            # 🛡️ VALIDAÇÃO CRÍTICA: LIMITE MÁXIMO DE KITS PERMITIDO
            # =================================================================
            # Evita divisão por zero caso unidade_de_venda esteja nulo ou inválido
            divisor_unidade = unidade_de_venda if unidade_de_venda > 0 else 1
            limite_maximo_kits = limite_maximo_cartelas // divisor_unidade

            if numero_kit_inicial > limite_maximo_kits or numero_kit_final > limite_maximo_kits:
                error_redirect_kwargs['error'] = f"⛔ Venda Bloqueada! O número máximo de kit permitido para este evento é {limite_maximo_kits} (Limite: {limite_maximo_cartelas} cartelas)."
                return redirect(url_for('venda_lite.nova_venda_lite', **error_redirect_kwargs))
            # =================================================================

            if numero_kit_final < numero_kit_inicial:
                error_redirect_kwargs['error'] = "O Kit Final não pode ser menor que o Kit Inicial."
                return redirect(url_for('venda_lite.nova_venda_lite', **error_redirect_kwargs))

            quantidade_kits = (numero_kit_final - numero_kit_inicial) + 1
            quantidade = quantidade_kits # Unidades brutas (Kits)
            quantidade_cartelas_atual = quantidade_kits * unidade_de_venda
            
            # Chama a nossa nova função matemática baseada no período
            numero_inicial_atual, numero_final_atual = converter_intervalo_kits_para_cartelas(
                numero_kit_inicial, numero_kit_final, unidade_de_venda
            )
            
            # Validação de Conflito
            conflito = checar_conflito_venda(db, numero_inicial_atual, numero_final_atual, id_evento_int_para_controle)
        
            if conflito:
                v_ini = conflito.get('numero_inicial')
                v_fim = conflito.get('numero_final')
            
                print(f"[DEBUG] Validando: Pedido ({numero_inicial_atual}-{numero_final_atual}) vs Conflito ({v_ini}-{v_fim})")
                print(f"[DEBUG] Tipos: Pedido={type(numero_inicial_atual)}, Conflito={type(v_ini)}")

                # Lógica de Diferenciação
                if v_ini >= numero_inicial_atual and v_fim <= numero_final_atual:
                    if numero_inicial_atual == v_ini and numero_final_atual == v_fim:
                        msg_erro = "⛔ Venda Totalmente Bloqueada: Este período já foi vendido!"
                    else:
                        msg_erro = f"⚠️ Parte deste período já foi vendido! (Conflito detectado nas cartelas {v_ini} à {v_fim})"
                else:
                    msg_erro = f"⚠️ Parte deste período já foi vendido! (Conflito detectado nas cartelas {v_ini} à {v_fim})"
            
                error_redirect_kwargs['error'] = msg_erro
                return redirect(url_for('venda_lite.nova_venda_lite', **error_redirect_kwargs))

        elif padrao_venda == 'quantidade':
            quantidade = int(request.form.get('quantidade', 0))
            if quantidade <= 0: raise ValueError("Quantidade deve ser positiva.")
            
            quantidade_cartelas_atual = quantidade * unidade_de_venda
            
            numero_inicial_atual = get_next_bilhete_sequence(
                db, id_evento_int_para_controle, 'inicial_proxima_venda', 
                quantidade_cartelas_atual, limite_maximo_cartelas
            )
            if numero_inicial_atual is None:
                raise Exception("Falha de concorrência ao obter bilhete.")
            
            if numero_inicial_atual == 1:
                numero_inicial_atual = int(selected_event.get('numero_inicial', 1))
                db.controle_venda.update_one(
                    {'id_evento': id_evento_int_para_controle},
                    {'$set': {'inicial_proxima_venda': numero_inicial_atual + quantidade_cartelas_atual}}
                )
                
            numero_final_atual = numero_inicial_atual + quantidade_cartelas_atual - 1

        # GRAVAÇÃO
        valor_total_atual = valor_unitario * quantidade
        novo_id_venda_int = get_next_global_sequence(db, 'id_vendas_global')
        id_venda_formatado = f"VL{novo_id_venda_int:05d}" 

        registro_venda = {
            "id_venda": id_venda_formatado,
            "id_evento_ObjectId": selected_event['_id'], 
            "id_evento": id_evento_int_para_controle, 
            "descricao_evento": selected_event.get('descricao'),
            "id_regional": regional_operador,
            "id_cliente": 0, 
            "nome_cliente": nick_cliente_lite,
            "telefone_cliente": "",
            "id_colaborador": colaborador_id, 
            "nick_colaborador": nick_colaborador_sessao,  # 🛠️ CORREÇÃO: Grava o operador logado diretamente
            "id_vendedor": colaborador_id,
            "data_venda": hora_brasil(),
            "tipo_cartela": tipo_cartela,
            "quantidade_unidades": quantidade,
            "quantidade_cartelas": quantidade_cartelas_atual,
            "numero_inicial": numero_inicial_atual,
            "numero_final": numero_final_atual,
            "numero_inicial2": 0,
            "numero_final2": 0,
            "valor_unitario": Decimal128(str(valor_unitario)), 
            "valor_total": Decimal128(str(valor_total_atual)),
            "origem": "venda_lite"
        }

        db[nome_colecao_venda].insert_one(registro_venda)

        db.eventos.update_one(
            {"id_evento": id_evento_int_para_controle},
            {"$inc": {"valor_pendente_telemovel": float(valor_total_atual)}}
        )

        taxa_operador_bruta = parametros.get('perc_venda_direta', 15.0)
        taxa_operador = float(str(taxa_operador_bruta))
        registrar_comissao_vendedor(
            db=db, 
            id_colaborador=colaborador_id, 
            valor=valor_total_atual * (taxa_operador / 100),
            tipo='vd',
            id_evento=id_evento_int_para_controle,
            id_venda=id_venda_formatado,
            taxa_aplicada=taxa_operador,
            descricao=f"Comissão Venda Lite {id_venda_formatado}"
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_redirect_kwargs['error'] = f"Erro na gravação: {str(e)}"
        return redirect(url_for('venda_lite.nova_venda_lite', **error_redirect_kwargs))

    # Pós-Venda (Bluetooth e Cupom)
    host = request.host_url.rstrip('/')
    url_api_json = (f"{host}/api/venda_bluetooth_json?numero_inicial={numero_inicial_atual}"
                    f"&numero_final={numero_final_atual}&id_evento={id_evento_int_para_controle}"
                    f"&nome_cliente={nick_cliente_lite}")
    
    session['url_bluetooth_print'] = f"my.bluetoothprint.scheme://{url_api_json}"
    
    success_msg = (
        f"<strong>✅ VENDA LITE CONCLUÍDA</strong><br>"
        f"<strong>> {id_venda_formatado} <</strong><br>"
        f"Cliente: {nick_cliente_lite}<br>"
        f"Cartelas: {numero_inicial_atual} a {numero_final_atual}<br>"
        f"Valor: R$ {valor_total_atual:.2f}"
    )
    
    session['success_message'] = success_msg 
    session['print_data'] = {
        'id_evento': id_evento_int_para_controle,
        'nome_cliente': nick_cliente_lite,
        'numero_inicial': numero_inicial_atual,
        'numero_final': numero_final_atual,
        'tipo_cartela': int(selected_event.get('tipo_de_cartela', 25))
    }

    return redirect(url_for('venda_lite.nova_venda_lite', id_evento=id_evento_string))


# 4. Rota para Copiar Listagem de Vendas (Área de Transferência)
@venda_lite_bp.route('/api/copiar_listagem_vendas', methods=['GET'])
def api_copiar_listagem_vendas():
    from flask import session, request, jsonify
    if not session.get('logged_in'):
        return jsonify({"erro": "Acesso negado"}), 401

    from app import get_vendas_db
    db = get_vendas_db()
    
    id_evento_bruto = str(request.args.get('id_evento', '')).strip()
    
    if db is None or not id_evento_bruto:
        return jsonify({"erro": "Parâmetros inválidos"}), 400
        
    try:
        # =================================================================
        # TRADUTOR DE ID (ObjectId -> Número Inteiro)
        # Se o ID recebido tiver 24 caracteres (padrão MongoDB ObjectId)
        # =================================================================
        id_evento_final = id_evento_bruto
        if len(id_evento_bruto) == 24:
            from bson.objectid import ObjectId
            # Vai na tabela de eventos e descobre qual é o número real
            evento = db.eventos.find_one({"_id": ObjectId(id_evento_bruto)})
            if evento and 'id_evento' in evento:
                id_evento_final = str(evento['id_evento']) # Transforma o 159 em "159"
        
        # Agora sim, monta o nome certo! (ex: vendas159)
        nome_col = f"vendas{id_evento_final}"
        # =================================================================
            
        # Busca TUDO na coleção (ignorando se tem o campo "tipo" ou não)
        vendas = db[nome_col].find()
        
        linhas_para_ordenar = []
        for v in vendas:
            # Pula se for cupom (se existir o campo)
            if v.get('tipo') == 'cupom':
                continue
                
            try:
                n_ini = int(v.get('numero_inicial', 0))
                n_fim = int(v.get('numero_final', 0))
            except (ValueError, TypeError):
                n_ini = 0
                n_fim = 0
            
            # Só processa se tiver numeração válida
            if n_ini > 0:
                qtd_kits = v.get('quantidade_unidades', 1) 
                cliente = str(v.get('nome_cliente', 'N/A')).strip().upper()
                
                vendedor = str(v.get('nick_colaborador', '')).strip().upper()
                if not vendedor:
                    vendedor = f"COLAB {v.get('id_colaborador', '?')}"
                
                linha_texto = f"{n_ini} - {n_fim} ({qtd_kits}) {cliente}/{vendedor}"
                linhas_para_ordenar.append((n_ini, linha_texto))
        
        if not linhas_para_ordenar:
            print(f"[DEBUG] A coleção {nome_col} não retornou vendas com numeração válida.")
            return jsonify({"texto": ""})
            
        # Ordena a lista de forma crescente
        linhas_para_ordenar.sort(key=lambda x: x[0])
        
        # Extrai os textos na ordem correta
        textos_ordenados = [item[1] for item in linhas_para_ordenar]
        texto_final = "\n".join(textos_ordenados)
        
        return jsonify({"texto": texto_final})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"erro": "Erro interno do servidor"}), 500