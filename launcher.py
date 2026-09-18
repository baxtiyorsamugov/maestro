import asyncio
import logging
import os
import socket
import threading
import time
import webbrowser

ADMIN_HOST = "127.0.0.1"
ADMIN_PORT = 8002
ADMIN_URL = f"http://{ADMIN_HOST}:{ADMIN_PORT}/dashboard"
STATUS_URL = f"http://{ADMIN_HOST}:{ADMIN_PORT}/"


def run_admin() -> None:
    try:
        import uvicorn

        from admin_panel import app

        config = uvicorn.Config(
            app,
            host=ADMIN_HOST,
            port=ADMIN_PORT,
            log_level="info",
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.run()
    except Exception:
        logging.exception("Admin server failed")
        raise


def open_dashboard() -> None:
    if os.getenv("MAESTRO_OPEN_BROWSER", "1") == "0":
        return
    for _ in range(30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((ADMIN_HOST, ADMIN_PORT)) == 0:
                webbrowser.open(STATUS_URL)
                return
        time.sleep(1)
    logging.warning("Admin server did not become reachable; browser was not opened")


def run_bot_forever() -> None:
    while True:
        try:
            import bot

            logging.info("Starting Telegram bot polling")
            asyncio.run(bot.main())
        except Exception:
            logging.exception("Telegram bot failed; retrying in 30 seconds")
            time.sleep(30)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("maestro_launcher.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.info("Starting Maestro admin panel at %s", ADMIN_URL)

    threading.Thread(target=run_admin, name="maestro-admin", daemon=True).start()
    threading.Thread(target=open_dashboard, name="open-dashboard", daemon=True).start()

    if os.getenv("MAESTRO_SKIP_BOT", "0") == "1":
        logging.info("Telegram bot polling skipped by MAESTRO_SKIP_BOT=1")
        while True:
            time.sleep(3600)

    run_bot_forever()


if __name__ == "__main__":
    main()
