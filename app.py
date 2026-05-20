import streamlit as st
import datetime
import pandas as pd
from database import (
    inicializar_banco, 
    listar_slots_por_data, 
    realizar_agendamento, 
    obter_agendamentos_completos,
    CALENDAR_ID,
    limpar_banco
)

# Configurações de layout da página
st.set_page_config(page_title="Balcão Virtual de Atendimento", layout="wide", page_icon="🏫")

# Garante inicialização e carga primária da base de dados
inicializar_banco()

st.title("🏫 Balcão de Atendimento Virtual")
st.write("Agende um horário para esclarecer as suas dúvidas através do Google Meet. Cada sessão tem a duração de 30 minutos.")

# Navegação lateral discreta entre as visões do sistema
menu = st.sidebar.radio("Navegar por:", ["Área do Utilizador (Agendamento)", "Painel do Administrador"])

# --- VISÃO 1: ÁREA DO UTILIZADOR ---
if menu == "Área do Utilizador (Agendamento)":
    
    # --- FLUXO DE CONFIRMAÇÃO PERSISTENTE ---
    if "sucesso_agendamento" in st.session_state:
        detalhes = st.session_state["sucesso_agendamento"]
        
        # Se o link for do tipo "fail-vrt", mostra um aviso legível com o erro real retornado pelo Google
        if "fail-vrt" in detalhes['link']:
            st.error("⚠️ **O agendamento foi guardado localmente na base de dados, mas não pôde ser sincronizado com o Google Agenda.**")
            if "ultimo_erro_google" in st.session_state:
                st.markdown("### 🔍 Detalhes Técnicos do Erro (Exibição Completa Sem Filtro HTML):")
                # Exibe o log de erro real como código de texto puro, impedindo que o navegador o oculte
                st.code(st.session_state["ultimo_erro_google"], language="text")
                st.info("Utilize as informações apresentadas acima para verificar as permissões de partilha ou configurações de rede.")
        else:
            st.success("🎉 Agendamento realizado com sucesso!")
            st.balloons()
        
        st.subheader("📋 Detalhes do seu Atendimento")
        st.info(f"**Importante:** Um convite oficial do Google Agenda contendo o link do Meet foi enviado para o e-mail **{detalhes['email']}**.")
        
        st.markdown(f"**Data Selecionada:** {detalhes['data']}")
        st.markdown(f"**Horário Reservado:** {detalhes['horario']}")
        st.markdown(f"**Nome do Solicitante:** {detalhes['nome']}")
        
        st.code(f"Link da sua sala virtual: {detalhes['link']}", language="text")
        
        # Só exibe o link direto do Meet se não for um link de falha
        if "fail-vrt" not in detalhes['link']:
            st.markdown(f"### [👉 Clique aqui para entrar direto no Google Meet]({detalhes['link']})")
        
        if st.button("Agendar outro Horário", type="primary", use_container_width=True):
            del st.session_state["sucesso_agendamento"]
            st.rerun()
            
    else:
        st.header("📅 Selecione uma Data e Horário")
        
        # Limita o calendário do Streamlit estritamente dentro da vigência configurada
        data_minima = datetime.date(2026, 5, 21)
        data_maxima = datetime.date(2026, 5, 29)  # Trava de vigência final ajustada para 29/05/2026
        
        # Seletor de data formatado no padrão brasileiro/português DD/MM/AAAA
        data_selecionada = st.date_input(
            "Selecione o dia do atendimento:",
            value=data_minima,
            min_value=data_minima,
            max_value=data_maxima,
            format="DD/MM/YYYY"
        )
        
        data_str = data_selecionada.strftime("%Y-%m-%d")
        
        # Valida se o utilizador escolheu um fim de semana diretamente no componente
        if data_selecionada.weekday() >= 5:
            st.warning("O balcão virtual opera apenas em dias úteis (Segunda a Sexta). Por favor, altere a data selecionada acima.")
        else:
            slots = listar_slots_por_data(data_str)
            
            # Ajuste dinâmico do texto informativo do dia
            st.subheader(f"Horários disponíveis em {data_selecionada.strftime('%d/%m/%Y')}:")
            
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
            
            # Se um horário foi clicado, abre o formulário de registo logo abaixo
            if "id_selecionado" in st.session_state:
                st.write("---")
                st.subheader(f"Confirmar Agendamento para às {st.session_state['horario_texto']}")
                
                with st.form(key="form_agendamento", clear_on_submit=True):
                    nome = st.text_input("Seu Nome Completo *")
                    email = st.text_input("Seu E-mail * (O link do Google Meet será enviado para cá)")
                    duvida = st.text_area("Descreva de forma breve a sua dúvida ou assunto *")
                    
                    enviar = st.form_submit_button("Confirmar Horário de Atendimento")
                    
                    if enviar:
                        if not nome or not email or not duvida:
                            st.error("Por favor, preencha todos os campos obrigatórios marcados com (*).")
                        elif "@" not in email:
                            st.error("Insira um endereço de e-mail válido para receber o convite.")
                        else:
                            with st.spinner("A estabelecer ligação com o Google Agenda e a gerar a sala de Meet..."):
                                link_meet = realizar_agendamento(
                                    st.session_state["id_selecionado"], 
                                    nome, 
                                    email, 
                                    duvida
                                )
                                
                            if link_meet:
                                # Guarda de forma persistente as informações da sessão antes do Rerun
                                st.session_state["sucesso_agendamento"] = {
                                    "nome": nome,
                                    "email": email,
                                    "link": link_meet,
                                    "data": data_selecionada.strftime('%d/%m/%Y'),
                                    "horario": st.session_state['horario_texto']
                                }
                                # Limpa os estados de seleção ativa para evitar loops de envio
                                del st.session_state["id_selecionado"]
                                if "horario_texto" in st.session_state:
                                    del st.session_state["horario_texto"]
                                st.rerun()
                            else:
                                st.error("Este horário acabou de ser reservado por outro utilizador. Escolha outro slot.")

