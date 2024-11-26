import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
from google.oauth2.service_account import Credentials
import json
import toml

# Configurar credenciais e acesso à planilha
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# creds_str = st.secrets["google_sheets_credentials"]

# Converter a string JSON em um dicionário
creds_dict = st.secrets["google_sheets_credentials"]

# Obter as credenciais do serviço
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
client = gspread.authorize(creds)


@st.cache_data(ttl=3)
# Função para inicializar os DataFrames a partir da Google Sheets
def init_dataframes():
    try:
        vendas_sheet = client.open("vendas").worksheet("vendas")
        vendas_df = pd.DataFrame(vendas_sheet.get_all_records())
        # Se o DataFrame estiver vazio, defina as colunas necessárias
        if vendas_df.empty:
            vendas_df = pd.DataFrame(columns=["Código da Venda", "Produto", "Lote", "Quantidade",
                                              "Método de Pagamento", "Data da Venda", "Valor Unitário (R$)",
                                              "Valor Total (R$)"])
    except gspread.exceptions.WorksheetNotFound:
        vendas_df = pd.DataFrame(columns=["Código da Venda", "Produto", "Lote", "Quantidade",
                                          "Método de Pagamento", "Data da Venda", "Valor Unitário (R$)",
                                          "Valor Total (R$)"])

    try:
        registro_estoque_sheet = client.open("registro_estoque").worksheet("registro_estoque")
        registro_estoque_df = pd.DataFrame(registro_estoque_sheet.get_all_records())
        # Se o DataFrame estiver vazio, defina as colunas necessárias
        if registro_estoque_df.empty:
            registro_estoque_df = pd.DataFrame(columns=["Produto","Setor", "Lote", "Quantidade", "Data de Entrada",
                                                        "Data de Validade", "Custo (R$)", "Valor de Venda (R$)"])
    except gspread.exceptions.WorksheetNotFound:
        registro_estoque_df = pd.DataFrame(columns=["Produto","Setor", "Lote", "Quantidade", "Data de Entrada",
                                                    "Data de Validade", "Custo (R$)", "Valor de Venda (R$)"])

    return vendas_df, registro_estoque_df


# Carregar os DataFrames das planilhas
vendas_df, registro_estoque_df = init_dataframes()


# Salvar os DataFrames nas planilhas Google
def salvar_dados():
    # Converter colunas de data para string
    if 'Data de Entrada' in registro_estoque_df.columns:
        registro_estoque_df['Data de Entrada'] = registro_estoque_df['Data de Entrada'].astype(str)
    if 'Data de Validade' in registro_estoque_df.columns:
        registro_estoque_df['Data de Validade'] = registro_estoque_df['Data de Validade'].astype(str)
    if 'Data da Venda' in vendas_df.columns:
        vendas_df['Data da Venda'] = vendas_df['Data da Venda'].astype(str)

    # Formatar colunas de valores numéricos com ponto decimal
    float_columns = ["Custo (R$)", "Valor de Venda (R$)", "Valor Unitário (R$)", "Valor Total (R$)"]

    for col in float_columns:
        if col in registro_estoque_df.columns:
            registro_estoque_df[col] = registro_estoque_df[col].apply(
                lambda x: f"{x:.2f}".replace(",", ".") if pd.notnull(x) else x)
        if col in vendas_df.columns:
            vendas_df[col] = vendas_df[col].apply(lambda x: f"{x:.2f}".replace(",", ".") if pd.notnull(x) else x)

    # Abrir as planilhas e atualizar
    vendas_sheet = client.open("vendas").worksheet("vendas")
    vendas_sheet.update([vendas_df.columns.values.tolist()] + vendas_df.values.tolist())

    registro_estoque_sheet = client.open("registro_estoque").worksheet("registro_estoque")
    registro_estoque_sheet.update([registro_estoque_df.columns.values.tolist()] + registro_estoque_df.values.tolist())
    init_dataframes()


