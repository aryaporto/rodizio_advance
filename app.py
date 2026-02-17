import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
import io
import re
import random

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Sistema de Alocação de Amostras",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS ---
st.markdown("""
<style>
    .block-container {padding-top: 1.5rem;}
    h1 {font-family: 'Segoe UI', sans-serif; font-size: 2.0rem; color: #2c3e50;}
    .stButton>button {
        background-color: #2980b9; color: white; border-radius: 5px; height: 3em; font-weight: 600; width: 100%;
    }
    .stButton>button:hover {background-color: #3498db;}
</style>
""", unsafe_allow_html=True)

# --- CLASSE DO OTIMIZADOR ---
class OtimizadorAlocacao:
    def __init__(self, fixos, rotativos, slots, df_demografico=None, cols_cota=None):
        self.fixos = fixos
        self.rotativos = rotativos
        self.todos_produtos = fixos + rotativos
        self.n_slots = slots
        self.df_demografico = df_demografico
        self.cols_cota = cols_cota if cols_cota else [] # Lista de colunas selecionadas pelo usuário
        
        if df_demografico is not None:
            self.n_respondentes = len(df_demografico)
        else:
            self.n_respondentes = 0 
            
    def resolver(self, num_resp_manual=None):
        n_resp = self.n_respondentes if self.df_demografico is not None else num_resp_manual
        n_prod = len(self.todos_produtos)
        n_fixos = len(self.fixos)
        
        # Embaralha produtos para evitar vício de ordem alfabética
        indices_produtos = list(range(n_prod))
        random.shuffle(indices_produtos)
        
        model = cp_model.CpModel()
        
        # Variáveis: x[respondente, slot, produto]
        x = {}
        for r in range(n_resp):
            for c in range(self.n_slots):
                for p in range(n_prod):
                    x[(r, c, p)] = model.NewBoolVar(f'x_{r}_{c}_{p}')
        
        # --- REGRAS RÍGIDAS (HARD CONSTRAINTS) ---
        
        # 1. Um produto por slot
        for r in range(n_resp):
            for c in range(self.n_slots):
                model.Add(sum(x[(r, c, p)] for p in range(n_prod)) == 1)
        
        # 2. Não repetir produto para a mesma pessoa
        for r in range(n_resp):
            for p in range(n_prod):
                model.Add(sum(x[(r, c, p)] for c in range(self.n_slots)) <= 1)
        
        # 3. Produtos Fixos Obrigatórios
        ids_fixos = [i for i, prod in enumerate(self.todos_produtos) if prod in self.fixos]
        for p_idx in ids_fixos:
            for r in range(n_resp):
                model.Add(sum(x[(r, c, p_idx)] for c in range(self.n_slots)) == 1)

        # --- REGRAS DE EQUILÍBRIO (SOFT CONSTRAINTS) ---
        penalidades = []
        
        # A. Equilíbrio Global (Todo mundo vê tudo igual no total)
        total_slots = n_resp * self.n_slots
        slots_rotativos = total_slots - (n_resp * n_fixos)
        n_rotativos = len(self.rotativos)
        target_rotativo_global = int(slots_rotativos / n_rotativos / self.n_slots) if n_rotativos > 0 else 0
        
        # Variável para controlar o pior desvio (Minimax)
        max_desvio = model.NewIntVar(0, n_resp, 'max_dev')

        for p in range(n_prod):
            is_fixo = self.todos_produtos[p] in self.fixos
            if not is_fixo:
                # Conta quantas vezes o produto aparece na posição X (para não viciar posição)
                for c in range(self.n_slots):
                    soma_posicao = sum(x[(r, c, p)] for r in range(n_resp))
                    diff = model.NewIntVar(0, n_resp, f'diff_global_{c}_{p}')
                    model.Add(soma_posicao - target_rotativo_global <= diff)
                    model.Add(target_rotativo_global - soma_posicao <= diff)
                    model.Add(diff <= max_desvio)
                    penalidades.append(diff)

        # B. Equilíbrio por Cotas
        if self.df_demografico is not None and len(self.cols_cota) > 0:
            
            # Agrupa as linhas do Excel que têm o mesmo perfil nas colunas selecionadas
            try:
                grupos = self.df_demografico.groupby(self.cols_cota).groups
            except KeyError:
                grupos = {} # Fallback se der erro na coluna

            for nome_grupo, indices in grupos.items():
                n_pessoas_grupo = len(indices)
                if n_pessoas_grupo < 2: continue # Ignora grupos muito pequenos

                target_grupo = int((n_pessoas_grupo * (self.n_slots - n_fixos)) / n_rotativos) if n_rotativos > 0 else 0
                
                for p in range(n_prod):
                    if self.todos_produtos[p] in self.rotativos:
                        # Soma aparições APENAS nas linhas desse grupo
                        soma_grupo = sum(sum(x[(r, c, p)] for c in range(self.n_slots)) for r in indices)
                        
                        dev_grupo = model.NewIntVar(0, n_pessoas_grupo, f'dev_g_{p}')
                        model.Add(soma_grupo - target_grupo <= dev_grupo)
                        model.Add(target_grupo - soma_grupo <= dev_grupo)
                        
                        # Multiplicamos por 10 para dar prioridade ao equilíbrio da Cota sobre o Global
                        penalidades.append(dev_grupo * 10)

        # --- OBJETIVO FINAL ---
        # Minimizar erros + Fator de Caos (Entropia) para garantir aleatoriedade
        random_score = []
        for r in range(n_resp):
            for c in range(self.n_slots):
                for p in range(n_prod):
                    w = random.randint(1, 50) # Peso aleatório
                    random_score.append(x[(r, c, p)] * w)
        
        model.Minimize(sum(penalidades) * 100 - sum(random_score))
        
        # Solver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0
        # Seed aleatória para garantir que cada clique gere um rodízio diferente
        solver.parameters.random_seed = random.randint(0, 100000) 
        
        status = solver.Solve(model)
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            dados_saida = []
            base_dados = self.df_demografico.to_dict('records') if self.df_demografico is not None else [{'ID': i+1} for i in range(n_resp)]
            
            for r in range(n_resp):
                linha = base_dados[r].copy()
                pos_counter = 1
                for c in range(self.n_slots):
                    for p in range(n_prod):
                        if solver.Value(x[(r, c, p)]) == 1:
                            linha[f'Posicao_{pos_counter}'] = self.todos_produtos[p]
                            pos_counter += 1
                dados_saida.append(linha)
            return pd.DataFrame(dados_saida), "Sucesso"
        else:
            return None, "Inviável (Verifique nº de slots vs produtos fixos)"

