import streamlit as st
import pandas as pd
import io
import random
import math
from itertools import cycle, islice

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Sistema de Alocação (Random + Cotas)",
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
    .stMetric {background-color: #f0f2f6; padding: 10px; border-radius: 5px;}
</style>
""", unsafe_allow_html=True)

# --- ESTATÍSTICA ---
def calcular_runs_stats(lista_produtos):
    """
    Calcula estatísticas de Runs (Sequências) para validar aleatoriedade.
    Retorna: Runs Observados, Runs Esperados, Ratio
    """
    n = len(lista_produtos)
    if n == 0: return 0, 0, 0
    
    # 1. Conta Runs Observados (quantas vezes muda o produto)
    runs_obs = 1
    for i in range(1, n):
        if lista_produtos[i] != lista_produtos[i-1]:
            runs_obs += 1
            
    # 2. Calcula Runs Esperados (Fórmula de Wald-Wolfowitz Generalizada)
    # E(R) = N * (1 - soma(pi^2)) + 1
    counts = pd.Series(lista_produtos).value_counts()
    soma_quadrados_probs = sum((count / n) ** 2 for count in counts)
    runs_esp = n * (1 - soma_quadrados_probs) + 1
    
    ratio = runs_obs / runs_esp if runs_esp > 0 else 0
    
    return runs_obs, runs_esp, ratio

# --- CLASSE DE DISTRIBUIÇÃO ---
class DistribuidorAleatorio:
    def __init__(self, fixos, rotativos, n_slots_total):
        self.fixos = fixos
        self.rotativos = rotativos
        self.n_slots_rotativos = n_slots_total - len(fixos)
        
    def processar(self, df_input, cols_cota):
        df = df_input.copy()
        
        # Prepara colunas
        total_slots = len(self.fixos) + self.n_slots_rotativos
        cols_posicao = [f'Posicao_{i+1}' for i in range(total_slots)]
        
        for col in cols_posicao:
            df[col] = None

        # 1. Aloca os FIXOS (sempre nas primeiras posições para organizar)
        for i, prod_fixo in enumerate(self.fixos):
            df[cols_posicao[i]] = prod_fixo
        
        # Slots restantes para rotativos
        cols_destino_rotativo = cols_posicao[len(self.fixos):]

        if not cols_destino_rotativo or not self.rotativos:
            return df

        # 2. Distribuição por Grupo (Cota) ou Geral
        if not cols_cota:
            self._distribuir_embaralhado(df, df.index, cols_destino_rotativo)
        else:
            try:
                # Trata NaNs nas colunas de cota para não quebrar o groupby
                for c in cols_cota:
                    df[c] = df[c].fillna("N/A")
                    
                grupos = df.groupby(cols_cota)
                for name, group in grupos:
                    self._distribuir_embaralhado(df, group.index, cols_destino_rotativo)
            except Exception as e:
                st.error(f"Erro ao agrupar cotas: {e}")
                return None

        return df

    def _distribuir_embaralhado(self, df_geral, indices_grupo, cols_destino):
        qtd_pessoas = len(indices_grupo)
        qtd_slots_por_pessoa = len(cols_destino)
        total_posicoes = qtd_pessoas * qtd_slots_por_pessoa
        
        if total_posicoes == 0: return

        # A. Cria o Baralho Balanceado
        # Gera a sequência exata de produtos necessária para preencher os slots
        baralho = list(islice(cycle(self.rotativos), total_posicoes))
        
        # B. Embaralha (Shuffle) - AQUI ESTÁ A ALEATORIEDADE REAL
        random.shuffle(baralho)
        
        # C. Distribui
        contador = 0
        for idx in indices_grupo:
            # Produtos já atribuídos a esta pessoa (ex: fixos)
            linha_atual = df_geral.loc[idx].values.tolist()
            
            for col in cols_destino:
                carta = baralho[contador]
                
                # Tenta evitar repetição imediata na mesma linha (swap simples)
                # Se a carta sorteada já existe na linha desta pessoa...
                if carta in [x for x in df_geral.loc[idx, cols_destino] if x is not None] or carta in self.fixos:
                    # Tenta pegar a próxima carta do monte se possível
                    if contador + 1 < len(baralho):
                        # Troca
                        baralho[contador], baralho[contador+1] = baralho[contador+1], baralho[contador]
                        carta = baralho[contador]
                
                df_geral.at[idx, col] = carta
                contador += 1

# --- INTERFACE (SIDEBAR) ---
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
                
                st.markdown("**Balanceamento (Cotas):**")
                cols_ignorar = ['id', 'nome', 'participante', 'telefone', 'email', 'obs', 'data']
                cols_possiveis = [c for c in df_upload.columns if c.lower() not in cols_ignorar]
                
                cols_selecionadas = st.multiselect(
                    "Selecione as colunas para equilibrar:",
                    options=cols_possiveis,
                    help="O sistema garantirá que cada grupo receba a mesma quantidade de produtos."
                )
            except Exception as e:
                st.error(f"Erro ao ler arquivo: {e}")
    else:
        num_respondentes = st.number_input("Nº de IDs a gerar", min_value=12, value=120, step=6)
        
    st.markdown("---")
    st.subheader("2. Produtos")
    
    c1, c2 = st.columns(2)
    with c1:
        fixos_str = st.text_area("Fixos (Todos veem)", height=100, placeholder="Ex: A")
    with c2:
        rot_str = st.text_area("Rotativos (Rodízio)", value="P1, P2, P3", height=100)
        
    lista_fixos = [x.strip() for x in fixos_str.split(',') if x.strip()]
    lista_rotativos = [x.strip() for x in rot_str.split(',') if x.strip()]
    
    total_itens = len(lista_fixos) + len(lista_rotativos)
    
    st.subheader("3. Slots")
    min_s = len(lista_fixos) + 1 if len(lista_rotativos) > 0 else len(lista_fixos)
    n_slots = st.slider("Produtos por pessoa (Total)", min_value=min_s, max_value=max(total_itens, 1), value=min(3, total_itens))
    
    st.markdown("---")
    btn_processar = st.button("GERAR RODÍZIO", type="primary")

# --- LÓGICA PRINCIPAL (MAIN) ---
st.title("Sistema de Alocação Balanceada")

if btn_processar:
    if len(lista_rotativos) == 0 and len(lista_fixos) == 0:
        st.warning("Adicione produtos.")
    else:
        # Prepara base
        if df_upload is not None:
            df_base = df_upload
        else:
            df_base = pd.DataFrame({'ID': range(1, num_respondentes + 1)})

        distribuidor = DistribuidorAleatorio(lista_fixos, lista_rotativos, n_slots)
        
        with st.spinner("Embaralhando e distribuindo..."):
            df_final = distribuidor.processar(df_base, cols_selecionadas)
            
            if df_final is not None:
                st.session_state['res_matrix'] = df_final
                st.session_state['proj_nome'] = nome_estudo
                st.success("Distribuição realizada com sucesso!")
            else:
                st.error("Erro no processamento.")

# --- VISUALIZAÇÃO DOS RESULTADOS ---
if 'res_matrix' in st.session_state:
    df = st.session_state['res_matrix']
    
    # Identifica colunas rotativas para análise
    cols_rotativas = [c for c in df.columns if 'Posicao' in c and df[c].iloc[0] not in lista_fixos]
    
    tab1, tab2, tab3 = st.tabs(["📊 Matriz", "🎲 Auditoria (Runs Test)", "📥 Exportar"])
    
    with tab1:
        st.dataframe(df, use_container_width=True)
        if cols_selecionadas:
            st.info(f"Balanceamento aplicado dentro de: {', '.join(cols_selecionadas)}")

    with tab2:
        st.markdown("### Teste de Aleatoriedade (Runs Test)")
        st.write("Verifica se os produtos estão alternando de forma natural ou se há vícios.")
        
        if cols_rotativas:
            # Pega a primeira coluna rotativa para análise (amostra)
            col_teste = cols_rotativas[0]
            
            # Se houver cota, analisamos dentro do maior grupo para ser justo
            if cols_selecionadas:
                col_cota = cols_selecionadas[0]
                maior_grupo = df[col_cota].value_counts().idxmax()
                st.caption(f"Analisando grupo: **{col_cota} = {maior_grupo}** (Coluna: {col_teste})")
                sequencia = df[df[col_cota] == maior_grupo][col_teste].tolist()
            else:
                st.caption(f"Analisando Total Geral (Coluna: {col_teste})")
                sequencia = df[col_teste].tolist()
            
            # Cálculo Estatístico
            r_obs, r_esp, ratio = calcular_runs_stats(sequencia)
            
            # Exibição
            c1, c2, c3 = st.columns(3)
            c1.metric("Trocas (Runs) Observadas", r_obs)
            c2.metric("Trocas (Runs) Esperadas", f"{r_esp:.1f}")
            
            status_delta = "OK"
            status_color = "normal"
            
            if 0.85 <= ratio <= 1.15:
                status_text = "✅ Aleatoriedade Aprovada"
                msg_detail = "A sequência apresenta variação natural."
            elif ratio < 0.85:
                status_text = "⚠️ Poucas Trocas (Agrupado)"
                msg_detail = "Os produtos estão repetindo em blocos (ex: AAABBB). Pode indicar viés de agrupamento."
                status_delta = "- Baixo"
                status_color = "inverse"
            else:
                status_text = "⚠️ Muitas Trocas (Alternado)"
                msg_detail = "Os produtos estão alternando demais (ex: ABABAB). Parece artificial."
                status_delta = "+ Alto"
                status_color = "inverse"
                
            c3.metric("Status Estatístico", status_text, delta=status_delta, delta_color=status_color)
            st.info(msg_detail)
            
            st.markdown("---")
            st.markdown("#### Distribuição Visual")
            st.bar_chart(pd.Series(sequencia).value_counts())
            
        else:
            st.warning("Não há colunas rotativas suficientes para análise.")

    with tab3:
        buffer = io.BytesIO()
        nome_arquivo = f"{st.session_state['proj_nome']}_Final.xlsx"
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Baixar Excel (.xlsx)", buffer.getvalue(), nome_arquivo, type="primary")