# Função para calcular o estoque atualizado
def calcular_estoque_atualizado():
    estoque_entrada = registro_estoque_df.groupby(["Produto", "Lote", "Setor"], as_index=False)["Quantidade"].sum()
    vendas = vendas_df.groupby(["Produto", "Lote"], as_index=False)["Quantidade"].sum()
    vendas["Quantidade"] *= -1
    estoque_atualizado_df = pd.merge(
        estoque_entrada,
        vendas,
        on=["Produto", "Lote"],
        how="outer",
        suffixes=("_entrada", "_venda")
    )
    estoque_atualizado_df.fillna(0, inplace=True)
    estoque_atualizado_df["Saldo"] = (
        estoque_atualizado_df["Quantidade_entrada"] + estoque_atualizado_df["Quantidade_venda"]
    )
    estoque_atualizado_df = pd.merge(
        estoque_atualizado_df,
        registro_estoque_df[["Produto", "Lote", "Setor", "Data de Entrada", "Data de Validade", "Custo (R$)"]],
        on=["Produto", "Lote", "Setor"],
        how="left"
    )
    estoque_atualizado_df["Custos Totais"] = (
        estoque_atualizado_df["Saldo"] * estoque_atualizado_df["Custo (R$)"]
    )
    estoque_atualizado_df.loc[estoque_atualizado_df["Saldo"] == 0, "Data de Validade"] = ""
    return estoque_atualizado_df


# Página de Entrada de Estoque
def entrada_estoque():
    global registro_estoque_df

    st.header("Entrada de Estoque")
    produto = st.text_input("Nome do Produto").upper()
    quantidade = st.number_input("Quantidade", min_value=0, step=1)
    setor = st.text_input("Setor do Produto").upper()  # Novo campo
    data_entrada = datetime.today().date()
    data_validade = st.date_input("Data de Validade")
    custo = st.number_input("Custo do Produto (R$)")
    valor_venda = st.number_input("Valor de Venda (R$)")

    if produto in registro_estoque_df["Produto"].values:
        ultimo_lote = (
            registro_estoque_df.loc[registro_estoque_df["Produto"] == produto, "Lote"]
            .str.extract(r"(\d+)")  # Extraindo números do lote
            .astype(int)
            .max()
            .values[0]
        )
        lote = f"LOTE {ultimo_lote + 1}"
    else:
        lote = "LOTE 1"

    if st.button("Adicionar ao Estoque"):
        novo_produto = pd.DataFrame(
            {
                "Produto": [produto],
                "Setor": [setor],  # Adicionando o setor
                "Lote": [lote],
                "Quantidade": [quantidade],
                "Data de Entrada": [data_entrada],
                "Data de Validade": [data_validade],
                "Custo (R$)": [custo],
                "Valor de Venda (R$)": [valor_venda],
            }
        )
        registro_estoque_df = pd.concat([registro_estoque_df, novo_produto], ignore_index=True)

        salvar_dados()
        vendas_df, registro_estoque_df = init_dataframes()
        st.success(f"{quantidade} unidades de '{produto}' (Lote: {lote}, Setor: {setor}) adicionadas ao estoque.")


