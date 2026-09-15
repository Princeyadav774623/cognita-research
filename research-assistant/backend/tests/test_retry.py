"""invoke_with_retry wraps every LLM call in the system and had no coverage."""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from utils import (
    invoke_with_retry,
    _is_retryable,
    _is_model_unavailable,
    _retry_after_seconds,
    MAX_ATTEMPTS,
)


def _plain_llm(side_effect):
    """A stand-in that passes the isinstance(BaseChatModel) check, so the
    model-substitution path is reachable in tests."""
    llm = MagicMock(spec=BaseChatModel)
    llm.invoke.side_effect = side_effect
    llm.model_name = "openai/gpt-oss-120b"
    llm.temperature = 0.2
    llm.max_tokens = 512
    return llm


class TestClassification:
    @pytest.mark.parametrize("msg", [
        "Error code: 429 - rate_limit_exceeded",
        "503 Service Unavailable",
        "Connection aborted",
        "Request timed out",
    ])
    def test_transient_errors_are_retryable(self, msg):
        assert _is_retryable(Exception(msg)) is True

    @pytest.mark.parametrize("msg", [
        "400 Bad Request: invalid messages",
        "401 Unauthorized: bad api key",
        "context_length_exceeded",
    ])
    def test_client_errors_are_not_retryable(self, msg):
        """The old code retried these too, doubling the latency of a request
        that could never succeed."""
        assert _is_retryable(Exception(msg)) is False

    def test_model_unavailable_is_recognised(self):
        assert _is_model_unavailable(Exception("model_not_found")) is True
        assert _is_model_unavailable(Exception("429 rate limit")) is False


class TestRetryAfter:
    def test_parses_seconds_from_groq_message(self):
        exc = Exception("Rate limit reached. Please try again in 7.5s")
        assert _retry_after_seconds(exc) == 7.5

    def test_parses_milliseconds(self):
        assert _retry_after_seconds(Exception("try again in 500ms")) == 0.5

    def test_reads_retry_after_header(self):
        exc = Exception("429")
        exc.response = MagicMock()
        exc.response.headers = {"retry-after": "3"}
        assert _retry_after_seconds(exc) == 3.0

    def test_caps_absurd_waits(self):
        assert _retry_after_seconds(Exception("try again in 9000s")) == 20.0

    def test_returns_none_when_absent(self):
        assert _retry_after_seconds(Exception("boom")) is None


class TestInvoke:
    def test_returns_first_success_without_sleeping(self):
        llm = _plain_llm([MagicMock(content="ok")])
        with patch("utils.time.sleep") as sleep:
            assert invoke_with_retry(llm, []).content == "ok"
        sleep.assert_not_called()

    def test_retries_transient_then_succeeds(self):
        llm = _plain_llm([Exception("429 rate limit"), MagicMock(content="recovered")])
        with patch("utils.time.sleep") as sleep:
            assert invoke_with_retry(llm, []).content == "recovered"
        assert sleep.call_count == 1

    def test_does_not_retry_client_errors(self):
        llm = _plain_llm([Exception("400 Bad Request")])
        with patch("utils.time.sleep"):
            with pytest.raises(Exception, match="400"):
                invoke_with_retry(llm, [])
        assert llm.invoke.call_count == 1

    def test_honours_server_supplied_wait(self):
        llm = _plain_llm([Exception("try again in 2.5s"), MagicMock(content="ok")])
        with patch("utils.time.sleep") as sleep:
            invoke_with_retry(llm, [])
        sleep.assert_called_once_with(2.5)

    def test_gives_up_after_max_attempts(self):
        llm = _plain_llm([Exception("429 rate limit")] * (MAX_ATTEMPTS + 2))
        with patch("utils.time.sleep"):
            with pytest.raises(Exception, match="429"):
                invoke_with_retry(llm, [])
        assert llm.invoke.call_count == MAX_ATTEMPTS

    @patch("langchain_groq.ChatGroq")
    def test_model_substitution_is_logged_not_silent(self, mock_groq, caplog):
        """A swap changes answer quality; it must never happen quietly."""
        replacement = MagicMock()
        replacement.invoke.return_value = MagicMock(content="from fallback")
        mock_groq.return_value = replacement

        llm = _plain_llm([Exception("model_not_found")])
        with caplog.at_level("WARNING"):
            result = invoke_with_retry(llm, [])

        assert result.content == "from fallback"
        assert any("substituting" in r.getMessage().lower() for r in caplog.records)

    def test_structured_runnable_is_never_model_swapped(self):
        """Rebuilding a structured runnable as a bare ChatGroq drops the schema,
        so the caller's isinstance() check fails and it silently takes defaults.
        Raising lets the caller use its own JSON fallback instead."""
        structured = MagicMock()   # not a BaseChatModel
        structured.invoke.side_effect = Exception("model_not_found")

        with pytest.raises(Exception, match="model_not_found"):
            invoke_with_retry(structured, [])
        assert structured.invoke.call_count == 1


