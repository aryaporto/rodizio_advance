import streamlit as st
import pandas as pd
import io
import random
import math
from itertools import cycle, islice

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Alocador Pro (Posição Aleatória)",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS ---
st.markdown("""
<style>
    .block-container {padding-top: 1rem;}
    h1 {color: #2c3e50; font-family: sans-serif;}
    .stMetric {background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #e9ecef;}
    .stDataFrame {border: 1px solid #e0e0e0; border-radius: 5px;}
</style>
""", unsafe_allow_html=True)

# --- CLASSE DE DISTRIBUIÇÃO ---
class DistribuidorTotalmenteAleatorio:
    def __init__(self, fixos, rotativos, n_slots_total):
        self.fixos = fixos
        self.rotativos = rotativos
        self.n_slots_total = n_slots_total
        # Quantos slots sobram para rodízio após colocar os fixos
        self.n_slots_rotativos = n_slots_total - len(fixos)
        
    def processar(self, df_input, cols_cota):
        df = df_input.copy()
        
        # Validação de Segurança
        if self.n_slots_rotativos < 0:
            st.error(f"Erro: Você definiu {self.n_slots_total} dias de teste, mas tem {len(self.fixos)} produtos fixos. Faltam dias!")
            return None

        # Cria as colunas de Posição (Dia 1, Dia 2... Dia N)
        cols_posicao = [f'Posicao_{i+1}' for i in range(self.n_slots_total)]
        for col in cols_posicao:
            df[col] = None

        # Se não houver rotativos, apenas distribui os fixos embaralhados
        if not self.rotativos:
            self._apenas_fixos_embaralhados(df, cols_posicao)
            return df

        # Lógica de Distribuição por Cota
        if not cols_cota:
            self._distribuir_com_posicao_livre(df, df.index, cols_posicao)
        else:
            try:
                # Preenche vazios nas cotas
                for c in cols_cota:
                    df[c] = df[c].fillna("N/A")
                    
                grupos = df.groupby(cols_cota)
                for name, group in grupos:
                    self._distribuir_com_posicao_livre(df, group.index, cols_posicao)
            except Exception as e:
                st.error(f"Erro ao processar cotas: {e}")
                return None

        return df

    def _distribuir_com_posicao_livre(self, df_geral, indices_grupo, cols_posicao):
        """
        1. Define QUAIS produtos a pessoa recebe (Fixos + Baralho Equilibrado de Rotativos).
        2. Define a ORDEM (Shuffle total).
        """
        qtd_pessoas = len(indices_grupo)
        
        # --- PASSO 1: O BARALHO DE "QUEM RECEBE O QUÊ" (EQUIDADE) ---
        # Calcula exatamente quantos rotativos precisamos para esse grupo
        total_rotativos_necessarios = qtd_pessoas * self.n_slots_rotativos
        
        if total_rotativos_necessarios > 0:
            # Cria baralho balanceado (Ex: A, B, C, A, B, C...)
            baralho_rotativos = list(islice(cycle(self.rotativos), total_rotativos_necessarios))
            random.shuffle(baralho_rotativos)
        else:
            baralho_rotativos = []
            
        # --- MONTAGEM DA SACOLA INDIVIDUAL E SORTEIO DA POSIÇÃO ---
        contador_baralho = 0
        
        for idx in indices_grupo:
            # A. Pega os Fixos
            minha_sacola = self.fixos.copy()
            
            # B. Pega os Rotativos do Baralho (para completar os dias)
            # Pega exatamente a quantidade necessária para preencher os dias que faltam
            meus_rotativos = []
            for _ in range(self.n_slots_rotativos):
                if contador_baralho < len(baralho_rotativos):
                    carta = baralho_rotativos[contador_baralho]
                    
                    # (Opcional) Tenta evitar duplicidade SE a pessoa já pegou esse rotativo na mesma sacola
                    # Nota: Em estudos longos (10 dias) com poucos produtos, repetição é obrigatória.
                    # Se tiver muitos produtos, tentamos evitar.
                    if carta in meus_rotativos:
                         # Tenta trocar com o próximo do baralho (Lookahead swap)
                         if contador_baralho + 1 < len(baralho_rotativos):
                             carta_prox = baralho_rotativos[contador_baralho+1]
                             if carta_prox not in meus_rotativos:
                                 # Swap no baralho principal
                                 baralho_rotativos[contador_baralho], baralho_rotativos[contador_baralho+1] = \
                                 baralho_rotativos[contador_baralho+1], baralho_rotativos[contador_baralho]
                                 carta = baralho_rotativos[contador_baralho]
                    
                    meus_rotativos.append(carta)
                    contador_baralho += 1
            
            minha_sacola.extend(meus_rotativos)
            
            # C. O GRANDE FINAL: EMBARALHAR A POSIÇÃO
            # Aqui garantimos que o Fixo não fica sempre no dia 1
            random.shuffle(minha_sacola)
            
            # D. Escreve nas colunas (Dia 1, Dia 2...)
            for i, produto in enumerate(minha_sacola):
                if i < len(cols_posicao): # Segurança
                    df_geral.at[idx, cols_posicao[i]] = produto

    def _apenas_fixos_embaralhados(self, df, cols_posicao):
        # Caso especial onde só existem produtos fixos e queremos apenas sortear a ordem
        for idx in df.index:
            sacola = self.fixos.copy()
            # Assumindo preenchimento vazio se sobrar dia, ou ciclo se faltar produto.
            random.shuffle(sacola)
            for i, col in enumerate(cols_posicao):
                if i < len(sacola):
                    df.at[idx, col] = sacola[i]

