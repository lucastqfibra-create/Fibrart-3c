import os
import json
import requests
from collections import Counter
from datetime import datetime, timedelta

# ==============================================================
# CONFIGURAÇÕES (Secrets do GitHub)
# ==============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TOKEN_3C_PLUS = os.getenv("TOKEN_3C_PLUS")

URL_PADRAO_DOCS = "https://script.google.com/macros/s/AKfycbyZOreWCznYOuUltu22Iwyt6eoho60WuqMPEQtFYFni30J2trT9pCm68bgs0ugZeUBc/exec"
ENV_DOCS = (os.getenv("GOOGLE_DOCS_WEBHOOK_URL") or "").strip(" '\"")
GOOGLE_DOCS_WEBHOOK_URL = ENV_DOCS if ENV_DOCS.startswith("http") else URL_PADRAO_DOCS

DOMINIO_FIBRART = "https://fibrartindustria.3c.plus"

def time_to_sec(t):
    if not t or str(t).strip() in ["", "0", "00:00:00", "None"]:
        return 0
    parts = str(t).strip().split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return 0
    return 0

def extrair_mailing(m_str):
    if not m_str:
        return {}
    try:
        return json.loads(m_str)
    except Exception:
        return {}

def buscar_todas_ligacoes_3c(data_alvo):
    """Busca 100% das ligações do dia na 3C Plus paginando até o fim."""
    url = f"{DOMINIO_FIBRART}/api/v1/calls"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN_3C_PLUS}"}
    todas = []
    pagina = 1

    print(f"Buscando todas as páginas de chamadas para {data_alvo}...")
    while True:
        params = {
            "api_token": TOKEN_3C_PLUS,
            "start_date": f"{data_alvo} 00:00:00",
            "end_date": f"{data_alvo} 23:59:59",
            "page": pagina,
            "per_page": 100
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=60)
            if not resp.ok:
                break
            dados = resp.json()
            itens = dados.get("data", dados) if isinstance(dados, dict) else dados
            if not itens or not isinstance(itens, list):
                break
            todas.extend(itens)
            if len(itens) < 100:
                break
            pagina += 1
        except Exception as e:
            print(f"Erro na página {pagina}: {e}")
            break

    print(f"Total de ligações recuperadas: {len(todas)}")
    return todas

def buscar_conversas_omnichannel(data_alvo):
    """Busca os atendimentos de WhatsApp do dia."""
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

