import os
import secrets
from datetime import date, timedelta

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from wtforms.fields import SelectField

import database as db

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "barber_secret_pass")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY") or secrets.token_urlsafe(32)


class MyBackend(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            request.session.update({"token": ADMIN_SECRET_KEY})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("token") == ADMIN_SECRET_KEY


authentication_backend = MyBackend(secret_key=ADMIN_SECRET_KEY)

app = FastAPI(title="BarberBot Admin")
admin = Admin(app, db.engine, authentication_backend=authentication_backend)


class CatalogServiceAdmin(ModelView, model=db.CatalogService):
    name = "Услуга каталога"
    name_plural = "Каталог услуг"
    icon = "fa-solid fa-book"

    column_list = [db.CatalogService.id, db.CatalogService.name]
    column_searchable_list = [db.CatalogService.name]
    column_sortable_list = [db.CatalogService.id, db.CatalogService.name]


class BarbershopAdmin(ModelView, model=db.Barbershop):
    name = "Барбершоп"
    name_plural = "Барбершопы"
    icon = "fa-solid fa-shop"

    column_list = [
        db.Barbershop.id,
        db.Barbershop.name,
        db.Barbershop.district,
        db.Barbershop.address,
        db.Barbershop.latitude,
        db.Barbershop.longitude,
    ]
    column_searchable_list = [
        db.Barbershop.name,
        db.Barbershop.district,
        db.Barbershop.address,
    ]
    column_sortable_list = [db.Barbershop.id, db.Barbershop.name, db.Barbershop.district]


class UserAdmin(ModelView, model=db.User):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"

    column_list = [
        db.User.id,
        db.User.first_name,
        db.User.phone_number,
        db.User.role,
        db.User.is_active,
        db.User.subscription_until,
    ]
    column_details_list = [
        db.User.id,
        db.User.telegram_id,
        db.User.first_name,
        db.User.phone_number,
        db.User.language_code,
        db.User.role,
        db.User.is_active,
        db.User.subscription_until,
    ]
    column_editable_list = [db.User.role, db.User.is_active, db.User.subscription_until]
    column_searchable_list = [db.User.first_name, db.User.phone_number, db.User.telegram_id]
    column_sortable_list = [db.User.id, db.User.first_name, db.User.role, db.User.subscription_until]

    form_overrides = {"role": SelectField}
    form_args = {
        "role": {
            "choices": [
                ("client", "client"),
                ("stylist", "stylist"),
                ("owner", "owner"),
            ]
        }
    }

    async def after_model_change(self, data: dict, model: db.User, is_created: bool, request: Request) -> None:
        async with db.async_session() as session:
            user = await session.get(db.User, model.id)
            if not user or user.role != "stylist":
                return

            existing_stylist = await session.scalar(
                select(db.Stylist).where(db.Stylist.user_id == user.id)
            )
            if existing_stylist:
                if not existing_stylist.name:
                    existing_stylist.name = user.first_name or f"Stylist {user.id}"
                    await session.commit()
                return

            default_barbershop = await session.scalar(
                select(db.Barbershop).order_by(db.Barbershop.id)
            )
            if not default_barbershop:
                return

            session.add(
                db.Stylist(
                    name=user.first_name or f"Stylist {user.id}",
                    user_id=user.id,
                    barbershop_id=default_barbershop.id,
                )
            )
            await session.commit()


class StylistAdmin(ModelView, model=db.Stylist):
    name = "Мастер"
    name_plural = "Мастера"
    icon = "fa-solid fa-scissors"

    column_list = [
        db.Stylist.id,
        db.Stylist.name,
        "user_account.first_name",
        "barbershop.name",
        db.Stylist.avg_rating,
    ]
    column_details_list = [
        db.Stylist.id,
        db.Stylist.name,
        "user_account.telegram_id",
        "user_account.first_name",
        "barbershop.name",
        db.Stylist.avg_rating,
    ]
    column_labels = {
        "user_account.first_name": "Аккаунт Telegram",
        "user_account.telegram_id": "Telegram ID",
        "barbershop.name": "Барбершоп",
    }
    column_searchable_list = [db.Stylist.name]
    column_sortable_list = [db.Stylist.id, db.Stylist.name, db.Stylist.avg_rating]


class ServiceAdmin(ModelView, model=db.Service):
    name = "Услуга мастера"
    name_plural = "Услуги мастеров"
    icon = "fa-solid fa-tag"

    column_list = [
        db.Service.id,
        "catalog_service.name",
        "stylist.name",
        db.Service.price,
        db.Service.duration_min,
    ]
    column_labels = {
        "catalog_service.name": "Услуга",
        "stylist.name": "Мастер",
        db.Service.duration_min: "Длительность, мин",
    }
    column_sortable_list = [db.Service.id, db.Service.price, db.Service.duration_min]


class ScheduleAdmin(ModelView, model=db.Schedule):
    name = "График"
    name_plural = "Графики мастеров"
    icon = "fa-solid fa-calendar-days"

    column_list = [
        db.Schedule.id,
        "stylist.name",
        db.Schedule.day_of_week,
        db.Schedule.start_time,
        db.Schedule.end_time,
    ]
    column_labels = {"stylist.name": "Мастер", db.Schedule.day_of_week: "День недели"}
    column_sortable_list = [db.Schedule.id, db.Schedule.day_of_week, db.Schedule.start_time]


class BookingAdmin(ModelView, model=db.Booking):
    name = "Запись"
    name_plural = "Записи"
    icon = "fa-solid fa-calendar-check"

    column_list = [
        db.Booking.id,
        "user.first_name",
        "stylist.name",
        "service.catalog_service.name",
        db.Booking.datetime,
        db.Booking.status,
        db.Booking.rating,
    ]
    column_labels = {
        "user.first_name": "Клиент",
        "stylist.name": "Мастер",
        "service.catalog_service.name": "Услуга",
    }
    column_searchable_list = [db.Booking.datetime, db.Booking.status]
    column_sortable_list = [db.Booking.id, db.Booking.datetime, db.Booking.status, db.Booking.rating]
    column_default_sort = [(db.Booking.datetime, True)]


class PortfolioAdmin(ModelView, model=db.Portfolio):
    name = "Фото портфолио"
    name_plural = "Портфолио"
    icon = "fa-solid fa-images"

    column_list = [db.Portfolio.id, "stylist.name", db.Portfolio.telegram_photo_file_id]
    column_labels = {"stylist.name": "Мастер", db.Portfolio.telegram_photo_file_id: "Telegram file_id"}
    column_sortable_list = [db.Portfolio.id]


admin.add_view(CatalogServiceAdmin)
admin.add_view(BarbershopAdmin)
admin.add_view(UserAdmin)
admin.add_view(StylistAdmin)
admin.add_view(ServiceAdmin)
admin.add_view(ScheduleAdmin)
admin.add_view(BookingAdmin)
admin.add_view(PortfolioAdmin)


@app.get("/health")
async def healthcheck():
    return {
        "status": "ok",
        "date": date.today().isoformat(),
        "trial_expiry_example": (date.today() + timedelta(days=30)).isoformat(),
    }


if __name__ == "__main__":
    uvicorn.run("admin_panel:app", host="0.0.0.0", port=8002, reload=True)
