import unittest
from unittest.mock import AsyncMock, patch

from app.modules.openai_compat import service
from app.modules.openai_compat.schemas import ChatCompletionRequest


class TestMediaGalleryPayloadExtraction(unittest.TestCase):
    def test_extract_upload_prefers_source_ref_for_data_url(self):
        payload = ChatCompletionRequest(
            model="mws-gpt-alpha",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at this"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,abc",
                                "source_ref": "file-123",
                                "width": 640,
                                "height": 480,
                            },
                            "mime_type": "image/png",
                            "size_bytes": 2048,
                        },
                    ],
                }
            ],
        )

        extracted = service._extract_media_payloads_from_last_user_message(payload)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["url"], "file-123")
        self.assertEqual(extracted[0]["source_ref"], "file-123")
        self.assertEqual(extracted[0]["mime_type"], "image/png")
        self.assertEqual(extracted[0]["size_bytes"], 2048)
        self.assertEqual(extracted[0]["width"], 640)
        self.assertEqual(extracted[0]["height"], 480)

    def test_extract_upload_prefers_top_level_source_ref_for_data_url(self):
        payload = ChatCompletionRequest(
            model="mws-gpt-alpha",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at this"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,abc"},
                            "source_ref": "/api/v1/files/file-456/content",
                            "mime_type": "image/png",
                            "size_bytes": 1024,
                        },
                    ],
                }
            ],
        )

        extracted = service._extract_media_payloads_from_last_user_message(payload)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["url"], "/api/v1/files/file-456/content")
        self.assertEqual(extracted[0]["source_ref"], "/api/v1/files/file-456/content")
        self.assertEqual(extracted[0]["mime_type"], "image/png")
        self.assertEqual(extracted[0]["size_bytes"], 1024)


class TestMediaGalleryIngestion(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_skips_invalid_upload_item_and_continues(self):
        payload = ChatCompletionRequest(
            model="mws-gpt-alpha",
            chat_id="chat-1",
            parent_id="msg-1",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "images"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + ("a" * 25050)}},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,bbb"},
                            "source_ref": "file-okay",
                        },
                    ],
                }
            ],
        )

        with patch.object(service, "ingest_media_gallery_items", new=AsyncMock(return_value=1)) as ingest_mock:
            await service._ingest_media_gallery(
                payload=payload,
                user_id="user-1",
                thread_id="thread-1",
                selected_model="mws-gpt-alpha",
                user_text="images",
                assistant_text="",
            )

        ingest_mock.assert_awaited_once()
        ingest_items = ingest_mock.await_args.args[1]
        self.assertEqual(len(ingest_items), 1)
        self.assertEqual(ingest_items[0].media_url, "file-okay")
        self.assertEqual(ingest_items[0].chat_id, "chat-1")
        self.assertEqual(ingest_items[0].message_id, "msg-1")


class TestChatLinkContext(unittest.IsolatedAsyncioTestCase):
    def test_extract_chat_link_urls_normalizes_and_dedupes(self):
        text = (
            "Посмотри https://example.com/page. "
            "И еще https://example.com/page, "
            "а также https://docs.python.org/3/. "
            "И вот markdown-ссылка https://ru.wikipedia.org/wiki/Собачье_сердце** "
            "и валидная wiki-ссылка https://ru.wikipedia.org/wiki/Почтовое_и_телеграфное_отделение_(Лима)"
        )
        urls = service._extract_chat_link_urls(text)
        self.assertEqual(
            urls,
            [
                "https://example.com/page",
                "https://docs.python.org/3/",
                "https://ru.wikipedia.org/wiki/Собачье_сердце",
            ],
        )

    def test_extract_chat_link_urls_keeps_balanced_parentheses(self):
        text = "Ссылка: https://ru.wikipedia.org/wiki/Почтовое_и_телеграфное_отделение_(Лима)"
        urls = service._extract_chat_link_urls(text)
        self.assertEqual(
            urls,
            ["https://ru.wikipedia.org/wiki/Почтовое_и_телеграфное_отделение_(Лима)"],
        )

    async def test_build_chat_link_context_includes_fetched_content(self):
        original_mode = service.settings.deep_research_link_capture_mode
        service.settings.deep_research_link_capture_mode = "attach_and_chat_links"
        try:
            with patch.object(
                service,
                "fetch_webpage_excerpt",
                new=AsyncMock(
                    side_effect=[
                        "Example page content",
                        "Python docs content",
                    ]
                ),
            ):
                context = await service._build_chat_link_context(
                    "read https://example.com/page and https://docs.python.org/3/"
                )
        finally:
            service.settings.deep_research_link_capture_mode = original_mode

        self.assertIn("Context from links mentioned in the user message:", context)
        self.assertIn("https://example.com/page", context)
        self.assertIn("Example page content", context)


if __name__ == "__main__":
    unittest.main()
