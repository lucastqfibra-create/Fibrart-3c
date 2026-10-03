import os
import json
import base64
import tempfile
import time
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
    params = {
        "api_token": TOKEN_3C_PLUS,
        "start_date": f"{data_alvo} 00:00:00",
        "end_date": f"{data_alvo} 23:59:59"
    }
    
    print(f"Conectando a {url} para a data {data_alvo}...")
    response = requests.get(url, params=params, headers=headers, timeout=60)
    
    if not response.ok:
        params_simples = {"api_token": TOKEN_3C_PLUS, "start_date": data_alvo, "end_date": data_alvo}
        response = requests.get(url, params=params_simples, headers=headers, timeout=60)
        response.raise_for_status()

    dados = response.json()
    ligacoes = dados.get("data", dados) if isinstance(dados, dict) else dados
    print(f"Sucesso! Total de chamadas retornadas pela API da Fibrart: {len(ligacoes)}")
    return ligacoes

def analisar_audio_com_gemini(audio_base64):
    """Envia o áudio para o Gemini testando modelos estáveis com fallback automático."""
    modelos = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-3.8-flash"]
    payload = {
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
    
    for modelo in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_API_KEY}"
        print(f"Tentando análise com o modelo estável: {modelo}...")
        try:
            resp = requests.post(url, json=payload, timeout=90)
            if resp.status_code == 503:
                print(f"Modelo {modelo} com pico de demanda (503). Alternando para o próximo...")
                time.sleep(2)
                continue
            resp.raise_for_status()
            dados = resp.json()
            return dados["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"Aviso no modelo {modelo}: {e}")
            continue
            
    raise Exception("Todos os modelos testados retornaram indisponibilidade temporária.")

def processar_e_enviar():
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Iniciando consolidação do dia {data_alvo}...")

    ligacoes = buscar_ligacoes_3c(data_alvo)
    
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
            # 1. Download do áudio via subdomínio da Fibrart
            audio_url = raw_recording_url.replace("app.3c.plus", "fibrartindustria.3c.plus")
            if "api_token" not in audio_url:
                audio_url = f"{audio_url}?api_token={TOKEN_3C_PLUS}"
                
            headers_audio = {
                "Authorization": f"Bearer {TOKEN_3C_PLUS}",
                "User-Agent": "Mozilla/5.0 FibrartAutomation/1.0"
            }
            
            resp_audio = requests.get(audio_url, headers=headers_audio, timeout=60)
            if resp_audio.status_code == 404:
                print(f"Gravação {call_id} não encontrada na 3C Plus (HTTP 404). Pulando...")
                continue
            resp_audio.raise_for_status()

            # 2. Converte para base64 e analisa com o Gemini
            audio_base64 = base64.b64encode(resp_audio.content).decode("utf-8")
            texto_analise = analisar_audio_com_gemini(audio_base64)
            
            texto_limpo = texto_analise.strip().replace("```json", "").replace("```", "")
            try:
                analise_json = json.loads(texto_limpo)
            except Exception:
                analise_json = {"analise_texto": texto_analise}

            # 3. Pacote para entrega no Google Docs
            registro = {
                "id": call_id,
                "data_hora": chamada.get("call_date", data_alvo),
                "agente": agente,
                "numero": numero,
                "qualificacao": qualificacao,
                "analise": analise_json
            }

            # 4. Entrega no Google Docs
            print("Entregando análise no Google Docs...")
            resp_doc = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro, timeout=30)
            print(f"Sucesso! Status no Google Docs: {resp_doc.status_code}")

        except Exception as e:
            print(f"Erro ao processar chamada {call_id}: {e}")

    print("\nConsolidação diária finalizada com sucesso!")

if __name__ == "__main__":
    processar_e_enviar()
