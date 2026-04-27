import json
import re

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

# @username (буквы/цифры/_/.). Дефис в username Django запрещён по умолчанию,
# но мы поддерживаем его — некоторые инсталляции с кастомным USERNAME_FIELD
# его разрешают. Стартовый @ должен быть либо в начале строки, либо после
# whitespace/punctuation, чтобы email-ы не превращались в упоминания.
MENTION_RE = re.compile(r"(?:^|(?<=[\s,;:!?(\[\"]))@([A-Za-z0-9_.\-]{2,32})")


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"chat_{self.room_id}"
        user = self.scope["user"]

        if user.is_anonymous:
            await self.close()
            return

        is_participant = await self._is_participant(user.pk, self.room_id)
        if not is_participant:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        body = (data.get("body") or "").strip()
        # Опциональное вложение: book_id (int) — выбранная пользователем книга из пикера.
        book_id_raw = data.get("book_id")
        try:
            book_id = int(book_id_raw) if book_id_raw not in (None, "", 0) else None
        except (TypeError, ValueError):
            book_id = None

        # Пустое сообщение без вложения — игнорируем
        if not body and book_id is None:
            return

        user = self.scope["user"]
        msg = await self._save_message(user.pk, self.room_id, body, book_id)

        # Если в сообщении есть @username и они являются участниками комнаты —
        # шлём отдельное Notification (KIND_MENTIONED). Делаем это после
        # _save_message, чтобы у нас был message_id для линка.
        mentioned_usernames = self._extract_mentions(body)
        if mentioned_usernames:
            await self._notify_mentions(
                actor_id=user.pk,
                actor_username=user.username,
                room_id=self.room_id,
                message_id=msg["id"],
                body=body,
                usernames=mentioned_usernames,
            )

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "message_id": msg["id"],
                "body": msg["body"],
                "username": msg["username"],
                "avatar_url": msg["avatar_url"],
                "avatar_gradient": msg["avatar_gradient"],
                "created_at": msg["created_at"],
                "book": msg.get("book"),  # None или dict с полями карточки
            },
        )

    @staticmethod
    def _extract_mentions(body: str) -> list[str]:
        """Возвращает уникальный список упомянутых @usernames (без @, lowercase)."""
        if not body:
            return []
        seen = set()
        out = []
        for m in MENTION_RE.finditer(body):
            uname = m.group(1).lower()
            if uname not in seen:
                seen.add(uname)
                out.append(uname)
        return out

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "id": event["message_id"],
            "body": event["body"],
            "username": event["username"],
            "avatar_url": event.get("avatar_url", ""),
            "avatar_gradient": event.get("avatar_gradient", "orchid"),
            "created_at": event["created_at"],
            "book": event.get("book"),
        }))

    async def chat_reaction(self, event):
        """Шлём клиентам обновлённую сводку реакций по сообщению."""
        await self.send(text_data=json.dumps({
            "type": "reaction",
            "message_id": event["message_id"],
            "counts": event["counts"],
        }))

    @database_sync_to_async
    def _is_participant(self, user_id, room_id):
        from .models import ChatParticipant
        return ChatParticipant.objects.filter(user_id=user_id, room_id=room_id).exists()

    @database_sync_to_async
    def _notify_mentions(self, actor_id, actor_username, room_id, message_id, body, usernames):
        """
        Создаёт Notification(KIND_MENTIONED) для каждого упомянутого участника комнаты.
        Ограничения:
          • упомянутый должен быть участником этой room (а не любого юзера сайта)
          • не уведомляем самого себя
          • дедуп — один пользователь = одно уведомление, даже если упомянут несколько раз
        """
        from .models import ChatParticipant
        from notifications.models import Notification

        if not usernames:
            return

        # Подбираем именно из participants комнаты — case-insensitive по username.
        participants = (
            ChatParticipant.objects
            .filter(room_id=room_id)
            .select_related("user")
        )
        targets = []
        lower_to_user = {p.user.username.lower(): p.user for p in participants}
        for uname in usernames:
            user = lower_to_user.get(uname.lower())
            if user and user.id != actor_id:
                targets.append(user)

        if not targets:
            return

        # Превью текста — обрезаем длинное body до 140 символов
        preview = (body or "").strip()
        if len(preview) > 140:
            preview = preview[:137].rstrip() + "…"
        text = f"{actor_username} упомянул вас: «{preview}»"
        url = f"/chat/{room_id}/#msg-{message_id}"

        notes = [
            Notification(
                user=u,
                kind=Notification.KIND_MENTIONED,
                actor_id=actor_id,
                text=text,
                url=url,
                extra={"room_id": room_id, "message_id": message_id},
            )
            for u in targets
        ]
        Notification.objects.bulk_create(notes)

    @database_sync_to_async
    def _save_message(self, user_id, room_id, body, book_id):
        from .models import ChatMessage
        from books.models import Book

        book = None
        if book_id:
            book = Book.objects.filter(pk=book_id).prefetch_related("authors").first()

        msg = ChatMessage.objects.create(
            user_id=user_id,
            room_id=room_id,
            body=body,
            attached_book=book,
        )

        book_payload = None
        if book:
            book_payload = {
                "id": book.pk,
                "title": book.title,
                "authors": ", ".join(a.name for a in book.authors.all()),
                "cover_url": book.cover_image.url if book.cover_image else "",
                "url": f"/books/{book.pk}/",
                "avg_rating": float(book.avg_rating) if book.avg_rating else None,
            }

        profile = getattr(msg.user, "profile", None)
        avatar_url = profile.avatar.url if profile and profile.avatar else ""
        avatar_gradient = profile.avatar_gradient if profile else "orchid"

        return {
            "id": msg.pk,
            "body": msg.body,
            "username": msg.user.username,
            "avatar_url": avatar_url,
            "avatar_gradient": avatar_gradient,
            "created_at": msg.created_at.strftime("%H:%M"),
            "book": book_payload,
        }
