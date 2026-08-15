import pytest
from unittest.mock import patch, MagicMock
from graph.state import ResearchState
from graph.research_graph import create_initial_state, should_loop_or_report, should_continue_after_search
from agents.planner_agent import planner_agent, ResearchPlan
from agents.gap_analysis_agent import gap_analysis_agent, GapAnalysisResult
from agents.factcheck_agent import factcheck_agent, ClaimsList, ClaimVerification


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
        empty_state = make_eval_state(search_results=[])
        assert should_continue_after_search(empty_state) == "report"

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

    @patch("agents.factcheck_agent.ChatGroq")
    def test_factcheck_structured_evaluation(self, mock_groq_class):
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        
        # When called with ClaimsList vs ClaimVerification
        def mock_invoke(messages):
            # If claim extraction prompt
            if "Extract the 5 most important" in messages[0].content:
                return ClaimsList(claims=["Mamba uses selective state spaces", "Transformers have quadratic complexity"])
            return ClaimVerification(verified=True, confidence=0.95, source="Arxiv 2024", explanation="Supported")

        mock_structured.invoke.side_effect = mock_invoke
        mock_llm.with_structured_output.return_value = mock_structured
        mock_groq_class.return_value = mock_llm

        state = make_eval_state(
            draft_answer="Mamba uses selective state spaces. Transformers have quadratic complexity.",
            source_documents=[{"title": "Arxiv", "url": "https://arxiv.org", "text": "Mamba introduces selective state spaces."}]
        )

        result = factcheck_agent(state)
        assert len(result["verified_claims"]) == 2
        assert result["overall_confidence"] == 0.95
        assert result["current_step"] == "factcheck_done"
