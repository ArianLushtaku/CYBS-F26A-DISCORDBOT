from wsgiref import headers
from fastapi import Response
from utils import app, DISCORD_TOKEN
from bot_event import bot
import os

# At the bottom of your main.py, replace the current code with:


@app.head('/')
async def HEAD():
    return Response(status_code=200, headers=headers)

if __name__ == "__main__":
    import uvicorn
    import threading

    # Start FastAPI in a separate thread
    def run_fastapi():
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

    fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()

    # Start the Discord bot in the main thread
    bot.run(DISCORD_TOKEN)
