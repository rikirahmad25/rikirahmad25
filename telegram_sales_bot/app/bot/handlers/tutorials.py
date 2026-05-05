from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.filters import MenuTextFilter
from app.bot.keyboards.user import tutorials_keyboard
from app.db.session import SessionLocal
from app.services.settings_service import SettingsService
from app.services.tutorial_service import TutorialService

router = Router(name='tutorials')


@router.message(MenuTextFilter('tutorials', '🎬 آموزش‌ها'))
async def tutorials_menu(message: Message) -> None:
    async with SessionLocal() as session:
        settings = SettingsService(session)
        features = await settings.get('features')
        texts = await settings.get('texts')
        tutorials = await TutorialService(session).list_active()
    if not features.get('tutorials_enabled', True):
        await message.answer('بخش آموزش‌ها فعلاً غیرفعال است.')
        return
    if not tutorials:
        await message.answer(texts.get('no_tutorials', 'فعلاً آموزشی ثبت نشده است.'))
        return
    await message.answer(texts.get('tutorials_title', 'آموزش‌های موجود:'), reply_markup=tutorials_keyboard(tutorials))


@router.callback_query(F.data.startswith('tutorial:view:'))
async def view_tutorial(callback: CallbackQuery) -> None:
    await callback.answer()
    tutorial_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        tutorial = await TutorialService(session).get(tutorial_id)
    if not tutorial or not tutorial.is_active:
        await callback.message.answer('این آموزش پیدا نشد یا غیرفعال است.')
        return
    meta = tutorial.metadata_json or {}
    content_type = meta.get('content_type') or ('video' if tutorial.video_file_id else 'text')
    text_content = meta.get('text_content') or tutorial.description or tutorial.title
    photo_file_id = meta.get('photo_file_id')

    if content_type == 'text':
        await callback.message.answer(text_content)
        return

    if content_type in {'photo', 'photo_text'}:
        if not photo_file_id:
            await callback.message.answer(text_content)
            return
        caption = text_content if content_type == 'photo_text' else None
        if caption and len(caption) > 1024:
            await callback.message.answer_photo(photo=photo_file_id)
            await callback.message.answer(caption)
        else:
            await callback.message.answer_photo(photo=photo_file_id, caption=caption)
        return

    caption = tutorial.description or tutorial.title
    if tutorial.video_file_id:
        await callback.message.answer_video(video=tutorial.video_file_id, caption=caption)
    else:
        await callback.message.answer(text_content)
