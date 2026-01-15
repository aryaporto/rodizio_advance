Otimizador de Design Experimental

Solução customizada para a Avance Research que moderniza o fluxo de planejamento amostral. Reduz o tempo de criação de rodízios de horas para segundos, garantindo precisão matemática e integridade dos dados.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-App-red)
![OR-Tools](https://img.shields.io/badge/Google-OR--Tools-green)
![Status](https://img.shields.io/badge/Status-Production-success)

Contexto e Motivação

O projeto nasceu de uma iniciativa proativa para modernizar o fluxo de trabalho interno. Originalmente, a criação de rodízios dependia de softwares legados de estatística (KofN) executados via emuladores antigos (DOSBox).

Identifiquei que esse processo manual não apenas consumia tempo excessivo da equipe, mas também era uma barreira tecnológica. Decidi então pesquisar e desenvolver uma solução própria e automatizada, migrando de um ambiente DOS arcaico para uma aplicação Web moderna em Python, acessível a qualquer membro da equipe via navegador.

Sobre o Projeto

Este sistema web resolve um problema clássico de Pesquisa Operacional e Estatística: a alocação balanceada de produtos em testes de mercado (Design de Blocos Incompletos Balanceados - BIBD).

Diferente de sorteios aleatórios simples, este sistema utiliza um motor de **Programação por Restrições (Constraint Programming)** para garantir que:
1. O tamanho da amostra estatística seja respeitado.
2. O viés de posição (Order Bias) seja minimizado.
3. Produtos "Fixos" (Controle) e "Rotativos" convivam na mesma matriz sem quebrar o balanceamento.

Desafio Matemático

Em testes sensoriais, distribuir, por exemplo, 9 produtos rotativos + 1 fixo para 130 pessoas em 6 posições gera um problema de "cobertor curto" (divisão não exata).

A Solução:
Desenvolvi um algoritmo personalizado utilizando o solver CP-SAT do Google OR-Tools com uma função objetivo de Minimização de Penalidade Quadrática (Minimax).
Em vez de apenas buscar uma média simples, o algoritmo penaliza exponencialmente desvios individuais.
Resultado: O sistema "achata a curva" de distribuição, evitando que um produto apareça 12 vezes enquanto outros aparecem 9, garantindo homogeneidade quase perfeita (ex: todos ficam entre 9 e 10 aparições).

ech Stack

Frontend: [Streamlit](https://streamlit.io/) (Interface reativa e profissional).
Engine de Otimização: [Google OR-Tools](https://developers.google.com/optimization) (CP-SAT Solver).
Manipulação de Dados: Pandas & NumPy.
Exportação: Engine OpenPyXL para relatórios Excel com múltiplas abas.

Funcionalidades

Alocação Híbrida: Suporta múltiplos produtos de Controle (Fixos) misturados com Rotativos.
Auditoria em Tempo Real: Gera heatmaps e tabelas de frequência para validar o viés estatístico instantaneamente.
Alta Performance: Resolve matrizes de milhares de variáveis booleanas em <30 segundos.
UX Profissional: Interface limpa, upload de logo dinâmico e validação de erros de input.



Como Rodar Localmente

```bash
# Clone o repositório
git clone [https://github.com/seu-usuario/rodizio-pesquisa.git](https://github.com/seu-usuario/rodizio-pesquisa.git)

# Instale as dependências
pip install -r requirements.txt

# Execute a aplicação
streamlit run app.py