def saida_vendas():
    global registro_estoque_df
    init_dataframes()

    st.header("Saída de Vendas")

    estoque_atualizado_df = calcular_estoque_atualizado()
    produtos_disponiveis = estoque_atualizado_df[estoque_atualizado_df["Saldo"] > 0]
    produtos_ordenados = produtos_disponiveis.sort_values(["Produto", "Data de Validade"], ascending=[True, True])
    produtos_ordenados = produtos_ordenados.drop_duplicates(subset=["Produto", "Lote"], keep="last")

    produtos_selecionados = st.multiselect("Selecione os Produtos",
                                           produtos_ordenados["Produto"] + " - " + produtos_ordenados["Lote"])
    if not produtos_selecionados:
        st.warning("Por favor, selecione ao menos um produto.")
        return

    vendas_temp_data = []
    codigo_venda_temp = datetime.now().strftime("%Y%m%d%H%M%S")

    for produto_lote in produtos_selecionados:
        produto, lote = produto_lote.split(" - ")
        st.subheader(f"Informações do Produto: {produto} (Lote: {lote})")
        quantidade_disponivel = estoque_atualizado_df.loc[
            (estoque_atualizado_df["Produto"] == produto) & (estoque_atualizado_df["Lote"] == lote), "Saldo"].values[0]
        quantidade = st.number_input(f"Quantidade para {produto} (Lote: {lote})", min_value=1,
                                     max_value=int(quantidade_disponivel), step=1, key=f"quantidade_{produto}_{lote}")
        metodo_pagamento = st.selectbox("Selecione o Método de Pagamento",
                                        options=["Dinheiro", "Pix", "Cartão de Crédito", "Cartão de Débito"],
                                        key=f"metodo_pagamento_{produto}_{lote}")
        valor_minimo_venda = registro_estoque_df.loc[(registro_estoque_df["Produto"] == produto) & (
                    registro_estoque_df["Lote"] == lote), "Valor de Venda (R$)"].values[0]
        valor_unitario = st.number_input(f"Valor Unitário (R$) para {produto} (Lote: {lote})",
                                         min_value=valor_minimo_venda,
                                         help=f"Digite o valor de venda mínimo de {valor_minimo_venda} para o produto.",
                                         key=f"valor_unitario_{produto}_{lote}")
        valor_total = valor_unitario * quantidade
        data_hora_venda = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        vendas_temp_data.append(
            {"Código da Venda": codigo_venda_temp, "Produto": produto, "Lote": lote, "Quantidade": quantidade,
             "Método de Pagamento": metodo_pagamento, "Valor Unitário (R$)": valor_unitario,
             "Valor Total (R$)": valor_total, "Data da Venda": data_hora_venda})

    global vendas_temp_df
    vendas_temp_df = pd.DataFrame(vendas_temp_data)

    if st.button("Registrar Venda"):
        global vendas_df
        vendas_df = pd.concat([vendas_df, vendas_temp_df], ignore_index=True)
        salvar_dados()
        st.success("Venda registrada com sucesso.")
        vendas_df, registro_estoque_df = init_dataframes()

    st.subheader("Produtos Selecionados para Venda:")
    st.dataframe(vendas_temp_df)


# Página de Visualização de Estoque e Vendas

def visualizar_dados():
    vendas_df, registro_estoque_df = init_dataframes()

    st.header("Registro de Estoque")
    st.dataframe(registro_estoque_df)

    st.header("Vendas")
    st.dataframe(vendas_df)

    st.header("Estoque Atualizado")
    estoque_atualizado_df = calcular_estoque_atualizado()
    st.dataframe(estoque_atualizado_df)

    vendas_com_custo_df = pd.merge(
        vendas_df,
        registro_estoque_df[["Produto", "Lote", "Setor", "Custo (R$)"]],
        on=["Produto", "Lote"],
        how="left"
    )
    vendas_com_custo_df["Custo Total Vendido (R$)"] = (
        vendas_com_custo_df["Quantidade"] * vendas_com_custo_df["Custo (R$)"]
    )
    valor_total_vendido = vendas_com_custo_df["Valor Total (R$)"].sum()
    custo_total_vendido = vendas_com_custo_df["Custo Total Vendido (R$)"].sum()
    lucro_total = valor_total_vendido - custo_total_vendido
    produto_mais_vendido = vendas_df.groupby("Produto")["Quantidade"].sum().idxmax()
    custo_em_estoque = estoque_atualizado_df["Custos Totais"].sum()

    mostrar_informacoes_negocio = st.sidebar.checkbox("Mostrar Informações do Negócio", value=False)

    if mostrar_informacoes_negocio:
        st.header("Informações sobre o Negócio")
        st.subheader("Lucro Total")
        st.write(f"O lucro total é: R$ {lucro_total:.2f}")

        st.subheader("Produto Mais Vendido")
        st.write(f"O produto mais vendido é: {produto_mais_vendido}")

        st.subheader("Custo em Estoque")
        st.write(f"O custo em estoque é: R$ {custo_em_estoque:.2f}")


# Função para saída de vendas (similar à sua função original)

# Barra de Navegação
page = st.sidebar.radio("Selecione uma opção", options=["Saída de Vendas"])
vendas_df, registro_estoque_df = init_dataframes()
# Exibindo a página selecionada
if page == "Saída de Vendas":
    vendas_df, registro_estoque_df = init_dataframes()
    saida_vendas()
else:
    saida_vendas()
