import sqlite3
import datetime
from datetime import timedelta
import os
import json
import uuid  # Adicionado para gerar IDs de requisições de Meet únicos e seguros
import streamlit as st
# Bibliotecas oficiais do Google API Client
from google.oauth2 import service_account
from googleapiclient.discovery import build

DB_NAME = "balcao_virtual.db"
CALENDAR_ID = "dapj.gdf@gmail.com"
GOOGLE_CREDENTIALS_FILE = "credentials.json"

def obter_servico_google():
    """
    Autentica na API do Google Calendar de forma híbrida e ultra-robusta.
    Tenta decodificar a chave a partir do Streamlit Cloud em múltiplos formatos.
    """
    scopes = ['https://www.googleapis.com/auth/calendar']
    info = None
    
    # Caminho 1: Verificação de credenciais nos Secrets do Streamlit (Nuvem)
    try:
        # Caso A: Colado diretamente como chaves TOML raíz
        if "private_key" in st.secrets:
            info = dict(st.secrets)
        # Caso B: Colado sob a seção [gcp_service_account]
        elif "gcp_service_account" in st.secrets:
            info = dict(st.secrets["gcp_service_account"])
        # Caso C: Colado sob a variável google_credentials_json como string JSON
        elif "google_credentials_json" in st.secrets:
            raw_json = st.secrets["google_credentials_json"]
            if isinstance(raw_json, dict):
                info = raw_json
            else:
                # strict=False ignora quebras de linha literais introduzidas pelo TOML
                info = json.loads(raw_json, strict=False)
        
        if info:
            # Corrige as quebras de linha (\n) duplicadas ou mal formatadas
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
                
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=scopes
            )
            # Remove mensagem de erro anterior se autenticou com sucesso
            if "erro_autenticacao" in st.session_state:
                del st.session_state["erro_autenticacao"]
            return build('calendar', 'v3', credentials=creds)
        else:
            st.session_state["erro_autenticacao"] = "Nenhuma credencial do Google encontrada nos Secrets do Streamlit."
    except Exception as e:
        st.session_state["erro_autenticacao"] = f"Erro ao decodificar chaves do Google Cloud: {e}"

    # Caminho 2: Procura pelo ficheiro físico local no computador (Desenvolvimento)
    if os.path.exists(GOOGLE_CREDENTIALS_FILE):
        try:
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=scopes
            )
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            st.session_state["erro_autenticacao_local"] = f"Erro no ficheiro local credentials.json: {e}"
        
    return None

