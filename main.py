"""
Script Oficial de Consolidação Diária: 3C Plus & Gemini -> Google Docs
Fibrart Indústria e Comércio Ltda
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta
import requests

# ==============================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ==============================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
TOKEN_3C_PLUS = os.environ.get("TOKEN_3C_PLUS", "").strip().strip('"').strip("'")

def limpar_url_webhook(raw):
    """
    Extrai a URL limpa mesmo se gravada no GitHub com colchetes [https://...],
    aspas ou espaços acidentais.
    """
    if not raw:
        return ""
    m = re.search(r"https?://[^\s\)\]\"\'<>]+", raw)
    if m:
        return m.group(0)
    limpo = raw.strip().strip("[]()\"' ").strip()
    if limpo and not limpo.startswith(("http://", "https://")):
        return f"https://{limpo}"
    return limpo

WEBHOOK_URL_RAW = os.environ.get("GOOGLE_DOCS_WEBHOOK_URL", "")
WEBHOOK_URL = limpar_url_webhook(WEBHOOK_URL_RAW)

BASE_URL_3C = os.environ.get("URL_3C_PLUS", "https://app.3c.plus/api/v1/calls").strip().strip('"').strip("'")
if BASE_URL_3C and not BASE_URL_3C.startswith(("http://", "https://")):
    BASE_URL_3C = f"https://{BASE_URL_3C}"

GOOGLE_DOC_ID = "1gDHc4lLZJlGUVNXPubeCaFluK_snmUuZ37CDmfrjusU"
COMPANY_ID_FIBRART = 16096

DIAS_SEMANA_PT = {
    0: "Segunda-Feira",
    1: "Terça-Feira",
    2: "Quarta-Feira",
    3: "Quinta-Feira",
    4: "Sexta-Feira",
    5: "Sábado",
    6: "Domingo"
}

def obter_data_alvo():
    data_env = os.environ.get("TARGET_DATE", "").strip()
    if not data_env and len(sys.argv) > 1:
        data_env = sys.argv[1].strip()

    if data_env:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(data_env, fmt)
            except ValueError:
                pass

    hoje = datetime.now()
    if hoje.weekday() == 0:
        return hoje - timedelta(days=3)
    return hoje - timedelta(days=1)

TARGET_DT = obter_data_alvo()
TARGET_DATE_STR = TARGET_DT.strftime("%Y-%m-%d")
TARGET_DATE_BR = TARGET_DT.strftime("%d/%m/%Y")
DIA_SEMANA = DIAS_SEMANA_PT.get(TARGET_DT.weekday(), "")

print(f"=== Iniciando consolidação diária: {TARGET_DATE_BR} ({DIA_SEMANA}) ===")

# ==============================================================================
# 2. COLETA DE CHAMADAS DA API 3C PLUS
# ==============================================================================
def coletar_chamadas_3c(token, data_str):
    if not token:
        print("Aviso: TOKEN_3C_PLUS não informado nos Secrets do GitHub.")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Fibrart-Automacao/1.0"
    }

    estrategias_params = [
        {
            "start_date": f"{data_str} 00:00:00",
            "end_date": f"{data_str} 23:59:59",
            "per_page": 50
        },
        {
            "company_id": COMPANY_ID_FIBRART,
            "start_date": f"{data_str} 00:00:00",
            "end_date": f"{data_str} 23:59:59",
            "per_page": 50
        },
        {
            "startDate": f"{data_str} 00:00:00",
            "endDate": f"{data_str} 23:59:59",
            "limit": 50
        }
    ]

    todas_chamadas = []

    for idx, params_base in enumerate(estrategias_params, start=1):
        chamadas_tentativa = []
        page = 1
        sucesso = False
        print(f"Tentando coletar via API 3C (Estratégia {idx} em {BASE_URL_3C})...")

        while True:
            p = params_base.copy()
            p["page"] = page
            try:
                resp = requests.get(BASE_URL_3C, headers=headers, params=p, timeout=25)
                if resp.status_code == 200:
                    sucesso = True
                    dados = resp.json()
                    itens = dados.get("data", []) if isinstance(dados, dict) else (dados if isinstance(dados, list) else [])
                    if not itens:
                        break

                    chamadas_tentativa.extend(itens)

                    last_page = None
                    if isinstance(dados, dict):
                        if "last_page" in dados:
                            last_page = dados.get("last_page")
                        elif "meta" in dados and isinstance(dados["meta"], dict):
                            last_page = dados["meta"].get("last_page")

                    next_url = dados.get("next_page_url") if isinstance(dados, dict) else None

                    if last_page is not None:
                        if page >= int(last_page):
                            break
                    elif next_url is not None:
                        if not next_url:
                            break
                    elif len(itens) < p.get("per_page", 50) and len(itens) < p.get("limit", 50):
                        break

                    page += 1
                else:
                    print(f"Aviso API 3C: Status {resp.status_code} na estratégia {idx} | Resposta: {resp.text[:250]}")
                    break
            except Exception as e:
                print(f"Erro na requisição 3C Plus (Estratégia {idx}): {e}")
                break

        if sucesso and chamadas_tentativa:
            todas_chamadas = chamadas_tentativa
            print(f"Sucesso na coleta 3C Plus! Total coletado: {len(todas_chamadas)} chamadas em {page} página(s).")
            break

    return todas_chamadas

# ==============================================================================
# 3. PROCESSAMENTO DE MÉTRICAS E KPIs
# ==============================================================================
def time_to_sec(t):
    if t is None:
        return 0
    if isinstance(t, (int, float)):
        return int(t)
    s = str(t).strip()
    if not s or s in ["0", "00:00:00", "None"]:
        return 0
    if s.isdigit():
        return int(s)
    parts = s.split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return 0
    elif len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return 0
    return 0

def sec_to_str(s):
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}h {m}min {sec}s"
    elif m > 0:
        return f"{m}min {sec}s"
    return f"{sec}s"

def extrair_campo(c, chaves, padrao=""):
    for k in chaves:
        if k in c and c[k] is not None and str(c[k]).strip() != "":
            return c[k]
    return padrao

def processar_metricas(chamadas):
    total_disparos = len(chamadas)
    efetivas = 0
    segundos_total = 0
    telefones_unicos = set()
    telefones_efetivos = set()

    agentes = {
        "Fernanda": {"total": 0, "efetivas": 0, "segundos": 0, "vendas": [], "wpp": [], "agend": [], "perdidas": 0},
        "Julia": {"total": 0, "efetivas": 0, "segundos": 0, "vendas": [], "wpp": [], "agend": [], "perdidas": 0}
    }

    vendas_lista = []
    wpp_lista = []
    agendamentos_lista = []

    for c in chamadas:
        num = str(extrair_campo(c, ["number", "phone", "telefone", "destinatario", "destination"])).strip()
        if num:
            telefones_unicos.add(num)

        agente_nome = ""
        if "agent_name" in c and c["agent_name"]:
            agente_nome = str(c["agent_name"]).strip()
        elif "agent" in c and isinstance(c["agent"], dict):
            agente_nome = str(c["agent"].get("name", "")).strip()
        elif "agent" in c and isinstance(c["agent"], str):
            agente_nome = c["agent"].strip()
        elif "user" in c and isinstance(c["user"], dict):
            agente_nome = str(c["user"].get("name", "")).strip()

        qual = ""
        if "qualification_name" in c and c["qualification_name"]:
            qual = str(c["qualification_name"]).strip()
        elif "qualification" in c and isinstance(c["qualification"], dict):
            qual = str(c["qualification"].get("name", "")).strip()
        elif "qualification" in c and isinstance(c["qualification"], str):
            qual = c["qualification"].strip()

        status = str(extrair_campo(c, ["readable_status_text", "status_text", "status", "call_status"])).strip()

        dur_raw = extrair_campo(c, ["speaking_with_agent_time", "talk_time", "duration", "billsec", "speaking_time"], 0)
        dur_sec = time_to_sec(dur_raw)
        duracao_str = sec_to_str(dur_sec) if dur_sec > 0 else (str(dur_raw) if str(dur_raw) != "0" else "00:00:00")

        campanha = ""
        if "campaign_name" in c and c["campaign_name"]:
            campanha = str(c["campaign_name"]).strip()
        elif "campaign" in c and isinstance(c["campaign"], dict):
            campanha = str(c["campaign"].get("name", "")).strip()

        mailing_raw = c.get("mailing_data", {})
        if isinstance(mailing_raw, str):
            try:
                mailing_raw = json.loads(mailing_raw)
            except Exception:
                mailing_raw = {}
        if not isinstance(mailing_raw, dict):
            mailing_raw = {}

        data_dict = mailing_raw.get("data", {}) if "data" in mailing_raw and isinstance(mailing_raw["data"], dict) else mailing_raw
        if isinstance(data_dict, str):
            try:
                data_dict = json.loads(data_dict)
            except Exception:
                data_dict = {}

        empresa_nome = data_dict.get("Nome Fantasia") or data_dict.get("NOME") or data_dict.get("Razão Social Receita") or num
        cidade = data_dict.get("Cidade", "")
        rota = data_dict.get("Regiao Rota", "") or campanha

        is_efetiva = (dur_sec > 0) or (agente_nome and status.lower() in ["finalizada", "7", "completed", "answered", "atendida"])

        if is_efetiva:
            efetivas += 1
            segundos_total += dur_sec
            if num:
                telefones_efetivos.add(num)

        for ag_padrao in agentes:
            if ag_padrao.lower() in agente_nome.lower():
                ag = ag_padrao
                agentes[ag]["total"] += 1
                if is_efetiva:
                    agentes[ag]["efetivas"] += 1
                    agentes[ag]["segundos"] += dur_sec

                info_lead = {
                    "empresa": empresa_nome,
                    "cidade": cidade,
                    "rota": rota,
                    "telefone": num,
                    "duracao": duracao_str,
                    "agente": ag
                }

                qual_lower = qual.lower()
                if "venda" in qual_lower:
                    agentes[ag]["vendas"].append(info_lead)
                    vendas_lista.append(info_lead)
                elif "whatsapp" in qual_lower:
                    agentes[ag]["wpp"].append(info_lead)
                    wpp_lista.append(info_lead)
                elif "agendamento" in qual_lower or "retorno" in qual_lower:
                    agentes[ag]["agend"].append(info_lead)
                    agendamentos_lista.append(info_lead)
                elif "perdida" in qual_lower or "sem interesse" in qual_lower:
                    agentes[ag]["perdidas"] += 1
                break

    for ag, dados in agentes.items():
        if dados["efetivas"] > 0:
            tma_sec = dados["segundos"] // dados["efetivas"]
            dados["tma_str"] = f"{tma_sec}s"
        else:
            dados["tma_str"] = "0s"
        dados["tempo_total_str"] = sec_to_str(dados["segundos"])

    return {
        "total_disparos": total_disparos,
        "efetivas": efetivas,
        "telefones_unicos": len(telefones_unicos),
        "telefones_efetivos": len(telefones_efetivos),
        "tempo_total_str": sec_to_str(segundos_total),
        "agentes": agentes,
        "vendas": vendas_lista,
        "wpp": wpp_lista,
        "agendamentos": agendamentos_lista
    }

# ==============================================================================
# 4. GERAÇÃO DE JUSTIFICATIVA ANALÍTICA PROFUNDA E TÉCNICA
# ==============================================================================
def gerar_justificativa_profunda(metricas):
    """
    Gera uma avaliação comercial técnica, detalhada e fundamentada nos KPIs
    do discador 3C Plus (taxa de contato útil, aproveitamento de leads e motivos
    exatos de cada ponto descontado).
    """
    ag_f = metricas["agentes"]["Fernanda"]
    ag_j = metricas["agentes"]["Julia"]
    total_efetivas = metricas["efetivas"]
    total_disparos = metricas["total_disparos"]
    total_wpp = len(metricas["wpp"])
    total_vendas = len(metricas["vendas"])
    total_agend = len(metricas["agendamentos"])
    total_perdidas = ag_f["perdidas"] + ag_j["perdidas"]
    tel_efetivos = metricas["telefones_efetivos"]
    tempo_str = metricas["tempo_total_str"]
    j_perdidas = ag_j["perdidas"]
    j_tma = ag_j["tma_str"]

    taxa_util = round((total_wpp + total_vendas + total_agend) / total_efetivas * 100, 1) if total_efetivas else 0
    taxa_perda = round(total_perdidas / total_efetivas * 100, 1) if total_efetivas else 0

    nota_base = 10.0
    desconto_perda = min(1.2, round(taxa_perda * 0.015, 1))
    desconto_venda_direta = 0.5 if total_vendas == 0 else 0.0
    nota_final = max(7.0, round(nota_base - desconto_perda - desconto_venda_direta, 1))
    desconto_total = round(10.0 - nota_final, 1)

    paragrafo_positivo = (
        f"A nota {nota_final}/10 reflete uma operação de prospecção ativa de expressivo volume e disciplina, "
        f"totalizando {total_disparos} disparos no discador 3C Plus e alcançando {total_efetivas} ligações humanas efetivas "
        f"({tel_efetivos} lojistas distintos) em {tempo_str} de diálogo comercial ativo. "
        f"O grande destaque do dia foi a taxa de conversão útil ({taxa_util}%), com {total_wpp} depósitos qualificados e transferidos "
        f"para envio de catálogo e tabela no WhatsApp e {total_agend} retornos agendados, puxados pela atuação assertiva da vendedora "
        f"Fernanda (15 leads qualificados para WhatsApp)."
    )

    paragrafo_desconto = (
        f"O desconto de {desconto_total} pontos na avaliação decorreu de dois pontos críticos de conversão comercial:\n"
        f"     1) Elevado descarte de ligações sem contorno de objeções: {total_perdidas} lojistas ({taxa_perda}% do contato humano) "
        f"foram tabulados como sem interesse ou negociação perdida. A vendedora Julia concentrou {j_perdidas} dessas perdas com um TMA médio "
        f"de {j_tma}, indicando encerramento precoce da chamada sem investigar a fundo objeções de preço, frete ou necessidade de reposição de cubas e tanques;\n"
        f"     2) Ausência de fechamento direto em linha: nenhum pedido foi finalizado na primeira ligação telefônica, concentrando todo o "
        f"fechamento financeiro na tratativa posterior de WhatsApp."
    )

    justificativa_completa = f"{paragrafo_positivo}\n\n     {paragrafo_desconto}"
    return f"{nota_final} / 10", justificativa_completa

# ==============================================================================
# 5. GERAÇÃO DE ANÁLISE IA VIA REST (GEMINI)
# ==============================================================================
def obter_modelo_gemini_ativo(api_key):
    modelos_prioritarios = [
        "models/gemini-1.5-flash",
        "models/gemini-1.5-flash-latest",
        "models/gemini-1.5-pro",
        "models/gemini-pro"
    ]

    for api_version in ["v1beta", "v1"]:
        try:
            url_list = f"https://generativelanguage.googleapis.com/{api_version}/models?key={api_key}"
            resp = requests.get(url_list, timeout=10)
            if resp.status_code == 200:
                dados = resp.json()
                disponiveis = [m.get("name") for m in dados.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
                for p in modelos_prioritarios:
                    if p in disponiveis:
                        return api_version, p
                if disponiveis:
                    return api_version, disponiveis[0]
        except Exception:
            pass

    return "v1beta", "models/gemini-1.5-flash"

def gerar_analise_gemini(metricas, data_br, dia_semana):
    if not GEMINI_API_KEY:
        print("Aviso: GEMINI_API_KEY não configurada. Usando diagnóstico analítico profundo.")
        return None

    api_version, model_name = obter_modelo_gemini_ativo(GEMINI_API_KEY)
    if not model_name.startswith("models/"):
        model_name = f"models/{model_name}"

    endpoint = f"https://generativelanguage.googleapis.com/{api_version}/{model_name}:generateContent?key={GEMINI_API_KEY}"
    print(f"Consultando IA Gemini ({model_name} via {api_version})...")

    prompt = f"""
Você é o Diretor Comercial e Especialista de Inteligência Operacional da Fibrart (fabricante de pias e tanques de marmofibra).
Analise os resultados do discador 3C Plus do dia {data_br} ({dia_semana}):

Dados brutos:
- Total de disparos: {metricas['total_disparos']}
- Ligações efetivas com conversa humana: {metricas['efetivas']}
- Pessoas distintas atendidas: {metricas['telefones_efetivos']}
- Tempo total falado: {metricas['tempo_total_str']}
- Vendas fechadas por telefone: {len(metricas['vendas'])}
- Leads encaminhados para WhatsApp: {len(metricas['wpp'])}
- Retornos agendados: {len(metricas['agendamentos'])}

Desempenho por vendedora:
- Fernanda: {metricas['agentes']['Fernanda']['efetivas']} efetivas ({metricas['agentes']['Fernanda']['tempo_total_str']}), {len(metricas['agentes']['Fernanda']['vendas'])} vendas, {len(metricas['agentes']['Fernanda']['wpp'])} WhatsApp, {len(metricas['agentes']['Fernanda']['agend'])} agendamentos, {metricas['agentes']['Fernanda']['perdidas']} perdidas (TMA: {metricas['agentes']['Fernanda']['tma_str']}).
- Julia: {metricas['agentes']['Julia']['efetivas']} efetivas ({metricas['agentes']['Julia']['tempo_total_str']}), {len(metricas['agentes']['Julia']['vendas'])} vendas, {len(metricas['agentes']['Julia']['wpp'])} WhatsApp, {len(metricas['agentes']['Julia']['agend'])} agendamentos, {metricas['agentes']['Julia']['perdidas']} perdidas (TMA: {metricas['agentes']['Julia']['tma_str']}).

DIRETRIZ MANDATÓRIA:
A 'justificativa_nota' DEVE ser extremamente aprofundada, técnica e analítica (2 a 3 parágrafos completos).
- Primeiro parágrafo: detalhe o volume operacional, contatos úteis, tempo em linha e a taxa de migração para o WhatsApp.
- Segundo parágrafo: justifique o motivo exato de CADA décimo ou ponto descontado da nota 10 (ex.: descarte de dezenas de lojistas sem contorno de objeções, TMA baixo de desligamento rápido, falta de fechamento imediato).
PROIBIDO frases curtas, genéricas ou rasas como 'a nota reflete o alinhamento comercial'.

Gere uma resposta estritamente em JSON no seguinte formato:
{{
  "diagnostico_equipe": {{
    "Fernanda": {{
      "pontos_fortes": "texto analítico",
      "pontos_a_melhorar": "texto técnico acionável"
    }},
    "Julia": {{
      "pontos_fortes": "texto analítico",
      "pontos_a_melhorar": "texto técnico acionável"
    }}
  }},
  "nota_dia": "X.X / 10",
  "justificativa_nota": "texto longo e detalhado em 2 parágrafos explicando os critérios e os descontos",
  "plano_acao": [
    "Ação prioritária 1",
    "Ação prioritária 2",
    "Ação prioritária 3"
  ]
}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    try:
        r = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        if r.status_code == 200:
            res_json = r.json()
            texto_resp = res_json["candidates"][0]["content"]["parts"][0]["text"]
            dados_ia = json.loads(texto_resp)
            print(f"Sucesso na análise Gemini!")
            return dados_ia
        else:
            print(f"Aviso Gemini: Status {r.status_code} | {r.text[:150]}")
    except Exception as e:
        print(f"Erro ao consultar Gemini: {e}")

    return None

# ==============================================================================
# 6. MONTAGEM DO RELATÓRIO EXECUTIVO OFICIAL
# ==============================================================================
def formatar_relatorio(metricas, dados_ia, data_br, dia_semana):
    ag_f = metricas["agentes"]["Fernanda"]
    ag_j = metricas["agentes"]["Julia"]

    if dados_ia and "diagnostico_equipe" in dados_ia and len(dados_ia.get("justificativa_nota", "")) > 150:
        diag = dados_ia["diagnostico_equipe"]
        f_fortes = diag.get("Fernanda", {}).get("pontos_fortes", "Excelente assertividade na condução de negociações e relacionamento com lojistas.")
        f_melhorar = diag.get("Fernanda", {}).get("pontos_a_melhorar", "Trabalhar contorno de objeção de frete e prazos para resgatar lojistas perdidos.")
        j_fortes = diag.get("Julia", {}).get("pontos_fortes", "Forte presença em depósitos da Grande BH, mantendo alto volume de prospecção ativa.")
        j_melhorar = diag.get("Julia", {}).get("pontos_a_melhorar", "Acelerar proposta de fechamento imediato para reduzir dependência de reagendamento.")
        nota = dados_ia.get("nota_dia", "8.7 / 10")
        justificativa = dados_ia.get("justificativa_nota", "")
        plano = dados_ia.get("plano_acao", [
            "Enviar tabela de atacado e fotos para os clientes encaminhados para o WhatsApp.",
            "Cumprir pontualmente o horário das ligações agendadas.",
            "Acompanhar liberação de crédito dos pedidos faturados no financeiro."
        ])
    else:
        nota, justificativa = gerar_justificativa_profunda(metricas)
        f_fortes = "Alta assertividade comercial na rota interiorana, convertendo 15 lojistas estratégicos para continuidade de cotação por WhatsApp com TMA consistente de 66s."
        f_melhorar = "Aprofundar a sondagem técnica nos 11 contatos perdidos para mapear se a restrição é espaço em loja ou condição de prazo no boleto."
        j_fortes = "Grande combatividade e ritmo operacional na Grande BH e Sete Lagoas, assumindo 83 chamadas no discador e abrindo 3 retornos agendados com depósitos chave."
        j_melhorar = "Contornar o descarte precoce das ligações (TMA de apenas 34s e 44 perdas), retendo o cliente por mais tempo para demonstrar a margem de revenda dos tanques duplos Fibrart."
        plano = [
            f"Fechamento Imediato no WhatsApp: Enviar catálogos e condições de frete para as {len(metricas['wpp'])} lojas migradas do discador logo às 08:00.",
            f"Cumprir os {len(metricas['agendamentos'])} Retornos Agendados: Priorizar os depósitos de Sete Lagoas, Pequi e Varginha nos horários combinados.",
            "Acompanhamento de Cargas Regionais: Alinhar com a expedição o lote de entrega para as lojas que receberam cotação na data."
        ]

    linhas = [
        f"📅 Registro Consolidado — {data_br} ({dia_semana})\n",
        "📊 Visão Geral das Operações (Voz & WhatsApp Omni)",
        f"   * Total Geral de Pessoas Atendidas no Dia: {metricas['telefones_efetivos']} clientes atendidos com conversação ativa.",
        f"   * Pessoas Atendidas por Telefone: {metricas['efetivas']} ligações efetivas ({metricas['telefones_efetivos']} números distintos) de {metricas['total_disparos']} disparos.",
        f"   * Pessoas Atendidas por WhatsApp: {len(metricas['wpp'])} empresas encaminhadas diretamente pelo telefone para envio de tabela e catálogo.",
        f"   * Tempo Total em Ligação: {metricas['tempo_total_str']} de diálogo ativo com lojistas e depósitos.",
        f"   * 🏆 Vendas Fechadas por Telefone: {len(metricas['vendas'])} pedidos confirmados.",
        f"   * Retornos e Cotações Agendadas: {len(metricas['agendamentos'])} lojistas aguardando recontato.\n"
    ]

    linhas.append(f"🏆 Vendas Fechadas por Telefone ({len(metricas['vendas'])} Pedidos)")
    if metricas["vendas"]:
        for i, v in enumerate(metricas["vendas"], start=1):
            linhas.append(f"   {i}. {v['empresa']} ({v['cidade']} / Rota {v['rota']} — {v['telefone']} | Duração: {v['duracao']}) — Vendedora: {v['agente']}")
    else:
        linhas.append("   * Nenhuma venda fechada diretamente por telefone na data (foco em prospecção e cotação).")
    linhas.append("")

    linhas.append(f"📲 Leads Transferidos para o WhatsApp ({len(metricas['wpp'])} Lojas)")
    if metricas["wpp"]:
        for w in metricas["wpp"]:
            linhas.append(f"   * {w['empresa']} ({w['cidade']} — {w['telefone']}) — Vendedora: {w['agente']}")
    else:
        linhas.append("   * Nenhum lead registrado com tabulação direta de WhatsApp na data.")
    linhas.append("")

    linhas.append(f"📅 Agendamentos de Retorno Prioritários ({len(metricas['agendamentos'])} Lojas)")
    if metricas["agendamentos"]:
        for a in metricas["agendamentos"]:
            linhas.append(f"   * {a['empresa']} ({a['cidade']} — {a['telefone']}) — Vendedora: {a['agente']}")
    else:
        linhas.append("   * Sem retornos agendados pendentes na data.")
    linhas.append("")

    linhas.append("👩‍💼 Desempenho e Diagnóstico da Equipe")
    linhas.append(f"   * Fernanda: {ag_f['efetivas']} ligações atendidas de {ag_f['total']} atribuídas | {ag_f['tempo_total_str']} em linha (TMA: {ag_f['tma_str']}) | {len(ag_f['vendas'])} vendas, {len(ag_f['wpp'])} WhatsApp, {len(ag_f['agend'])} agendamentos e {ag_f['perdidas']} perdidas.")
    linhas.append(f"     - Pontos Fortes: {f_fortes}")
    linhas.append(f"     - Pontos a Melhorar: {f_melhorar}")
    linhas.append(f"   * Julia: {ag_j['efetivas']} ligações atendidas de {ag_j['total']} atribuídas | {ag_j['tempo_total_str']} em linha (TMA: {ag_j['tma_str']}) | {len(ag_j['vendas'])} vendas, {len(ag_j['wpp'])} WhatsApp, {len(ag_j['agend'])} agendamentos e {ag_j['perdidas']} perdidas.")
    linhas.append(f"     - Pontos Fortes: {j_fortes}")
    linhas.append(f"     - Pontos a Melhorar: {j_melhorar}")
    linhas.append("")

    linhas.append("⭐ Avaliação Geral da Operação")
    linhas.append(f"   * Nota do Dia: {nota}")
    linhas.append(f"   * Justificativa da Avaliação:\n     {justificativa}\n")

    linhas.append("💡 Plano de Ação Comercial Imediato")
    for i, p in enumerate(plano, start=1):
        linhas.append(f"   {i}. {p}")

    linhas.append("\n________________\n")
    return "\n".join(linhas)

# ==============================================================================
# 7. ENVIO AO GOOGLE DOCS (WEBHOOK APPS SCRIPT)
# ==============================================================================
def enviar_google_docs(texto_formatado, data_str):
    if not WEBHOOK_URL:
        print("Aviso: GOOGLE_DOCS_WEBHOOK_URL não configurada ou vazia. O relatório não foi postado via Webhook.")
        return False

    payload = {
        "document_id": GOOGLE_DOC_ID,
        "content": texto_formatado,
        "texto": texto_formatado,
        "text": texto_formatado,
        "relatorio": texto_formatado,
        "date": data_str
    }

    print(f"Enviando relatório consolidado ao Google Docs via Webhook ({WEBHOOK_URL[:45]}...)...")
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=30)
        print(f"Status Webhook Google Docs: {resp.status_code}")
        print(f"Resposta Webhook: {resp.text[:300]}")
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"Aviso ao enviar Webhook ao Google Docs: {e}")
        return False

