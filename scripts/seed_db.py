# Файл: seed_db.py
# Просто запускаем, чтобы он пересоздал таблицы по новой схеме.
# Стилисты пока не будут привязаны к юзерам, мы сделаем это командой.
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db

async def seed_data():
    print("🗑️ Пересоздаем таблицы по новой схеме...")
    async with db.engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.drop_all)
    await db.create_tables()

    async with db.async_session() as session:
        # 1. Барбершопы (С КООРДИНАТАМИ)
        shop1 = db.Barbershop(
            name="Top Chop",
            district="Mirzo Ulugbek",
            address="Mustaqillik, 15",
            # --- НОВЫЕ СТРОКИ ---
            latitude=41.3251,
            longitude=69.3378
            # --------------------
        )
        session.add(shop1)
        await session.flush()

        # ... остальной код (стилисты, услуги, расписание) без изменений ...

        # 2. Стилисты
        s1 = db.Stylist(name="Aziz", barbershop_id=shop1.id)
        s2 = db.Stylist(name="Dima", barbershop_id=shop1.id)
        session.add_all([s1, s2])
        await session.flush()

        # --- НОВАЯ ЛОГИКА СОЗДАНИЯ УСЛУГ ---
        # 1. Создаем Глобальный Каталог
        cat_soch = db.CatalogService(name="Erkaklar soch olish (Стрижка)")
        cat_soqol = db.CatalogService(name="Soqol (Борода)")
        cat_kompleks = db.CatalogService(name="Kompleks (Стрижка + Борода)")
        session.add_all([cat_soch, cat_soqol, cat_kompleks])
        await session.flush()  # Получаем их ID

        # 2. Создаем Услуги Мастеров, ссылаясь на каталог
        srv1 = db.Service(catalog_service_id=cat_soch.id, price=150000, duration_min=60, stylist_id=s1.id)
        srv2 = db.Service(catalog_service_id=cat_soqol.id, price=80000, duration_min=30, stylist_id=s1.id)
        srv3 = db.Service(catalog_service_id=cat_soch.id, price=100000, duration_min=60, stylist_id=s2.id)
        session.add_all([srv1, srv2, srv3])

        # 4. Расписание
        for day in range(1, 6):
            session.add(db.Schedule(stylist_id=s1.id, day_of_week=day, start_time="10:00", end_time="18:00"))
        for day in range(1, 7):
            session.add(db.Schedule(stylist_id=s2.id, day_of_week=day, start_time="09:00", end_time="17:00"))

        await session.commit()
        print("✅ База обновлена с новой структурой и координатами.")

def _guard() -> None:
    """Защита от запуска по боевой базе: скрипт делает drop_all()."""
    import os

    if os.getenv("DB_DRIVER", "sqlite").lower() != "sqlite":
        sys.exit(
            "ОТКАЗ: seed_db.py удаляет все таблицы и разрешён только при DB_DRIVER=sqlite.\n"
            "Текущий драйвер: " + os.getenv("DB_DRIVER", "sqlite")
        )
    if "--i-know-what-i-do" not in sys.argv:
        sys.exit(
            "ОТКАЗ: seed_db.py выполняет drop_all() и уничтожает все данные.\n"
            "Если это действительно нужно, запустите:\n"
            "    python scripts/seed_db.py --i-know-what-i-do"
        )


if __name__ == "__main__":
    _guard()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed_data())