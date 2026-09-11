"""Blinded and independent judging infrastructure for subjective quality evaluation.

Implements:
- Protocol `BenchmarkJudge`
- `DeterministicJudge`: rule-based rubric scoring for hermetic CI and fast evaluation
- `ModelJudge`: blinded model-backed pairwise judge via HowlPlane with independent provider tracking
- Position-bias tracking and randomized candidate ordering
"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Protocol, runtime_checkable

from howlwriter.evaluation.models import (
    BenchmarkCase,
    CandidateOutput,
    IndependenceStatus,
    PairwiseComparison,
)
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole

JUDGE_PROMPT_TEMPLATE = """You are an expert, impartial writing judge. Compare two candidate responses to the same assignment.
You are blinded: you do not know which model, system, or configuration produced Candidate A or Candidate B.

ASSIGNMENT TASK:
{task}

SPECIFIC REQUIREMENTS:
{requirements}

CANDIDATE A:
{candidate_a}

CANDIDATE B:
{candidate_b}

EVALUATION CRITERIA:
1. Clarity & Coherence: Is the writing clear, logically structured, and easy to follow?
2. Specificity & Depth: Does it provide precise technical depth and evidence rather than vague generalities?
3. Naturalness & Tone: Does it sound authentic, avoiding AI clichés, unnecessary buzzwords, and boilerplate?
4. Requirement Adherence: Does it satisfy the specific constraints and purpose of the prompt?
5. Conciseness: Does it avoid fluff, redundancy, and unnecessary filler?

