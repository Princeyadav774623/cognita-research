"""The model client.

Only the parts that are ours: parsing what comes back, and accounting for what
it cost. The provider's behaviour is not under test; our tolerance of it is.
"""
import pytest


class TestJsonParsing:
    """Models wrap JSON in prose or a fence more often than they emit it bare,
    and a pipeline that dies on that fails for a reason no user can act on."""

    def test_bare_json(self):
        from app.llm import _loads
        assert _loads('{"a": 1}') == {"a": 1}

    def test_a_fenced_block(self):
        from app.llm import _loads
        assert _loads('```json\n{"a": 1}\n```') == {"a": 1}

    def test_an_unlabelled_fence(self):
        from app.llm import _loads
        assert _loads('```\n{"a": 1}\n```') == {"a": 1}

    def test_json_buried_in_prose(self):
        from app.llm import _loads
        assert _loads('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}

    def test_a_bare_array_is_wrapped_rather_than_dropped(self):
        from app.llm import _loads
        assert _loads('[1, 2]') == {"items": [1, 2]}

    def test_unparseable_output_returns_none_rather_than_guessing(self):
        from app.llm import _loads
        assert _loads("I'd rather not") is None
        assert _loads("") is None
        assert _loads(None) is None


class TestLedger:
    def test_usage_accumulates_across_calls(self):
        from app.llm import _record, ledger
        with ledger() as book:
            _record("openai/gpt-oss-20b", {"prompt_tokens": 100,
                                           "completion_tokens": 20,
                                           "total_tokens": 120})
            _record("openai/gpt-oss-20b", {"prompt_tokens": 50,
                                           "completion_tokens": 10,
                                           "total_tokens": 60})
        assert book.calls == 2
        assert book.total == 180

    def test_an_unknown_model_contributes_no_cost_rather_than_a_guess(self):
        """An invented number reads as a measurement. Zero is honest."""
        from app.llm import _record, ledger
        with ledger() as book:
            _record("some-model-we-do-not-price", {"prompt_tokens": 1000,
                                                   "completion_tokens": 1000,
                                                   "total_tokens": 2000})
        assert book.total == 2000
        assert book.cost_usd() == 0.0

    def test_a_priced_model_produces_a_cost(self):
        from app.llm import _record, ledger
        with ledger() as book:
            _record("openai/gpt-oss-120b", {"prompt_tokens": 10_000,
                                            "completion_tokens": 1_000,
                                            "total_tokens": 11_000})
        assert 0 < book.cost_usd() < 1.0

    def test_calls_outside_a_ledger_are_ignored_not_an_error(self):
        from app.llm import _record
        _record("openai/gpt-oss-20b", {"total_tokens": 5})   # must not raise


class TestRetryAfter:
    def test_it_prefers_the_header(self):
        from app.llm import _retry_after
        resp = type("R", (), {"headers": {"retry-after": "12"}, "text": ""})()
        assert _retry_after(resp) == 12.0

    def test_it_falls_back_to_the_message_body(self):
        """Groq puts the wait in prose when it omits the header, and honouring
        it is the difference between finishing and burning the day's budget on
        retries."""
        from app.llm import _retry_after
        resp = type("R", (), {"headers": {},
                              "text": "Rate limit reached. Please try again in 7.5s."})()
        assert _retry_after(resp) == 7.5

    def test_no_hint_at_all_returns_none(self):
        from app.llm import _retry_after
        resp = type("R", (), {"headers": {}, "text": "nope"})()
        assert _retry_after(resp) is None
