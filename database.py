import sqlite3
import datetime
from datetime import timedelta
import os
# Bibliotecas do Google API Client
from google.oauth2 import service_account
from googleapiclient.discovery import build

DB_NAME = "balcao_virtual.db"
CALENDAR_ID = "dapj.gdf@gmail.com"

# Arquivo de credenciais JSON fornecido pelo Google Cloud Console
# Deve ser configurado com escopo: https://www.googleapis.com/auth/calendar
GOOGLE_CREDENTIALS_FILE = "credentials.json"

def obter_servico_google():
    """Autentica na API do Google Calendar usando Service Account ou OAuth."""
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        return None
    
    scopes = ['https://www.googleapis.com/auth/calendar']
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE, scopes=scopes
    )
    # Para agir em nome de dapj.gdf@gmail.com usando Service Account com Domain-Wide Delegation:
    # creds = creds.with_subject(CALENDAR_ID)
    
    return build('calendar', 'v3', credentials=creds)

def inicializar_banco():
    """Cria as tabelas e gera a carga inicial de slots se o banco estiver vazio."""
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
    
    # Verificar se já existem registros populados
    cursor.execute("SELECT COUNT(*) FROM slots")
    if cursor.fetchone()[0] == 0:
        gerar_carga_horarios_fixos(cursor)
        conn.commit()
        
    conn.close()

def gerar_carga_horarios_fixos(cursor):
    """Gera slots matutinos de 30 min entre 21/05/2026 e 29/05/2026 em dias úteis."""
    data_inicio = datetime.date(2026, 5, 21)
    data_fim = datetime.date(2026, 6, 29)
    
    # Horários fixos do turno matutino (8 slots de 30 min)
    slots_horarios = [
        ("08:00", "08:30"), ("08:30", "09:00"),
        ("09:00", "09:30"), ("09:30", "10:00"),
        ("10:00", "10:30"), ("10:30", "11:00"),
        ("11:00", "11:30"), ("11:30", "12:00")
    ]
    
    data_atual = data_inicio
    while data_atual <= data_fim:
        # 0 = Segunda, 1 = Terça, ..., 4 = Sexta, 5 = Sábado, 6 = Domingo
        if data_atual.weekday() < 5:  # Apenas dias úteis (Segunda a Sexta)
            data_str = data_atual.strftime("%Y-%m-%d")
            for inicio, fim in slots_horarios:
                cursor.execute('''
                    INSERT INTO slots (data, horario_inicio, horario_fim, status)
                    VALUES (?, ?, ?, 'Disponivel')
                ''', (data_str, inicio, fim))
        data_atual += timedelta(days=1)

def criar_evento_google_meet(data, hora_inicio, hora_fim, nome, email, duvida):
    """Cria o evento no Google Calendar e solicita a geração do link do Meet."""
    service = obter_servico_google()
    
    # Se não houver arquivo de credenciais configurado, gera um link simulado para desenvolvimento
    if not service:
        return f"https://meet.google.com/mock-vrt-{data.replace('-', '')}"
        
    start_time = f"{data}T{hora_inicio}:00"
    end_time = f"{data}T{hora_fim}:00"
    
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
            sendUpdates='all' # Dispara e-mail de convite nativo do Google com o link do Meet ao usuário
        ).execute()
        
        # Extrai o link do Meet gerado dinamicamente
        meet_link = event.get('conferenceData', {}).get('entryPoints', [{}])[0].get('uri', '')
        return meet_link
    except Exception as e:
        print(f"Erro ao conectar com API do Google Calendar: {e}")
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
    
    # Recuperar dados do slot para criar o evento no Google Calendar
    cursor.execute("SELECT data, horario_inicio, horario_fim FROM slots WHERE id = ?", (slot_id,))
    slot = cursor.fetchone()
    
    if not slot:
        conn.close()
        return None
        
    data, hora_inicio, hora_fim = slot
    
    # Invoca API do Google para gerar o link único
    meet_link = criar_evento_google_meet(data, hora_inicio, hora_fim, nome, email, duvida)
    
    # Salva o agendamento localmente mudando o status para Ocupado
    cursor.execute('''
        UPDATE slots
        SET status = 'Ocupado', nome_usuario = ?, email_usuario = ?, duvida = ?, meet_link = ?
        WHERE id = ? AND status = 'Disponivel'
    ''', (nome, email, duvida, meet_link, slot_id))
    
    success = conn.total_changes > 0
    conn.commit()
    conn.close()
    
    return meet_link if success else None