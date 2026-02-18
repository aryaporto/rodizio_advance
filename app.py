import streamlit as st
import pandas as pd
import io
import random
import math
from itertools import cycle, islice

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Alocador Pro V3",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS ---
st.markdown("""
<style>
    .block-container {padding-top: 1rem;}
    h1 {color: #2c3e50; font-family: 'Helvetica', sans-serif;}
    .stMetric {background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 5px; padding: 10px;}
    .dataframe {font-size: 12px;}
</style>
""", unsafe_allow_html=True)

# --- CLASSE DE DISTRIBUIÇÃO ---
class DistribuidorSeparado:
    def __init__(self, fixos, rotativos, n_amostras_teste, n_colunas_excel):
        self.fixos = fixos
        self.rotativos = rotativos
        
        # Quantos produtos a pessoa VAI USAR (ex: 5)
        self.n_amostras = n_amostras_teste
        
        # Quantas colunas o Excel VAI TER (ex: 10)
        self.n_colunas = n_colunas_excel
        
        # Quantos rotativos precisamos sortear para completar as amostras?
        self.n_rotativos_necessarios = self.n_amostras - len(fixos)
        
    def processar(self, df_input, cols_cota):
        df = df_input.copy()
        
        # Validações de Segurança
        if self.n_rotativos_necessarios < 0:
            st.error(f"Erro: Você pediu {self.n_amostras} amostras, mas já tem {len(self.fixos)} produtos fixos. O total excede o pedido.")
            return None
            
        if self.n_colunas < self.n_amostras:
            st.error(f"Erro: O Excel tem menos colunas ({self.n_colunas}) do que produtos a testar ({self.n_amostras}).")
            return None

        # Cria as colunas do Excel (Ordem_1, Ordem_2... ou Dia_1...)
        cols_output = [f'Posicao_{i+1}' for i in range(self.n_colunas)]
        for col in cols_output:
            df[col] = None # Inicia vazio

        # Se não houver rotativos, apenas distribui os fixos
        if not self.rotativos:
            self._distribuir_apenas_fixos(df, cols_output)
            return df

        # Lógica de Distribuição por Cota (Ou Geral)
        if not cols_cota:
            self._distribuir_grupo(df, df.index, cols_output)
        else:
            try:
                # Preenche vazios nas cotas para agrupar corretamente
                for c in cols_cota:
                    df[c] = df[c].fillna("Indefinido")
                    
                grupos = df.groupby(cols_cota)
                for name, group in grupos:
                    self._distribuir_grupo(df, group.index, cols_output)
            except Exception as e:
                st.error(f"Erro ao processar colunas de cota: {e}")
                return None

        return df

    def _distribuir_grupo(self, df_geral, indices_grupo, cols_output):
        """
        Lógica:
        1. Calcula quantos rotativos esse grupo precisa no total.
        2. Cria um 'Baralho' com a quantidade exata.
        3. Distribui para cada pessoa.
        """
        qtd_pessoas = len(indices_grupo)
        
        # TOTAL de produtos rotativos que precisam ser consumidos por esse grupo
        # Ex: 10 pessoas * 3 rotativos cada = 30 produtos para tirar do baralho
        total_itens_necessarios = qtd_pessoas * self.n_rotativos_necessarios
        
        if total_itens_necessarios > 0:
            # Cria baralho perfeitamente balanceado (A, B, C, A, B, C...)
            baralho = list(islice(cycle(self.rotativos), total_itens_necessarios))
            # Embaralha o monte
            random.shuffle(baralho)
        else:
            baralho = []
            
        contador_baralho = 0
        
        for idx in indices_grupo:
            minha_mao = self.fixos.copy()
            
            # Pega do baralho os rotativos que faltam para essa pessoa
            for _ in range(self.n_rotativos_necessarios):
                if contador_baralho < len(baralho):
                    carta = baralho[contador_baralho]
                    
                    # (Swap simples para evitar repetição imediata na mão, se possível)
                    if carta in minha_mao and len(self.rotativos) > 1:
                        # Tenta olhar a próxima
                        if contador_baralho + 1 < len(baralho):
                            carta_prox = baralho[contador_baralho+1]
                            if carta_prox not in minha_mao:
                                # Troca no baralho
                                baralho[contador_baralho], baralho[contador_baralho+1] = baralho[contador_baralho+1], baralho[contador_baralho]
                                carta = baralho[contador_baralho]
                    
                    minha_mao.append(carta)
                    contador_baralho += 1
            
            # 2. Aleatoriedade de Posição
            random.shuffle(minha_mao)
            
            # 3. Preenche as colunas
            # Preenche as colunas sequencialmente (Posicao_1, Posicao_2...)
            # As colunas excedentes (se dias > amostras) ficarão vazias (None)
            for i, produto in enumerate(minha_mao):
                if i < len(cols_output):
                    df_geral.at[idx, cols_output[i]] = produto

    def _distribuir_apenas_fixos(self, df, cols_output):
        for idx in df.index:
            mao = self.fixos.copy()
            random.shuffle(mao)
            for i, prod in enumerate(mao):
                if i < len(cols_output):
                    df.at[idx, cols_output[i]] = prod

