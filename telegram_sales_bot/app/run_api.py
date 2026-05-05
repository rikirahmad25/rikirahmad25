import uvicorn

from app.config import get_settings

settings = get_settings()


if __name__ == '__main__':
    uvicorn.run('app.api.app:app', host=settings.api_host, port=settings.api_port, reload=settings.app_debug)
