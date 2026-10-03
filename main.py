import os
import json
import tempfile
import requests
from datetime import datetime, timedelta
from google import genai

# ==============================================================
# CONFIGURAÇÕES (Lidas com segurança dos Secrets do GitHub)
# ==============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TOKEN_3C_PLUS = os.getenv("TOKEN_3C_PLUS") # Token de Gestor da 3C Plus
GOOGLE_DOCS_WEBHOOK_URL = os.getenv("GOOGLE_DOCS_WEBHOOK_URL")

client = genai.Client(api_key=GEMINI_API_KEY)

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
    """Consulta a API oficial da 3C Plus para obter as ligações do dia."""
    url = f"https://app.3c.plus/api/v1/calls?api_token={TOKEN_3C_PLUS}&start_date={data_alvo}&end_date={data_alvo}"
    print(f"Buscando ligações no 3C Plus para a data: {data_alvo}...")
    
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    
    dados = response.json()
    # A depender do formato da 3C Plus, pega a lista em 'data' ou raiz
    ligacoes = dados.get("data", dados) if isinstance(dados, dict) else dados
    print(f"Total de chamadas encontradas na API: {len(ligacoes)}")
    return ligacoes

def processar_e_enviar():
    # Data de ontem (D-1)
    data_alvo = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Iniciando consolidação do dia {data_alvo}...")

    ligacoes = buscar_ligacoes_3c(data_alvo)
    
    # Filtra apenas ligações finalizadas com áudio gravado
    chamadas_com_audio = [c for c in ligacoes if c.get("recording") and c.get("status") == 7 or c.get("speaking_with_agent_time")]
    print(f"Chamadas com gravação e conversação ativa: {len(chamadas_com_audio)}")

    for chamada in chamadas_com_audio:
        call_id = chamada.get("id")
        agente = chamada.get("agent", "Desconhecido")
        numero = chamada.get("number", "Não informado")
        qualificacao = chamada.get("qualification", "Sem tabulação")
        recording_url = chamada.get("recording")

        print(f"\n--- Processando Chamada {call_id} ({agente} ➔ {numero}) ---")
        
        temp_audio_path = None
        try:
            # 1. Download do áudio com o token da 3C Plus
            audio_url = f"{recording_url}?api_token={TOKEN_3C_PLUS}" if "api_token" not in recording_url else recording_url
            resp_audio = requests.get(audio_url, stream=True, timeout=60)
            resp_audio.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
                for chunk in resp_audio.iter_content(chunk_size=16384):
                    tmp_file.write(chunk)
                temp_audio_path = tmp_file.name

            # 2. Upload e Análise com o Gemini
            print("Enviando áudio para o Gemini 3.8 Flash...")
            uploaded_file = client.files.upload(file=temp_audio_path)
            
            resposta = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[uploaded_file, PROMPT_ANALISE]
            )
            
            texto_limpo = resposta.text.strip().replace("```json", "").replace("```", "")
            try:
                analise_json = json.loads(texto_limpo)
            except Exception:
                analise_json = {"analise_texto": resposta.text}

            # 3. Monta o payload para o Google Docs
            registro = {
                "id": call_id,
                "data_hora": chamada.get("call_date", data_alvo),
                "agente": agente,
                "numero": numero,
                "qualificacao": qualificacao,
                "analise": analise_json
            }

            # 4. Envia direto para o Google Apps Script do Google Docs
            print("Entregando análise no Google Docs...")
            resp_doc = requests.post(GOOGLE_DOCS_WEBHOOK_URL, json=registro, timeout=30)
            print(f"Status no Google Docs: {resp_doc.status_code}")

        except Exception as e:
            print(f"Erro ao processar chamada {call_id}: {e}")
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)

    print("\nConsolidação diária finalizada com sucesso!")

if __name__ == "__main__":
    processar_e_enviar()