# --- INTERFACE SIDEBAR ---
with st.sidebar:
    # --- LOGO COM FALLBACK ---
    col_logo, col_txt = st.columns([1, 4])
    try:
        st.image("logo.png", use_container_width=True)
    except:
        st.write("## 🧪 Allocator")
    
    st.markdown("---")
    st.header("1. Configuração")
    
    # 1. Input de Dados
    tipo_input = st.radio("Fonte de Dados:", ["Upload de Arquivo", "Gerar IDs (Simples)"])
    
    df_upload = None
    cols_cota = []
    
    if tipo_input == "Upload de Arquivo":
        arquivo = st.file_uploader("Arraste o Excel/CSV aqui", type=['xlsx', 'csv'])
        if arquivo:
            try:
                if arquivo.name.endswith('.csv'):
                    df_upload = pd.read_csv(arquivo)
                else:
                    df_upload = pd.read_excel(arquivo)
                st.success(f"✅ {len(df_upload)} participantes carregados.")
                
                # Seleção de Cotas
                st.markdown("**Balanceamento (Cotas):**")
                cols_ignorar = ['id', 'nome', 'celular', 'obs', 'data', 'email', 'telefone']
                cols_possiveis = [c for c in df_upload.columns if c.lower() not in cols_ignorar]
                cols_cota = st.multiselect("Equilibrar produtos por:", options=cols_possiveis)
                
            except Exception as e:
                st.error("Erro ao ler arquivo.")
    else:
        num_ids = st.number_input("Quantidade de IDs", value=50, step=10)
        df_upload = pd.DataFrame({'ID': range(1, num_ids + 1)})

    st.markdown("---")
    st.header("2. Produtos")
    
    col1, col2 = st.columns(2)
    with col1:
        fixos_txt = st.text_area("Fixos (Obrigatórios)", placeholder="Ex: Controle", height=100)
    with col2:
        rot_txt = st.text_area("Rotativos (Sorteio)", value="P1, P2, P3", height=100)
        
    l_fixos = [x.strip() for x in fixos_txt.split(',') if x.strip()]
    l_rotativos = [x.strip() for x in rot_txt.split(',') if x.strip()]
    
    # --- AQUI ESTÁ A CORREÇÃO DE LÓGICA (SEPARAÇÃO) ---
    st.markdown("---")
    st.header("3. Regras do Estudo")
    
    col_dias, col_amostras = st.columns(2)
    
    with col_dias:
        n_colunas = st.number_input(
            "Colunas no Excel", 
            min_value=1, value=5, 
            help="Quantas colunas de 'Posição' serão criadas no arquivo final? (Ex: Duração do estudo)"
        )
        
    with col_amostras:
        n_amostras = st.number_input(
            "Amostras por Pessoa", 
            min_value=1, value=5,
            help="Quantos produtos cada pessoa vai testar de fato?"
        )
        
    if n_amostras > n_colunas:
        st.error("⚠️ Erro: Você quer testar mais produtos do que existem colunas disponíveis!")

    st.markdown("---")
    btn_gerar = st.button("🚀 GERAR DISTRIBUIÇÃO", type="primary")

