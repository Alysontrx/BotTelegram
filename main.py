import os
import requests
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import threading
from flask import Flask
from supabase import create_client, Client

# Carrega as variáveis de ambiente
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

system_instruction = "Você é uma inteligência artificial criada pelo Alysontrx (seu criador, do gênero masculino). Aja como um assistente pessoal prestativo e muito inteligente no Telegram. IMPORTANTE: Vá direto ao ponto em suas respostas, não fique se apresentando nem dizendo o seu nome nas mensagens a menos que o usuário pergunte quem você é. IMPORTANTE 2: Não utilize formatação markdown (como asteriscos) em suas respostas. IMPORTANTE 3: Refira-se ao Alysontrx sempre no masculino (ex: 'criado pelo Alysontrx')."

# ----------------- BANCO DE DADOS (Supabase) -----------------
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_history(user_id, limit=200):
    """Busca as últimas mensagens do usuário no Supabase."""
    response = supabase.table("history").select("*").eq("user_id", user_id).order("id", desc=True).limit(limit).execute()
    docs = response.data
    
    history = []
    # Inverte a ordem para ficar do mais antigo para o mais novo
    for doc in reversed(docs):
        # Mapeia de volta para os roles padrão da OpenAI ('user' e 'assistant')
        role = 'assistant' if doc['role'] == 'model' else doc['role']
        history.append({"role": role, "content": doc['text']})
    return history

def save_message(user_id, role, text):
    """Salva uma mensagem no Supabase."""
    supabase.table("history").insert({
        "user_id": user_id,
        "role": role,
        "text": text
    }).execute()

def clear_history(user_id):
    """Apaga todo o histórico do usuário no Supabase."""
    supabase.table("history").delete().eq("user_id", user_id).execute()
# -----------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /start"""
    await update.message.reply_text("Olá! Eu sou a IA Alyson.\n\nFui reconstruído com o cérebro do Google Gemini, gerador do Hugging Face e agora meu cérebro está hospedado na nuvem com MongoDB Atlas! Pode conversar comigo.")