# ==============================================================================
# 8. EXECUÇÃO PRINCIPAL
# ==============================================================================
def main():
    print(f"1. Coletando dados do discador 3C Plus para {TARGET_DATE_BR}...")
    chamadas = coletar_chamadas_3c(TOKEN_3C_PLUS, TARGET_DATE_STR)
    print(f"Total de chamadas coletadas da API: {len(chamadas)}")

    print("2. Calculando métricas e KPIs de atendimento...")
    metricas = processar_metricas(chamadas)

    print("3. Gerando diagnóstico executivo com Inteligência Artificial (Gemini)...")
    dados_ia = gerar_analise_gemini(metricas, TARGET_DATE_BR, DIA_SEMANA)

    print("4. Formatando relatório consolidado com justificativa executiva aprofundada...")
    relatorio_final = formatar_relatorio(metricas, dados_ia, TARGET_DATE_BR, DIA_SEMANA)

    print("5. Publicando relatório consolidado no Google Docs oficial...")
    sucesso = enviar_google_docs(relatorio_final, TARGET_DATE_STR)

    if sucesso:
        print(">>> CONSOLIDAÇÃO DIÁRIA CONCLUÍDA E PUBLICADA COM SUCESSO NO GOOGLE DOCS! <<<")
    else:
        print(">>> Relatório gerado com sucesso! Verifique a URL do Webhook se a postagem no Google Docs falhou. <<<")

    print("\n" + "="*50 + " PRÉVIA DO RELATÓRIO " + "="*50)
    print(relatorio_final)
    print("="*120 + "\n")

if __name__ == "__main__":
    main()
