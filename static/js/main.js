// static/js/main.js

// Variável global que armazenará o valor unitário do evento, definida no HTML.
let Venda_ValorUnitario = 0; 
let campoQuantidade;
let elementoCustoTotal;

/**
 * Função para alternar a visibilidade da senha no campo de input.
 */
function togglePasswordVisibility() {
    const passwordInput = document.getElementById('senha');
    const toggleButton = document.getElementById('toggleSenha');

    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        toggleButton.textContent = '🙈 Ocultar';
    } else {
        passwordInput.type = 'password';
        toggleButton.textContent = '👁️ Visualizar';
    }
}

/**
 * Calcula e exibe o custo total da venda em tempo real.
 */
function updateTotalCost() {
    if (campoQuantidade && elementoCustoTotal) {
        const quantidade = parseInt(campoQuantidade.value) || 0;
        const total = quantidade * Venda_ValorUnitario;
        
        // Formata o valor para moeda BRL
        const totalFormatado = total.toLocaleString('pt-BR', { 
            style: 'currency', 
            currency: 'BRL' 
        });
        
        elementoCustoTotal.textContent = `Custo Total: ${totalFormatado}`;

        // Oculta/Mostra o botão de confirmação se a quantidade for > 0
        const confirmarButton = document.querySelector('button[value="confirmar_venda"]');
        if (confirmarButton) {
            confirmarButton.style.display = quantidade > 0 ? 'block' : 'none';
        }
    }
}

/**
 * Inicialização de listeners quando o DOM estiver completamente carregado.
 */
document.addEventListener('DOMContentLoaded', () => {
    // 1. Inicialização da Tela de Login
    const toggleButton = document.getElementById('toggleSenha');
    if (toggleButton) {
        toggleButton.addEventListener('click', togglePasswordVisibility);
    }
    
    // 2. Inicialização da Tela de Venda (Nova Venda)
    campoQuantidade = document.getElementById('quantidade');
    elementoCustoTotal = document.getElementById('total-custo');
    const eventoSelect = document.getElementById('id_evento');

    if (campoQuantidade && elementoCustoTotal && eventoSelect) {
        
        // Tenta obter o valor unitário de uma variável global definida pelo Jinja no HTML
        if (typeof Venda_ValorUnitario !== 'number' || Venda_ValorUnitario === 0) {
             // Se o valor global não foi setado, tenta usar o atributo data-valor do evento selecionado.
             const selectedOption = eventoSelect.options[eventoSelect.selectedIndex];
             if (selectedOption && selectedOption.dataset.valor) {
                 Venda_ValorUnitario = parseFloat(selectedOption.dataset.valor);
             }
        }
        
        // Adiciona listener para recalcular o custo ao digitar a quantidade
        campoQuantidade.addEventListener('input', updateTotalCost);

        // Dispara o cálculo inicial
        updateTotalCost();

        // 🚨 Futura Implementação (AJAX para Busca de Cliente sem recarregar)
        // Você poderia usar fetch/XMLHttpRequest aqui para chamar a rota /api/buscar_cliente 
        // e atualizar a caixa de cliente_encontrado no HTML.
    }
});


