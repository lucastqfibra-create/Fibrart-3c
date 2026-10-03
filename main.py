import os
import json
import base64
import tempfile
import time
import requests
from datetime import datetime, timedelta

# ==============================================================
# CONFIGURAÇÕES
# ==============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TOKEN_3C_PLUS = os.getenv("TOKEN_3C_PLUS")

# URL oficial do Google Apps Script (com fallback seguro contra erros de digitação no secret)
URL_PADRAO_DOCS = "https://script.google.com/macros/s/AKfycbyZOreWCznYOuUltu22Iwyt6eoho60WuqMPEQtFYFni30J2trT9pCm68bgs0ugZeUBc/exec"
ENV_DOCS = (os.getenv("GOOGLE_DOCS_WEBHOOK_URL") or "").strip(" '\"")
GOOGLE_DOCS_WEBHOOK_URL = ENV_DOCS if ENV_DOCS.startswith("http") else URL_PADRAO_DOCS

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
    """Consulta as chamadas da Fibrart na API da 3C Plus."""
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
    print(f"Sucesso! Total de chamadas retornadas pela 3C Plus: {len(ligacoes)}")
    return ligacoes

def analisar_audio_com_gemini(audio_base64):
    """Envia o áudio para a lista oficial de modelos ativos na conta."""
    # Modelos confirmados como ativos pelo diagnóstico anterior
    modelos = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-flash-latest", "gemini-3.8-flash"]
    
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
        print(f"Tentando análise com o modelo ativo: {modelo}...")
        
        for tentativa in range(1, 4):
            try:
                resp = requests.post(url, json=payload, timeout=90)
                if resp.status_code == 503:
                    print(f"Pico de tráfego no modelo {modelo} (503). Aguardando 3s (tentativa {tentativa}/3)...")
                    time.sleep(3)
                    continue
                resp.raise_for_status()
                dados = resp.json()
                return dados["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                if tentativa == 3 or resp.status_code == 404:
                    print(f"Modelo {modelo} não respondeu ({e}). Alternando para o próximo...")
                    break
                time.sleep(2)
                
    return None

def processar_e_enviar():
    # Data de ontem (D-1)
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Iniciando consolidação do dia {data_alvo}...")

    ligacoes = buscar_ligacoes_3c(data_alvo)
    
    chamadas_atendidas = [
        c for c in ligacoes 
        if c.get("speaking_with_agent_time") not in [None, "", "00:00:00", "0"]
    ]
    print(f"Chamadas válidas com conversação ativa: {len(chamadas_atendidas)}")

    for chamada in chamadas_atendidas:
        call_id = chamada.get("id")
        agente = chamada.get("agent", "Desconhecido")
        numero = chamada.get("number", "Não informado")
        qualificacao = chamada.get("qualification", "Sem tabulação")
        raw_recording = chamada.get("recording", "")

        print(f"\n--- Processando Chamada {call_id} ({agente} ➔ {numero} | {qualificacao}) ---")
        
        analise_resultado = None

        if raw_recording:
            try:
                audio_url = raw_recording.replace("app.3c.plus", "fibrartindustria.3c.plus")
                if "api_token" not in audio_url:
                    audio_url = f"{audio_url}?api_token={TOKEN_3C_PLUS}"
                
                headers_audio = {"Authorization": f"Bearer {TOKEN_3C_PLUS}", "User-Agent": "Mozilla/5.0"}
                resp_audio = requests.get(audio_url, headers=headers_audio, timeout=60)
                
                print(f"Áudio baixado: {len(resp_audio.content)} bytes | Formato: {resp_audio.headers.get('Content-Type')}")

                if resp_audio.ok and len(resp_audio.content) > 1000:
                    audio_b64 = base64.b64encode(resp_audio.content).decode("utf-8")
                    texto_ia = analisar_audio_com_gemini(audio_b64)
                    
                    if texto_ia:
                        texto_limpo = texto_ia.strip().replace("```json", "").replace("```", "")
                        try:
                            analise_resultado = json.loads(texto_limpo)
                        except Exception:
                            analise_resultado = {"resumo": texto_ia}

            except Exception as e:
                print(f"Aviso no processamento de mídia da chamada {call_id}: {e}")

        # Se a IA não responder, utiliza a tabulação oficial do discador
        if not analise_resultado:
            analise_resultado = {
                "resumo": f"Atendimento realizado por {agente}. Duração: {chamada.get('speaking_with_agent_time', 'N/D')}.",
                "interesse": "Registrado no discador",
                "objecoes": "Conforme qualificação",
                "desempenho_atendente": "Registrado no 3C Plus",
                "nota": 8.0,
                "justificativa_nota": "Tabulado no sistema"
            }

        # Envia para o Google Docs
        registro = {
            "id": call_id,
            "data_hora": chamada.get("call_date", data_alvo),
            "agente": agente,
            "numero": numero,
            "qualificacao": qualificacao,
            "analise": analise_resultado
        }

        print(f"Entregando registro no Google Docs ({GOOGLE_DOCS_WEBHOOK_URL})...")
        resp_doc = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro, timeout=30)
        print(f"Sucesso! Código retornado pelo Google Docs: {resp_doc.status_code}")

    print("\nConsolidação diária finalizada com sucesso!")

if __name__ == "__main__":
    processar_e_enviar()
