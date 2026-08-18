from fastapi import FastAPI

from app.api.routes import bot, commands, health, status

app = FastAPI(
    title="Meeting Bot Handler",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(bot.router)
app.include_router(commands.router)
app.include_router(status.router)


@app.get("/")
async def root():
    return {
        "service": "meeting-bot-handler",
        "status": "ok",
    }