Compare Candidate A and Candidate B carefully.
Output your evaluation strictly in JSON matching this format:
{{
  "winner": "A" | "B" | "TIE",
  "dimensions": {{
    "clarity": "A" | "B" | "TIE",
    "coherence": "A" | "B" | "TIE",
    "specificity": "A" | "B" | "TIE",
    "naturalness": "A" | "B" | "TIE",
    "organization": "A" | "B" | "TIE",
    "conciseness": "A" | "B" | "TIE"
  }},
  "rationale": "Concise paragraph explaining why one candidate is better, or why they are tied."
}}
"""


@runtime_checkable
class BenchmarkJudge(Protocol):
    """Protocol for pairwise evaluation judges."""

    def judge(
        self,
        case: BenchmarkCase,
        cand_1: CandidateOutput,
        cand_2: CandidateOutput,
        *,
        seed: int | None = None,
    ) -> PairwiseComparison: ...


class DeterministicJudge:
    """Zero-model, rule-based judge for hermetic CI and reproducible baseline comparison.

    Evaluates requirement coverage, slop words, and length compliance to determine
    the winner deterministically.
    """

    def judge(
        self,
        case: BenchmarkCase,
        cand_1: CandidateOutput,
        cand_2: CandidateOutput,
        *,
        seed: int | None = None,
    ) -> PairwiseComparison:
        from howlwriter.evaluation.metrics import (
            RequirementSatisfactionEvaluator,
            WritingQualitySignalsEvaluator,
        )

        req_eval = RequirementSatisfactionEvaluator()
        qual_eval = WritingQualitySignalsEvaluator()

        # Randomize which is A and which is B to test blinding and position tracking
        rng = random.Random(seed)
        cand_a, cand_b = (cand_1, cand_2) if rng.random() < 0.5 else (cand_2, cand_1)

        score_a_req = req_eval.evaluate(case, cand_a).score
        score_b_req = req_eval.evaluate(case, cand_b).score
        score_a_qual = qual_eval.evaluate(case, cand_a).score
        score_b_qual = qual_eval.evaluate(case, cand_b).score

        total_a = (score_a_req * 0.6) + (score_a_qual * 0.4)
        total_b = (score_b_req * 0.6) + (score_b_qual * 0.4)

        diff = total_a - total_b
        dimensions: dict[str, str] = {}

        if score_a_req > score_b_req + 0.05:
            dimensions["requirements"] = "A"
        elif score_b_req > score_a_req + 0.05:
            dimensions["requirements"] = "B"
        else:
            dimensions["requirements"] = "TIE"

        if score_a_qual > score_b_qual + 0.05:
            dimensions["quality_signals"] = "A"
        elif score_b_qual > score_a_qual + 0.05:
            dimensions["quality_signals"] = "B"
        else:
            dimensions["quality_signals"] = "TIE"

        if diff > 0.08:
            winner = "A"
            winning_system = cand_a.system_id
        elif diff < -0.08:
            winner = "B"
            winning_system = cand_b.system_id
        else:
            winner = "TIE"
            winning_system = "TIE"

        rationale = f"Deterministic comparison: Candidate A scored {total_a:.2f}, Candidate B scored {total_b:.2f}."

        return PairwiseComparison(
            case_id=case.id,
            candidate_a_system=cand_a.system_id,
            candidate_b_system=cand_b.system_id,
            winner=winner,
            winning_system=winning_system,
            dimension_scores=dimensions,
            rationale=rationale,
            judge_role="deterministic_evaluator",
            judge_provider="deterministic_local",
            judge_model="deterministic_rules_v1",
            independence_status=IndependenceStatus.INDEPENDENT.value,
            position_order=[cand_a.system_id, cand_b.system_id],
        )


class ModelJudge:
    """Blinded model-backed judge executing via HowlPlane with reviewer independence tracking."""

    def __init__(self, role: WritingRole = WritingRole.FINAL_REVIEWER) -> None:
        self.role = role

    def judge(
        self,
        case: BenchmarkCase,
        cand_1: CandidateOutput,
        cand_2: CandidateOutput,
        *,
        seed: int | None = None,
    ) -> PairwiseComparison:
        rng = random.Random(seed)
        cand_a, cand_b = (cand_1, cand_2) if rng.random() < 0.5 else (cand_2, cand_1)

        req_text = json.dumps(case.requirements or {}, indent=2)
        prompt = JUDGE_PROMPT_TEMPLATE.format(
            task=case.task,
            requirements=req_text,
            candidate_a=cand_a.text,
            candidate_b=cand_b.text,
        )

        bridge = get_howlplane_bridge()
        if not bridge.is_available():
            # Fall back to deterministic judging if model bridge is unconfigured
            fallback = DeterministicJudge()
            res = fallback.judge(case, cand_1, cand_2, seed=seed)
            res.rationale += " (Bridge unavailable; fell back to deterministic judge)"
            return res

        # Attempt reviewer independence: avoid provider of the candidates
        avoid_p = cand_a.provider or cand_b.provider
        independence_status = IndependenceStatus.INDEPENDENCE_NOT_VERIFIABLE.value
        judge_provider = ""
        judge_model = ""

        try:
            exec_res = bridge.execute_writing_role(
                role=self.role,
                prompt=prompt,
                avoid_provider=avoid_p,
            )
            raw_output = getattr(exec_res, "output", str(exec_res))
            judge_provider = getattr(exec_res, "provider", "") or ""
            judge_model = getattr(exec_res, "model", "") or ""

            if judge_provider:
                if avoid_p and judge_provider.lower() != avoid_p.lower():
                    independence_status = IndependenceStatus.INDEPENDENT.value
                else:
                    independence_status = IndependenceStatus.SAME_PROVIDER.value
            else:
                independence_status = IndependenceStatus.INDEPENDENCE_NOT_VERIFIABLE.value

            # Parse JSON from model output
            parsed = self._extract_json(raw_output)
            winner = parsed.get("winner", "TIE").upper()
            if winner not in ("A", "B", "TIE"):
                winner = "INCONCLUSIVE"

            winning_system = "TIE"
            if winner == "A":
                winning_system = cand_a.system_id
            elif winner == "B":
                winning_system = cand_b.system_id
            elif winner == "INCONCLUSIVE":
                winning_system = "INCONCLUSIVE"

            return PairwiseComparison(
                case_id=case.id,
                candidate_a_system=cand_a.system_id,
                candidate_b_system=cand_b.system_id,
                winner=winner,
                winning_system=winning_system,
                dimension_scores=parsed.get("dimensions", {}),
                rationale=parsed.get("rationale", ""),
                judge_role=self.role.value,
                judge_provider=judge_provider,
                judge_model=judge_model,
                independence_status=independence_status,
                position_order=[cand_a.system_id, cand_b.system_id],
            )
        except Exception as err:
            # On error, record inconclusive pairwise result rather than aborting benchmark
            return PairwiseComparison(
                case_id=case.id,
                candidate_a_system=cand_a.system_id,
                candidate_b_system=cand_b.system_id,
                winner="INCONCLUSIVE",
                winning_system="INCONCLUSIVE",
                rationale=f"Model judge failed: {err}",
                judge_role=self.role.value,
                judge_provider=judge_provider,
                judge_model=judge_model,
                independence_status=independence_status,
                position_order=[cand_a.system_id, cand_b.system_id],
            )

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        match2 = re.search(r"(\{.*\})", text, re.DOTALL)
        if match2:
            try:
                return json.loads(match2.group(1))
            except Exception:
                pass
        return {}


class ScriptedJudge:
    """Scripted judge for testing and verification."""

    def __init__(self, winner_choice: str = "TIE") -> None:
        self.winner_choice = winner_choice

    def judge(
        self,
        case: BenchmarkCase,
        cand_1: CandidateOutput,
        cand_2: CandidateOutput,
        *,
        seed: int | None = None,
    ) -> PairwiseComparison:
        winner = self.winner_choice
        winning_sys = "TIE"
        if winner == "A":
            winning_sys = cand_1.system_id
        elif winner == "B":
            winning_sys = cand_2.system_id

        return PairwiseComparison(
            case_id=case.id,
            candidate_a_system=cand_1.system_id,
            candidate_b_system=cand_2.system_id,
            winner=winner,
            winning_system=winning_sys,
            dimension_scores={"clarity": winner},
            rationale="Scripted test outcome.",
            judge_role="scripted",
            judge_provider="mock",
            judge_model="mock_v1",
            independence_status=IndependenceStatus.INDEPENDENT.value,
            position_order=[cand_1.system_id, cand_2.system_id],
        )
