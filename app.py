import streamlit as st
import datetime
import pandas as pd
from database import (
    inicializar_banco, 
    listar_slots_por_data, 
    realizar_agendamento, 
    obter_agendamentos_completos,
    CALENDAR_ID  # Importação adicionada para corrigir o NameError
)

# Configurações de layout da página
st.set_page_config(page_title="Balcão Virtual de Atendimento", layout="wide", page_icon="🏫")

# Garante inicialização e carga primária do banco
inicializar_banco()

st.title("🏫 Balcão de Atendimento Virtual - Super Janela 2025 PDM")
st.write("Agende um horário para tirar suas dúvidas via Google Meet. Cada sessão dura no máximo 30 minutos.")

# Navegação lateral discreta entre as visões do sistema
menu = st.sidebar.radio("Navegar por:", ["Área do Usuário (Agendamento)", "Painel do Administrador"])

# --- VISÃO 1: ÁREA DO USUÁRIO ---
if menu == "Área do Usuário (Agendamento)":
    st.header("📅 Selecione uma Data e Horário")
    
    # Limita o calendário do Streamlit estritamente dentro da vigência configurada
    data_minima = datetime.date(2026, 5, 21)
    data_maxima = datetime.date(2026, 5, 29)
    
    # Seletor de data formatado no padrão brasileiro DD/MM/AAAA
    data_selecionada = st.date_input(
        "Selecione o dia do atendimento:",
        value=data_minima,
        min_value=data_minima,
        max_value=data_maxima,
        format="DD/MM/YYYY"  # Correção aplicada para formato brasileiro
    )
    
    data_str = data_selecionada.strftime("%Y-%m-%d")
    
    # Valida se o usuário escolheu um final de semana diretamente no componente
    if data_selecionada.weekday() >= 5:
        st.warning("O balcão virtual opera apenas em dias úteis (Segunda a Sexta). Por favor, mude a data acima.")
    else:
        slots = listar_slots_por_data(data_str)
        
        st.subheader(f"Horários disponíveis para o turno Matutino em {data_selecionada.strftime('%d/%m/%Y')}:")
        
        # Renderização dos horários em formato de Grid de Cards usando colunas
        cols = st.columns(4)
        slot_selecionado = None
        
        for idx, (slot_id, inicio, fim, status) in enumerate(slots):
            col = cols[idx % 4]
            if status == "Disponivel":
                if col.button(f"🟢 {inicio} - {fim}", key=f"btn_{slot_id}", use_container_width=True):
                    st.session_state["id_selecionado"] = slot_id
                    st.session_state["horario_texto"] = f"{inicio} às {fim}"
            else:
                col.button(f"🔴 {inicio} - {fim} (Ocupado)", key=f"btn_{slot_id}", disabled=True, use_container_width=True)
        
        # Se um horário foi clicado, abre o formulário de cadastro logo abaixo
        if "id_selecionado" in st.session_state:
            st.write("---")
            st.subheader(f"Confirmar Agendamento para às {st.session_state['horario_texto']}")
            
            with st.form(key="form_agendamento", clear_on_submit=True):
                nome = st.text_input("Seu Nome Completo *")
                email = st.text_input("Seu E-mail * (O link do Google Meet será enviado para cá)")
                duvida = st.text_area("Descreva de forma breve sua dúvida ou assunto *")
                
                # Correção do nome da função do botão de envio do formulário
                enviar = st.form_submit_button("Confirmar Horário de Atendimento")
                
                if enviar:
                    if not nome or not email or not duvida:
                        st.error("Por favor, preencha todos os campos obrigatórios marcados com (*).")
                    elif "@" not in email:
                        st.error("Insira um endereço de e-mail válido para receber o convite.")
                    else:
                        with st.spinner("Conectando ao Google Agenda e gerando sua sala do Meet..."):
                            link_meet = realizar_agendamento(
                                st.session_state["id_selecionado"], 
                                nome, 
                                email, 
                                duvida
                            )
                            
                        if link_meet:
                            st.success("🎉 Agendamento realizado com sucesso!")
                            st.balloons()
                            
                            # Caixa de destaque contendo as informações e ações para o usuário
                            st.info(f"**Importante:** Um convite oficial do Google Calendar foi enviado para **{email}**.")
                            st.code(f"Link da sua sala virtual: {link_meet}", language="text")
                            st.markdown(f"[Clique aqui para entrar direto no Google Meet]({link_meet})")
                            
                            # Limpa o estado da sessão para evitar reenvios acidentais
                            del st.session_state["id_selecionado"]
                        else:
                            st.error("Este horário acabou de ser reservado por outro usuário. Por favor, escolha outro slot.")

# --- VISÃO 2: PAINEL DO ADMINISTRADOR ---
elif menu == "Painel do Administrador":
    st.header("📊 Painel de Controle - Gerenciamento de Atendimentos")
    st.write(f"Perfil de monitoramento ativo: **{CALENDAR_ID}**")
    
    agendamentos = obter_agendamentos_completos()
    
    if not agendamentos:
        st.info("Nenhum atendimento foi reservado por usuários até o momento.")
    else:
        st.subheader("Lista Cronológica de Atendimentos Marcados")
        
        # Converte a matriz em um DataFrame do Pandas para exibição rica e formatações nativas
        df = pd.DataFrame(agendamentos, columns=[
            "Data", "Início", "Fim", "Nome do Usuário", "E-mail do Usuário", "Dúvida / Assunto", "Link do Google Meet"
        ])
        
        # Tratamento visual da data para o padrão nacional
        df["Data"] = pd.to_datetime(df["Data"]).dt.strftime("%d/%m/%Y")
        
        # Exibe a tabela interativa com ordenação e filtros dinâmicos na tela
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # Recurso de exportação gerencial em CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Exportar Lista para CSV / Excel",
            data=csv,
            file_name=f"atendimentos_balcao_virtual_{datetime.date.today()}.csv",
            mime="text/csv"
        )
        
        st.write("---")
        st.subheader("💡 Dica de Fluxo de Trabalho")
        st.markdown("""
        * Todos os horários listados acima já constam no seu **Google Agenda** nativo associado ao e-mail cadastrado.
        * As dúvidas foram injetadas diretamente na caixa de descrição do compromisso na agenda para consulta rápida pelo celular.
        """)