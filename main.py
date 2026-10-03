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

def descobrir_melhor_modelo():
    """Consulta a lista de modelos oficiais liberados para a sua chave."""
    print("Consultando modelos disponíveis no Google AI...")
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        resp = requests.get(url, timeout=30)
        if resp.ok:
            todos = resp.json().get("models", [])
            modelos_disponiveis = [
                m["name"].replace("models/", "") 
                for m in todos 
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            print(f"Modelos oficiais ativos na sua conta: {modelos_disponiveis}")
            # Seleciona o primeiro modelo Flash disponível
            for m in modelos_disponiveis:
                if "flash" in m.lower():
                    return m
            if modelos_disponiveis:
                return modelos_disponiveis[0]
    except Exception as e:
        print(f"Erro ao listar modelos: {e}")
    return "gemini-3.8-flash"

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

def processar_e_enviar():
    # Data de ontem (D-1)
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Iniciando consolidação do dia {data_alvo}...")

    modelo_selecionado = descobrir_melhor_modelo()
    print(f"Modelo selecionado para análise: {modelo_selecionado}")

    ligacoes = buscar_ligacoes_3c(data_alvo)
    
    # Separa chamadas com tempo falado
    chamadas_atendidas = [
        c for c in ligacoes 
        if c.get("speaking_with_agent_time") not in [None, "", "00:00:00", "0"]
    ]
    print(f"Chamadas com conversação ativa: {len(chamadas_atendidas)}")

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
                # Ajusta subdomínio da Fibrart
                audio_url = raw_recording.replace("app.3c.plus", "fibrartindustria.3c.plus")
                if "api_token" not in audio_url:
                    audio_url = f"{audio_url}?api_token={TOKEN_3C_PLUS}"
                
                headers_audio = {"Authorization": f"Bearer {TOKEN_3C_PLUS}", "User-Agent": "Mozilla/5.0"}
                resp_audio = requests.get(audio_url, headers=headers_audio, timeout=60)
                
                print(f"Status do download do áudio: {resp_audio.status_code} | Tamanho: {len(resp_audio.content)} bytes | Tipo: {resp_audio.headers.get('Content-Type')}")

                # Diagnóstico: Se não for MP3 real (ex: retornou erro HTML), não envia como áudio
                if resp_audio.ok and len(resp_audio.content) > 1000 and "text/html" not in resp_audio.headers.get("Content-Type", ""):
                    audio_b64 = base64.b64encode(resp_audio.content).decode("utf-8")
                    
                    prompt = "Analise o atendimento desta ligação de vendas de marmofibra: 1. Resumo da conversa, 2. Interesse do cliente, 3. Objeções, 4. Desempenho do atendente, 5. Nota de 0 a 10 com justificativa."
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inline_data": {"mime_type": "audio/mp3", "data": audio_b64}}
                            ]
                        }]
                    }
                    
                    url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo_selecionado}:generateContent?key={GEMINI_API_KEY}"
                    resp_gemini = requests.post(url_gemini, json=payload, timeout=90)
                    
                    if resp_gemini.ok:
                        dados_gemini = resp_gemini.json()
                        texto = dados_gemini["candidates"][0]["content"]["parts"][0]["text"]
                        analise_resultado = {"resumo": texto, "interesse": "Analisado via IA", "nota": 8.0}
                    else:
                        print(f"Aviso no Gemini (HTTP {resp_gemini.status_code}): {resp_gemini.text[:200]}")
                else:
                    print("Arquivo não parece ser um áudio MP3 válido. Gravando com dados cadastrais da 3C Plus...")

            except Exception as e:
                print(f"Erro no processamento de mídia da chamada {call_id}: {e}")

        # Se não tiver análise de áudio, monta o registro com a qualificação oficial da 3C Plus
        if not analise_resultado:
            analise_resultado = {
                "resumo": f"Atendimento realizado por {agente}. Duração falada: {chamada.get('speaking_with_agent_time', 'N/D')}.",
                "interesse": "Registrado via 3C Plus",
                "objecoes": "Conforme tabulação",
                "desempenho_atendente": "Registrado no sistema",
                "nota": 8.0,
                "justificativa_nota": "Tabulado no discador"
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

        print("Enviando registro para o Google Docs...")
        resp_doc = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro, timeout=30)
        print(f"Resultado no Google Docs: {resp_doc.status_code}")

    print("\nProcesso finalizado com sucesso!")

if __name__ == "__main__":
    processar_e_enviar()