# --- ÁREA PRINCIPAL ---
st.title("Gerador de Rodízio Balanceado")

if btn_gerar:
    if not df_upload is not None:
        st.warning("Por favor, carregue um arquivo ou defina os IDs.")
    elif (len(l_fixos) + len(l_rotativos)) == 0:
        st.warning("Cadastre os produtos antes de continuar.")
    else:
        # Instancia a nova classe com a lógica separada
        motor = DistribuidorSeparado(l_fixos, l_rotativos, n_amostras, n_colunas)
        
        with st.spinner("Calculando equidade e sorteando posições..."):
            df_final = motor.processar(df_upload, cols_cota)
            
            if df_final is not None:
                st.session_state['resultado_v3'] = df_final
                st.session_state['params_v3'] = (l_fixos, l_rotativos)
                st.toast("Matriz gerada com sucesso!", icon="✅")

# --- VISUALIZAÇÃO E AUDITORIA ---
if 'resultado_v3' in st.session_state:
    df = st.session_state['resultado_v3']
    fixos, rotativos = st.session_state['params_v3']
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["📄 Base Final", "🔍 Auditoria (Visual Melhorado)", "📥 Download"])
    
    with tab1:
        st.dataframe(df, use_container_width=True)
        st.caption(f"Total de Linhas: {len(df)}")
        
    with tab2:
        st.markdown("### 📊 Raio-X da Distribuição")
        
        # Filtro de grupo para auditoria
        if cols_cota:
            st.markdown(f"**Verificando equilíbrio dentro de: {cols_cota[0]}**")
            opcoes = ["Todos"] + sorted(list(df[cols_cota[0]].astype(str).unique()))
            escolha = st.selectbox("Filtrar Grupo:", opcoes)
            
            if escolha != "Todos":
                df_audit = df[df[cols_cota[0]].astype(str) == escolha]
            else:
                df_audit = df
        else:
            df_audit = df

        # Identifica colunas de posição
        cols_pos = [c for c in df_audit.columns if 'Posicao' in c]
        
        # 1. Tabela de Contagem (Equidade)
        # Transforma a matriz em uma lista única de produtos usados
        produtos_usados = df_audit[cols_pos].values.flatten()
        # Remove vazios e conta
        produtos_usados = [x for x in produtos_usados if pd.notna(x)]
        
        if produtos_usados:
            contagem = pd.Series(produtos_usados).value_counts().reset_index()
            contagem.columns = ['Produto', 'Qtd Real']
            
            # Gráfico de Barras Simples
            c1, c2 = st.columns([1, 2])
            with c1:
                st.write("**Contagem Total**")
                # Estiliza a tabela com barra de dados
                st.dataframe(
                    contagem.style.bar(subset=['Qtd Real'], color='#d65f5f'),
                    use_container_width=True,
                    hide_index=True
                )
            with c2:
                st.write("**Distribuição por Posição (Heatmap)**")
                st.info("Verifique se as cores estão espalhadas (aleatoriedade) e não concentradas em colunas específicas.")
                
                # Heatmap: Produto x Posição
                df_melt = df_audit.melt(value_vars=cols_pos, var_name="Ordem", value_name="Produto")
                heatmap = pd.crosstab(df_melt['Produto'], df_melt['Ordem'])
                
                # Exibe colorido
                st.dataframe(heatmap.style.background_gradient(cmap="Blues"), use_container_width=True)
        else:
            st.warning("Nenhum produto encontrado nas colunas de posição.")

    with tab3:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name="Base_Gerada")
            # Adiciona aba de auditoria no Excel também
            if produtos_usados:
                contagem.to_excel(writer, index=False, sheet_name="Resumo_Auditoria")
                
        st.download_button(
            label="📥 Baixar Excel Completo",
            data=buffer.getvalue(),
            file_name="Rodizio_Final_Pro.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
