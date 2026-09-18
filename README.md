# Maestro

Maestro is a Python application with a Telegram bot, local SQLite or MySQL database, and a FastAPI/sqladmin admin panel.

## Документация

| Документ | Что внутри |
|---|---|
| [CLAUDE.md](CLAUDE.md) | рабочая инструкция для агента: правила, запреты, команды |
| [docs/ROADMAP.md](docs/ROADMAP.md) | дорожная карта по фазам с чекбоксами — основной план работ |
| [docs/AUDIT.md](docs/AUDIT.md) | аудит: найденные баги и риски с приоритетами |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | текущая и целевая архитектура, модель данных |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | соглашения по коду, callback_data, локализации |
| [docs/UX_GUIDELINES.md](docs/UX_GUIDELINES.md) | правила пользовательского опыта |
| [docs/SECURITY.md](docs/SECURITY.md) | модель угроз и чек-лист перед продом |

## Setup

1. Create a fresh virtual environment. The old `venv` in this checkout points to a missing Python path, so recreate it.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

2. Create `.env` from `.env.example` and fill real values.

```powershell
Copy-Item .env.example .env
```

Required variables for the default local mode: `BOT_TOKEN`, `DB_DRIVER=sqlite`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`.

In the Windows `.exe`, the default SQLite database is created at:

```text
%LOCALAPPDATA%\Maestro\maestro.db
```

For MySQL deployment set `DB_DRIVER=mysql` and fill `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_NAME`. `DB_PASS` may be empty only if the database user has no password.

## Local Run

Run the bot only:

```powershell
python bot.py
```

Run the admin panel only:

```powershell
python admin_panel.py
```

Open:

- Status page: `http://127.0.0.1:8002/`
- Dashboard: `http://127.0.0.1:8002/dashboard`
- CRUD admin: `http://127.0.0.1:8002/admin`
- Health check: `http://127.0.0.1:8002/health`

Run bot and admin together:

```powershell
python launcher.py
```

## Windows EXE

Build:

```powershell
pyinstaller Maestro.spec
Copy-Item .env.example dist\Maestro\.env.example -Force
```

The final executable will be:

```text
dist\Maestro\Maestro.exe
```

Place a filled `.env` next to `dist\Maestro\Maestro.exe` before launching. Double-clicking `Maestro.exe` starts the local admin panel and Telegram bot polling, then opens the dashboard in the default browser.

The project uses PyInstaller `onedir` mode because one-file mode failed on this Windows environment while extracting Visual C++ runtime DLLs. Keep the full `dist\Maestro\` folder together when distributing the app.

If the database is not available or `.env` points to the wrong host/port, the app still opens a status page and keeps the admin server alive. The bot retries startup every 30 seconds until the database becomes available.

For technical smoke tests only, these environment flags are available:

- `MAESTRO_OPEN_BROWSER=0` disables automatic browser opening.
- `MAESTRO_SKIP_BOT=1` starts only the local admin server.

## Database Safety

Do not run `scripts/seed_db.py` against production. It contains `drop_all()` and recreates tables with demo data. The script refuses to start unless `DB_DRIVER=sqlite` and `--i-know-what-i-do` is passed.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q
```
