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