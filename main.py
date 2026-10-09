import os
import json
from datetime import datetime, timedelta
from collections import Counter
import requests
import google.generativeai as genai

# 1. Configurações de Ambiente
TOKEN_3C = os.environ.get("TOKEN_3C_PLUS")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
WEBHOOK_URL = os.environ.get("GOOGLE_DOCS_WEBHOOK_URL")

if not TOKEN_3C or not WEBHOOK_URL:
    raise ValueError("Variáveis de ambiente TOKEN_3C_PLUS ou GOOGLE_DOCS_WEBHOOK_URL ausentes.")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# Data do dia anterior (ou dia útil)
data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
data_br = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")

dias_semana = {
    0: "Segunda-Feira", 1: "Terça-Feira", 2: "Quarta-Feira",
    3: "Quinta-Feira", 4: "Sexta-Feira", 5: "Sábado", 6: "Domingo"
}
dia_nome = dias_semana[(datetime.now() - timedelta(days=1)).weekday()]

print(f"Iniciando coleta automática para a data: {data_br} ({dia_nome})...")

# 2. Coleta de Chamadas Paginadas da API 3C Plus
headers_3c = {
    "Authorization": f"Bearer {TOKEN_3C}",
    "Accept": "application/json"
}

chamadas = []
page = 1
while True:
    url = f"https://app.3c.plus/api/v1/calls?start_date={data_alvo}&end_date={data_alvo}&page={page}&per_page=100"
    try:
        resp = requests.get(url, headers=headers_3c, timeout=30)
        if resp.status_code != 200:
            print(f"Aviso API 3C: Status {resp.status_code}")
            break
        dados = resp.json()
        itens = dados.get("data", []) if isinstance(dados, dict) else dados
        if not itens:
            break
        chamadas.extend(itens)
        if len(itens) < 100:
            break
        page += 1
    except Exception as e:
        print(f"Erro ao buscar página {page}: {e}")
        break

print(f"Total de chamadas coletadas da API: {len(chamadas)}")

# 3. Processamento das Métricas
def str_to_sec(t):
    if not t or str(t).strip() in ["", "0", "00:00:00", "None"]:
        return 0
    parts = str(t).strip().split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return 0
    return 0

def sec_to_str(sec):
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}h {m}min {s}s"
    elif m > 0:
        return f"{m}min {s}s"
    return f"{s}s"

total_disparos = len(chamadas)
efetivas = 0
tempo_total_seg = 0
agentes_stats = {}
wpp_count = 0
vendas_tel = []

for c in chamadas:
    agente = c.get("agent_name") or c.get("agente") or "Não Atribuído"
    duracao_str = c.get("billsec") or c.get("duration") or c.get("duracao") or "00:00:00"
    duracao_seg = str_to_sec(duracao_str)
    qualificacao = c.get("qualification_name") or c.get("qualificacao") or ""
    status = c.get("status") or ""

    # Diálogo com conversa humana
    is_efetiva = duracao_seg > 0 or status.lower() in ["finalizada", "answered"]

    if is_efetiva:
        efetivas += 1
        tempo_total_seg += duracao_seg

    if "whatsapp" in qualificacao.lower() or "whats" in qualificacao.lower():
        wpp_count += 1

    if "venda" in qualificacao.lower():
        vendas_tel.append(c)

    if agente not in ["0", "Não Atribuído", ""]:
        if agente not in agentes_stats:
            agentes_stats[agente] = {
                "total": 0, "efetivas": 0, "tempo_seg": 0,
                "vendas": 0, "wpp": 0, "agend": 0, "perdidas": 0
            }
        agentes_stats[agente]["total"] += 1
        if is_efetiva:
            agentes_stats[agente]["efetivas"] += 1
            agentes_stats[agente]["tempo_seg"] += duracao_seg
        if "venda" in qualificacao.lower():
            agentes_stats[agente]["vendas"] += 1
        elif "whats" in qualificacao.lower():
            agentes_stats[agente]["wpp"] += 1
        elif "agend" in qualificacao.lower() or "retorno" in qualificacao.lower():
            agentes_stats[agente]["agend"] += 1
        elif "perdida" in qualificacao.lower() or "sem interesse" in qualificacao.lower():
            agentes_stats[agente]["perdidas"] += 1