def gerar_analise_gemini(dados_apurados_texto):
    """Gera diagnóstico da equipe e plano de ação comercial com o Gemini."""
    prompt = f"""
Você é o Diretor Comercial da Fibrart (tanques e pias em marmofibra).
Com base nos números e listas de lojistas atendidos abaixo, redija DUAS seções executivas em português:
1. "👩‍💼 Desempenho e Diagnóstico da Equipe": analise a conversão, TMA, proatividade e ritmo de Julia e Fernanda.
2. "💡 Plano de Ação Comercial Imediato para Hoje": 3 ações táticas prioritárias (fechamento de pedidos, retorno de clientes agendados e acompanhamento de entregas).

Use marcadores (* ou 1.) e texto direto e profissional.

DADOS APURADOS:
{dados_apurados_texto}
"""
    modelos = ["gemini-2.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for m in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.ok:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception:
            pass
    return None

def processar_e_enviar():
    dias_semana = ['Segunda-Feira', 'Terça-Feira', 'Quarta-Feira', 'Quinta-Feira', 'Sexta-Feira', 'Sábado', 'Domingo']
    ontem = datetime.now() - timedelta(days=1)
    data_alvo = ontem.strftime("%Y-%m-%d")
    data_formatada = ontem.strftime("%d/%m/%Y")
    dia_semana = dias_semana[ontem.weekday()]

    print(f"\n========================================================")
    print(f"PROCESSANDO RELATÓRIO EXECUTIVO — {data_formatada} ({dia_semana})")
    print(f"========================================================\n")

    ligacoes = buscar_todas_ligacoes_3c(data_alvo)
    chats_wpp = buscar_conversas_omnichannel(data_alvo)

    # 1. Métricas de Voz
    total_voz = len(ligacoes)
    efetivas = [c for c in ligacoes if time_to_sec(c.get("speaking_with_agent_time")) > 0]
    tempo_total_seg = sum(time_to_sec(c.get("speaking_with_agent_time")) for c in ligacoes)
    horas_faladas = tempo_total_seg // 3600
    min_falados = (tempo_total_seg % 3600) // 60

    vendas = [c for c in ligacoes if c.get("qualification_name") == "Venda feita por telefone"]
    leads_wpp = [c for c in ligacoes if c.get("qualification_name") == "Em negociação whatsApp"]
    agendados = [c for c in ligacoes if c.get("qualification_name") == "Agendamento / Retorno"]

    # 2. Métricas por Atendente
    agentes_stats = {}
    for ag in ["Julia", "Fernanda"]:
        sub = [c for c in ligacoes if c.get("agent_name") == ag]
        sub_ef = [c for c in sub if time_to_sec(c.get("speaking_with_agent_time")) > 0]
        t_seg = sum(time_to_sec(c.get("speaking_with_agent_time")) for c in sub)
        agentes_stats[ag] = {
            "total": len(sub),
            "efetivas": len(sub_ef),
            "tempo_str": f"{t_seg // 60}m {t_seg % 60}s",
            "tma": f"{int(t_seg / len(sub_ef))}s" if len(sub_ef) else "0s",
            "vendas": len([c for c in sub if c.get("qualification_name") == "Venda feita por telefone"]),
            "wpp": len([c for c in sub if c.get("qualification_name") == "Em negociação whatsApp"]),
            "agend": len([c for c in sub if c.get("qualification_name") == "Agendamento / Retorno"])
        }

    # 3. Montar Linhas de Vendas Fechadas
    linhas_vendas = []
    for c in vendas:
        m = extrair_mailing(c.get("mailing_data.data"))
        nome = m.get("Nome Fantasia") or m.get("NOME") or "Loja sem cadastro"
        cid = m.get("Cidade") or ""
        cred = m.get("Receita") or m.get("Receita ") or ""
        ag = c.get("agent_name") or "Atendente"
        detalhe = f"{nome} ({cid} — {c.get('number', '')}"
        if cred and cred not in ["R$ 0,00", "0,00"]:
            detalhe += f" | Crédito/Receita: {cred}"
        detalhe += f") — Vendedora: {ag}"
        linhas_vendas.append(detalhe)

    # 4. Montar Linhas de WhatsApp
    linhas_leads_wpp = []
    for c in leads_wpp[:15]:
        m = extrair_mailing(c.get("mailing_data.data"))
        nome = m.get("Nome Fantasia") or m.get("NOME") or "Loja"
        cid = m.get("Cidade") or ""
        ag = c.get("agent_name") or ""
        linhas_leads_wpp.append(f"[{ag}] {nome} ({cid} — {c.get('number', '')})")

    # 5. Montar Linhas de Agendamentos
    linhas_agendados = []
    for c in agendados[:15]:
        m = extrair_mailing(c.get("mailing_data.data"))
        nome = m.get("Nome Fantasia") or m.get("NOME") or "Loja"
        cid = m.get("Cidade") or ""
        ag = c.get("agent_name") or ""
        linhas_agendados.append(f"[{ag}] {nome} ({cid} — {c.get('number', '')})")

    dados_ia_input = f"""
Operação do dia {data_formatada}:
- Total de disparos: {total_voz} | Efetivas: {len(efetivas)} | Tempo em linha: {horas_faladas}h {min_falados}min
- Vendas confirmadas: {len(vendas)}
- Leads para WhatsApp: {len(leads_wpp)}
- Retornos agendados: {len(agendados)}
- Atendimentos WhatsApp Omni: {len(chats_wpp)}
- Desempenho Fernanda: {agentes_stats.get('Fernanda')}
- Desempenho Julia: {agentes_stats.get('Julia')}
"""

    analise_ia = gerar_analise_gemini(dados_ia_input)
    if not analise_ia:
        analise_ia = f"""👩‍💼 Desempenho e Diagnóstico da Equipe
* Fernanda: {agentes_stats.get('Fernanda', {}).get('efetivas', 0)} atendimentos falados, {agentes_stats.get('Fernanda', {}).get('vendas', 0)} vendas fechadas e {agentes_stats.get('Fernanda', {}).get('wpp', 0)} encaminhamentos para WhatsApp.
* Julia: {agentes_stats.get('Julia', {}).get('efetivas', 0)} atendimentos falados, {agentes_stats.get('Julia', {}).get('vendas', 0)} venda fechada e {agentes_stats.get('Julia', {}).get('agend', 0)} retornos agendados.

💡 Plano de Ação Comercial Imediato
1. Fechamento das lojas no WhatsApp com envio de catálogo e tabela.
2. Contato prioritário para os agendamentos de retorno do dia.
3. Acompanhamento dos pedidos confirmados para liberação de faturamento."""

    # 6. Estruturação do Relatório Formatado Idêntico ao Modelo Oficial
    vendas_formatadas = "\n".join(f"{i+1}. {v}" for i, v in enumerate(linhas_vendas)) if linhas_vendas else "* Nenhuma venda direta tabulada no discador."
    wpp_formatados = "\n".join(f"* {item}" for item in linhas_leads_wpp) if linhas_leads_wpp else "* Nenhum lead transferido para WhatsApp."
    agend_formatados = "\n".join(f"* {item}" for item in linhas_agendados) if linhas_agendados else "* Nenhum agendamento pendente."

    relatorio_final = f"""📅 Registro Consolidado — {data_formatada} ({dia_semana})

📊 Visão Geral das Operações (Voz & WhatsApp Omni)
* Voz (Discador 3C Plus): {total_voz} disparos realizados | {len(efetivas)} ligações efetivas com conversa humana.
* Tempo Total em Ligação: {horas_faladas} horas e {min_falados} minutos de diálogo ativo com lojistas e depósitos.
* 🏆 Vendas Fechadas por Telefone: {len(vendas)} pedidos confirmados e faturados.
* WhatsApp (3C Omni): {len(chats_wpp)} atendimentos registrados no dia | {len(leads_wpp)} empresas encaminhadas pelo telefone para negociação.
* Retornos e Cotações Agendadas: {len(agendados)} lojistas aguardando recontato.

🏆 Vendas Fechadas por Telefone ({len(vendas)} Pedidos Confirmados)
{vendas_formatadas}

📲 Leads Transferidos para o WhatsApp ({len(leads_wpp)} Empresas Quentes)
{wpp_formatados}

📅 Agendamentos de Retorno Prioritários ({len(agendados)} Lojas)
{agend_formatados}

{analise_ia}
"""

    print("Enviando Relatório Executivo Formatado para o Google Docs...")
    payload = {
        "tipo": "relatorio_executivo",
        "data": data_alvo,
        "texto_formatado": relatorio_final
    }
    resp = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=payload, timeout=40)
    print(f"Status da entrega no Google Docs: {resp.status_code}")
    print("\n========================================================")
    print("RELATÓRIO EXECUTIVO DIÁRIO CONCLUÍDO COM SUCESSO!")
    print("========================================================\n")

if __name__ == "__main__":
    processar_e_enviar()
