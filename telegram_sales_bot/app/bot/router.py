from aiogram import Dispatcher

from app.bot.handlers import catalog, checkout, common, referral, tickets, tutorials, wallet
from app.bot.handlers.admin import admins, broadcasts, dashboard, lottery, orders, products, settings, users
from app.bot.middlewares.access_gate import AccessGateMiddleware
from app.bot.middlewares.antispam import AntiSpamMiddleware


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    anti_spam = AntiSpamMiddleware()
    access_gate = AccessGateMiddleware()
    dp.message.middleware(anti_spam)
    dp.callback_query.middleware(anti_spam)
    dp.message.middleware(access_gate)
    dp.callback_query.middleware(access_gate)

    dp.include_router(common.router)
    dp.include_router(catalog.router)
    dp.include_router(tutorials.router)
    dp.include_router(checkout.router)
    dp.include_router(wallet.router)
    dp.include_router(referral.router)
    dp.include_router(tickets.router)

    dp.include_router(dashboard.router)
    dp.include_router(orders.router)
    dp.include_router(products.router)
    dp.include_router(users.router)
    dp.include_router(broadcasts.router)
    dp.include_router(lottery.router)
    dp.include_router(admins.router)
    dp.include_router(settings.router)
    return dp
