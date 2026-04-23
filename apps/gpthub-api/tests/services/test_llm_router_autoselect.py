import unittest
from unittest.mock import AsyncMock, patch

from app.services.llm_router import ClassificationResult, LLMRouter


class TestLLMRouterAutoselect(unittest.IsolatedAsyncioTestCase):
    def test_classifier_prompt_appends_user_message_when_placeholder_missing(self):
        prompt = LLMRouter._ensure_classifier_user_prompt(
            template="Classify request into CODING/GENERAL. Return only label.",
            rendered_prompt="Classify request into CODING/GENERAL. Return only label.",
            user_message="Напиши код на Python",
        )

        self.assertIn("User request:", prompt)
        self.assertIn("Напиши код на Python", prompt)

    async def test_low_confidence_classifier_uses_keyword_fallback(self):
        router = LLMRouter()
        messages = [{"role": "user", "content": "Напиши код FastAPI с тестами"}]

        with (
            patch("app.services.llm_router.settings.auto_classifier_confidence_threshold", 0.65),
            patch("app.services.llm_router.settings.auto_task_model_general", "mws-gpt-alpha"),
            patch("app.services.llm_router.settings.auto_task_model_coding", "qwen3-coder-480b-a35b"),
            patch.object(
                router,
                "_classify_autoselect_task",
                new=AsyncMock(return_value=ClassificationResult(label="GENERAL", confidence=0.2, reason="low")),
            ),
            patch.object(
                router,
                "_classify_autoselect_by_keywords",
                return_value=ClassificationResult(
                    label="CODING",
                    confidence=1.0,
                    reason="keyword:best=CODING,score=2,runner_up=0",
                ),
            ),
        ):
            selected_model, reason = await router._autoselect_model(messages)

        self.assertEqual(selected_model, "qwen3-coder-480b-a35b")
        self.assertIn("classifier_low_confidence:keyword_fallback", reason)
        self.assertIn("keyword_label=CODING", reason)


if __name__ == "__main__":
    unittest.main()
