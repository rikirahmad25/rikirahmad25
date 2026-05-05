from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TutorialVideo


class TutorialService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active(self) -> list[TutorialVideo]:
        result = await self.session.execute(
            select(TutorialVideo).where(TutorialVideo.is_active.is_(True)).order_by(TutorialVideo.sort_order.asc(), TutorialVideo.id.desc())
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[TutorialVideo]:
        result = await self.session.execute(select(TutorialVideo).order_by(TutorialVideo.id.desc()))
        return list(result.scalars().all())

    async def get(self, tutorial_id: int) -> TutorialVideo | None:
        return await self.session.get(TutorialVideo, tutorial_id)

    async def create(
        self,
        title: str,
        description: str | None = None,
        video_file_id: str = '',
        sort_order: int = 100,
        content_type: str = 'text',
        text_content: str | None = None,
        photo_file_id: str | None = None,
    ) -> TutorialVideo:
        metadata: dict[str, str] = {'content_type': content_type}
        if text_content:
            metadata['text_content'] = text_content
        if photo_file_id:
            metadata['photo_file_id'] = photo_file_id
        item = TutorialVideo(
            title=title,
            description=description,
            video_file_id=video_file_id or '',
            sort_order=sort_order,
            is_active=True,
            metadata_json=metadata,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def toggle(self, item: TutorialVideo) -> TutorialVideo:
        item.is_active = not item.is_active
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: TutorialVideo) -> None:
        await self.session.delete(item)
        await self.session.commit()
