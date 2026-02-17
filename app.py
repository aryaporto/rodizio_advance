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
    h3 {font-family: 'Segoe UI', sans-serif; font-size: 1.2rem; color: #34495e;}
    .stButton>button {
        background-color: #2980b9; color: white; border-radius: 5px; height: 3em; font-weight: 600; width: 100%;
    }
    .stButton>button:hover {background-color: #3498db;}
    .stAlert {border-radius: 5px;}
</style>
""", unsafe_allow_html=True)

# --- CLASSE DO OTIMIZADOR ---
class OtimizadorAlocacao:
    def __init__(self, fixos, rotativos, slots, df_demografico=None):
        self.fixos = fixos
        self.rotativos = rotativos
        self.todos_produtos = fixos + rotativos
        self.n_slots = slots
        self.df_demografico = df_demografico
        
        # Se tem arquivo, usa o tamanho do arquivo. Se não, usa o numérico passado.
        if df_demografico is not None:
            self.n_respondentes = len(df_demografico)
        else:
            self.n_respondentes = 0 # Será setado externamente se não houver df
            
    def resolver(self, num_resp_manual=None):
        # Definição final do N de respondentes
        n_resp = self.n_respondentes if self.df_demografico is not None else num_resp_manual
        n_prod = len(self.todos_produtos)
        n_fixos = len(self.fixos)
        
        # Embaralha índices para evitar viés de ordem alfabética na solução
        indices_produtos = list(range(n_prod))
        random.shuffle(indices_produtos)
        
        model = cp_model.CpModel()
        
        # Variáveis de Decisão: x[respondente, slot, produto]
        x = {}
        for r in range(n_resp):
            for c in range(self.n_slots):
                for p in range(n_prod):
                    x[(r, c, p)] = model.NewBoolVar(f'x_{r}_{c}_{p}')
        
        # --- Regras Invioláveis ---
        
        # 1. Exatamente um produto por slot
        for r in range(n_resp):
            for c in range(self.n_slots):
                model.Add(sum(x[(r, c, p)] for p in range(n_prod)) == 1)
        
        # 2. O mesmo produto não pode aparecer mais de uma vez para a mesma pessoa
        for r in range(n_resp):
            for p in range(n_prod):
                model.Add(sum(x[(r, c, p)] for c in range(self.n_slots)) <= 1)
        
        # 3. Produtos Fixos Obrigatórios (aparecem para todos)
        # Mapeia o índice original para o índice embaralhado
        ids_fixos = [i for i, prod in enumerate(self.todos_produtos) if prod in self.fixos]
        for p_idx in ids_fixos:
            for r in range(n_resp):
                model.Add(sum(x[(r, c, p_idx)] for c in range(self.n_slots)) == 1)

        # --- SOFT CONSTRAINTS (Metas de Balanceamento) ---
        penalidades = []
        
        # A. Balanceamento por Posição (Nivelamento Visual)
        total_slots = n_resp * self.n_slots
        slots_rotativos = total_slots - (n_resp * n_fixos)
        n_rotativos = len(self.rotativos)
        
        target_rotativo = int(slots_rotativos / n_rotativos / self.n_slots) if n_rotativos > 0 else 0
        
        max_desvio_coluna = model.NewIntVar(0, n_resp, 'max_dev_col')
        
        for c in range(self.n_slots):
            for p in range(n_prod):
                # Se for fixo, o target é n_resp/n_slots (balancear posição)
                # Se for rotativo, é o target calculado acima
                is_fixo = self.todos_produtos[p] in self.fixos
                t = int(n_resp / self.n_slots) if is_fixo else target_rotativo
                
                soma_coluna = sum(x[(r, c, p)] for r in range(n_resp))
                
                # Cria variável de desvio
                diff = model.NewIntVar(0, n_resp, f'diff_{c}_{p}')
                model.Add(soma_coluna - t <= diff)
                model.Add(t - soma_coluna <= diff)
                model.Add(diff <= max_desvio_coluna) # Minimax estratégia
                penalidades.append(diff)

        # B. Balanceamento Demográfico
        # Se houver dados demográficos, garante que os produtos sejam distribuídos igualmente
        # dentro de cada subgrupo (Ex: Entre Jovens Classe B, todos veem o prod X igualmente)
        if self.df_demografico is not None:
            # Identifica colunas de cota (exclui ID se houver)
            cols_cota = [c for c in self.df_demografico.columns if c.lower() not in ['id', 'nome', 'participante']]
            
            if cols_cota:
                # Agrupa índices por perfil
                grupos = self.df_demografico.groupby(cols_cota).groups
                
                for nome_grupo, indices in grupos.items():
                    # indices é a lista de linhas (respondentes) que pertencem a esse grupo
                    n_pessoas_grupo = len(indices)
                    if n_pessoas_grupo < 2: continue # Ignora grupos muito pequenos
                    
                    # Target esperado dentro desse grupo
                    # (Quantas vezes o produto X deve aparecer neste grupo?)
                    target_grupo = int((n_pessoas_grupo * (self.n_slots - n_fixos)) / n_rotativos) if n_rotativos > 0 else 0
                    
                    for p in range(n_prod):
                        if self.todos_produtos[p] in self.rotativos:
                            soma_grupo = sum(sum(x[(r, c, p)] for c in range(self.n_slots)) for r in indices)
                            
                            dev_grupo = model.NewIntVar(0, n_pessoas_grupo, f'dev_g_{nome_grupo}_{p}')
                            model.Add(soma_grupo - target_grupo <= dev_grupo)
                            model.Add(target_grupo - soma_grupo <= dev_grupo)
                            
                            # Peso alto para garantir representatividade nas cotas
                            penalidades.append(dev_grupo * 5) 

        # --- FUNÇÃO OBJETIVO ---
        # Minimizar penalidades + Maximizar Entropia (Random Score)
        
        random_score = []
        for r in range(n_resp):
            for c in range(self.n_slots):
                for p in range(n_prod):
                    # Peso aleatório para quebrar simetrias
                    w = random.randint(1, 100)
                    random_score.append(x[(r, c, p)] * w)
        
        model.Minimize(sum(penalidades) * 1000 - sum(random_score))
        
        # Solver Config
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0
        solver.parameters.random_seed = random.randint(0, 10000) # Garante aleatoriedade real na seed
        
        status = solver.Solve(model)
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            dados_saida = []
            
            # Se tiver DF original, pega os dados dele, senão cria IDs sequenciais
            base_dados = self.df_demografico.to_dict('records') if self.df_demografico is not None else [{'ID': i+1} for i in range(n_resp)]
            
            colunas_header = list(base_dados[0].keys()) + [f'Posicao_{k+1}' for k in range(self.n_slots)]
            
            for r in range(n_resp):
                linha = base_dados[r].copy()
                # Preenche as posições
                pos_counter = 1
                for c in range(self.n_slots):
                    for p in range(n_prod):
                        if solver.Value(x[(r, c, p)]) == 1:
                            linha[f'Posicao_{pos_counter}'] = self.todos_produtos[p]
                            pos_counter += 1
                dados_saida.append(linha)
                
            return pd.DataFrame(dados_saida), "Sucesso"
        else:
            return None, "Inviável (Verifique se há slots suficientes para os produtos fixos)"

# --- INTERFACE SIDEBAR ---
with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        st.write("## 🧪 Allocator Pro")
    
    st.markdown("---")
    st.header("1. Configuração")
    nome_estudo = st.text_input("Nome do Estudo", value="Teste_Sensorial_Jan26")
    
    st.subheader("Definição de Amostra")
    tipo_input = st.radio("Fonte de Dados:", ["Gerar IDs Numéricos", "Upload de Arquivo (Cotas)"])
    
    df_upload = None
    num_respondentes = 120
    
    if tipo_input == "Upload de Arquivo (Cotas)":
        arquivo = st.file_uploader("Suba Excel/CSV com os perfis", type=['xlsx', 'csv'])
        if arquivo:
            try:
                if arquivo.name.endswith('.csv'):
                    df_upload = pd.read_csv(arquivo)
                else:
                    df_upload = pd.read_excel(arquivo)
                st.success(f"{len(df_upload)} participantes carregados.")
            except:
                st.error("Erro ao ler arquivo.")
    else:
        num_respondentes = st.number_input("Nº de IDs a gerar", min_value=12, value=120, step=6)
        
    st.markdown("---")
    st.subheader("2. Produtos")
    
    # Inputs de produtos
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        fixos_str = st.text_area("Fixos (Todos veem)", value="", height=100, placeholder="Ex: A, B")
    with col_p2:
        rot_str = st.text_area("Rotativos (Rodízio)", value="P1, P2, P3, P4, P5, P6", height=100)
        
    lista_fixos = [x.strip() for x in fixos_str.split(',') if x.strip()]
    lista_rotativos = [x.strip() for x in rot_str.split(',') if x.strip()]
    
    total_itens = len(lista_fixos) + len(lista_rotativos)
    st.caption(f"Total SKUs: {total_itens}")
    
    st.subheader("3. Design")
    min_s = len(lista_fixos) + 1 if len(lista_rotativos) > 0 else len(lista_fixos)
    n_slots = st.slider("Produtos por pessoa (Slots)", min_value=min_s, max_value=max(total_itens, 1), value=min(3, total_itens))
    
    st.markdown("---")
    btn_processar = st.button("GERAR MATRIZ OTIMIZADA", type="primary")

# --- LÓGICA PRINCIPAL NA TELA ---
st.title("Sistema de Alocação Balanceada")

if btn_processar:
    if len(lista_rotativos) == 0 and len(lista_fixos) == 0:
        st.warning("Adicione pelo menos um produto.")
    else:
        # Instancia a classe otimizadora
        motor = OtimizadorAlocacao(lista_fixos, lista_rotativos, n_slots, df_demografico=df_upload)
        
        with st.spinner("Calculando melhor distribuição (Balanceamento + Entropia)..."):
            # Chama o método resolver
            df_final, status_msg = motor.resolver(num_resp_manual=num_respondentes)
            
            if df_final is not None:
                st.session_state['resultado_matrix'] = df_final
                st.session_state['nome_projeto'] = nome_estudo
                st.success("Distribuição gerada com sucesso!")
                
                # Alerta sobre cotas
                if df_upload is not None:
                    cols_usadas = [c for c in df_upload.columns if c.lower() not in ['id','nome']]
                    st.info(f"💡 Otimização realizada considerando balanceamento nas colunas: {', '.join(cols_usadas)}")
            else:
                st.error(f"Erro: {status_msg}")

# --- VISUALIZAÇÃO DOS DADOS ---
if 'resultado_matrix' in st.session_state:
    df = st.session_state['resultado_matrix']
    
    tab1, tab2, tab3 = st.tabs(["📊 Matriz Final", "⚖️ Auditoria de Balanceamento", "📥 Exportar"])
    
    with tab1:
        st.dataframe(df, use_container_width=True)
    
    with tab2:
        st.markdown("### Frequência de Exposição")
        # Conta quantas vezes cada produto aparece
        cols_pos = [c for c in df.columns if 'Posicao' in c]
        contagem = pd.Series(df[cols_pos].values.ravel()).value_counts().sort_index()
        st.bar_chart(contagem)
        
        st.write("Tabela Detalhada:")
        st.dataframe(contagem.to_frame(name="Qtd Aparições").T)

    with tab3:
        buffer = io.BytesIO()
        nome_arquivo = f"{st.session_state['nome_projeto']}_Alocacao.xlsx"
        
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Matriz")
            contagem.to_frame(name="Total").to_excel(writer, sheet_name="Resumo")
            
        st.download_button(
            label="📥 BAIXAR PLANILHA FINAL",
            data=buffer.getvalue(),
            file_name=nome_arquivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

