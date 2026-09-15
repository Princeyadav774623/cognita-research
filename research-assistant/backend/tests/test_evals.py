import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from graph.state import ResearchState
from graph.research_graph import create_initial_state, should_loop_or_report, should_continue_after_search
from agents.planner_agent import planner_agent, ResearchPlan
from agents.gap_analysis_agent import gap_analysis_agent, GapAnalysisResult
from agents.factcheck_agent import (
    factcheck_agent, ClaimsList, ClaimVerification, BatchedVerification, BatchedVerdict,
)


def make_eval_state(**kwargs) -> ResearchState:
    base = create_initial_state("What are the architectural differences between Transformer and SSM models?", "eval-session-1")
    base.update(kwargs)
    return base


class TestEvaluations:
    @patch("agents.planner_agent.ChatGroq")
    def test_planner_generates_sub_queries_with_structured_output(self, mock_groq_class):
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = ResearchPlan(
            sub_queries=[
                "Transformer attention mechanism scalability",
                "State Space Models Mamba architecture",
                "Transformer vs SSM compute benchmark comparison"
            ],
            strategy="Comparative architectural and benchmark analysis"
        )
        mock_llm.with_structured_output.return_value = mock_structured
        mock_groq_class.return_value = mock_llm

        state = make_eval_state()
        new_state = planner_agent(state)

        assert len(new_state["sub_queries"]) == 3
        assert "Transformer attention" in new_state["sub_queries"][0]
        assert new_state["current_step"] == "plan_done"

    def test_routing_after_search_handles_empty_and_filled(self):
        # A web dead end must no longer end the run. The user's own uploaded
        # documents may hold the answer, so an empty web result set falls
        # through to the corpus rather than straight to the report.
        empty_state = make_eval_state(search_results=[])
        assert should_continue_after_search(empty_state) == "corpus"

        filled_state = make_eval_state(search_results=[{"url": "https://a.com", "title": "A", "content": "c", "score": 1.0}])
        assert should_continue_after_search(filled_state) == "read"

    def test_gap_analysis_triggers_reflection_loop_when_insufficient(self):
        insufficient_state = make_eval_state(
            is_sufficient=False,
            iteration=1,
            max_iterations=2,
            overall_confidence=0.5
        )
        assert should_loop_or_report(insufficient_state) == "search"

    def test_gap_analysis_stops_at_max_iterations(self):
        max_iter_state = make_eval_state(
            is_sufficient=False,
            iteration=2,
            max_iterations=2,
            overall_confidence=0.5
        )
        # gap_analysis_agent sets is_sufficient=True when iteration >= max_iterations
        new_state = gap_analysis_agent(max_iter_state)
        assert new_state["is_sufficient"] is True
        assert should_loop_or_report(new_state) == "report"

    @pytest.mark.asyncio
    @patch("agents.factcheck_agent._gather_corroboration", new_callable=AsyncMock, return_value={})
    @patch("agents.factcheck_agent.ChatGroq")
    async def test_factcheck_structured_evaluation(self, mock_groq_class, _no_corroboration):
        mock_llm = MagicMock()
        mock_structured = MagicMock()

        def mock_invoke(messages):
            if "Extract the 5 most important" in messages[0].content:
                return ClaimsList(claims=["Mamba uses selective state spaces", "Transformers have quadratic complexity"])
            # One batched call now carries a verdict per claim, each judged
            # against its own evidence block.
            return BatchedVerification(verdicts=[
                BatchedVerdict(claim_index=0, verified=True, confidence=0.95, source="Arxiv 2024"),
                BatchedVerdict(claim_index=1, verified=True, confidence=0.95, source="Arxiv 2024"),
            ])

        mock_structured.invoke.side_effect = mock_invoke
        mock_llm.with_structured_output.return_value = mock_structured
        mock_groq_class.return_value = mock_llm

        state = make_eval_state(
            draft_answer="Mamba uses selective state spaces. Transformers have quadratic complexity.",
            source_documents=[{"title": "Arxiv", "url": "https://arxiv.org", "text": "Mamba introduces selective state spaces."}]
        )

        result = await factcheck_agent(state)
        assert len(result["verified_claims"]) == 2
        # Both claims scored 0.95, but the whole run rests on a single source,
        # so the score is capped regardless of how sure the verifier was.
        # Perfect claims over one document is not a confident answer.
        assert result["overall_confidence"] == 0.60
        assert any("source" in f["label"].lower() for f in result["confidence_factors"])
        assert result["confidence_to_improve"], "a capped score must say what would lift it"
        assert result["current_step"] == "factcheck_done"


