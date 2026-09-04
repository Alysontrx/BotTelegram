import os
import requests
import pymongo
import certifi
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import threading
from flask import Flask

# Carrega as variáveis de ambiente
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")

# Configura o Gemini
genai.configure(api_key=GEMINI_API_KEY)
model_gemini = genai.GenerativeModel('gemini-3.6-flash',
    system_instruction="Você é um assistente pessoal virtual amigável, prestativo e muito inteligente, criado no Telegram."
)

# ----------------- BANCO DE DADOS (MongoDB Atlas) -----------------
# Conecta ao MongoDB usando o certifi para evitar erros de SSL no Windows
mongo_client = pymongo.MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
db = mongo_client["telegram_bot"]
history_collection = db["history"]

def get_history(user_id, limit=20):
    """Busca as últimas mensagens do usuário no MongoDB."""
    # Busca ordenando do mais novo para o mais antigo, limitado a 20
    docs = list(history_collection.find({"user_id": user_id}).sort("_id", pymongo.DESCENDING).limit(limit))
    
    history = []
    # Inverte a ordem para ficar do mais antigo para o mais novo
    for doc in reversed(docs):
        history.append({'role': doc['role'], 'parts': [doc['text']]})
    return history

def save_message(user_id, role, text):
    """Salva uma mensagem no MongoDB."""
    history_collection.insert_one({
        "user_id": user_id,
        "role": role,
        "text": text
    })

def clear_history(user_id):
    """Apaga todo o histórico do usuário no MongoDB."""
    history_collection.delete_many({"user_id": user_id})
# -----------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /start"""
    await update.message.reply_text("Olá! Eu sou a IA Alyson.\n\nFui reconstruído com o cérebro do Google Gemini, gerador do Hugging Face e agora meu cérebro está hospedado na nuvem com MongoDB Atlas! Pode conversar comigo.")

async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /esquecer (Limpa a memória do MongoDB)"""
    user_id = update.message.from_user.id
    clear_history(user_id)
    await update.message.reply_text("Memória apagada da nuvem! ☁️ Prontinho, esqueci tudo o que conversamos. Qual o novo assunto?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto comuns usando Gemini com Memória (Chat)"""
    user_text = update.message.text
    user_id = update.message.from_user.id
    
    thinking_message = await update.message.reply_text("Pensando...")
    try:
        # Recupera o histórico do MongoDB
        history = get_history(user_id)
        
        # Inicia a sessão de chat com o histórico
        chat = model_gemini.start_chat(history=history)
        
        # Envia a mensagem e recebe a resposta
        response = chat.send_message(user_text)
        
        # Salva as duas mensagens no MongoDB (A do usuário, e a da IA)
        save_message(user_id, 'user', user_text)
        save_message(user_id, 'model', response.text)
        
        await thinking_message.edit_text(response.text)
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
        
        audio_file = genai.upload_file(path=audio_path)
        
        response = model_gemini.generate_content(
            ["Responda ao usuário baseado nesse áudio de forma super natural e direta, sem fazer introduções formais.", audio_file]
        )
        
        await thinking_message.edit_text(response.text)
        
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
        
        img_file = genai.upload_file(path=photo_path)
        prompt = update.message.caption or "Descreva esta imagem de forma detalhada."
        response = model_gemini.generate_content([prompt, img_file])
        
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
        
        response = requests.post(API_URL, headers=headers, json={"inputs": prompt})
        
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

def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY or not MONGODB_URI:
        print("Erro: Tokens ausentes no .env!")
        return

    # Testa a conexão com o MongoDB antes de iniciar o bot
    try:
        mongo_client.admin.command('ping')
        print("Conexão com MongoDB Atlas estabelecida com sucesso!")
    except Exception as e:
        print(f"Erro ao conectar no MongoDB Atlas: {e}")
        return

    # Inicia o servidor web em segundo plano para o Render não matar o bot
    threading.Thread(target=run_flask, daemon=True).start()

    import asyncio
    # Força a criação de um loop de eventos para o Telegram não dar crash de thread no Render
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gerar", generate_image))
    app.add_handler(CommandHandler("esquecer", forget))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Super Robô Híbrido rodando com MongoDB Atlas! (Nuvem)")
    app.run_polling()

if __name__ == '__main__':
    main()