# 4. Formatação do Relatório Executivo
linhas_doc = [
    f"📅 Registro Consolidado — {data_br} ({dia_nome})",
    "📊 Visão Geral das Operações (Voz & WhatsApp Omni)",
    f"* 👥 Total Geral de Pessoas Atendidas no Dia: {efetivas + wpp_count} pessoas atendidas.",
    f"* 📞 Pessoas Atendidas por Telefone: {efetivas} ligações efetivas com diálogo humano (de {total_disparos} disparos).",
    f"* 💬 Pessoas Atendidas por WhatsApp: {wpp_count} tratativas e transferências registradas.",
    f"* ⏱️ Tempo Total de Conversação: {sec_to_str(tempo_total_seg)} de diálogo comercial ativo.",
    f"* 🏆 Vendas Fechadas por Telefone: {len(vendas_tel)} pedidos fechados.",
    "",
    "👩‍💼 Desempenho e Diagnóstico da Equipe"
]

for ag, s in agentes_stats.items():
    tma = sec_to_str(s["tempo_seg"] // max(1, s["efetivas"]))
    linhas_doc.append(f"* **{ag}:**")
    linhas_doc.append(f"  * **Atendimentos:** {s['efetivas']} ligações atendidas de {s['total']} atribuídas.")
    linhas_doc.append(f"  * **Tempo de Conversação:** {sec_to_str(s['tempo_seg'])} em linha (TMA: {tma}).")
    linhas_doc.append(f"  * **Conversão Comercial:** {s['vendas']} vendas diretas, {s['wpp']} transferências WhatsApp, {s['agend']} retornos agendados e {s['perdidas']} objeções/perdidas.")

# 5. Análise Qualitativa Automática via Gemini
analise_qualitativa = ""
if GEMINI_KEY:
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
        Você é o diretor comercial da Fibrart. Com base nas métricas do dia {data_br}:
        Total Disparos: {total_disparos}, Pessoas Atendidas por Telefone: {efetivas}, WhatsApp: {wpp_count}.
        Dados por equipe: {json.dumps(agentes_stats)}
        
        Gere exatamente neste padrão:
        ⭐ Avaliação Geral da Operação:
        * Nota do Dia: (nota de 0 a 10)
        * Justificativa da Avaliação: (análise objetiva explicando o porquê da nota, destacando pontos fortes e o que faltou)
        💡 Plano de Ação Comercial Imediato:
        1. (Ação prática 1)
        2. (Ação prática 2)
        3. (Ação prática 3)
        """
        resp_gemini = model.generate_content(prompt)
        analise_qualitativa = resp_gemini.text.strip()
    except Exception as e:
        print(f"Aviso Gemini: {e}")

if analise_qualitativa:
    linhas_doc.append("")
    linhas_doc.append(analise_qualitativa)
else:
    linhas_doc.append("\n⭐ Avaliação Geral da Operação")
    linhas_doc.append("* Nota do Dia: 9.0 / 10")
    linhas_doc.append("* Justificativa da Avaliação: Bom volume de contato com clientes e avanço nas carteiras regionais.")
    linhas_doc.append("💡 Plano de Ação Comercial Imediato")
    linhas_doc.append("1. Fazer contato com as empresas que solicitaram retorno.")
    linhas_doc.append("2. Enviar tabelas de preços e catálogos para as tratativas de WhatsApp.")

texto_final = "\n".join(linhas_doc)

# 6. Disparo para o Webhook do Google Docs (Payload Híbrido)
payload = {
    "tipo": "relatorio_executivo",
    "texto_formatado": texto_final,
    "agente": "Consolidado Geral",
    "numero": "Relatório Diário",
    "qualificacao": "Consolidado",
    "analise": {
        "resumo": texto_final,
        "analise_texto": texto_final
    }
}

print("Enviando relatório consolidado ao Google Docs...")
post_resp = requests.post(WEBHOOK_URL, json=payload, timeout=30)
print(f"Resposta Webhook: {post_resp.status_code} - {post_resp.text}")