// Confirmação personalizada com cores fixas e botões grandes
function bingoConfirm(msg, callback) {
    let confirmBox = document.createElement('div');
    confirmBox.className = 'modal-overlay'; 
    confirmBox.style.cssText = "display: flex; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 5000; justify-content: center; align-items: center;";
    
    confirmBox.innerHTML = `
        <div style="background: #ffffff; color: #333333; width: 450px; padding: 20px; border-radius: 15px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
            <h3 style="margin-top: 0; color: #2c3e50; font-size: 24px; border-bottom: 2px solid #27ae60; padding-bottom: 5px;">Confirmação</h3>
            <p style="margin: 25px 0; font-size: 19px; line-height: 1.4; font-weight: 500;">${msg}</p>
            <div style="display: flex; gap: 20px; justify-content: center;">
                <button id="confirm-sim" style="background: #27ae60; color: white; padding: 20px 40px; font-size: 20px; min-width: 160px; cursor: pointer; border-radius: 10px; border: none; font-weight: bold; transition: 0.2s; outline: none; box-shadow: 0 0 0 4px rgba(39, 174, 96, 0.4);">SIM</button>
                <button id="confirm-nao" style="background: #e74c3c; color: white; padding: 20px 40px; font-size: 20px; min-width: 160px; cursor: pointer; border-radius: 10px; border: none; font-weight: bold; transition: 0.2s;">NÃO</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(confirmBox);

    const btnSim = document.getElementById('confirm-sim');
    const btnNao = document.getElementById('confirm-nao');

    btnSim.onclick = () => { confirmBox.remove(); callback(); };
    btnNao.onclick = () => { confirmBox.remove(); };

    // 🚀 DIRECIONA O FOCO PARA O BOTÃO SIM
    // O setTimeout com 10ms garante que o navegador já desenhou o botão na tela antes de focar
    setTimeout(() => {
        btnSim.focus();
    }, 10);
    
    // (Bônus) Permite fechar o modal com a tecla ESC
    confirmBox.tabIndex = -1;
    confirmBox.onkeydown = (e) => {
        if (e.key === 'Escape') {
            confirmBox.remove();
        }
    };
}

// Alerta personalizado com cores fixas
function bingoAlert(msg, tempo = 3000, cor = '#27ae60') {
    let alertBox = document.getElementById('bingo-alert-container');
    if (!alertBox) {
        alertBox = document.createElement('div');
        alertBox.id = 'bingo-alert-container';
        alertBox.className = 'bingo-modal-alert';
        // Forçando fundo branco e texto escuro no alerta também
        alertBox.style.cssText = "display: none; position: fixed; top: 20px; right: 20px; background: #ffffff; color: #333333; border-radius: 8px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); z-index: 6000; padding: 20px; width: 300px; border-left: 8px solid " + cor + ";";
        alertBox.innerHTML = '<div id="alert-msg" style="font-weight: bold; font-size: 16px;"></div><div id="alert-timer" class="timer-bar"></div>';
        document.body.appendChild(alertBox);
    }

    const timerBar = alertBox.querySelector('#alert-timer');
    alertBox.querySelector('#alert-msg').innerText = msg;
    alertBox.style.borderLeftColor = cor;
    timerBar.style.backgroundColor = cor;
    alertBox.style.display = 'block';
    
    timerBar.style.width = '0%';
    setTimeout(() => { 
        timerBar.style.transition = `width ${tempo}ms linear`; 
        timerBar.style.width = '100%'; 
    }, 50);
    
    setTimeout(() => { alertBox.style.display = 'none'; timerBar.style.transition = 'none'; }, tempo + 100);
}


// Variável global que guardará a impressora que passou na validação
let impressoraAtiva = null;

function verificarImpressoraAoCarregar() {
    // Se não houver o objeto AndroidTerminal, significa que estamos testando no PC
    if (!window.AndroidTerminal) {
        console.log("Sistema carregado no PC. Modo de impressão via USB/Janela ativo.");
        return;
    }

    try {
        // Solicita a lista de dispositivos para a ponte Kotlin
        const resposta = window.AndroidTerminal.obterDispositivosBluetooth();

        // Cenário A: Bluetooth desligado no celular
        if (resposta === "DESLIGADO") {
            bingoAlert("⚠️ O Bluetooth está desligado!<br>Não haverá impressão de comprovantes.", 4000, '#e74c3c');
            return;
        }

        const aparelhosPareados = JSON.parse(resposta);

        // Cenário B: Bluetooth ligado, mas nenhum dispositivo pareado
        if (!aparelhosPareados || aparelhosPareados.length === 0) {
            bingoAlert("⚠️ Nenhuma impressora Bluetooth pareada.<br>Impressão desativada.", 4000, '#e74c3c');
            return;
        }

        // 👉 A MÁGICA ENTRA AQUI: Verifica se já tem uma impressora salva no navegador
        const impressoraSalva = localStorage.getItem("impressora_padrao_salva");

        // Se já escolhemos uma antes e ela continua pareada no celular, conecta em silêncio!
        if (impressoraSalva && aparelhosPareados.includes(impressoraSalva)) {
            impressoraAtiva = impressoraSalva;
            console.log(`🖨️ Impressora reconectada silenciosamente: ${impressoraAtiva}`);
            return; // Encerra a função aqui, sem janelas na tela!
        }

        // Cenário C: Primeira vez rodando (ou impressora antiga sumiu). Vamos procurar a padrão.
        const impressoraPadrao = "MTP-II_5E06";
        const encontrouPadrao = aparelhosPareados.includes(impressoraPadrao);

        if (encontrouPadrao) {
            bingoConfirm(`Impressora padrão detectada:<br>👉 <b>${impressoraPadrao}</b><br><br>Deseja ativar esta impressora?`, () => {
                impressoraAtiva = impressoraPadrao;
                localStorage.setItem("impressora_padrao_salva", impressoraAtiva); // Salva no caderninho!
                bingoAlert("Impressora ativada e salva com sucesso!", 3000, '#27ae60');
            });
            
        } else {
            // Se a padrão não estiver na lista, oferece a primeira disponível
            const alternativa = aparelhosPareados[0]; 
            
            bingoConfirm(`Impressora padrão não encontrada.<br>Detectamos: <b>${alternativa}</b>.<br>Deseja tentar imprimir nela?`, () => {
                impressoraAtiva = alternativa;
                localStorage.setItem("impressora_padrao_salva", impressoraAtiva); // Salva no caderninho!
                bingoAlert("Impressora alternativa ativada e salva!", 3000, '#27ae60');
            });
        }

    } catch (erro) {
        console.error("Erro na inicialização do módulo de impressão:", erro);
        bingoAlert("Erro ao iniciar módulo de impressão.", 3000, '#e74c3c');
    }
}


// Variável global para segurar a conexão e não pedir permissão toda hora
let impressoraWebBluetooth = null;

async function imprimirViaWebBluetooth(conteudo) {
    try {
        // 1. Pede permissão e conecta (só na primeira vez)
        if (!impressoraWebBluetooth) {
            console.log("Buscando impressoras BLE...");
            const device = await navigator.bluetooth.requestDevice({
                filters: [{ services: ['000018f0-0000-1000-8000-00805f9b34fb'] }], // UUID genérico comum de impressoras
                optionalServices: ['e7810a71-73ae-499d-8c15-faa9aef0c3f2'] // UUID característico de escrita
            });

            console.log("Conectando ao GATT Server...");
            const server = await device.gatt.connect();
            
            // Aqui você buscaria o serviço e a característica exata da sua impressora
            // impressoraWebBluetooth = await server.getPrimaryService(...).then(s => s.getCharacteristic(...));
        }

        // 2. Converte o JSON ou Texto em Array de Bytes (ESC/POS)
        let bytesParaImprimir = converterParaEscPos(conteudo); // Você precisará desta função de parser

        // 3. Envia os bytes divididos em pacotes (MTU do BLE geralmente é pequeno, ~512 bytes)
        // await impressoraWebBluetooth.writeValue(bytesParaImprimir);
        console.log("Impressão Web Bluetooth enviada com sucesso!");

    } catch (error) {
        console.error("Falha na impressão Web Bluetooth:", error);
    }
}


// ==========================================
// UTILITÁRIOS DE MOEDA
// ==========================================

// 1. Transforma "R$ 2.174,01" (ou "2.174,01") em número real (2174.01) para o sistema calcular
function parseMoedaBRL(valor) {
    if (!valor) return 0.0;
    if (typeof valor === 'number') return valor;
    
    // Remove o R$, espaços em branco e os pontos de milhar, depois troca a vírgula por ponto decimal
    let limpo = String(valor).replace(/R\$/g, '').replace(/\s/g, '').replace(/\./g, '').replace(',', '.');
    let numero = parseFloat(limpo);
    
    return isNaN(numero) ? 0.0 : numero;
}

// 2. Transforma número (2174.01) de volta para o formato visual "2.174,01"
function formatarMoedaBRL(valor) {
    let numero = parseFloat(valor);
    if (isNaN(numero)) numero = 0.0;
    
    // Formata no padrão brasileiro com 2 casas decimais obrigatoriamente
    return numero.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Força o navegador a rodar a checagem automaticamente assim que a estrutura da página estiver pronta
window.addEventListener('DOMContentLoaded', verificarImpressoraAoCarregar);

function imprimirComprovanteUniversal(conteudoRecibo) {
    console.log("--- [IMPRESSAO] Iniciando processo ---");
    
    // Verifica se o conteúdo é o nosso novo pacote JSON estruturado
    const isJson = (typeof conteudoRecibo === 'string' && conteudoRecibo.trim().startsWith('{'));
    console.log("Tipo de conteúdo detectado:", isJson ? "JSON (Estruturado)" : "Texto Puro");

    if (window.AndroidTerminal) {
        console.log("Modo: Android (Bluetooth)");
        
        if (!impressoraAtiva) {
            console.warn("Impressora não definida, tentando recuperar...");
            bingoAlert("Procurando impressora conectada...", 3000, '#f39c12');
            verificarImpressoraAoCarregar();
            
            if (!impressoraAtiva) {
                console.error("Erro: Nenhuma impressora ativa encontrada.");
                return; 
            }
        }
        
        console.log("Enviando para a ponte Android. Impressora:", impressoraAtiva);
        if (isJson) {
            window.AndroidTerminal.imprimirReciboJson(conteudoRecibo, impressoraAtiva);
        } else {
            window.AndroidTerminal.imprimirRecibo(conteudoRecibo, impressoraAtiva);
        }
    } else if (/Android/i.test(navigator.userAgent)) {
        console.log("Modo: Android Web (RawBT)");
        
        let textoParaRawBT = conteudoRecibo;

        // Comandos Universais ESC/POS
        const BOLD_ON = "\x1B\x45\x01";
        const BOLD_OFF = "\x1B\x45\x00";
        const SIZE_NORMAL = "\x1D\x21\x00";
        const SIZE_DUPLA_ALTURA = "\x1D\x21\x01";
        const SIZE_DUPLA_LARGURA = "\x1D\x21\x10"; // Comando para esticar na horizontal

        if (isJson) {
            try {
                const pacote = JSON.parse(conteudoRecibo);
                textoParaRawBT = "";
                
                const LARGURA_LINHA = 32; 

                pacote.linhas.forEach(linha => {
                    let txt = linha.texto.trim();
                    
                    // Condições para detetar o conteúdo da linha
                    const isNumerosCartela = (linha.tipo === 'cartela' || txt.match(/^\d+ \d+ \d+ \d+ \d+$/));
                    const isTituloCartela = txt.includes("Ctla."); 
                    
                    if (isTituloCartela) {
                        // 1. TÍTULO DA CARTELA ("Ctla. xxxxx")
                        // Largura Dupla ocupa 2 espaços por caractere. Calculamos o centro baseado nisso.
                        let espacosEsquerda = Math.max(0, Math.floor((LARGURA_LINHA - (txt.length * 2)) / 2));
                        let paddingCenter = " ".repeat(espacosEsquerda);
                        
                        textoParaRawBT += paddingCenter + SIZE_DUPLA_LARGURA + BOLD_ON + txt + BOLD_OFF + SIZE_NORMAL + "\n";
                    } 
                    else if (isNumerosCartela) {
                        // 2. MATRIZ DE DEZENAS (Espaçamento Total)
                        let numerosArray = txt.split(/\s+/); // Separa as dezenas originais
                        
                        // Transforma "02" em "0 2"
                        let dezenasSeparadas = numerosArray.map(num => num.split("").join(" "));
                        
                        // Junta tudo com 3 espaços entre as dezenas
                        let cartelaEspacada = dezenasSeparadas.join("   "); 
                        
                        // O cartelaEspacada terá 31 caracteres. Calcula o centro (quase 0, pois já ocupa tudo)
                        let espacosEsquerda = Math.max(0, Math.floor((LARGURA_LINHA - cartelaEspacada.length) / 2));
                        let paddingCenter = " ".repeat(espacosEsquerda);
                        
                        textoParaRawBT += paddingCenter + SIZE_DUPLA_ALTURA + BOLD_ON + cartelaEspacada + BOLD_OFF + SIZE_NORMAL + "\n";
                    } 
                    else {
                        // 3. TEXTO NORMAL (Cabeçalho/Rodapé)
                        // Ignoramos linhas vazias enviadas pelo JSON para garantir que não sobram buracos
                        if (txt === "") return; 

                        if (linha.alinhamento === 'centro') {
                            let espacos = Math.max(0, Math.floor((LARGURA_LINHA - txt.length) / 2));
                            txt = " ".repeat(espacos) + txt;
                        }
                        
                        if (linha.negrito) {
                            txt = BOLD_ON + txt + BOLD_OFF;
                        }
                        
                        textoParaRawBT += txt + "\n";
                    }
                });
                
                // Removido o avanço de linhas no final (\n\n\n)
            } catch(e) {
                console.error("Erro ao converter JSON para RawBT:", e);
                textoParaRawBT = conteudoRecibo; 
            }
        }

        try {
            const base64Data = btoa(unescape(encodeURIComponent(textoParaRawBT)));
            const intentUrl = "intent:base64," + base64Data + "#Intent;scheme=rawbt;package=ru.a402d.rawbtprinter;end;";
            window.location.href = intentUrl;
        } catch (err) {
            console.error("Falha ao gerar o link do RawBT:", err);
            alert("Erro ao tentar abrir o RawBT.");
        }
        
    } else {
        console.log("Modo: PC (USB)");
        
        // Modo PC (Chrome Kiosk) - Estrutura original com window.open
        let htmlParaImprimir = conteudoRecibo;

        if (isJson) {
            try {
                const pacote = JSON.parse(conteudoRecibo);
                htmlParaImprimir = "";
                pacote.linhas.forEach(linha => {
                    let estilo = "";
                    if (linha.alinhamento === 'centro') estilo += "text-align: center; ";
                    if (linha.alinhamento === 'direita') estilo += "text-align: right; ";
                    if (linha.negrito) estilo += "font-weight: 900; ";
                    if (linha.tamanho === 'duplo') estilo += "font-size: 1.2em; ";
                    
                    htmlParaImprimir += `<div style="${estilo}">${linha.texto}</div>`;
                });
            } catch(e) {
                console.error("Erro ao renderizar JSON no PC:", e);
            }
        }

        const printWindow = window.open('', '_blank', 'width=300,height=500,left=-1000,top=-1000');
        printWindow.document.write(`
            <html>
            <head>
                <style>
                    @page { margin: 0; }
                    body { 
                        font-family: 'Courier New', Courier, monospace; 
                        font-size: 14px; 
                        margin: 5mm; 
                        white-space: pre-wrap; 
                        color: black;
                        font-weight: bold;
                    }
                </style>
            </head>
            <body>${htmlParaImprimir}</body>
            </html>
        `);
        printWindow.document.close();
        printWindow.focus();
        
        setTimeout(() => {
            // O Kiosk vai piscar a tela, enviar para a fila e o onafterprint fecha a janela limpa
            printWindow.onafterprint = function() {
                printWindow.close();
            };
            
            printWindow.print();
        }, 250);
    }
}

// 🧮 Motor Matemático do Combo (Frontend)
function calcularRodadasCombo(numeroInicial, qtdCartelasCompradas, unidadeVenda, comboQtde) {
    const rodadas = [];
    // Calcula qual foi o Kit primário comprado
    const kitBase = Math.floor((numeroInicial - 1) / unidadeVenda) + 1;

    for (let r = 1; r <= comboQtde; r++) {
        let kitAtual = kitBase + (r - 1);
        let iniAtual = ((kitAtual - 1) * unidadeVenda) + 1;
        let fimAtual = iniAtual + qtdCartelasCompradas - 1;

        rodadas.push({
            rodada: r,
            kit: kitAtual,
            inicial: iniAtual,
            final: fimAtual
        });
    }
    return rodadas;
}

// ==========================================
// FUNÇÕES GLOBAIS DE INTEGRAÇÃO COM WHATSAPP
// ==========================================

function abrirWhatsApp(textoParaEnviar, telefoneCliente) {
    // Garante que não ocorra erro caso a variável global 'tempTelefone' não exista na página atual
    var rawTelefone = telefoneCliente || (typeof tempTelefone !== 'undefined' ? tempTelefone : ""); 
    var telefone = rawTelefone.replace(/\D/g, '');
  
    // Lógica do 55 (Brasil)
    if (telefone && telefone.length > 0) {
         if (telefone.length <= 9) {
            telefone = "11" + telefone;
        }
         if (telefone.length <= 11) {
            telefone = "55" + telefone;
        }
    } else {
        telefone = "";
    }

    var mensagem = textoParaEnviar || "";
    var mensagemCodificada = encodeURIComponent(mensagem);

    var url = "https://wa.me/" + telefone + "?text=" + mensagemCodificada;

    window.open(url, '_blank');
}

function abrirWhatsAppComPDF(urlDoPDF, telefoneCliente) {
    // Garante que não ocorra erro caso a variável global 'tempTelefone' não exista na página atual
    var rawTelefone = telefoneCliente || (typeof tempTelefone !== 'undefined' ? tempTelefone : ""); 
    var telefone = rawTelefone.replace(/\D/g, '');
  
    // Lógica do 55 (Brasil)
    if (telefone && telefone.length > 0) {
         if (telefone.length <= 9) {
            telefone = "11" + telefone;
        }
         if (telefone.length <= 11) {
            telefone = "55" + telefone;
        }
    } else {
        alert("Nenhum número de WhatsApp válido foi fornecido.");
        return;
    }

    // Monta a mensagem com quebras de linha e emojis
    var mensagem = "Olá! 🎟️ Aqui estão as suas cartelas.\n\n" +
                   "👇 Clique no link abaixo para visualizar ou baixar o seu PDF:\n" + 
                   urlDoPDF + "\n\n" +
                   "Boa sorte!";
                   
    var mensagemCodificada = encodeURIComponent(mensagem);

    // Gera o link da API do WhatsApp
    var url = "https://wa.me/" + telefone + "?text=" + mensagemCodificada;

    // Abre numa nova aba
    window.open(url, '_blank');
}