# --- INTERFACE ---
with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        st.write("## 🧪 Allocator Pro")
    
    st.markdown("---")
    st.header("1. Configuração")
    nome_estudo = st.text_input("Nome do Estudo", value="Estudo_Jan26")
    
    st.subheader("Amostra")
    tipo_input = st.radio("Fonte de Dados:", ["Gerar IDs Numéricos", "Upload de Arquivo (Cotas)"])
    
    df_upload = None
    cols_selecionadas = []
    num_respondentes = 120
    
    if tipo_input == "Upload de Arquivo (Cotas)":
        arquivo = st.file_uploader("Suba Excel/CSV", type=['xlsx', 'csv'])
        if arquivo:
            try:
                if arquivo.name.endswith('.csv'):
                    df_upload = pd.read_csv(arquivo)
                else:
                    df_upload = pd.read_excel(arquivo)
                st.success(f"✅ {len(df_upload)} linhas carregadas.")
                
                # --- AQUI ESTÁ A CORREÇÃO: SELEÇÃO MANUAL DE COTAS ---
                st.markdown("**Balanceamento (Cotas):**")
                cols_possiveis = [c for c in df_upload.columns if c.lower() not in ['id', 'nome']]
                cols_selecionadas = st.multiselect(
                    "Selecione as colunas para equilibrar:",
                    options=cols_possiveis,
                    help="O sistema tentará distribuir os produtos igualmente dentro desses grupos."
                )
                if cols_selecionadas:
                    st.caption(f"Otimizando por: {', '.join(cols_selecionadas)}")
                else:
                    st.caption("⚠️ Nenhuma cota selecionada (Rodízio Aleatório Global).")
                # -----------------------------------------------------

            except Exception as e:
                st.error(f"Erro: {e}")
    else:
        num_respondentes = st.number_input("Nº de IDs a gerar", min_value=12, value=120, step=6)
        
    st.markdown("---")
    st.subheader("2. Produtos")
    
    c1, c2 = st.columns(2)
    with c1:
        fixos_str = st.text_area("Fixos", height=100, placeholder="Ex: A")
    with c2:
        rot_str = st.text_area("Rotativos", value="P1, P2, P3", height=100)
        
    lista_fixos = [x.strip() for x in fixos_str.split(',') if x.strip()]
    lista_rotativos = [x.strip() for x in rot_str.split(',') if x.strip()]
    
    total_itens = len(lista_fixos) + len(lista_rotativos)
    
    st.subheader("3. Slots")
    min_s = len(lista_fixos) + 1 if len(lista_rotativos) > 0 else len(lista_fixos)
    n_slots = st.slider("Produtos por pessoa", min_value=min_s, max_value=max(total_itens, 1), value=min(3, total_itens))
    
    st.markdown("---")
    btn_processar = st.button("GERAR MATRIZ", type="primary")

