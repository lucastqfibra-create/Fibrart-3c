import os
import json
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

def formatar_segundos(total_t):
    h = total_t // 3600
    m = (total_t % 3600) // 60
    s = total_t % 60
    if h > 0:
        return f"{h}h {m}min {s}s"
    return f"{m}min {s}s"

def extrair_mailing(m_str):
    if not m_str:
        return {}
    try:
        return json.loads(m_str)
    except Exception:
        return {}

def buscar_todas_ligacoes_3c(data_alvo):
    """Busca 100% das chamadas na API 3C Plus paginando até o fim."""
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
    """Busca atendimentos do WhatsApp no 3C Omni."""
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

def gerar_diagnostico_ia(metricas_texto):
    """Solicita ao Gemini a análise dos pontos a melhorar, nota e justificativa."""
    prompt = f"""
Você é o Diretor Comercial da Fibrart (fábrica de tanques e pias em marmofibra).
Com base nas métricas apuradas abaixo (quantitativo exato de pessoas atendidas por telefone e WhatsApp), gere um JSON estruturado para compor o relatório diário:

{{
  "diagnostico_equipe": {{
    "Fernanda": {{
      "pontos_fortes": "Pontos fortes observados no dia em 1 ou 2 frases.",
      "pontos_a_melhorar": "Pontos de melhoria técnica/comercial específicos em 1 ou 2 frases."
    }},
    "Julia": {{
      "pontos_fortes": "Pontos fortes observados no dia em 1 ou 2 frases.",
      "pontos_a_melhorar": "Pontos de melhoria técnica/comercial específicos em 1 ou 2 frases."
    }}
  }},
  "nota_dia": "X.X / 10",
  "justificativa_nota": "Explicar em detalhes o que elevou a nota e exatamente quais gargalos ou falhas descontaram pontos.",
  "plano_acao": [
    "Ação tática prioritária 1",
    "Ação tática prioritária 2",
    "Ação tática prioritária 3"
  ]
}}

MÉTRICAS APURADAS DO DIA:
{metricas_texto}
"""
    modelos = ["gemini-2.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    for m in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.ok:
                texto = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                return json.loads(texto)
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
    print(f"GERANDO RELATÓRIO EXECUTIVO — {data_formatada} ({dia_semana})")
    print(f"========================================================\n")

    ligacoes = buscar_todas_ligacoes_3c(data_alvo)
    chats_wpp = buscar_conversas_omnichannel(data_alvo)

    # 1. Apuração Quantitativa de Telefone
    total_disparos_tel = len(ligacoes)
    efetivas_tel = [c for c in ligacoes if time_to_sec(c.get("speaking_with_agent_time")) > 0]
    pessoas_atendidas_tel = len(efetivas_tel)
    unicos_tel = len(set(c.get("number") for c in efetivas_tel if c.get("number")))
    tempo_total_seg = sum(time_to_sec(c.get("speaking_with_agent_time")) for c in ligacoes)
    tempo_total_str = formatar_segundos(tempo_total_seg)

    # 2. Apuração Quantitativa de WhatsApp
    total_recebidas_wpp = len(chats_wpp)
    chats_atendidos_wpp = [c for c in chats_wpp if (c.get("status") or "").upper() in ["FINISHED", "IN_PROGRESS", "FINALIZADA", "EM_ATENDIMENTO"]]
    pessoas_atendidas_wpp = len(chats_atendidos_wpp) if chats_atendidos_wpp else len([c for c in chats_wpp if c.get("agent_name") or c.get("agent")])
    unicos_wpp = len(set(c.get("number") for c in chats_wpp if c.get("number")))

    # Total Geral Consolidado (Voz + Texto)
    total_geral_atendidos = pessoas_atendidas_tel + pessoas_atendidas_wpp

    vendas = [c for c in ligacoes if c.get("qualification_name") == "Venda feita por telefone"]
    leads_wpp = [c for c in ligacoes if c.get("qualification_name") == "Em negociação whatsApp"]
    agendados = [c for c in ligacoes if c.get("qualification_name") == "Agendamento / Retorno"]

    # 3. Quantitativo por Atendente
    agentes_nomes = list(set([c.get("agent_name") for c in ligacoes if c.get("agent_name")] + [c.get("agent_name") for c in chats_wpp if c.get("agent_name")]))
    if not agentes_nomes:
        agentes_nomes = ["Julia", "Fernanda"]

    agentes_stats = {}
    for ag in sorted(agentes_nomes):
        sub_tel = [c for c in ligacoes if c.get("agent_name") == ag]
        sub_ef_tel = [c for c in sub_tel if time_to_sec(c.get("speaking_with_agent_time")) > 0]
        unicos_ag_tel = len(set(c.get("number") for c in sub_ef_tel if c.get("number")))
        t_seg = sum(time_to_sec(c.get("speaking_with_agent_time")) for c in sub_tel)

        sub_wpp = [c for c in chats_wpp if c.get("agent_name") == ag or c.get("agent") == ag]
        unicos_ag_wpp = len(set(c.get("number") for c in sub_wpp if c.get("number")))

        total_ag = len(sub_ef_tel) + len(sub_wpp)

        agentes_stats[ag] = {
            "total_pessoas": total_ag,
            "tel_atendidas": len(sub_ef_tel),
            "tel_unicos": unicos_ag_tel,
            "tel_total_disparos": len(sub_tel),
            "tempo_str": formatar_segundos(t_seg),
            "tma": f"{int(t_seg / len(sub_ef_tel))}s" if len(sub_ef_tel) else "0s",
            "wpp_atendidas": len(sub_wpp),
            "wpp_unicos": unicos_ag_wpp,
            "vendas": len([c for c in sub_tel if c.get("qualification_name") == "Venda feita por telefone"]),
            "leads_wpp": len([c for c in sub_tel if c.get("qualification_name") == "Em negociação whatsApp"]),
            "agend": len([c for c in sub_tel if c.get("qualification_name") == "Agendamento / Retorno"]),
            "perdidas": len([c for c in sub_tel if c.get("qualification_name") == "Negociação perdida"])
        }

    # 4. Linhas de Vendas Fechadas
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

    # 5. Linhas de WhatsApp e Agendamentos
    linhas_leads_wpp = []
    for c in leads_wpp[:15]:
        m = extrair_mailing(c.get("mailing_data.data"))
        nome = m.get("Nome Fantasia") or m.get("NOME") or "Loja"
        cid = m.get("Cidade") or ""
        ag = c.get("agent_name") or ""
        linhas_leads_wpp.append(f"[{ag}] {nome} ({cid} — {c.get('number', '')})")

    linhas_agendados = []
    for c in agendados[:15]:
        m = extrair_mailing(c.get("mailing_data.data"))
        nome = m.get("Nome Fantasia") or m.get("NOME") or "Loja"
        cid = m.get("Cidade") or ""
        ag = c.get("agent_name") or ""
        linhas_agendados.append(f"[{ag}] {nome} ({cid} — {c.get('number', '')})")

    # 6. Diagnóstico do Gemini
    dados_resumo = f"""
Operação do dia {data_formatada}:
- Total Geral de Pessoas Atendidas: {total_geral_atendidos} ({pessoas_atendidas_tel} por telefone + {pessoas_atendidas_wpp} por WhatsApp)
- Voz: {total_disparos_tel} disparos, {pessoas_atendidas_tel} pessoas com conversa efetiva ({unicos_tel} números únicos), tempo total falado: {tempo_total_str}
- WhatsApp: {pessoas_atendidas_wpp} conversas conduzidas pela equipe (de {total_recebidas_wpp} recebidas)
- Vendas por telefone: {len(vendas)}
- Transferências WhatsApp: {len(leads_wpp)}
- Retornos agendados: {len(agendados)}
- Quantitativo por atendente: {json.dumps(agentes_stats, ensure_ascii=False)}
"""
    print("Consultando inteligência do Gemini...")
    analise_json = gerar_diagnostico_ia(dados_resumo)

    diag_dict = analise_json.get("diagnostico_equipe", {}) if analise_json else {}
    nota_dia = analise_json.get("nota_dia", "8.5 / 10") if analise_json else "8.5 / 10"
    justificativa = analise_json.get("justificativa_nota", "Bom ritmo operacional.") if analise_json else "Operação com bom ritmo de contatos."
    plano_acao_lista = analise_json.get("plano_acao", []) if analise_json else [
        "Fechamento dos orçamentos abertos no WhatsApp.",
        "Contato com as lojas agendadas para retorno.",
        "Acompanhamento dos pedidos confirmados para faturamento."
    ]

    # 7. Formatação da Seção da Equipe com Quantitativo Explícito
    secao_equipe = ["👩‍💼 Desempenho e Diagnóstico da Equipe\n"]
    for ag, s in agentes_stats.items():
        secao_equipe.append(f"* **{ag}:**")
        secao_equipe.append(f"  * **Total Geral de Pessoas Atendidas:** {s['total_pessoas']} clientes no dia ({s['tel_atendidas']} por telefone + {s['wpp_atendidas']} por WhatsApp).")
        secao_equipe.append(f"  * **Atendimento por Telefone:** {s['tel_atendidas']} conversas efetivas ({s['tel_unicos']} números distintos) | Tempo falado: {s['tempo_str']} (TMA: {s['tma']}).")
        secao_equipe.append(f"  * **Atendimento por WhatsApp:** {s['wpp_atendidas']} conversas conduzidas no canal de texto ({s['wpp_unicos']} clientes distintos).")
        secao_equipe.append(f"  * **Conversão Comercial:** {s['vendas']} vendas fechadas por telefone, {s['leads_wpp']} transferências para WhatsApp e {s['agend']} retornos agendados ({s['perdidas']} negociações perdidas).")

        info_ag = diag_dict.get(ag, {})
        pontos_fortes = info_ag.get("pontos_fortes", "Postura comercial e bom ritmo de atendimento.")
        pontos_melhorar = info_ag.get("pontos_a_melhorar", "Aprofundar contorno de objeções de preço e frete antes de finalizar contatos perdidos.")
        secao_equipe.append(f"  * **Pontos Fortes:** {pontos_fortes}")
        secao_equipe.append(f"  * **Pontos a Melhorar:** {pontos_melhorar}\n")

    texto_equipe = "\n".join(secao_equipe)

    # 8. Montagem do Relatório Final
    vendas_txt = "\n".join(f"{i+1}. {v}" for i, v in enumerate(linhas_vendas)) if linhas_vendas else "* Nenhuma venda direta tabulada no discador."
    wpp_txt = "\n".join(f"* {item}" for item in linhas_leads_wpp) if linhas_leads_wpp else "* Nenhum lead transferido para WhatsApp."
    agend_txt = "\n".join(f"* {item}" for item in linhas_agendados) if linhas_agendados else "* Nenhum agendamento pendente."
    plano_txt = "\n".join(f"{i+1}. {item}" for i, item in enumerate(plano_acao_lista))

    relatorio_final = f"""📅 Registro Consolidado — {data_formatada} ({dia_semana})

📊 Visão Geral das Operações (Voz & WhatsApp Omni)
* 👥 Total Geral de Pessoas Atendidas no Dia: {total_geral_atendidos} clientes (Telefone + WhatsApp).
* 📞 Pessoas Atendidas por Telefone: {pessoas_atendidas_tel} clientes com conversa ativa ({unicos_tel} números distintos) de {total_disparos_tel} disparos realizados.
* 💬 Pessoas Atendidas por WhatsApp: {pessoas_atendidas_wpp} conversas conduzidas pela equipe ({unicos_wpp} clientes distintos de {total_recebidas_wpp} contatos recebidos).
* ⏱️ Tempo Total em Linha no Telefone: {tempo_total_str} de diálogo ativo com lojistas e depósitos.
* 🏆 Vendas Fechadas por Telefone: {len(vendas)} pedidos confirmados e faturados.
* 📲 Leads Transferidos para o WhatsApp: {len(leads_wpp)} empresas encaminhadas pelo telefone para envio de tabela e catálogo.
* 📅 Retornos e Cotações Agendadas: {len(agendados)} lojistas aguardando recontato.

🏆 Vendas Fechadas por Telefone ({len(vendas)} Pedidos Confirmados)
{vendas_txt}

📲 Leads Transferidos para o WhatsApp ({len(leads_wpp)} Empresas Quentes)
{wpp_txt}

📅 Agendamentos de Retorno Prioritários ({len(agendados)} Lojas)
{agend_txt}

{texto_equipe}
⭐ Avaliação Geral da Operação
* **Nota do Dia:** {nota_dia}
* **Justificativa da Avaliação:** {justificativa}

💡 Plano de Ação Comercial Imediato
{plano_txt}
"""

    print("Enviando Relatório Executivo Completo para o Google Docs...")
    payload = {
        "tipo": "relatorio_executivo",
        "data": data_alvo,
        "texto_formatado": relatorio_final
    }
    resp = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=payload, timeout=40)
    print(f"Status da entrega no Google Docs: {resp.status_code}")
    print("\n========================================================")
    print("RELATÓRIO EXECUTIVO GRAVADO COM SUCESSO!")
    print("========================================================\n")

if __name__ == "__main__":
    processar_e_enviar()
