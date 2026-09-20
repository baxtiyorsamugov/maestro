# Образ для бота и админки: одна сборка, две команды запуска.
#
# 3.12 — та же версия, что стоит на боевом хостинге (см. .htaccess). Держать
# в контейнере другую значит однажды поймать разницу, которой нет локально.
#
# slim, а не alpine: alpine собирает asyncpg и greenlet из исходников,
# и образ выходит дольше и не меньше.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Tashkent

WORKDIR /app

# Зависимости отдельным слоем: правка кода не должна перекачивать пакеты.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Работа не от root: код в контейнере выполняет чужой ввод из Telegram.
RUN useradd --create-home --uid 10001 maestro \
    && chown -R maestro:maestro /app
USER maestro

# Команда задаётся в docker-compose: из одного образа поднимаются
# и бот (polling), и админка (uvicorn).
CMD ["python", "bot.py"]
