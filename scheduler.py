from datetime import datetime, timedelta, date
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from aiogram import Bot
import database as db
import logging

# 1. Напоминания за 24 часа и за 1 час
async def check_reminders(bot: Bot):
    logging.info("Проверка напоминаний...")
    now = datetime.now()
    
    async with db.async_session() as session:
        # Берем только одобренные записи
        query = select(db.Booking).where(db.Booking.status == "approved").options(
            joinedload(db.Booking.user),
            joinedload(db.Booking.service).joinedload(db.Service.catalog_service)
        )
        bookings = (await session.execute(query)).scalars().all()

        for b in bookings:
            try:
                b_time = datetime.strptime(b.datetime, "%Y-%m-%d %H:%M")
                lang = b.user.language_code or "ru"
                diff = b_time - now

                # Уведомление за 1 день (если осталось от 23 до 25 часов)
                if timedelta(hours=23) <= diff <= timedelta(hours=25) and not b.reminder_day_sent:
                    text = {
                        "uz": f"👋 Salom! Ertaga soat {b_time.strftime('%H:%M')} da sizni kutamiz.\nУслуга: {b.service.catalog_service.name}",
                        "ru": f"👋 Привет! Напоминаем о вашей завтрашней записи в {b_time.strftime('%H:%M')}.\nУслуга: {b.service.catalog_service.name}"
                    }[lang]
                    await bot.send_message(b.user.telegram_id, text)
                    b.reminder_day_sent = True

                # Уведомление за 1 час (если осталось от 45 до 75 минут)
                elif timedelta(minutes=45) <= diff <= timedelta(minutes=75) and not b.reminder_hour_sent:
                    text = {
                        "uz": f"⚡️ Eslatma! Bir soatdan keyin uchrashuvimiz bor. Manzilni unutmang! 😊",
                        "ru": f"⚡️ Напоминаем! Ждем вас через час. Пожалуйста, не опаздывайте! 😊"
                    }[lang]
                    await bot.send_message(b.user.telegram_id, text)
                    b.reminder_hour_sent = True
                
            except Exception as e:
                logging.error(f"Ошибка в напоминании {b.id}: {e}")
        
        await session.commit()

# 2. Напоминание через 20 дней (Пора стричься)
async def check_follow_ups(bot: Bot):
    logging.info("Проверка 'Пора стричься'...")
    # Ищем записи, которые были завершены ровно 20 дней назад
    target_date = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")

    async with db.async_session() as session:
        query = select(db.Booking).where(
            db.Booking.status == "completed",
            db.Booking.datetime.like(f"{target_date}%"),
            db.Booking.follow_up_sent == False
        ).options(joinedload(db.Booking.user), joinedload(db.Booking.stylist))
        
        bookings = (await session.execute(query)).scalars().all()

        for b in bookings:
            # Проверяем, не записался ли он уже снова (чтобы не быть навязчивым)
            recent = await session.scalar(
                select(db.Booking).where(db.Booking.user_id == b.user_id, db.Booking.datetime > b.datetime)
            )
            if recent:
                continue

            lang = b.user.language_code or "ru"
            # Ссылка сразу на этого же мастера
            link = f"https://t.me/maestro_bot?start={b.stylist_id}"
            
            text = {
                "uz": f"Salom, {b.user.first_name}! 👋\nOxirgi marta {b.stylist.name} bilan ko'rishganingizdan beri 20 kun o'tdi. Balki yangilanish vaqti kelgandir?\n👉 Yozilish: {link}",
                "ru": f"Привет, {b.user.first_name}! 👋\nПрошло 20 дней с визита к мастеру {b.stylist.name}. Пора обновить образ?\n👉 Записаться: {link}"
            }[lang]

            try:
                await bot.send_message(b.user.telegram_id, text, disable_web_page_preview=True)
                b.follow_up_sent = True
            except Exception as e:
                logging.error(f"Ошибка в follow-up: {e}")
        
        await session.commit()
        
async def check_subscription_expiry(bot: Bot):
    print(f"[{datetime.now()}] Проверка срока подписки мастеров...")
    today = date.today()
    
    async with db.async_session() as session:
        # Ищем активных мастеров, у которых есть дата окончания подписки
        users = (await session.execute(
            select(db.User).where(
                db.User.role == "stylist",
                db.User.is_active == True,
                db.User.subscription_until != None
            )
        )).scalars().all()

        for user in users:
            days_left = (user.subscription_until - today).days
            
            # Напоминаем за 7, 3 и 1 день
            if days_left in [7, 3, 1]:
                lang = user.language_code or "ru"
                text = {
                    "uz": f"<b>Tarif muddati yakunlanmoqda!</b>\nQolgan vaqt: {days_left} kun. Xizmatni uzaytirish uchun admin bilan bog'laning.",
                    "ru": f"<b>Срок тарифа истекает!</b>\nОсталось дней: {days_left}. Не забудьте продлить доступ, чтобы не потерять записи клиентов."
                }[lang]
                
                try:
                    await bot.send_message(user.telegram_id, text, parse_mode="HTML")
                except Exception as e:
                    print(f"Ошибка отправки уведомления мастеру {user.id}: {e}")