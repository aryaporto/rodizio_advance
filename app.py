import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
import io
import re
import math
import random

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Sistema de Alocação de Amostras",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS PROFISSIONAL ---
st.markdown("""
<style>
    .block-container {padding-top: 1.5rem;}
    h1 {font-family: 'Segoe UI', sans-serif; font-size: 2.0rem; color: #2c3e50;}
    h3 {font-family: 'Segoe UI', sans-serif; font-size: 1.2rem; color: #34495e;}
    .stButton>button {
        background-color: #2980b9; color: white; border-radius: 5px; height: 3em; font-weight: 600;
    }
    .stButton>button:hover {background-color: #3498db;}
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    # ---------------------------------------------------------
    # ÁREA DA LOGO
    # ---------------------------------------------------------
    try:
        # Certifique-se de ter um arquivo chamado 'logo.png' na mesma pasta
        st.image("logo.png", use_container_width=True)
    except:
        pass
    # ---------------------------------------------------------
    
    st.markdown("---")
    
    st.header("Configuração do Estudo")
    nome_estudo = st.text_input("Nome do Projeto", value="Teste_Sensorial_2024")
    
    st.subheader("1. Definição da Amostra")
    num_respondentes = st.number_input("Nº de Respondentes (IDs)", min_value=10, value=128, step=1)
    
    st.subheader("2. Produtos")
    
    # Checkbox para múltiplos fixos
    tem_fixo = st.checkbox("Incluir produtos controle?", value=True)
    
    lista_fixos = []
    if tem_fixo:
        input_fixos = st.text_area("Produtos Fixos (Obrigatórios)", 
                                  value="M42",
                                  help="Produtos que aparecem para TODOS os respondentes. Separe por vírgula.",
                                  height=70)
        lista_fixos = [p.strip() for p in input_fixos.split(',') if p.strip()]
    
    input_rotativos = st.text_area("Produtos Rotativos", 
                                 value="P1, P2, P3, P4, P5, P6, P7, P8, P9",
                                 help="Produtos distribuídos via bloco incompleto balanceado.",
                                 height=100)
    lista_rotativos = [p.strip() for p in input_rotativos.split(',') if p.strip()]
    
    # Universo
    todos_produtos = lista_fixos + lista_rotativos
    total_itens = len(todos_produtos)
    qtd_fixos = len(lista_fixos)
    
    st.info(f"Total de SKUs: {total_itens}")
    
    st.subheader("3. Design do Bloco")
    min_slots = qtd_fixos + 1 if qtd_fixos > 0 else 1
    
    produtos_por_pessoa = st.slider("Produtos por pessoa (Slots)", 
                                   min_value=min_slots, 
                                   max_value=total_itens, 
                                   value=min(3, total_itens))
    
    if qtd_fixos >= produtos_por_pessoa:
        st.error(f"Erro: Nº de fixos ({qtd_fixos}) deve ser menor que slots ({produtos_por_pessoa}).")

    st.markdown("---")
    btn_processar = st.button("PROCESSAR ALOCAÇÃO OTIMIZADA", type="primary")

# --- MOTOR DE OTIMIZAÇÃO (HÍBRIDO: NIVELAMENTO + ENTROPIA) ---
def gerar_rodizio_avancado(n_resp, l_fixos, l_rotativos, n_slots):
    todos = l_fixos + l_rotativos
    n_prod = len(todos)
    n_fixos = len(l_fixos)
    n_rotativos = len(l_rotativos)
    
    model = cp_model.CpModel()
    
    # Variáveis
    x = {}
    for r in range(n_resp):
        for c in range(n_slots):
            for p in range(n_prod):
                x[(r, c, p)] = model.NewBoolVar(f'x_{r}_{c}_{p}')
    
    # --- HARD CONSTRAINTS ---
    # 1. Um produto por slot
    for r in range(n_resp):
        for c in range(n_slots):
            model.Add(sum(x[(r, c, p)] for p in range(n_prod)) == 1)
            
    # 2. Sem repetição na linha
    for r in range(n_resp):
        for p in range(n_prod):
            model.Add(sum(x[(r, c, p)] for c in range(n_slots)) <= 1)
            
    # 3. Fixos obrigatórios
    for idx in range(n_fixos):
        for r in range(n_resp):
            model.Add(sum(x[(r, c, idx)] for c in range(n_slots)) == 1)

    # --- SOFT CONSTRAINTS (PENALIDADES) ---
    penalidades = []
    
    # Metas Globais
    total_slots = n_resp * n_slots
    slots_rotativos_total = total_slots - (n_resp * n_fixos)
    
    if n_rotativos > 0:
        target_global = int(round(slots_rotativos_total / n_rotativos))
        for p in range(n_fixos, n_prod):
            soma = sum(x[(r, c, p)] for r in range(n_resp) for c in range(n_slots))
            dev = model.NewIntVar(0, n_resp, f'dev_glob_{p}')
            model.Add(soma - target_global <= dev)
            model.Add(target_global - soma <= dev)
            penalidades.append(dev)

    # Metas por Coluna (Evitar o 12)
    avg_col_fixo = n_resp / n_slots
    target_fixo = int(round(avg_col_fixo))
    
    avg_col_rot = (slots_rotativos_total / n_rotativos) / n_slots if n_rotativos > 0 else 0
    target_rot = int(round(avg_col_rot))
    
    max_desvio_coluna = model.NewIntVar(0, n_resp, 'max_dev_col')

    for c in range(n_slots):
        for p in range(n_prod):
            soma_col = sum(x[(r, c, p)] for r in range(n_resp))
            
            t = target_fixo if p < n_fixos else target_rot
            
            diff = model.NewIntVar(0, n_resp, f'diff_{c}_{p}')
            model.Add(soma_col - t <= diff)
            model.Add(t - soma_col <= diff)
            model.Add(diff <= max_desvio_coluna)
            penalidades.append(diff)

    # --- FATOR DE CAOS (ALEATORIEDADE) ---
    # Introduz entropia para evitar padrões repetitivos (robóticos)
    random_score = []
    for r in range(n_resp):
        for c in range(n_slots):
            for p in range(n_prod):
                peso_random = random.randint(1, 100) 
                random_score.append(x[(r, c, p)] * peso_random)

    # FUNÇÃO OBJETIVO HÍBRIDA
    # Prioridade 1 (Alta): Minimizar Erro Máximo (max_desvio_coluna)
    # Prioridade 2 (Média): Minimizar Erro Global (sum penalidades)
    # Prioridade 3 (Baixa): Maximizar Aleatoriedade (subtrair random_score)
    
    model.Minimize(
        (sum(penalidades) * 1000) +       
        (max_desvio_coluna * 10000) -     
        sum(random_score)                 
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 45.0
    status = solver.Solve(model)
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        dados = []
        colunas = ['ID'] + [f'Posicao_{k+1}' for k in range(n_slots)]
        for r in range(n_resp):
            linha = [r + 1]
            for c in range(n_slots):
                for p_idx, p_val in enumerate(todos):
                    if solver.Value(x[(r, c, p_idx)]) == 1:
                        linha.append(p_val)
            dados.append(linha)
        return pd.DataFrame(dados, columns=colunas), "Sucesso"
    else:
        return None, "Inviável"

# --- INTERFACE ---

st.title("Sistema de Planejamento Amostral")

if btn_processar:
    if qtd_fixos >= produtos_por_pessoa:
        st.error("Configuração Inválida: Produtos fixos ocupam todos os slots.")
    else:
        with st.spinner('Otimizando distribuição (Nivelamento com Entropia)...'):
            df_resultado, status = gerar_rodizio_avancado(
                num_respondentes, lista_fixos, lista_rotativos, produtos_por_pessoa
            )
            
        if df_resultado is not None:
            st.session_state['data_matrix_v3'] = df_resultado
            st.session_state['meta_projeto'] = nome_estudo
            st.success("Matriz gerada! Otimização híbrida aplicada.")
        else:
            st.error(f"Não foi possível gerar a matriz: {status}")

# VISUALIZAÇÃO
if 'data_matrix_v3' in st.session_state:
    df = st.session_state['data_matrix_v3']
    
    check_cols = {}
    for col in df.columns[1:]:
        check_cols[col] = df[col].value_counts()
    check_df = pd.DataFrame(check_cols).fillna(0).astype(int).sort_index()
    
    tab1, tab2, tab3 = st.tabs(["Matriz", "Auditoria", "Exportação"])
    
    with tab1:
        st.dataframe(df, use_container_width=True)
        
    with tab2:
        st.markdown("#### Frequência por Posição")
        st.caption("Verifique se os produtos rotativos estão nivelados (Ex: entre 9 e 10).")
        st.dataframe(check_df, use_container_width=True)
        
        # Gráficos
        st.markdown("---")
        pos = st.selectbox("Visualizar Posição:", df.columns[1:])
        st.bar_chart(df[pos].value_counts())

    with tab3:
        buffer = io.BytesIO()
        nome_arq = f"{re.sub(r'[^a-zA-Z0-9]', '_', st.session_state['meta_projeto'])}_Final.xlsx"
        
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Matriz', index=False)
            check_df.to_excel(writer, sheet_name='Auditoria', index=False)
            # Aba Meta removida
            
        st.download_button("Baixar Planilha (.xlsx)", buffer.getvalue(), nome_arq, type="primary")