def inicializar_banco():
    """Cria as tabelas e gera a carga inicial de slots se a base de dados estiver vazia."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            horario_inicio TEXT NOT NULL,
            horario_fim TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Disponivel',
            nome_usuario TEXT,
            email_usuario TEXT,
            duvida TEXT,
            meet_link TEXT
        )
    ''')
    conn.commit()
    
    # Verifica se já existem registos populados
    cursor.execute("SELECT COUNT(*) FROM slots")
    if cursor.fetchone()[0] == 0:
        gerar_carga_horarios_fixos(cursor)
        conn.commit()
        
    conn.close()

def gerar_carga_horarios_fixos(cursor):
    """
    Gera slots vespertinos de 30 min entre 21/05/2026 e 29/05/2026.
    Apenas em dias úteis (Segunda a Sexta-feira).
    """
    data_inicio = datetime.date(2026, 5, 21)
    data_fim = datetime.date(2026, 5, 29)
    
    # Horários fixos do turno vespertino (6 slots de 30 min)
    slots_horarios = [
        ("14:30", "15:00"), ("15:00", "15:30"),
        ("15:30", "16:00"), ("16:00", "16:30"),
        ("16:30", "17:00"), ("17:00", "17:30")
    ]
    
    data_atual = data_inicio
    while data_atual <= data_fim:
        # 0 = Segunda, 1 = Terça, ..., 4 = Sexta, 5 = Sábado, 6 = Domingo
        if data_atual.weekday() < 5:  # Apenas dias úteis
            data_str = data_atual.strftime("%Y-%m-%d")
            for inicio, fim in slots_horarios:
                cursor.execute('''
                    INSERT INTO slots (data, horario_inicio, horario_fim, status)
                    VALUES (?, ?, ?, 'Disponivel')
                ''', (data_str, inicio, fim))
        data_atual += timedelta(days=1)

def criar_evento_google_meet(data, hora_inicio, hora_fim, nome, email, duvida):
    """Cria o evento real no Google Calendar e solicita o link do Google Meet."""
    service = obter_servico_google()
    
    # Se não houver autenticação configurada ou ativa, gera o link de simulação
    if not service:
        return f"https://meet.google.com/mock-vrt-{data.replace('-', '')}"
        
    # CORREÇÃO CRÍTICA 1: Formatação RFC3339 estrita adicionando o offset de fuso horário (-03:00) para Brasília
    start_time = f"{data}T{hora_inicio}:00-03:00"
    end_time = f"{data}T{hora_fim}:00-03:00"
    
    # CORREÇÃO CRÍTICA 2: Gerador de ID de requisição 100% único para evitar erros de duplicidade do Meet no Google
    unique_request_id = f"req-{data}-{hora_inicio.replace(':', '')}-{str(uuid.uuid4())[:8]}"
    
    event_body = {
        'summary': f'Atendimento Virtual: {nome}',
        'description': f'Dúvida/Assunto registrado pelo usuário:\n{duvida}',
        'start': {
            'dateTime': start_time,
            'timeZone': 'America/Sao_Paulo',
        },
        'end': {
            'dateTime': end_time,
            'timeZone': 'America/Sao_Paulo',
        },
        # CORREÇÃO CRÍTICA 3: Removido o CALENDAR_ID da lista de convidados para evitar erro de auto-convite na própria agenda
        'attendees': [
            {'email': email}
        ],
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
        event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates='all' # Dispara o e-mail de convite oficial com o link do Meet ao utilizador
        ).execute()
        
        # Extrai o link do Google Meet criado dinamicamente
        meet_link = event.get('conferenceData', {}).get('entryPoints', [{}])[0].get('uri', '')
        if "ultimo_erro_google" in st.session_state:
            del st.session_state["ultimo_erro_google"]
        return meet_link
    except Exception as e:
        # Armazena o erro exato retornado pelos servidores do Google para exibição diagnóstica
        st.session_state["ultimo_erro_google"] = f"Falha na API de criação do Google Calendar: {e}"
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
        SELECT data, horario_inicio, horario_fim, nome_usuario, email_usuario, duvida, meet_link 
        FROM slots 
        WHERE status = 'Ocupado'
        ORDER BY data ASC, horario_inicio ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def realizar_agendamento(slot_id, nome, email, duvida):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Recupera os dados do slot para enviar na criação do evento
    cursor.execute("SELECT data, horario_inicio, horario_fim FROM slots WHERE id = ?", (slot_id,))
    slot = cursor.fetchone()
    
    if not slot:
        conn.close()
        return None
        
    data, hora_inicio, hora_fim = slot
    
    # Invoca a API do Google para gerar o link único real
    meet_link = criar_evento_google_meet(data, hora_inicio, hora_fim, nome, email, duvida)
    
    # Atualiza o status localmente para "Ocupado"
    cursor.execute('''
        UPDATE slots
        SET status = 'Ocupado', nome_usuario = ?, email_usuario = ?, duvida = ?, meet_link = ?
        WHERE id = ? AND status = 'Disponivel'
    ''', (nome, email, duvida, meet_link, slot_id))
    
    success = conn.total_changes > 0
    conn.commit()
    conn.close()
    
    return meet_link if success else None

def limpar_banco():
    """
    Deleta a estrutura existente e força a reinicialização limpa
    para reestruturar o banco de dados com os novos horários configurados.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS slots")
    conn.commit()
    conn.close()
    
    # Recria o banco de dados carregando os slots vespertinos
    inicializar_banco()
