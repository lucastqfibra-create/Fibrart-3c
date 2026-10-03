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

PROMPT_CONSOLIDACAO_DIARIA = """
Você é o Diretor Comercial e Especialista de Qualidade da Fibrart (indústria de pias e tanques em marmofibra).
Com base nos dados brutos de ligações de voz e nas conversas do WhatsApp Omnichannel do discador 3C Plus referentes ao dia de atendimento, gere um RELATÓRIO EXECUTIVO CONSOLIDADO DAS TRATATIVAS para a diretoria.

O relatório deve conter estritamente em formato JSON com as chaves:
{
  "resumo": "Visão geral do dia, volume de atendimentos e principais temas tratados",
  "interesse": "Status das negociações no WhatsApp e pedidos em andamento",
  "objecoes": "Principais objeções levantadas pelos clientes e gargalos operacionais (ex: fila de espera, tempo de resposta, frete)",
  "desempenho_atendente": "Diagnóstico do desempenho das atendentes (Fernanda, Julia, Gabriele): conversão, postura e agilidade",
  "lead_quente": true,
  "nota": 8.5,
  "justificativa_nota": "Plano de ação imediato para fechar as negociações abertas e zerar pendências"
}
Retorne estritamente o JSON sem blocos markdown.
"""

def buscar_ligacoes_3c(data_alvo):
    url = f"{DOMINIO_FIBRART}/api/v1/calls"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN_3C_PLUS}"}
    params = {"api_token": TOKEN_3C_PLUS, "start_date": f"{data_alvo} 00:00:00", "end_date": f"{data_alvo} 23:59:59"}
    
    print(f"Consultando ligações de voz para {data_alvo}...")
    try:
        response = requests.get(url, params=params, headers=headers, timeout=60)
        if not response.ok:
            params_simples = {"api_token": TOKEN_3C_PLUS, "start_date": data_alvo, "end_date": data_alvo}
            response = requests.get(url, params=params_simples, headers=headers, timeout=60)
        dados = response.json()
        return dados.get("data", dados) if isinstance(dados, dict) else dados
    except Exception as e:
        print(f"Erro ao buscar chamadas de voz: {e}")
        return []

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
    print(f"Consultando conversas do WhatsApp para {data_alvo}...")
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=40)
        if resp.ok:
            dados = resp.json()
            itens = dados.get("data", dados) if isinstance(dados, dict) else dados
            if isinstance(itens, list):
                return itens
    except Exception as e:
        print(f"Erro ao buscar WhatsApp: {e}")
    return []

def sintetizar_com_gemini(dados_brutos_texto):
    """Envia o consolidado do dia para o Gemini gerar o relatório executivo."""
    modelos = ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-flash-latest"]
    payload = {
        "contents": [{
            "parts": [
                {"text": f"{PROMPT_CONSOLIDACAO_DIARIA}\n\nDADOS BRUTOS DA OPERAÇÃO:\n{dados_brutos_texto}"}
            ]
        }]
    }
    for m in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        try:
            resp = requests.post(url, json=payload, timeout=90)
            if resp.ok:
                dados = resp.json()
                return dados["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            pass
    return None

def processar_e_enviar():
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\n========================================================")
    print(f"GERANDO RELATÓRIO EXECUTIVO CONSOLIDADO — {data_alvo}")
    print(f"========================================================\n")

    # 1. Coleta de dados
    ligacoes = buscar_ligacoes_3c(data_alvo)
    conversas = buscar_conversas_omnichannel(data_alvo)
    
    # 2. Compilação dos dados brutos
    total_voz = len(ligacoes)
    atendidas_voz = [c for c in ligacoes if c.get("speaking_with_agent_time") not in [None, "", "00:00:00", "0"]]
    
    total_wpp = len(conversas)
    agentes_wpp = Counter(c.get("agent_name") or c.get("agent") or "Sem Agente" for c in conversas)
    status_wpp = Counter(c.get("status") or "Em Aberto" for c in conversas)
    
    clientes_wpp = [
        f"- {c.get('name', 'Cliente')} ({c.get('number', '')}) | Status: {c.get('status', '')} | Agente: {c.get('agent_name', '')}"
        for c in conversas[:30]
    ]

    chamadas_detalhes = [
        f"- {c.get('agent', '')} ➔ {c.get('number', '')} | Duração: {c.get('speaking_with_agent_time', '')} | Tabulação: {c.get('qualification', '')}"
        for c in atendidas_voz
    ]

    texto_para_ia = f"""
DATA DO RELATÓRIO: {data_alvo}

MÉTRICAS DE VOZ (DISCADOR 3C PLUS):
- Total de disparos: {total_voz}
- Chamadas efetivas com conversa: {len(atendidas_voz)}
Detalhes das ligações atendidas:
{chr(10).join(chamadas_detalhes) if chamadas_detalhes else 'Nenhuma chamada com tempo falado.'}

MÉTRICAS DE WHATSAPP (3C OMNI):
- Total de conversas no dia: {total_wpp}
- Distribuição por atendente: {dict(agentes_wpp)}
- Status das conversas: {dict(status_wpp)}
Amostra das tratativas abertas no WhatsApp:
{chr(10).join(clientes_wpp) if clientes_wpp else 'Nenhuma conversa registrada.'}
"""

    print("Enviando dados brutos consolidados para a inteligência do Gemini...")
    sintese_ia = sintetizar_com_gemini(texto_para_ia)
    
    analise_resultado = None
    if sintese_ia:
        texto_limpo = sintese_ia.strip().replace("```json", "").replace("```", "")
        try:
            analise_resultado = json.loads(texto_limpo)
        except Exception:
            analise_resultado = {"resumo": sintese_ia}

    if not analise_resultado:
        analise_resultado = {
            "resumo": f"Operação do dia {data_alvo}: {len(atendidas_voz)} chamadas atendidas no discador e {total_wpp} conversas registradas no WhatsApp.",
            "interesse": f"WhatsApp: {dict(status_wpp)}",
            "objecoes": "Mapeamento diário de tratativas",
            "desempenho_atendente": f"Atendimento via canais 3C Omni: {dict(agentes_wpp)}",
            "lead_quente": True,
            "nota": 8.5,
            "justificativa_nota": "Consolidado diário automático"
        }

    # 3. Envia UM ÚNICO bloco executivo para o Google Docs
    registro_executivo = {
        "id": f"consolidado-{data_alvo}",
        "data_hora": f"{data_alvo} 18:00:00",
        "agente": "Diretoria Comercial Fibrart",
        "numero": f"{len(atendidas_voz)} Ligações | {total_wpp} WhatsApp",
        "qualificacao": "Relatório Executivo Consolidado das Tratativas",
        "analise": analise_resultado
    }

    print("Gravando Relatório Executivo Consolidado no Google Docs...")
    resp = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro_executivo, timeout=30)
    print(f"Status da entrega no Google Docs: {resp.status_code}")

    print("\n========================================================")
    print("CONSOLIDAÇÃO EXECUTIVA FINALIZADA COM SUCESSO!")
    print("========================================================\n")

if __name__ == "__main__":
    processar_e_enviar()
