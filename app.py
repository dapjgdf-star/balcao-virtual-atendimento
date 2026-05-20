import streamlit as st
import datetime
import pandas as pd
import sqlite3
import os
import json
import uuid
from datetime import timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURAÇÕES GERAIS ---
DB_NAME = "balcao_virtual.db"
CALENDAR_ID = "dapj.gdf@gmail.com"
GOOGLE_CREDENTIALS_FILE = "credentials.json"

# ==========================================
# SEÇÃO 1: FUNÇÕES DE BACKEND E BASE DE DADOS
# ==========================================

def obter_servico_google():
    """Autentica na API do Google Calendar de forma híbrida."""
    scopes = ['https://www.googleapis.com/auth/calendar']
    info = None
    
    try:
        if "private_key" in st.secrets:
            info = dict(st.secrets)
        elif "gcp_service_account" in st.secrets:
            info = dict(st.secrets["gcp_service_account"])
        elif "google_credentials_json" in st.secrets:
            raw_json = st.secrets["google_credentials_json"]
            if isinstance(raw_json, dict):
                info = raw_json
            else:
                info = json.loads(raw_json, strict=False)
        
        if info:
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
                
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=scopes
            )
            if "erro_autenticacao" in st.session_state:
                del st.session_state["erro_autenticacao"]
            return build('calendar', 'v3', credentials=creds)
        else:
            st.session_state["erro_autenticacao"] = "Nenhuma credencial do Google encontrada."
    except Exception as e:
        st.session_state["erro_autenticacao"] = f"Erro ao decodificar chaves: {e}"

    if os.path.exists(GOOGLE_CREDENTIALS_FILE):
        try:
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=scopes
            )
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            st.session_state["erro_autenticacao_local"] = f"Erro no ficheiro local: {e}"
        
    return None

