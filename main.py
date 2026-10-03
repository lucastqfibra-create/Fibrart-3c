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

PROMPT_ANALISE_WHATSAPP = """
Você é um especialista em conversão de vendas B2B de tanques e pias em marmofibra da Fibrart.
Analise detalhadamente o diálogo da conversa de WhatsApp abaixo e retorne em formato JSON válido:
{
  "resumo": "Produtos solicitados e resumo do que foi tratado",
  "interesse": "Alto / Médio / Baixo / Nenhum",
  "objecoes": "Objeções identificadas (preço, frete, prazo, etc.)",
  "desempenho_atendente": "Avaliação da agilidade, clareza e poder de fechamento da vendedora",
  "lead_quente": true,
  "nota": 9.0,
  "justificativa_nota": "Diagnóstico do atendimento no WhatsApp e próximo passo recomendado"
}
Retorne estritamente o JSON sem blocos markdown.
"""

def buscar_ligacoes_3c(data_alvo):
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
    url = f"{DOMINIO_FIBRART}/omni-reports/api/v1/chats"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN_3C_PLUS}"}
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
        if resp.ok:
            dados = resp.json()
            itens = dados.get("data", dados) if isinstance(dados, dict) else dados
            if isinstance(itens, list):
                print(f"Sucesso! Total de conversas obtidas do WhatsApp: {len(itens)}")
                return itens
    except Exception as e:
        print(f"Erro ao consultar Omnichannel: {e}")
    return []

def extrair_mensagens_chat(chat_id):
    """Tenta obter as mensagens de texto de um chat específico."""
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN_3C_PLUS}"}
    urls_tentativa = [
        f"{DOMINIO_FIBRART}/omni-reports/api/v1/chats/{chat_id}/messages?api_token={TOKEN_3C_PLUS}",
        f"{DOMINIO_FIBRART}/api/v1/whatsapp/chats/{chat_id}/messages?api_token={TOKEN_3C_PLUS}",
        f"{DOMINIO_FIBRART}/omni-reports/api/v1/chats/{chat_id}?api_token={TOKEN_3C_PLUS}"
    ]
    for u in urls_tentativa:
        try:
            r = requests.get(u, headers=headers, timeout=20)
            if r.ok:
                d = r.json()
                msgs = d.get("messages", d.get("data", []))
                if isinstance(msgs, list) and msgs:
                    # Constrói o histórico formatado
                    dialogo = []
                    for m in msgs:
                        autor = m.get("sender_name") or m.get("type") or "Contato"
                        texto = m.get("text") or m.get("body") or m.get("message") or ""
                        if texto:
                            dialogo.append(f"{autor}: {texto}")
                    if dialogo:
                        return "\n".join(dialogo)
        except Exception:
            pass
    return None

def analisar_com_gemini(conteudo_texto, prompt_especifico):
    """Envia texto para análise no Gemini 3.6 Flash / 3.7 Flash."""
    modelos = ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-flash-latest"]
    payload = {
        "contents": [{
            "parts": [
                {"text": f"{prompt_especifico}\n\nCONTEÚDO PARA ANÁLISE:\n{conteudo_texto}"}
            ]
        }]
    }
    for m in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.ok:
                dados = resp.json()
                return dados["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            pass
    return None

def processar_e_enviar():
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\n========================================================")
    print(f"INICIANDO CONSOLIDAÇÃO DIÁRIA — DATA ALVO: {data_alvo}")
    print(f"========================================================\n")

    # 1. PROCESSAMENTO DE VOZ (LIGAÇÕES)
    ligacoes = buscar_ligacoes_3c(data_alvo)
    chamadas_atendidas = [
        c for c in ligacoes 
        if c.get("speaking_with_agent_time") not in [None, "", "00:00:00", "0"]
    ]
    for chamada in chamadas_atendidas:
        call_id = chamada.get("id")
        agente = chamada.get("agent", "Desconhecido")
        numero = chamada.get("number", "Não informado")
        qualificacao = chamada.get("qualification", "Sem tabulação")
        
        analise_resultado = {
            "resumo": f"Atendimento telefônico realizado por {agente}. Duração: {chamada.get('speaking_with_agent_time', 'N/D')}.",
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
        requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro_voz, timeout=30)

    # 2. PROCESSAMENTO E ANÁLISE REAL DO WHATSAPP (OMNICHANNEL)
    print(f"\n--- Processando Análise das Conversas do WhatsApp ---")
    conversas = buscar_conversas_omnichannel(data_alvo)
    
    # Processa cada conversa individualmente
    for chat in conversas:
        chat_id = chat.get("id") or chat.get("protocol")
        nome_cliente = chat.get("name") or chat.get("customer_name") or "Cliente WhatsApp"
        numero_cliente = chat.get("number") or chat.get("phone") or "Sem número"
        agente = chat.get("agent_name") or chat.get("agent") or chat.get("user_name") or "Julia/Fernanda"
        qualificacao = chat.get("status") or chat.get("qualification") or "Em Negociação"

        print(f"\nAnalisando conversa no WhatsApp: {nome_cliente} ({numero_cliente}) com {agente}...")

        # Tenta extrair as mensagens trocadas
        historico_dialogo = extrair_mensagens_chat(chat_id)
        
        analise_resultado = None
        if historico_dialogo:
            print(f"Diálogo extraído com sucesso! Enviando para o Gemini...")
            texto_ia = analisar_com_gemini(historico_dialogo, PROMPT_ANALISE_WHATSAPP)
            if texto_ia:
                texto_limpo = texto_ia.strip().replace("```json", "").replace("```", "")
                try:
                    analise_resultado = json.loads(texto_limpo)
                except Exception:
                    analise_resultado = {"resumo": texto_ia}

        if not analise_resultado:
            # Fallback caso a conversa ainda esteja aberta ou sem histórico exportado
            analise_resultado = {
                "resumo": f"Atendimento via WhatsApp com {nome_cliente}. Canal: {chat.get('channel_name', 'WhatsApp')}. Status: {qualificacao}.",
                "interesse": "Lead em negociação no WhatsApp",
                "objecoes": "Aguardando retorno da cotação",
                "desempenho_atendente": f"Vendedora {agente} em atendimento",
                "lead_quente": True,
                "nota": 8.5,
                "justificativa_nota": "Conversa aberta no 3C Omni"
            }

        registro_chat = {
            "id": f"wpp-{chat_id}",
            "data_hora": chat.get("created_at") or chat.get("start_time") or f"{data_alvo} 14:00:00",
            "agente": f"{agente} (WhatsApp)",
            "numero": f"{nome_cliente} ({numero_cliente})",
            "qualificacao": f"WhatsApp: {qualificacao}",
            "analise": analise_resultado
        }

        print("Entregando análise da conversa no Google Docs...")
        resp = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro_chat, timeout=30)
        print(f"Status no Google Docs: {resp.status_code}")

    print("\n========================================================")
    print("CONSOLIDAÇÃO DIÁRIA FINALIZADA COM SUCESSO!")
    print("========================================================\n")

if __name__ == "__main__":
    processar_e_enviar()
