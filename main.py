import os
import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import threading
from flask import Flask
from supabase import create_client, Client

# Carrega as variáveis de ambiente
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Configura o Gemini
client = genai.Client(api_key=GEMINI_API_KEY)
system_instruction = "Você é a IA Alyson, uma assistente pessoal virtual amigável, prestativa e muito inteligente no Telegram. Você sabe que o seu criador, dono e alfa é o Alysontrx. Sempre que perguntarem sobre quem te criou, afirme com orgulho que foi o Alysontrx. IMPORTANTE: Não utilize formatação markdown (como asteriscos) em suas respostas."

# ----------------- BANCO DE DADOS (Supabase) -----------------
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_history(user_id, limit=200):
    """Busca as últimas mensagens do usuário no Supabase."""
    response = supabase.table("history").select("*").eq("user_id", user_id).order("id", desc=True).limit(limit).execute()
    docs = response.data
    
    history = []
    # Inverte a ordem para ficar do mais antigo para o mais novo
    for doc in reversed(docs):
        history.append(types.Content(role=doc['role'], parts=[types.Part.from_text(text=doc['text'])]))
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
        start_time = time.time()
        
        print(f"[{time.strftime('%X')}] Buscando histórico...")
        # Recupera o histórico do MongoDB sem travar o loop
        history = await asyncio.to_thread(get_history, user_id)
        print(f"[{time.strftime('%X')}] Histórico carregado em {time.time() - start_time:.2f}s")
        
        # Inicia a sessão de chat com o histórico
        config = types.GenerateContentConfig(system_instruction=system_instruction)
        chat = client.aio.chats.create(model="gemini-3.6-flash", config=config, history=history)
        
        print(f"[{time.strftime('%X')}] Chamando Gemini...")
        gemini_start = time.time()
        # Envia a mensagem e recebe a resposta de forma assíncrona com stream
        response = await chat.send_message_stream(user_text)
        
        full_text = ""
        last_edit_time = 0
        from telegram.error import BadRequest
        
        async for chunk in response:
            full_text += chunk.text
            # Atualiza a mensagem no Telegram no máximo a cada 1 segundo (evita bloqueio)
            if time.time() - last_edit_time > 1.0:
                clean_text = full_text.replace('**', '').replace('*', '')
                if clean_text.strip():
                    try:
                        await thinking_message.edit_text(clean_text)
                        last_edit_time = time.time()
                    except BadRequest:
                        pass # Ignora erro se o texto for exatamente o mesmo
        
        # Atualização final com o texto completo
        clean_text = full_text.replace('**', '').replace('*', '')
        try:
            await thinking_message.edit_text(clean_text)
        except Exception as e:
            pass
            
        print(f"[{time.strftime('%X')}] Gemini terminou de responder em {time.time() - gemini_start:.2f}s")
        
        # Salva as duas mensagens no Supabase em segundo plano
        asyncio.create_task(asyncio.to_thread(save_message, user_id, 'user', user_text))
        asyncio.create_task(asyncio.to_thread(save_message, user_id, 'model', full_text))
        print(f"[{time.strftime('%X')}] Processamento total concluído em {time.time() - start_time:.2f}s")
    except Exception as e:
        print(f"Erro (Texto): {e}")
        await thinking_message.edit_text(f"Desculpe, ocorreu um erro com o Google Gemini: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa áudios (Voice) recebidos usando Gemini"""
    thinking_message = await update.message.reply_text("Ouvindo o áudio e pensando... 🎧")
    audio_path = "temp_audio.ogg"
    audio_file = None
    try:
        file = await update.message.voice.get_file()
        await file.download_to_drive(audio_path)
        
        # Lê os bytes do arquivo para enviar diretamente (evita o genai.upload_file que está dando erro de API Key)
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
            
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")
        
        response = await client.aio.models.generate_content(
            model="gemini-3.6-flash",
            contents=["Responda ao usuário baseado nesse áudio de forma super natural e direta, sem fazer introduções formais.", audio_part]
        )
        
        # Remove asteriscos para não afetar a fala
        clean_text = response.text.replace('**', '').replace('*', '')
        
        await thinking_message.edit_text("🎤 Gravando áudio...")
        
        import asyncio
        from gtts import gTTS
        tts = gTTS(text=clean_text, lang='pt', tld='com.br')
        tts_path = "resposta_audio.ogg"
        await asyncio.to_thread(tts.save, tts_path)
        
        # Envia o áudio gravado e apaga a mensagem de status
        await update.message.reply_voice(voice=open(tts_path, 'rb'))
        await thinking_message.delete()
        
        # Salva o histórico de áudio no Supabase
        user_id = update.message.from_user.id
        asyncio.create_task(asyncio.to_thread(save_message, user_id, 'user', '[Áudio Recebido]'))
        asyncio.create_task(asyncio.to_thread(save_message, user_id, 'model', clean_text))
        
        # Limpa o arquivo de áudio gerado
        if os.path.exists(tts_path):
            os.remove(tts_path)
        
    except Exception as e:
        print(f"Erro (Áudio): {e}")
        await thinking_message.edit_text(f"Desculpe, ocorreu um erro ao processar seu áudio: {e}")
    finally:
        if audio_file:
            try:
                audio_file.delete()
            except:
                pass
        if os.path.exists(audio_path):
            os.remove(audio_path)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa fotos recebidas usando Gemini Vision"""
    thinking_message = await update.message.reply_text("Analisando a imagem... 👁️")
    photo_path = "temp_photo.jpg"
    img_file = None
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        await file.download_to_drive(photo_path)
        
        import asyncio
        img_file = await asyncio.to_thread(client.files.upload, file=photo_path)
        prompt = update.message.caption or "Descreva esta imagem de forma detalhada."
        response = await client.aio.models.generate_content(model="gemini-3.6-flash", contents=[prompt, img_file])
        
        await thinking_message.edit_text(response.text)
        
    except Exception as e:
        print(f"Erro (Foto): {e}")
        await thinking_message.edit_text(f"Desculpe, não consegui analisar a imagem. Erro: {e}")
    finally:
        if img_file:
            try:
                img_file.delete()
            except:
                pass
        if os.path.exists(photo_path):
            os.remove(photo_path)

async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /gerar (usando Hugging Face Inference API)"""
    if not HUGGINGFACE_API_KEY:
         await update.message.reply_text("⚠️ A geração de imagens requer uma Chave do Hugging Face! Eu preciso que você me forneça a chave no Telegram (como te pedi) para habilitar isso.")
         return

    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Por favor, diga o que você quer gerar. Exemplo:\n`/gerar um cachorro robô no espaço`", parse_mode='Markdown')
        return
        
    thinking_message = await update.message.reply_text("🎨 Pintando a sua imagem com a IA Flux (Hugging Face)... (isso pode levar uns 30 segundos)")
    try:
        API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
        headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
        
        import asyncio
        response = await asyncio.to_thread(requests.post, API_URL, headers=headers, json={"inputs": prompt})
        
        if response.status_code == 200:
            image_bytes = response.content
            await update.message.reply_photo(photo=image_bytes, caption=f"🎨 {prompt}")
            await thinking_message.delete()
        else:
            error_msg = response.json().get('error', 'Erro desconhecido. Talvez o modelo esteja sobrecarregado.')
            await thinking_message.edit_text(f"Desculpe, o Hugging Face recusou o pedido: {error_msg}")
            
    except Exception as e:
        print(f"Erro (Gerar Imagem): {e}")
        await thinking_message.edit_text(f"Desculpe, falha na conexão com Hugging Face. {e}")

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
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
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