def inicializar_banco():
    """Cria a base de dados e realiza migração automática caso necessário."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Cria a tabela caso não exista (já com a nova estrutura ideal)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            horario_inicio TEXT NOT NULL,
            horario_fim TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Disponivel',
            nome_usuario TEXT,
            email_usuario TEXT,
            telefone_usuario TEXT,
            duvida TEXT,
            meet_link TEXT
        )
    ''')
    conn.commit()
    
    # --- MIGRAÇÃO AUTOMÁTICA ---
    # Verifica dinamicamente as colunas existentes na tabela slots
    cursor.execute("PRAGMA table_info(slots)")
    colunas = [coluna[1] for coluna in cursor.fetchall()]
    
    # Se a coluna 'telefone_usuario' não existir (base antiga), adiciona-a agora sem quebrar nada
    if "telefone_usuario" not in colunas:
        cursor.execute("ALTER TABLE slots ADD COLUMN telefone_usuario TEXT")
        conn.commit()
    # ---------------------------
    
    cursor.execute("SELECT COUNT(*) FROM slots")
    if cursor.fetchone()[0] == 0:
        gerar_carga_horarios_fixos(cursor)
        conn.commit()
        
    conn.close()

def gerar_carga_horarios_fixos(cursor):
    """Gera os horários fixos para o período definido."""
    data_inicio = datetime.date(2026, 5, 21)
    data_fim = datetime.date(2026, 5, 29)
    
    slots_horarios = [
        ("14:30", "15:00"), ("15:00", "15:30"),
        ("15:30", "16:00"), ("16:00", "16:30"),
        ("16:30", "17:00"), ("17:00", "17:30")
    ]
    
    data_atual = data_inicio
    while data_atual <= data_fim:
        if data_atual.weekday() < 5: 
            data_str = data_atual.strftime("%Y-%m-%d")
            for inicio, fim in slots_horarios:
                cursor.execute('''
                    INSERT INTO slots (data, horario_inicio, horario_fim, status)
                    VALUES (?, ?, ?, 'Disponivel')
                ''', (data_str, inicio, fim))
        data_atual += timedelta(days=1)

def criar_evento_google_meet(data, hora_inicio, hora_fim, nome, email, telefone, duvida):
    """Cria o evento na agenda SEM convidar utilizadores para evitar erro 403."""
    service = obter_servico_google()
    
    if not service:
        return f"https://meet.google.com/mock-vrt-{data.replace('-', '')}"
        
    start_time = f"{data}T{hora_inicio}:00-03:00"
    end_time = f"{data}T{hora_fim}:00-03:00"
    
    unique_request_id = f"req-{data}-{hora_inicio.replace(':', '')}-{str(uuid.uuid4())[:8]}"
    
    # Adicionando todos os dados de contato diretamente na descrição do evento na sua agenda
    descricao_completa = f"📞 Telefone/WhatsApp: {telefone}\n✉️ E-mail: {email}\n\n📝 Dúvida/Assunto registado pelo utilizador:\n{duvida}"
    
    event_body = {
        'summary': f'Atendimento Virtual: {nome}',
        'description': descricao_completa,
        'start': {
            'dateTime': start_time,
            'timeZone': 'America/Sao_Paulo',
        },
        'end': {
            'dateTime': end_time,
            'timeZone': 'America/Sao_Paulo',
        },
        # REMOVIDO: 'attendees': [{'email': email}], -> Isso causava o Erro 403 em contas gratuitas
        'conferenceData': {
            'createRequest': {
                'requestId': unique_request_id,
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        },
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},
                {'method': 'popup', 'minutes': 15},
            ],
        },
    }

    try:
        # REMOVIDO: sendUpdates='all' -> Não podemos disparar emails automáticos
        event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event_body,
            conferenceDataVersion=1
        ).execute()
        
        meet_link = event.get('conferenceData', {}).get('entryPoints', [{}])[0].get('uri', '')
        if "ultimo_erro_google" in st.session_state:
            del st.session_state["ultimo_erro_google"]
        return meet_link
        
    except HttpError as e:
        try:
            error_details = json.loads(e.content.decode('utf-8'))
            msg_erro = error_details.get('error', {}).get('message', str(e))
        except:
            msg_erro = str(e)
        st.session_state["ultimo_erro_google"] = f"Falha na API do Calendário Google: {msg_erro}"
        return f"https://meet.google.com/fail-vrt-{data.replace('-', '')}"
    except Exception as e:
        st.session_state["ultimo_erro_google"] = f"Falha inesperada no registo do evento: {e}"
        return f"https://meet.google.com/fail-vrt-{data.replace('-', '')}"

def listar_slots_por_data(data_str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, horario_inicio, horario_fim, status FROM slots WHERE data = ?", (data_str,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def obter_agendamentos_completos():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT data, horario_inicio, horario_fim, nome_usuario, email_usuario, telefone_usuario, duvida, meet_link 
        FROM slots 
        WHERE status = 'Ocupado'
        ORDER BY data ASC, horario_inicio ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def realizar_agendamento(slot_id, nome, email, telefone, duvida):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT data, horario_inicio, horario_fim FROM slots WHERE id = ?", (slot_id,))
    slot = cursor.fetchone()
    
    if not slot:
        conn.close()
        return None
        
    data, hora_inicio, hora_fim = slot
    
    meet_link = criar_evento_google_meet(data, hora_inicio, hora_fim, nome, email, telefone, duvida)
    
    cursor.execute('''
        UPDATE slots
        SET status = 'Ocupado', nome_usuario = ?, email_usuario = ?, telefone_usuario = ?, duvida = ?, meet_link = ?
        WHERE id = ? AND status = 'Disponivel'
    ''', (nome, email, telefone, duvida, meet_link, slot_id))
    
    success = conn.total_changes > 0
    conn.commit()
    conn.close()
    
    return meet_link if success else None

def limpar_banco():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS slots")
    conn.commit()
    conn.close()
    inicializar_banco()

def gerar_texto_cartao(detalhes):
    """Gera o conteúdo em texto plano para o ficheiro TXT."""
    texto =  "=========================================\n"
    texto += "      🏫 BALCÃO VIRTUAL DE ATENDIMENTO\n"
    texto += "        CARTÃO DE AGENDAMENTO OFICIAL\n"
    texto += "=========================================\n\n"
    texto += f"Olá, {detalhes['nome']}!\n\n"
    texto += "O seu horário foi reservado com sucesso.\n"
    texto += "Aqui estão os detalhes do seu atendimento:\n\n"
    texto += f"📅 Data: {detalhes['data']}\n"
    texto += f"⏰ Horário: {detalhes['horario']}\n"
    texto += f"📱 Telefone registado: {detalhes['telefone']}\n"
    texto += f"📝 Assunto: {detalhes['duvida']}\n\n"
    texto += "🔗 LINK DA SALA VIRTUAL (GOOGLE MEET):\n"
    texto += f"{detalhes['link']}\n\n"
    texto += "Guarde este documento. No dia e horário\n"
    texto += "marcados, basta clicar ou copiar o link\n"
    texto += "acima no seu navegador para entrar na sala.\n"
    texto += "=========================================\n"
    return texto


# ==========================================
# SEÇÃO 2: INTERFACE DO UTILIZADOR (FRONTEND)
# ==========================================

st.set_page_config(page_title="Balcão Virtual de Atendimento", layout="wide", page_icon="🏫")

inicializar_banco()

st.title("🏫 Balcão de Atendimento Virtual")
st.write("Agende um horário para esclarecer as suas dúvidas através do Google Meet. Cada sessão tem a duração de 30 minutos.")

menu = st.sidebar.radio("Navegar por:", ["Área do Utilizador (Agendamento)", "Painel do Administrador"])

# --- VISÃO 1: ÁREA DO UTILIZADOR ---
if menu == "Área do Utilizador (Agendamento)":
    
    if "sucesso_agendamento" in st.session_state:
        detalhes = st.session_state["sucesso_agendamento"]
        
        if "fail-vrt" in detalhes['link']:
            st.error("⚠️ **O agendamento foi guardado localmente na base de dados, mas não pôde ser sincronizado com o Google Agenda.**")
            if "ultimo_erro_google" in st.session_state:
                st.markdown("### 🔍 Detalhes Técnicos do Erro:")
                st.code(st.session_state["ultimo_erro_google"], language="text")
                st.info("O suporte técnico deve verificar as chaves no Streamlit Cloud.")
        else:
            st.success("🎉 Agendamento realizado com sucesso e link do Meet gerado!")
            st.balloons()
        
        st.subheader("📋 Detalhes do seu Atendimento")
        st.info("Guarde as informações abaixo. Para sua segurança e privacidade, descarregue o seu cartão de agendamento através do botão ao final da página.")
        
        st.markdown(f"**Data Selecionada:** {detalhes['data']}")
        st.markdown(f"**Horário Reservado:** {detalhes['horario']}")
        st.markdown(f"**Nome do Solicitante:** {detalhes['nome']}")
        st.markdown(f"**Telefone / WhatsApp:** {detalhes['telefone']}")
        
        st.code(f"Link da sua sala virtual: {detalhes['link']}", language="text")
        
        if "fail-vrt" not in detalhes['link']:
            st.markdown(f"### [👉 Clique aqui para testar o acesso à sala do Google Meet]({detalhes['link']})")
        
        st.write("---")
        
        # Gera o botão de download com o texto do cartão
        conteudo_cartao = gerar_texto_cartao(detalhes)
        nome_ficheiro = f"Cartao_Agendamento_{detalhes['data'].replace('/', '-')}.txt"
        
        st.download_button(
            label="📥 Descarregar Cartão de Agendamento (Guardar)",
            data=conteudo_cartao,
            file_name=nome_ficheiro,
            mime="text/plain",
            type="primary",
            use_container_width=True
        )

        st.write(" ") # Espaçamento
        
        if st.button("Agendar outro Horário", use_container_width=True):
            del st.session_state["sucesso_agendamento"]
            st.rerun()
            
    else:
        st.header("📅 Selecione uma Data e Horário")
        
        data_minima = datetime.date(2026, 5, 21)
        data_maxima = datetime.date(2026, 5, 29)
        
        data_selecionada = st.date_input(
            "Selecione o dia do atendimento:",
            value=data_minima,
            min_value=data_minima,
            max_value=data_maxima,
            format="DD/MM/YYYY"
        )
        
        data_str = data_selecionada.strftime("%Y-%m-%d")
        
        if data_selecionada.weekday() >= 5:
            st.warning("O balcão virtual opera apenas em dias úteis (Segunda a Sexta). Por favor, altere a data selecionada acima.")
        else:
            slots = listar_slots_por_data(data_str)
            
            st.subheader(f"Horários disponíveis em {data_selecionada.strftime('%d/%m/%Y')}:")
            
            cols = st.columns(4)
            
            for idx, (slot_id, inicio, fim, status) in enumerate(slots):
                col = cols[idx % 4]
                if status == "Disponivel":
                    if col.button(f"🟢 {inicio} - {fim}", key=f"btn_{slot_id}", use_container_width=True):
                        st.session_state["id_selecionado"] = slot_id
                        st.session_state["horario_texto"] = f"{inicio} às {fim}"
                else:
                    col.button(f"🔴 {inicio} - {fim} (Ocupado)", key=f"btn_{slot_id}", disabled=True, use_container_width=True)
            
            if "id_selecionado" in st.session_state:
                st.write("---")
                st.subheader(f"Confirmar Agendamento para às {st.session_state['horario_texto']}")
                
                with st.form(key="form_agendamento", clear_on_submit=True):
                    nome = st.text_input("Seu Nome Completo *")
                    email = st.text_input("Seu E-mail *")
                    telefone = st.text_input("Seu Telefone ou WhatsApp * (Ex: 61 99999-9999)")
                    duvida = st.text_area("Descreva de forma breve a sua dúvida ou assunto *")
                    
                    enviar = st.form_submit_button("Confirmar Horário de Atendimento")
                    
                    if enviar:
                        if not nome or not email or not telefone or not duvida:
                            st.error("Por favor, preencha todos os campos obrigatórios marcados com (*).")
                        elif "@" not in email:
                            st.error("Insira um endereço de e-mail válido.")
                        else:
                            with st.spinner("A reservar horário e a gerar sala no Google Meet..."):
                                link_meet = realizar_agendamento(
                                    st.session_state["id_selecionado"], 
                                    nome, 
                                    email, 
                                    telefone,
                                    duvida
                                )
                                
                            if link_meet:
                                st.session_state["sucesso_agendamento"] = {
                                    "nome": nome,
                                    "email": email,
                                    "telefone": telefone,
                                    "duvida": duvida,
                                    "link": link_meet,
                                    "data": data_selecionada.strftime('%d/%m/%Y'),
                                    "horario": st.session_state['horario_texto']
                                }
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
    
    if "erro_autenticacao" in st.session_state:
        st.error(f"❌ **Falha na Ligação Google (Nuvem):** {st.session_state['erro_autenticacao']}")
    if "ultimo_erro_google" in st.session_state:
        st.error(f"❌ **Erro no Registo de Eventos da API:** {st.session_state['ultimo_erro_google']}")
    
    agendamentos = obter_agendamentos_completos()
    
    if not agendamentos:
        st.info("Nenhum atendimento foi reservado por utilizadores até ao momento.")
    else:
        st.subheader("Lista Cronológica de Atendimentos Marcados")
        
        # Colunas atualizadas para incluir o Telefone
        df = pd.DataFrame(agendamentos, columns=[
            "Data", "Início", "Fim", "Nome do Utilizador", "E-mail", "Telefone", "Dúvida / Assunto", "Link Google Meet"
        ])
        
        df["Data"] = pd.to_datetime(df["Data"]).dt.strftime("%d/%m/%Y")
        
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Exportar Lista para CSV",
            data=csv,
            file_name=f"atendimentos_balcao_virtual_{datetime.date.today()}.csv",
            mime="text/csv"
        )
        
        st.write("---")
        st.subheader("💡 Dica de Fluxo de Trabalho")
        st.markdown("""
        * O bloqueio automático de emails do Google para contas gratuitas foi contornado.
        * Todos os eventos estão no seu Calendário, com os links do Meet perfeitamente gerados.
        * Os dados de contato (E-mail e Telefone/WhatsApp) estão visíveis no próprio evento da Agenda!
        """)

    st.write("---")
    st.subheader("⚙️ Zona de Perigo")
    st.caption("Ações de manutenção do sistema de base de dados.")

    if "confirmar_limpeza" not in st.session_state:
        st.session_state["confirmar_limpeza"] = False

    if not st.session_state["confirmar_limpeza"]:
        if st.button("🔴 Limpar Todos os Agendamentos de Teste", use_container_width=True):
            st.session_state["confirmar_limpeza"] = True
            st.rerun()
    else:
        st.warning("⚠️ **Tem a certeza de que deseja prosseguir com esta ação?** Todos os agendamentos salvos serão eliminados permanentemente e a estrutura será atualizada com a nova coluna de Telefone.")
        
        col_sim, col_nao = st.columns(2)
        with col_sim:
            if st.button("✅ Sim, limpar e atualizar a base", type="primary", use_container_width=True):
                limpar_banco()
                st.success("💥 Base de dados recriada com sucesso! A nova estrutura já está pronta a ser utilizada.")
                st.session_state["confirmar_limpeza"] = False
                st.rerun()
        with col_nao:
            if st.button("❌ Cancelar", use_container_width=True):
                st.session_state["confirmar_limpeza"] = False
                st.rerun()
