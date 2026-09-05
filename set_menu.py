import asyncio
import os
from dotenv import load_dotenv
from telegram import Bot, BotCommand

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

async def main():
    bot = Bot(TELEGRAM_TOKEN)
    await bot.set_my_commands([
        BotCommand("start", "Reiniciar o robô"),
        BotCommand("gerar", "Gerar uma imagem com IA"),
        BotCommand("esquecer", "Apagar memória e contexto")
    ])
    print("Comandos do menu adicionados com sucesso!")

if __name__ == "__main__":
    asyncio.run(main())