# --- VISÃO 2: PAINEL DO ADMINISTRADOR ---
elif menu == "Painel do Administrador":
    st.header("📊 Painel de Controle - Gerenciamento de Atendimentos")
    st.write(f"Perfil de monitorização ativo: **{CALENDAR_ID}**")
    
    # --- VISUALIZADOR DE ERROS DE CONEXÃO DO GOOGLE ---
    if "erro_autenticacao" in st.session_state:
        st.error(f"❌ **Falha na Ligação Google (Nuvem):**")
        st.code(st.session_state['erro_autenticacao'], language="text")
    if "ultimo_erro_google" in st.session_state:
        st.error(f"❌ **Erro no Registo de Eventos da API:**")
        st.code(st.session_state['ultimo_erro_google'], language="text")
    
    agendamentos = obter_agendamentos_completos()
    
    if not agendamentos:
        st.info("Nenhum atendimento foi reservado por utilizadores até o momento.")
    else:
        st.subheader("Lista Cronológica de Atendimentos Marcados")
        
        # Converte a matriz de dados num DataFrame do Pandas para exibição nativa
        df = pd.DataFrame(agendamentos, columns=[
            "Data", "Início", "Fim", "Nome do Utilizador", "E-mail do Utilizador", "Dúvida / Assunto", "Link do Google Meet"
        ])
        
        # Tratamento de visualização de data para o formato nacional
        df["Data"] = pd.to_datetime(df["Data"]).dt.strftime("%d/%m/%Y")
        
        # Exibe a tabela interativa enriquecida com opções de ordenação
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
        * Todos os horários listados acima já se encontram registados no seu **Google Agenda** nativo associado ao e-mail configurado.
        * As dúvidas foram injetadas diretamente na secção de descrição de cada compromisso no calendário.
        """)

    # --- ZONA DE PERIGO (RESET DE DADOS COM CONFIRMAÇÃO) ---
    st.write("---")
    st.subheader("⚙️ Zona de Perigo")
    st.caption("Ações de manutenção do sistema de base de dados.")

    # Inicializa o estado de confirmação da limpeza
    if "confirmar_limpeza" not in st.session_state:
        st.session_state["confirmar_limpeza"] = False

    if not st.session_state["confirmar_limpeza"]:
        # Botão primário para iniciar a limpeza
        if st.button("🔴 Limpar Todos os Agendamentos de Teste", use_container_width=True):
            st.session_state["confirmar_limpeza"] = True
            st.rerun()
    else:
        # Seção de confirmação estrita de segurança contra cliques acidentais
        st.warning("⚠️ **Tem a certeza de que deseja prosseguir com esta ação?** Todos os agendamentos salvos serão eliminados permanentemente, a tabela antiga será recriada e os slots vespertinos corretos serão redefinidos!")
        
        col_sim, col_nao = st.columns(2)
        with col_sim:
            if st.button("✅ Sim, limpar permanentemente", type="primary", use_container_width=True):
                limpar_banco()
                st.success("💥 Base de dados recriada com sucesso! Todos os novos horários vespertinos já estão disponíveis.")
                st.session_state["confirmar_limpeza"] = False
                st.rerun()
        with col_nao:
            if st.button("❌ Cancelar", use_container_width=True):
                st.session_state["confirmar_limpeza"] = False
                st.rerun()