# --- LÓGICA PRINCIPAL ---
st.title("Sistema de Alocação Balanceada")

if btn_processar:
    if len(lista_rotativos) == 0 and len(lista_fixos) == 0:
        st.warning("Adicione produtos.")
    else:
        # Passamos as colunas selecionadas para a classe
        motor = OtimizadorAlocacao(
            lista_fixos, 
            lista_rotativos, 
            n_slots, 
            df_demografico=df_upload, 
            cols_cota=cols_selecionadas  # <--- PASSANDO A ESCOLHA DO USUÁRIO
        )
        
        with st.spinner("Calculando melhor distribuição..."):
            df_final, status_msg = motor.resolver(num_resp_manual=num_respondentes)
            
            if df_final is not None:
                st.session_state['res_matrix'] = df_final
                st.session_state['proj_nome'] = nome_estudo
                st.success("Matriz Gerada!")
            else:
                st.error(f"Erro: {status_msg}")

# --- VISUALIZAÇÃO ---
if 'res_matrix' in st.session_state:
    df = st.session_state['res_matrix']
    
    tab1, tab2 = st.tabs(["📊 Matriz", "📥 Exportar"])
    
    with tab1:
        st.dataframe(df, use_container_width=True)
        
        # Auditoria rápida visual
        st.markdown("#### Checagem de Balanceamento")
        if cols_selecionadas:
            col_check = st.selectbox("Verificar equilíbrio por:", cols_selecionadas)
            col_pos = [c for c in df.columns if 'Posicao' in c]
            
            # Cria uma tabela cruzada: Cota vs Produtos
            df_long = df.melt(id_vars=[col_check], value_vars=col_pos, value_name="Produto")
            crosstab = pd.crosstab(df_long[col_check], df_long['Produto'])
            st.dataframe(crosstab)
        else:
            col_pos = [c for c in df.columns if 'Posicao' in c]
            st.bar_chart(pd.Series(df[col_pos].values.ravel()).value_counts())

    with tab2:
        buffer = io.BytesIO()
        nome_arquivo = f"{st.session_state['proj_nome']}_Final.xlsx"
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Baixar Excel", buffer.getvalue(), nome_arquivo, type="primary")