class TestTokenLedger:
    """cost_tracking was declared in state from the start and never written to,
    so the run cost — the number the Pro tier's margin depends on — was unknown."""

    def test_usage_metadata_is_accumulated(self):
        from utils import new_token_ledger, current_token_ledger, invoke_with_retry

        new_token_ledger()
        response = MagicMock(content="ok")
        response.usage_metadata = {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500}
        llm = _plain_llm([response])

        invoke_with_retry(llm, [])
        ledger = current_token_ledger()

        assert ledger["total_tokens"] == 1500
        assert ledger["input_tokens"] == 1200
        assert ledger["calls"] == 1
        assert ledger["by_model"]["openai/gpt-oss-120b"]["output_tokens"] == 300

    def test_falls_back_to_response_metadata_shape(self):
        from utils import new_token_ledger, current_token_ledger, invoke_with_retry

        new_token_ledger()
        response = MagicMock(content="ok")
        response.usage_metadata = None
        response.response_metadata = {"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        invoke_with_retry(_plain_llm([response]), [])

        assert current_token_ledger()["total_tokens"] == 15

    def test_a_response_without_usage_is_not_an_error(self):
        """Providers report usage inconsistently; a missing count must never
        break the call it is measuring."""
        from utils import new_token_ledger, current_token_ledger, invoke_with_retry

        new_token_ledger()
        response = MagicMock(content="ok")
        response.usage_metadata = None
        response.response_metadata = {}
        assert invoke_with_retry(_plain_llm([response]), []).content == "ok"
        assert current_token_ledger()["total_tokens"] == 0

    def test_cost_estimate_uses_configured_rates(self):
        from utils import estimate_cost_usd
        from config import get_settings

        s = get_settings()
        ledger = {"by_model": {
            s.groq_model_smart: {"calls": 1, "input_tokens": 1_000_000, "output_tokens": 1_000_000},
        }}
        expected = s.price_smart_input_per_mtok + s.price_smart_output_per_mtok
        assert estimate_cost_usd(ledger) == round(expected, 6)

    def test_unknown_model_contributes_nothing_rather_than_guessing(self):
        from utils import estimate_cost_usd
        ledger = {"by_model": {"some/unlisted-model": {"calls": 1, "input_tokens": 5_000_000, "output_tokens": 0}}}
        assert estimate_cost_usd(ledger) == 0.0

    def test_calls_outside_a_run_are_ignored(self):
        """No ledger set means no run in progress — recording must be a no-op,
        not a crash."""
        import utils
        from utils import invoke_with_retry
        utils._token_ledger.set(None)
        response = MagicMock(content="ok")
        response.usage_metadata = {"total_tokens": 99}
        assert invoke_with_retry(_plain_llm([response]), []).content == "ok"


class TestClientIP:
    """Behind a proxy, request.client.host is the proxy — identical for every
    visitor — so a per-IP limit became one global bucket for the whole app."""

    def _req(self, peer, xff=None):
        from starlette.requests import Request
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        scope = {"type": "http", "headers": headers, "client": (peer, 1234)}
        return Request(scope)

    def test_direct_connection_ignores_the_header(self):
        """With nothing in front of us the header is attacker-controlled."""
        from rate_limit_middleware import client_ip
        with patch("rate_limit_middleware.get_settings") as s:
            s.return_value.trusted_proxy_count = 0
            assert client_ip(self._req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"

    def test_one_proxy_returns_the_real_client(self):
        from rate_limit_middleware import client_ip
        with patch("rate_limit_middleware.get_settings") as s:
            s.return_value.trusted_proxy_count = 1
            # chain: client, then our proxy appended the client's address
            assert client_ip(self._req("10.0.0.1", "198.51.100.7")) == "198.51.100.7"

    def test_spoofed_entries_before_our_hops_are_ignored(self):
        from rate_limit_middleware import client_ip
        with patch("rate_limit_middleware.get_settings") as s:
            s.return_value.trusted_proxy_count = 1
            got = client_ip(self._req("10.0.0.1", "9.9.9.9, 198.51.100.7"))
            assert got == "198.51.100.7", "must take the hop we control, not the head"

    def test_short_chain_falls_back_to_peer(self):
        from rate_limit_middleware import client_ip
        with patch("rate_limit_middleware.get_settings") as s:
            s.return_value.trusted_proxy_count = 2
            assert client_ip(self._req("10.0.0.1", "198.51.100.7")) == "10.0.0.1"
