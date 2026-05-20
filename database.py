import sqlite3
import datetime
from datetime import timedelta
import os
import json
import streamlit as st
# Bibliotecas oficiais do Google API Client
from google.oauth2 import service_account
from googleapiclient.discovery import build

DB_NAME = "balcao_virtual.db"
CALENDAR_ID = "dapj.gdf@gmail.com"
GOOGLE_CREDENTIALS_FILE = "credentials.json"

def obter_servico_google():
    """
    Autentica na API do Google Calendar de forma híbrida.
    Tenta primeiro ler a partir dos Secrets do Streamlit Cloud (Nuvem).
    Caso não existam, procura pelo ficheiro local de credenciais.
    """
    scopes = ['https://www.googleapis.com/auth/calendar']
    
    # Caminho 1: Verificação de credenciais nos Secrets do Streamlit (Nuvem)
    if "google_credentials_json" in st.secrets:
        try:
            # Converte a string de texto JSON dos Secrets para um dicionário Python
            info = json.loads(st.secrets["google_credentials_json"])
            
            # CORREÇÃO CRÍTICA: Corrige as quebras de linha (\n) duplicadas pelo TOML do Streamlit Cloud
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
                
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=scopes
            )
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            # Reporta de forma discreta o erro nos logs internos da barra lateral para depuração
            st.sidebar.error(f"⚠️ Erro de Autenticação (Secrets): {e}")
            pass

    # Caminho 2: Procura pelo ficheiro físico local no computador (Desenvolvimento)
    if os.path.exists(GOOGLE_CREDENTIALS_FILE):
        try:
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=scopes
            )
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            st.sidebar.error(f"⚠️ Erro de Autenticação (Ficheiro Local): {e}")
            pass
        
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
        
    start_time = f"{data}T{hora_inicio}:00"
    end_time = f"{data}T{hora_fim}:00"
    
    event_body = {
        'summary': f'Atendimento Virtual: {nome}',
        'description': f'Dúvida/Assunto registado pelo utilizador:\n{duvida}',
        'start': {
            'dateTime': start_time,
            'timeZone': 'America/Sao_Paulo',
        },
        'end': {
            'dateTime': end_time,
            'timeZone': 'America/Sao_Paulo',
        },
        'attendees': [
            {'email': email},
            {'email': CALENDAR_ID}
        ],
        'conferenceData': {
            'createRequest': {
                'requestId': f"req-{data}-{hora_inicio.replace(':', '')}",
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
        return meet_link
    except Exception as e:
        st.sidebar.error(f"❌ Erro na API do Calendário: {e}")
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
    Reseta todos os agendamentos marcados de volta para 'Disponivel' 
    e limpa as informações de utilizadores, dúvidas e links das salas.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE slots
        SET status = 'Disponivel',
            nome_usuario = NULL,
            email_usuario = NULL,
            duvida = NULL,
            meet_link = NULL
    ''')
    conn.commit()
    conn.close()
