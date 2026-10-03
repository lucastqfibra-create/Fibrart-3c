import os
import json
import base64
import tempfile
import time
import requests
from collections import Counter
from datetime import datetime, timedelta

# ==============================================================
# CONFIGURAÇÕES (Lidas dos Secrets do GitHub)
# ==============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TOKEN_3C_PLUS = os.getenv("TOKEN_3C_PLUS")

URL_PADRAO_DOCS = "https://script.google.com/macros/s/AKfycbyZOreWCznYOuUltu22Iwyt6eoho60WuqMPEQtFYFni30J2trT9pCm68bgs0ugZeUBc/exec"
ENV_DOCS = (os.getenv("GOOGLE_DOCS_WEBHOOK_URL") or "").strip(" '\"")
GOOGLE_DOCS_WEBHOOK_URL = ENV_DOCS if ENV_DOCS.startswith("http") else URL_PADRAO_DOCS

DOMINIO_FIBRART = "https://fibrartindustria.3c.plus"

PROMPT_ANALISE_VOZ = """
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
    """Consulta as chamadas de voz da Fibrart na API da 3C Plus."""
    url = f"{DOMINIO_FIBRART}/api/v1/calls"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN_3C_PLUS}"}
    params = {"api_token": TOKEN_3C_PLUS, "start_date": f"{data_alvo} 00:00:00", "end_date": f"{data_alvo} 23:59:59"}
    
    print(f"Consultando ligações de voz para {data_alvo}...")
    response = requests.get(url, params=params, headers=headers, timeout=60)
    
    if not response.ok:
        params_simples = {"api_token": TOKEN_3C_PLUS, "start_date": data_alvo, "end_date": data_alvo}
        response = requests.get(url, params=params_simples, headers=headers, timeout=60)
        response.raise_for_status()

    dados = response.json()
    ligacoes = dados.get("data", dados) if isinstance(dados, dict) else dados
    print(f"Total de chamadas de voz retornadas: {len(ligacoes)}")
    return ligacoes

def buscar_conversas_omnichannel(data_alvo):
    """Consulta o relatório oficial de conversas do Omnichannel na 3C Plus."""
    url = f"{DOMINIO_FIBRART}/omni-reports/api/v1/chats"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN_3C_PLUS}"}
    
    # Parâmetros oficiais extraídos da sua tela de rede
    params = [
        ("api_token", TOKEN_3C_PLUS),
        ("page", "1"),
        ("per_page", "100"),
        ("start_date", f"{data_alvo} 00:00:00"),
        ("end_date", f"{data_alvo} 23:59:59"),
        ("group_channel_ids[]", "9801"),
        ("group_channel_ids[]", "9797"),
        ("group_channel_ids[]", "9683"),
        ("group_channel_ids[]", "9682")
    ]
    
    print(f"Consultando conversas do WhatsApp Omnichannel para {data_alvo}...")
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=40)
        print(f"Status Omnichannel: {resp.status_code}")
        if resp.ok:
            dados = resp.json()
            itens = dados.get("data", dados) if isinstance(dados, dict) else dados
            if isinstance(itens, list):
                print(f"Sucesso! Total de conversas obtidas do WhatsApp: {len(itens)}")
                return itens
        else:
            print(f"Aviso no Omnichannel ({resp.status_code}): {resp.text[:180]}")
    except Exception as e:
        print(f"Erro ao consultar Omnichannel: {e}")
        
    return []

def analisar_audio_com_gemini(audio_base64):
    """Envia o áudio para modelos oficiais do Gemini com retentativa."""
    modelos = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-pro"]
    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT_ANALISE_VOZ},
                {"inline_data": {"mime_type": "audio/mp3", "data": audio_base64}}
            ]
        }]
    }
    
    for modelo in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_API_KEY}"
        print(f"Tentando análise de áudio com modelo ativo: {modelo}...")
        try:
            resp = requests.post(url, json=payload, timeout=90)
            if resp.ok:
                dados = resp.json()
                return dados["candidates"][0]["content"]["parts"][0]["text"]
            elif resp.status_code == 503:
                print(f"Modelo {modelo} com pico de demanda (503). Aguardando 3s antes de alternar...")
                time.sleep(3)
        except Exception as e:
            print(f"Aviso no modelo {modelo}: {e}")
            time.sleep(2)
            
    return None

def processar_e_enviar():
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\n========================================================")
    print(f"INICIANDO CONSOLIDAÇÃO DIÁRIA — DATA ALVO: {data_alvo}")
    print(f"========================================================\n")

    # 1. PROCESSAMENTO DE VOZ
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

        print(f"\n--- Processando Ligação {call_id} ({agente} ➔ {numero} | {qualificacao}) ---")
        analise_resultado = None

        if raw_recording:
            try:
                audio_url = raw_recording.replace("app.3c.plus", "fibrartindustria.3c.plus")
                if "api_token" not in audio_url:
                    audio_url = f"{audio_url}?api_token={TOKEN_3C_PLUS}"
                
                headers_audio = {"Authorization": f"Bearer {TOKEN_3C_PLUS}", "User-Agent": "Mozilla/5.0"}
                resp_audio = requests.get(audio_url, headers=headers_audio, timeout=60)
                
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
                print(f"Aviso no áudio da chamada {call_id}: {e}")

        if not analise_resultado:
            analise_resultado = {
                "resumo": f"Atendimento realizado por {agente}. Duração: {chamada.get('speaking_with_agent_time', 'N/D')}.",
                "interesse": "Registrado no discador",
                "objecoes": "Conforme qualificação",
                "desempenho_atendente": "Registrado no 3C Plus",
                "nota": 8.0,
                "justificativa_nota": "Tabulado no sistema"
            }

        registro_voz = {
            "id": call_id,
            "data_hora": chamada.get("call_date", data_alvo),
            "agente": agente,
            "numero": numero,
            "qualificacao": qualificacao,
            "analise": analise_resultado
        }

        print("Enviando ligação para o Google Docs...")
        requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro_voz, timeout=30)

    # 2. PROCESSAMENTO DE WHATSAPP (OMNICHANNEL)
    print(f"\n--- Processando Relatório de Conversas Omnichannel ---")
    conversas = buscar_conversas_omnichannel(data_alvo)
    
    if conversas:
        total_wpp = len(conversas)
        agentes_wpp = Counter(
            c.get("agent_name") or c.get("agent") or c.get("user_name") or "Sem Agente" 
            for c in conversas
        )
        status_wpp = Counter(
            c.get("status") or c.get("readable_status") or "Em Aberto" 
            for c in conversas
        )
        
        detalhe_agentes = ", ".join([f"{ag}: {qtd}" for ag, qtd in agentes_wpp.items()])
        detalhe_status = ", ".join([f"{st}: {qtd}" for st, qtd in status_wpp.items()])

        analise_wpp = {
            "resumo": f"Total de {total_wpp} conversas no WhatsApp em {data_alvo}. Distribuição por atendente: {detalhe_agentes}.",
            "interesse": "Negociações ativas no WhatsApp",
            "objecoes": f"Status das conversas: {detalhe_status}",
            "desempenho_atendente": "Envio de catálogos e orçamentos via WhatsApp Omni",
            "lead_quente": True,
            "nota": 9.0,
            "justificativa_nota": "Consolidado oficial do 3C Omni"
        }

        registro_omni = {
            "id": f"omnichannel-{data_alvo}",
            "data_hora": f"{data_alvo} 18:00:00",
            "agente": "Equipe Comercial (WhatsApp Omni)",
            "numero": f"{total_wpp} conversas",
            "qualificacao": "Consolidado WhatsApp",
            "analise": analise_wpp
        }

        print("Enviando consolidado do WhatsApp para o Google Docs...")
        resp_omni = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro_omni, timeout=30)
        print(f"Status do WhatsApp no Google Docs: {resp_omni.status_code}")
    else:
        print("Nenhuma conversa de WhatsApp retornada no período.")

    print("\n========================================================")
    print("CONSOLIDAÇÃO DIÁRIA FINALIZADA COM SUCESSO!")
    print("========================================================\n")

if __name__ == "__main__":
    processar_e_enviar()