# --- AUDITORIA ---
def gerar_auditoria_posicao(df, fixos, rotativos):
    """Verifica se os produtos fixos estão realmente aleatórios nas posições"""
    cols_pos = [c for c in df.columns if 'Posicao' in c]
    
    # 1. Checagem de Balanceamento Geral (Quantidade)
    todos_valores = df[cols_pos].values.flatten()
    todos_valores = [x for x in todos_valores if x is not None]
    contagem = pd.Series(todos_valores).value_counts().reset_index()
    contagem.columns = ['Produto', 'Qtd Total']
    
    # Checagem de Posição (O Fixo está viciado na Posição 1?)
    # Cria uma matriz Produto x Posição
    df_melt = df.melt(value_vars=cols_pos, var_name="Dia", value_name="Produto")
    heatmap_data = pd.crosstab(df_melt['Produto'], df_melt['Dia'])
    
    return contagem, heatmap_data

# --- INTERFACE ---
with st.sidebar:
    st.header("⚙️ Configuração")
    
    # Dados
    st.subheader("1. Amostra")
    tipo_input = st.radio("Origem:", ["Upload Arquivo", "Gerar IDs"])
    
    df_upload = None
    cols_cota = []
    
    if tipo_input == "Upload Arquivo":
        arquivo = st.file_uploader("Excel/CSV", type=['xlsx', 'csv'])
        if arquivo:
            try:
                if arquivo.name.endswith('.csv'):
                    df_upload = pd.read_csv(arquivo)
                else:
                    df_upload = pd.read_excel(arquivo)
                st.success(f"Lidas {len(df_upload)} linhas.")
                
                cols_possiveis = [c for c in df_upload.columns if c.lower() not in ['id', 'nome', 'obs', 'data']]
                cols_cota = st.multiselect("Cotas (Balanceamento):", options=cols_possiveis)
            except:
                st.error("Erro no arquivo.")
    else:
        num_ids = st.number_input("Qtd IDs", value=30)
        df_upload = pd.DataFrame({'ID': range(1, num_ids + 1)})

    st.markdown("---")
    
    # Produtos
    st.subheader("2. Produtos")
    col1, col2 = st.columns(2)
    fixos_txt = col1.text_area("Fixos (Obrigatórios)", placeholder="Ex: Controle", height=100)
    rot_txt = col2.text_area("Rotativos (Sorteio)", value="P1, P2, P3", height=100)
    
    l_fixos = [x.strip() for x in fixos_txt.split(',') if x.strip()]
    l_rotativos = [x.strip() for x in rot_txt.split(',') if x.strip()]
    
    st.markdown("---")

    # Dias / Slots
    st.subheader("3. Duração")
    # O usuário define quantos dias dura o estudo
    total_dias = st.number_input("Quantos dias/amostras por pessoa?", min_value=1, value=3)
    
    if len(l_fixos) > total_dias:
        st.error(f"Atenção: Você tem {len(l_fixos)} fixos para apenas {total_dias} dias!")

    btn_gerar = st.button("🚀 Gerar Distribuição", type="primary")

# --- ÁREA PRINCIPAL ---
st.title("Distribuidor Multiprodutos (Posição Aleatória)")

if btn_gerar:
    if df_upload is None:
        st.warning("Forneça os dados.")
    else:
        # Instancia a nova classe
        motor = DistribuidorTotalmenteAleatorio(l_fixos, l_rotativos, int(total_dias))
        
        with st.spinner("Sorteando produtos e posições..."):
            df_final = motor.processar(df_upload, cols_cota)
            
            if df_final is not None:
                st.session_state['df_final_v2'] = df_final
                st.session_state['config_v2'] = (l_fixos, l_rotativos)
                st.toast("Sucesso!", icon="✅")

# --- VISUALIZAÇÃO ---
if 'df_final_v2' in st.session_state:
    df = st.session_state['df_final_v2']
    fixos, rotativos = st.session_state['config_v2']
    
    tab1, tab2, tab3 = st.tabs(["📄 Tabela", "🔍 Mapa de Calor (Posição)", "📥 Baixar"])
    
    with tab1:
        st.dataframe(df, use_container_width=True)
        
    with tab2:
        st.markdown("### Verificação de Aleatoriedade Posicional")
        st.write("Verifique se os produtos estão espalhados pelos dias (cores devem estar dispersas).")
        
        contagem, heatmap = gerar_auditoria_posicao(df, fixos, rotativos)
        
        # Exibe Heatmap
        st.dataframe(heatmap.style.background_gradient(cmap="Blues"), use_container_width=True)
        
        st.write("**Total de Aparições (Equidade):**")
        st.dataframe(contagem.T)

    with tab3:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Baixar Excel", buffer.getvalue(), "Rodizio_Aleatorio.xlsx", type="primary")