async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /esquecer (Limpa a memória do Supabase)"""
    user_id = update.message.from_user.id
    clear_history(user_id)
    await update.message.reply_text("Memória apagada da nuvem! ☁️ Prontinho, esqueci tudo o que conversamos. Qual o novo assunto?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto comuns usando Gemini com Memória (Chat)"""
    user_text = update.message.text
    user_id = update.message.from_user.id
    
    thinking_message = await update.message.reply_text("Pensando...")
    try:
        import asyncio
        import time
        import httpx
        import json
        start_time = time.time()
        
        # Recupera o histórico do MongoDB sem travar o loop
        history = await asyncio.to_thread(get_history, user_id)
        
        user_name = update.message.from_user.first_name
        
        # Constrói o array de mensagens
        dynamic_system_instruction = system_instruction + f" IMPORTANTE 4: Você está conversando agora mesmo com o seu criador, {user_name}. Trate-o com respeito e sempre use pronomes masculinos (ele/dele) ao se referir a ele."
        
        messages = [{"role": "system", "content": dynamic_system_instruction}] + history
        messages.append({"role": "user", "content": user_text})
        
        full_text = ""
        last_edit_time = 0
        from telegram.error import BadRequest
        
        # Faz a requisição normal (sem streaming) já que a Groq é extremamente rápida
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions", 
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-oss-20b",
                    "messages": messages,
                    "stream": False,
                    "temperature": 0.7,
                    "max_tokens": 1000,
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"Erro na API da Groq (Status {response.status_code}): {response.text}")
            
            data = response.json()
            full_text = data['choices'][0]['message']['content']
        
        # Atualização final com o texto completo
        clean_text = full_text.replace('**', '').replace('*', '')
        if not clean_text.strip():
            raise Exception(f"A API retornou uma resposta vazia! Debug: {response.text[:500]}")
            
        # Intercepta mensagens de recusa de segurança (Safety Filter)
        refusal_phrases = ["I'm sorry, but I can't help with that", "I cannot fulfill this request", "I cannot help with that"]
        is_refusal = any(phrase.lower() in clean_text.lower() for phrase in refusal_phrases)
        
        if is_refusal:
            clean_text = "Desculpe, meu filtro de segurança interno foi ativado. Eu não tenho permissão para ajudar com esse tipo de solicitação (como hacking ou invasões)."
            
        try:
            await thinking_message.edit_text(clean_text)
        except BadRequest:
            pass # Ignora erro se o texto for exatamente o mesmo
            
        # Salva as duas mensagens no Supabase apenas se NÃO for uma recusa (para não prender a IA no modo recusa)
        if not is_refusal:
            asyncio.create_task(asyncio.to_thread(save_message, user_id, 'user', user_text))
            asyncio.create_task(asyncio.to_thread(save_message, user_id, 'model', full_text))
        
    except Exception as e:
        print(f"Erro (Texto): {e}")
        await thinking_message.edit_text(f"Desculpe, ocorreu um erro com a nova inteligência artificial: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa áudios (Voice) recebidos"""
    await update.message.reply_text("🎧 A funcionalidade de áudio está temporariamente em manutenção enquanto atualizamos nossa inteligência artificial para o modelo gpt-5.2!")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa fotos recebidas"""
    await update.message.reply_text("👁️ A funcionalidade de visão está temporariamente em manutenção enquanto atualizamos nossa inteligência artificial para o modelo gpt-5.2!")

async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /gerar (usando API Hugging Face via FLUX)"""
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Por favor, diga o que você quer gerar. Exemplo:\n`/gerar um cachorro robô no espaço`", parse_mode='Markdown')
        return
        
    thinking_message = await update.message.reply_text("🎨 Pintando a sua imagem com inteligência FLUX... (isso pode levar alguns segundos)")
    try:
        import asyncio
        import requests
        
        API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
        
        if not HUGGINGFACE_API_KEY:
            raise Exception("Chave HUGGINGFACE_API_KEY ausente no ambiente.")
            
        headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
        
        def fetch_image():
            response = requests.post(API_URL, headers=headers, json={"inputs": prompt}, timeout=60)
            if response.status_code == 200:
                return response.content
            else:
                raise Exception(f"Status {response.status_code} - {response.text}")
                
        image_bytes = await asyncio.to_thread(fetch_image)
        
        await update.message.reply_photo(photo=image_bytes, caption=f"🎨 {prompt}")
        await thinking_message.delete()
            
    except Exception as e:
        print(f"Erro (Gerar Imagem): {e}")
        await thinking_message.edit_text(f"Desculpe, falha na conexão com o servidor de imagens. {e}")

# --- FLUXO WEB (Para manter o Render Free ativo) ---
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is running online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)
# ---------------------------------------------------

async def setup_commands(application):
    """Configura o menu azul do Telegram automaticamente"""
    await application.bot.set_my_commands([
        BotCommand("start", "Reiniciar o robô"),
        BotCommand("gerar", "Gerar uma imagem com IA"),
        BotCommand("esquecer", "Apagar memória e contexto")
    ])

def main():
    if not TELEGRAM_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
        print("Erro: Tokens ausentes no .env!")
        return

    # Testa a conexão com o Supabase antes de iniciar o bot
    try:
        supabase.table("history").select("id").limit(1).execute()
        print("Conexão com Supabase estabelecida com sucesso!")
    except Exception as e:
        print(f"Erro ao conectar no Supabase: {e}")
        return

    # Inicia o servidor web em segundo plano para o Render não matar o bot
    threading.Thread(target=run_flask, daemon=True).start()

    import asyncio
    # Força a criação de um loop de eventos para o Telegram não dar crash de thread no Render
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(setup_commands).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gerar", generate_image))
    app.add_handler(CommandHandler("esquecer", forget))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Super Robô Híbrido rodando com Supabase! (Nuvem rápida)")
    app.run_polling()

if __name__ == '__main__':
    main()