class TestTriageRouting:
    """Triage decides how much work a question earns. Its failure modes matter
    more than its happy path: a broken classifier must cost time, never
    correctness."""

    @patch("agents.triage_agent.ChatGroq")
    def test_chat_message_is_answered_without_research(self, mock_groq):
        from agents.triage_agent import triage_agent, Triage
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = Triage(complexity="chat", reason="greeting")
        mock_llm.with_structured_output.return_value = mock_structured
        # The user-facing call is tagged for token streaming, so it goes
        # through with_config() first.
        mock_llm.with_config.return_value = mock_llm
        mock_llm.invoke.return_value = MagicMock(content="Hello! What would you like researched?")
        mock_groq.return_value = mock_llm

        out = triage_agent({"query": "hi", "session_id": "s", "user_id": None})

        assert out["complexity"] == "chat"
        assert out["max_iterations"] == 0
        assert "Hello" in out["final_report"]
        # A direct reply must not claim confidence it never earned.
        assert out["overall_confidence"] == 0.0
        assert out["verified_claims"] == []

    @patch("agents.triage_agent.ChatGroq")
    def test_simple_question_runs_a_single_pass(self, mock_groq):
        from agents.triage_agent import triage_agent, Triage
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = Triage(complexity="simple", reason="definitional")
        mock_llm.with_structured_output.return_value = mock_structured
        mock_groq.return_value = mock_llm

        out = triage_agent({"query": "what does RAG stand for?", "session_id": "s", "user_id": None})
        assert out["max_iterations"] == 1
        assert "final_report" not in out or not out.get("final_report")

    @patch("agents.triage_agent.ChatGroq")
    def test_falls_back_to_json_when_structured_output_breaks(self, mock_groq):
        """Groq's tool-call wrapper intermittently rejects its own valid
        generation. Without the JSON fallback triage degrades to always-deep
        and saves nothing."""
        from agents.triage_agent import triage_agent
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = RuntimeError("tool call validation failed")
        mock_llm.with_structured_output.return_value = mock_structured
        mock_llm.invoke.return_value = MagicMock(
            content='{"complexity": "simple", "reason": "single fact"}')
        mock_groq.return_value = mock_llm

        out = triage_agent({"query": "capital of France?", "session_id": "s", "user_id": None})
        assert out["complexity"] == "simple", "JSON fallback should have classified this"
        assert out["max_iterations"] == 1

    @patch("agents.triage_agent.ChatGroq")
    def test_fails_open_to_deep_when_everything_breaks(self, mock_groq):
        from agents.triage_agent import triage_agent
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = RuntimeError("down")
        mock_llm.invoke.side_effect = RuntimeError("also down")
        mock_groq.return_value = mock_llm

        out = triage_agent({"query": "anything", "session_id": "s", "user_id": None})
        # Under-researching a real question is the worse error.
        assert out["complexity"] == "deep"
        assert out["max_iterations"] == 2

    @patch("agents.triage_agent.ChatGroq")
    def test_unknown_label_is_treated_as_deep(self, mock_groq):
        from agents.triage_agent import triage_agent, Triage
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = Triage(complexity="banana", reason="?")
        mock_llm.with_structured_output.return_value = mock_structured
        mock_groq.return_value = mock_llm

        out = triage_agent({"query": "q", "session_id": "s", "user_id": None})
        assert out["complexity"] == "deep"

    def test_router_sends_chat_to_the_end_and_research_to_the_planner(self):
        from graph.research_graph import route_after_triage
        assert route_after_triage({"complexity": "chat"}) == "done"
        assert route_after_triage({"complexity": "simple"}) == "planner"
        assert route_after_triage({"complexity": "deep"}) == "planner"
        assert route_after_triage({}) == "planner"


class TestAssistantIdentity:
    """The base model volunteers its own identity unprompted — it answered
    "This is ChatGPT, built by OpenAI" to a plain greeting. The chat path is
    user-facing, so the prompt has to hold that down."""

    FORBIDDEN = ("chatgpt", "openai", "gemini", "llama", "anthropic", "claude")

    def test_prompt_forbids_claiming_another_identity(self):
        from agents.triage_agent import CHAT_SYSTEM_PROMPT
        lowered = CHAT_SYSTEM_PROMPT.lower()
        assert "cognita" in lowered
        # The instruction must name the impostors explicitly; a generic
        # "you are Cognita" was not enough to stop it in practice.
        assert "chatgpt" in lowered and "never identify" in lowered

    @patch("agents.triage_agent.ChatGroq")
    def test_fallback_reply_does_not_leak_a_vendor(self, mock_groq):
        """Even the hardcoded fallback, used when the LLM call fails, must not
        name another assistant."""
        from agents.triage_agent import triage_agent, Triage
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = Triage(complexity="chat", reason="greeting")
        mock_llm.with_structured_output.return_value = mock_structured
        mock_llm.with_config.return_value = mock_llm
        mock_llm.invoke.side_effect = RuntimeError("model down")
        mock_groq.return_value = mock_llm

        out = triage_agent({"query": "hi", "session_id": "s", "user_id": None})
        answer = out["final_report"].lower()
        assert answer, "a chat message must still get a reply"
        for bad in self.FORBIDDEN:
            assert bad not in answer
