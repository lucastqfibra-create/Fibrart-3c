import os
import json
import base64
import tempfile
import requests
from datetime import datetime, timedelta

# ==============================================================
# CONFIGURAÇÕES (Lidas dos Secrets do GitHub)
# ==============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TOKEN_3C_PLUS = os.getenv("TOKEN_3C_PLUS")
GOOGLE_DOCS_WEBHOOK_URL = os.getenv("GOOGLE_DOCS_WEBHOOK_URL")

BASE_URL_3C = "https://fibrartindustria.3c.plus/api/v1"

PROMPT_ANALISE = """
Você é um especialista em qualidade e conversão de telemarketing e vendas de marmofibra (tanques e pias).
Analise detalhadamente o áudio da ligação anexa e retorne em formato JSON válido com as seguintes chaves:
{
  "resumo": "Breve resumo da conversa",
  "interesse": "Alto / Médio / Baixo / Nenhum",
  "objecoes": "Principais objeções levantadas pelo cliente",
  "desempenho_atendente": "Avaliação da postura, clareza e argumentação",
  "lead_quente": true,
  "nota": 8.5,
  "justificativa_nota": "Motivo da pontuação"
}
Retorne estritamente o JSON sem blocos markdown.
"""

def buscar_ligacoes_3c(data_alvo):
    """Consulta a API oficial da Fibrart na 3C Plus para obter as ligações do dia."""
    url = f"{BASE_URL_3C}/calls"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {TOKEN_3C_PLUS}"
    }
    # Filtro com horário completo
    params = {
        "api_token": TOKEN_3C_PLUS,
        "start_date": f"{data_alvo} 00:00:00",
        "end_date": f"{data_alvo} 23:59:59"
    }
    
    print(f"Conectando a {url} para a data {data_alvo}...")
    response = requests.get(url, params=params, headers=headers, timeout=60)
    
    if not response.ok:
        # Alternativa de formato simples
        params_simples = {"api_token": TOKEN_3C_PLUS, "start_date": data_alvo, "end_date": data_alvo}
        response = requests.get(url, params=params_simples, headers=headers, timeout=60)
        response.raise_for_status()

    dados = response.json()
    ligacoes = dados.get("data", dados) if isinstance(dados, dict) else dados
    print(f"Sucesso! Total de chamadas retornadas pela API da Fibrart: {len(ligacoes)}")
    return ligacoes

def processar_e_enviar():
    # Data de ontem (D-1)
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Iniciando consolidação do dia {data_alvo}...")

    ligacoes = buscar_ligacoes_3c(data_alvo)
    
    # Filtra apenas chamadas com gravação e que tiveram tempo de conversação
    chamadas_com_audio = [
        c for c in ligacoes 
        if c.get("recording") and c.get("speaking_with_agent_time") not in [None, "", "00:00:00", "0"]
    ]
    print(f"Chamadas válidas com conversação para análise: {len(chamadas_com_audio)}")

    for chamada in chamadas_com_audio:
        call_id = chamada.get("id")
        agente = chamada.get("agent", "Desconhecido")
        numero = chamada.get("number", "Não informado")
        qualificacao = chamada.get("qualification", "Sem tabulação")
        raw_recording_url = chamada.get("recording")

        print(f"\n--- Processando Chamada {call_id} ({agente} ➔ {numero}) ---")
        
        try:
            # 1. Ajusta o domínio do áudio para fibrartindustria.3c.plus
            audio_url = raw_recording_url.replace("app.3c.plus", "fibrartindustria.3c.plus")
            if "api_token" not in audio_url:
                audio_url = f"{audio_url}?api_token={TOKEN_3C_PLUS}"
                
            headers_audio = {
                "Authorization": f"Bearer {TOKEN_3C_PLUS}",
                "User-Agent": "Mozilla/5.0 FibrartAutomation/1.0"
            }
            
            resp_audio = requests.get(audio_url, headers=headers_audio, timeout=60)
            if resp_audio.status_code == 404:
                print(f"Gravação {call_id} não encontrada no S3 da 3C Plus (HTTP 404). Pulando...")
                continue
            resp_audio.raise_for_status()

            # Converte o áudio para base64
            audio_base64 = base64.b64encode(resp_audio.content).decode("utf-8")

            # 2. Envio REST com retentativa automática em caso de pico (HTTP 503)
            print("Enviando áudio para o Gemini 3.8 Flash...")
            gemini_payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": PROMPT_ANALISE},
                            {
                                "inline_data": {
                                    "mime_type": "audio/mp3",
                                    "data": audio_base64
                                }
                            }
                        ]
                    }
                ]
            }
            
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
            
            # Tenta até 3 vezes com pausa de 3 segundos se houver pico no Google
            max_tentativas = 3
            resp_gemini = None
            for tentativa in range(1, max_tentativas + 1):
                resp_gemini = requests.post(gemini_url, json=gemini_payload, timeout=90)
                if resp_gemini.status_code == 503 and tentativa < max_tentativas:
                    print(f"Pico temporário no Google (503). Aguardando 3s para tentar novamente ({tentativa}/{max_tentativas})...")
                    import time
                    time.sleep(3)
                    continue
                break

            resp_gemini.raise_for_status()
            
            dados_gemini = resp_gemini.json()
            texto_analise = dados_gemini["candidates"][0]["content"]["parts"][0]["text"]

            # 3. Pacote para entrega no Google Docs
            registro = {
                "id": call_id,
                "data_hora": chamada.get("call_date", data_alvo),
                "agente": agente,
                "numero": numero,
                "qualificacao": qualificacao,
                "analise": analise_json
            }

            # 4. Envio direto para o Webhook do Google Docs
            print("Entregando análise no Google Docs...")
            resp_doc = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro, timeout=30)
            print(f"Sucesso! Status no Google Docs: {resp_doc.status_code}")

        except Exception as e:
            print(f"Erro ao processar chamada {call_id}: {e}")

    print("\nConsolidação diária finalizada com sucesso!")

if __name__ == "__main__":
    processar_e_enviar()
