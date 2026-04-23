import unittest
from unittest.mock import AsyncMock, patch

from app.modules.model_court.schemas import ModelCourtCandidateResult
from app.modules.model_court import service


class TestModelCourtService(unittest.TestCase):
    def test_is_model_court_enabled_respects_gates(self):
        with patch.object(service.settings, 'model_court_enabled', True):
            self.assertFalse(
                service.is_model_court_enabled(
                    payload_model_court=True,
                    features={'model_court': True},
                    autopilot_enabled=True,
                )
            )
            self.assertTrue(
                service.is_model_court_enabled(
                    payload_model_court=True,
                    features=None,
                    autopilot_enabled=False,
                )
            )
            self.assertTrue(
                service.is_model_court_enabled(
                    payload_model_court=False,
                    features={'model_court': 1},
                    autopilot_enabled=False,
                )
            )

        with patch.object(service.settings, 'model_court_enabled', False):
            self.assertFalse(
                service.is_model_court_enabled(
                    payload_model_court=True,
                    features={'model_court': True},
                    autopilot_enabled=False,
                )
            )

    def test_select_candidate_models_for_coding_profile(self):
        with patch.object(service.settings, 'model_court_candidates_count', 3):
            models = service.select_candidate_models(
                selected_model='qwen3-coder-480b-a35b',
                user_text='Please debug this Python API endpoint',
                request_messages=[{'role': 'user', 'content': 'Please debug this Python API endpoint'}],
            )

        self.assertEqual(
            models,
            ['qwen3-coder-480b-a35b', 'glm-4.6-357b', 'mws-gpt-alpha'],
        )

    def test_select_candidate_models_for_vision_profile(self):
        with patch.object(service.settings, 'model_court_candidates_count', 3):
            models = service.select_candidate_models(
                selected_model='qwen-image',
                user_text='What is on this image?',
                request_messages=[
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': 'Analyze image'},
                            {'type': 'image_url', 'image_url': {'url': 'https://example.com/image.png'}},
                        ],
                    }
                ],
            )

        self.assertEqual(models, ['qwen2.5-vl-72b', 'qwen3-vl-30b-a3b-instruct', 'glm-4.6-357b'])

    def test_parse_judge_result_from_embedded_json(self):
        winner, rationale = service._parse_judge_result(
            'Judge output:\n{"winner_label":"B","rationale":"Most complete answer."}\nDone.'
        )
        self.assertEqual(winner, 'B')
        self.assertEqual(rationale, 'Most complete answer.')

    def test_parse_winner_label_supports_numeric_and_cyrillic(self):
        self.assertEqual(service._parse_winner_label('2', labels_in_order=['A', 'B', 'C']), 'B')
        self.assertEqual(service._parse_winner_label('Победитель: В'), 'B')

    def test_sanitize_rationale_removes_thinking_blocks(self):
        cleaned = service._sanitize_rationale('<think>hidden</think>  concise   rationale ')
        self.assertEqual(cleaned, 'concise rationale')

    def test_format_model_court_answer_includes_footer_and_winner(self):
        text = service.format_model_court_answer('Final answer', 'Because it is better', winner_model='glm-4.6-357b')
        self.assertIn('Final answer', text)
        self.assertIn('Model Court', text)
        self.assertIn('glm-4.6-357b', text)


class TestModelCourtServiceAsync(unittest.IsolatedAsyncioTestCase):
    async def test_judge_candidates_uses_parsed_json_verdict(self):
        candidates = [
            ModelCourtCandidateResult(label='A', model='model-a', response='short', latency_ms=200),
            ModelCourtCandidateResult(label='B', model='model-b', response='long and detailed', latency_ms=300),
        ]

        with patch.object(
            service.llm_router,
            'generate_text',
            new=AsyncMock(return_value='{"winner_label":"B","rationale":"<think>x</think> Stronger answer"}'),
        ):
            winner, rationale = await service._judge_candidates(
                judge_model='glm-4.6-357b',
                user_text='Compare answers',
                candidates=candidates,
            )

        self.assertEqual(winner.label, 'B')
        self.assertEqual(rationale, 'Stronger answer')

    async def test_judge_candidates_uses_label_only_recovery(self):
        candidates = [
            ModelCourtCandidateResult(label='A', model='model-a', response='answer A', latency_ms=200),
            ModelCourtCandidateResult(label='B', model='model-b', response='answer B', latency_ms=300),
        ]

        with patch.object(
            service.llm_router,
            'generate_text',
            new=AsyncMock(side_effect=['not valid json', '2']),
        ):
            winner, rationale = await service._judge_candidates(
                judge_model='glm-4.6-357b',
                user_text='Pick best',
                candidates=candidates,
            )

        self.assertEqual(winner.label, 'B')
        self.assertEqual(rationale, 'Победитель выбран судьей (label-only recovery).')

    async def test_judge_candidates_falls_back_on_judge_failure(self):
        candidates = [
            ModelCourtCandidateResult(label='A', model='model-a', response='this is clearly the best answer', latency_ms=500),
            ModelCourtCandidateResult(label='B', model='model-b', response='short', latency_ms=100),
        ]

        with patch.object(
            service.llm_router,
            'generate_text',
            new=AsyncMock(side_effect=RuntimeError('judge unavailable')),
        ):
            winner, rationale = await service._judge_candidates(
                judge_model='glm-4.6-357b',
                user_text='Pick best',
                candidates=candidates,
            )

        self.assertEqual(winner.label, 'A')
        self.assertIn('fallback-эвристике', rationale)

    async def test_run_model_court_raises_when_all_candidates_fail(self):
        failed = [
            ModelCourtCandidateResult(label='A', model='m1', response='', latency_ms=10, error='timeout'),
            ModelCourtCandidateResult(label='B', model='m2', response='', latency_ms=12, error='empty'),
        ]

        with (
            patch.object(service, 'select_candidate_models', return_value=['m1', 'm2']),
            patch.object(service, '_run_candidate', new=AsyncMock(side_effect=failed)),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await service.run_model_court(
                    selected_model='m1',
                    request_messages=[{'role': 'user', 'content': 'hello'}],
                    context_messages=[{'role': 'user', 'content': 'hello'}],
                    user_text='hello',
                    temperature=0.2,
                    max_tokens=128,
                )

        self.assertIn('All model court candidates failed', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
