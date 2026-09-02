#!/usr/bin/env python3
"""Dogfood experiment runner for Contextual Structural Variance v1.

Evaluates 20 diverse sparse prompts across:
  A. Baseline Model (raw LLM generation)
  B. Medium-Only (WritingMode.LINKEDIN without personal voice profile)
  C. Full HowlWriter + Active Contextual Voice (william profile under LinkedIn mode)

Extracts metrics, checks diversity preservation, evaluates structural variance,
and saves honest, un-cherry-picked results for review.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import time
from typing import Any

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.humanize.rewriter import ModelHumanizerRewriter
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.linting.engine import LintEngine
from howlwriter.voice.corpus import diversity as diversity_stage
from howlwriter.voice.corpus.features import DocumentFeatures, extract_features
from howlwriter.voice.corpus.store import VoiceStore

DOGFOOD_DIR = Path(__file__).resolve().parent
RESULTS_DIR = DOGFOOD_DIR / "structural_variance_experiment_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PROMPTS = [
    # 5 Technical / Systems Opinions
    {
        "id": "prompt_01",
        "category": "Technical: DB Connection Pooling",
        "sparse_text": (
            "Connection pooling sizing: Why setting max connections to 500 on a 16-core PostgreSQL "
            "instance is almost always worse than 30-50 connections with queuing. Make into a LinkedIn post."
        ),
    },
    {
        "id": "prompt_02",
        "category": "Technical: 2PC vs Saga Pattern",
        "sparse_text": (
            "Distributed state: Why two-phase commit is often the wrong tool for microservices "
            "compared to idempotent saga retries and outbox pattern. Make into a short professional post."
        ),
    },
    {
        "id": "prompt_03",
        "category": "Technical: Rust Memory Safety Invariants",
        "sparse_text": (
            "Memory safety vs runtime complexity: Rewriting working C/C++ services in Rust is about "
            "invariant verification at compile time, not just preventing buffer overflows. "
            "Make into an engineering post."
        ),
    },
    {
        "id": "prompt_04",
        "category": "Technical: Observability Cardinality",
        "sparse_text": (
            "Observability cardinality: Adding user_id as a high-cardinality Prometheus metric label "
            "turns a time-series DB into an OOM incident. Turn into a concise technical post."
        ),
    },
    {
        "id": "prompt_05",
        "category": "Technical: Cache Invalidation SLA",
        "sparse_text": (
            "Cache invalidation reality: If cache TTL is your primary consistency mechanism, you don't "
            "have a cache, you have eventual inconsistency with an SLA you can't measure. "
            "Make into a sharp post."
        ),
    },
    # 5 Career / Engineering Culture
    {
        "id": "prompt_06",
        "category": "Culture: Staff+ Uncomfortable Questions",
        "sparse_text": (
            "Staff+ engineering myth: Being a Staff engineer is not about having all the architectural "
            "answers; it's about asking uncomfortable questions before 20 engineers spend six months "
            "building the wrong thing. Make into a post."
        ),
    },
    {
        "id": "prompt_07",
        "category": "Culture: Reading vs Writing Code",
        "sparse_text": (
            "Reading code vs writing code: 80% of real software engineering is understanding existing "
            "systems and constraints, but we still interview like the goal is typing speed from a "
            "blank screen. Make into a LinkedIn post."
        ),
    },
    {
        "id": "prompt_08",
        "category": "Culture: Blameless Postmortems",
        "sparse_text": (
            "Blameless postmortems in practice: If a postmortem concludes 'engineer made a mistake in "
            "production', the postmortem failed to identify the tooling and guardrail gaps that allowed "
            "a single mistake to cause an outage. Make into a post."
        ),
    },
    {
        "id": "prompt_09",
        "category": "Culture: Generalist Systems Engineers",
        "sparse_text": (
            "Generalist vs specialist systems engineers: Depth in one database engine is useful for "
            "three years; understanding concurrency, queuing theory, and failure domains is useful for "
            "a whole career. Make into a concise post."
        ),
    },
    {
        "id": "prompt_10",
        "category": "Culture: Promotion-Driven Architecture",
        "sparse_text": (
            "Promotion-driven development: Complex distributed systems built solely to justify "
            "promotion packets leave behind operational debt that burdens teams for years after the "
            "author moves on. Make into a post."
        ),
    },
    # 5 DevOps / Reliability Engineering
    {
        "id": "prompt_11",
        "category": "DevOps: SLOs & Error Budgets",
        "sparse_text": (
            "SLOs and Error Budgets: An error budget is not a permission slip to be sloppy; it is a "
            "contract between product velocity and customer trust that determines when feature work "
            "must halt for reliability. Make into a post."
        ),
    },
    {
        "id": "prompt_12",
        "category": "DevOps: IaC Console Drift",
        "sparse_text": (
            "Infrastructure as Code drift: If engineers make manual fixes in AWS/GCP consoles during an "
            "incident and never backport them to Terraform, the codebase becomes fiction. Make into a post."
        ),
    },
    {
        "id": "prompt_13",
        "category": "DevOps: Fast CI/CD Builds",
        "sparse_text": (
            "CI/CD pipeline caching: Faster builds are not just a developer convenience; when deploy "
            "times drop from 30 minutes to 3 minutes, incident remediation changes from terrifying to "
            "routine. Make into a post."
        ),
    },
    {
        "id": "prompt_14",
        "category": "DevOps: Health vs Readiness Probes",
        "sparse_text": (
            "Health checks vs readiness probes: Liveness probes that check database connectivity create "
            "cascading cluster failures when the DB hiccups. Liveness must check process health; "
            "readiness checks dependency reachability. Make into a post."
        ),
    },
    {
        "id": "prompt_15",
        "category": "DevOps: Alert Fatigue",
        "sparse_text": (
            "Alert fatigue: When on-call engineers receive 50 alerts a night that require zero action, "
            "the first alert that actually matters will be acknowledged and ignored. Make into a sharp post."
        ),
    },
    # 5 Analytical / Architectural Trade-offs
    {
        "id": "prompt_16",
        "category": "Architecture: AI Code & Real Bottlenecks",
        "sparse_text": (
            "AI code assistants and architecture: AI reduces the friction of typing boilerplate, but "
            "boilerplate was never the bottleneck; architectural trade-offs, data boundaries, and "
            "operational invariants are the real work. Make into a post."
        ),
    },
    {
        "id": "prompt_17",
        "category": "Architecture: Monolith vs Microservices",
        "sparse_text": (
            "Monolith vs Microservices boundary: Splitting a monolith before you understand the domain "
            "boundaries doesn't give you microservices; it gives you a distributed monolith with "
            "network latency and partial failure modes. Make into a post."
        ),
    },
    {
        "id": "prompt_18",
        "category": "Architecture: Event-Driven vs RPC",
        "sparse_text": (
            "Event-driven vs synchronous RPC: Event-driven systems decouple runtime availability at "
            "the cost of debuggability and consistency tracking. It is a deliberate trade-off, not a "
            "universal upgrade. Make into a post."
        ),
    },
    {
        "id": "prompt_19",
        "category": "Architecture: Vendor Lock-in Cost",
        "sparse_text": (
            "Vendor lock-in reality: Abstracting every cloud service behind a custom internal layer to "
            "avoid vendor lock-in usually costs more engineering years than migrating between clouds "
            "ever would. Make into a post."
        ),
    },
    {
        "id": "prompt_20",
        "category": "Architecture: Zero-Downtime DB Migrations",
        "sparse_text": (
            "Database migrations in zero-downtime deployments: Expand-contract database schema changes "
            "are tedious and require multiple releases, but they are the only reliable way to avoid schema "
            "lock outages during rolling updates. Make into a post."
        ),
    },
]


def generate_baseline_output(prompt_text: str, provider: str = "agy") -> str:
    """Generate raw LLM output without HowlWriter voice or LinkedIn anti-slop rules."""
    bridge = get_howlplane_bridge()
    raw_prompt = (
        "Write a concise social/LinkedIn post expanding the following idea into clear, "
        "engaging professional prose:\n\n"
        f"{prompt_text}"
    )
    res = bridge.execute_writing_role(
        role=WritingRole.HUMANIZER,
        prompt=raw_prompt,
        preferred_provider=provider,
    )
    if not res.success or not res.raw_output.strip():
        raise RuntimeError(f"Baseline generation failed: {res.error_message}")
    return res.raw_output.strip()


def generate_medium_only_output(prompt_text: str, provider: str = "agy") -> str:
    """Generate HowlWriter output with LinkedIn mode rules but NO personal voice."""
    cfg = default_config()
    cfg.voice_profile = None  # Medium rules only
    doc = Document.parse(prompt_text, title="sparse_prompt", mode=WritingMode.LINKEDIN)
    rewriter = ModelHumanizerRewriter()
    res = rewriter.rewrite(doc, cfg)
    return res.document.text.strip()


def generate_full_howlwriter_output(
    prompt_text: str,
    voice_profile_path: str,
    provider: str = "agy",
    seed: int | None = None,
) -> str:
    """Generate Full HowlWriter output with LinkedIn mode + active contextual voice."""
    cfg = default_config()
    cfg.voice_profile = voice_profile_path
    doc = Document.parse(prompt_text, title="sparse_prompt", mode=WritingMode.LINKEDIN)
    realization = None
    if cfg.voice_profile:
        from howlwriter.humanize.rewriter import _load_voice_profile
        from howlwriter.voice.realization import derive_structural_realization

        profile = _load_voice_profile(cfg.voice_profile)
        if profile is not None:
            realization = derive_structural_realization(
                profile=profile,
                mode=WritingMode.LINKEDIN,
                target_words=doc.stats.words if doc.stats.words > 80 else 200,
                input_text=doc.text,
                seed=seed,
            )
    rewriter = ModelHumanizerRewriter()
    res = rewriter.rewrite(doc, cfg, realization=realization)
    return res.document.text.strip()


def compute_batch_stats(texts: list[str]) -> dict[str, Any]:
    features_list = [extract_features(t) for t in texts if t.strip()]
    if not features_list:
        return {}

    word_counts = [float(f.words) for f in features_list]
    para_counts = [float(f.paragraphs) for f in features_list]
    para_words_means = [float(f.paragraph_words_mean) for f in features_list]
    para_words_stdevs = [float(f.paragraph_words_stdev) for f in features_list]
    para_sent_means = [float(f.paragraph_sentences_mean) for f in features_list]
    sent_len_means = [float(f.sentence_length_mean) for f in features_list]
    sent_len_stdevs = [float(f.sentence_length_stdev) for f in features_list]
    single_p_rates = [float(f.single_sentence_paragraph_rate) for f in features_list]
    short_sent_rates = [float(f.short_sentence_rate) for f in features_list]
    long_sent_rates = [float(f.long_sentence_rate) for f in features_list]
    conjunction_rates = [float(f.sentence_initial_conjunction_rate) for f in features_list]
    fragment_rates = [float(f.fragment_rate) for f in features_list]
    parenthetical_rates = [float(f.parenthetical_rate) for f in features_list]
    transition_rates = [float(f.transition_rate) for f in features_list]
    question_rates = [float(f.question_rate) for f in features_list]
    first_person_rates = [float(f.first_person_rate) for f in features_list]
    second_person_rates = [float(f.second_person_rate) for f in features_list]

    def _stats(arr: list[float]) -> dict[str, float]:
        if not arr:
            return {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0, "cv": 0.0}
        m = statistics.mean(arr)
        s = statistics.pstdev(arr) if len(arr) > 1 else 0.0
        cv = (s / m) if abs(m) > 1e-6 else 0.0
        return {
            "mean": round(m, 2),
            "stdev": round(s, 2),
            "min": round(min(arr), 2),
            "max": round(max(arr), 2),
            "cv": round(cv, 2),
        }

    return {
        "samples": len(texts),
        "total_words": int(sum(word_counts)),
        "word_count": _stats(word_counts),
        "paragraph_count": _stats(para_counts),
        "paragraph_words_mean": _stats(para_words_means),
        "paragraph_words_stdev": _stats(para_words_stdevs),
        "paragraph_sentences_mean": _stats(para_sent_means),
        "sentence_length_mean": _stats(sent_len_means),
        "sentence_length_stdev": _stats(sent_len_stdevs),
        "single_sentence_paragraph_rate": _stats(single_p_rates),
        "short_sentence_rate": _stats(short_sent_rates),
        "long_sentence_rate": _stats(long_sent_rates),
        "conjunction_rate": _stats(conjunction_rates),
        "fragment_rate": _stats(fragment_rates),
        "parenthetical_rate": _stats(parenthetical_rates),
        "transition_rate": _stats(transition_rates),
        "question_rate": _stats(question_rates),
        "first_person_rate": _stats(first_person_rates),
        "second_person_rate": _stats(second_person_rates),
    }


def _verdict_payload(result: Any) -> dict[str, Any]:
    """Serialize a diversity result, dimensions and rhetorical signatures included."""
    return {
        "verdict": result.verdict,
        "converged_dimensions": result.converged_dimensions,
        "notes": result.notes,
        "opening_classes": getattr(result, "opening_classes", {}),
        "closing_classes": getattr(result, "closing_classes", {}),
        "rhetorical_signatures": getattr(result, "rhetorical_signatures", {}),
        "top_rhetorical_signature_share": getattr(result, "top_rhetorical_signature_share", 0.0),
        "dimensions": [
            {
                "name": d.name,
                "corpus_variation": d.corpus_variation,
                "generated_variation": d.generated_variation,
                "ratio": d.ratio,
                "converged": d.converged,
            }
            for d in result.dimensions
        ],
    }


def main():
    print("=================================================================")
    print("Running Contextual Structural Variance v1 Dogfood Experiment")
    print(f"Total Prompts: {len(PROMPTS)}")
    print("=================================================================\n")

    store = VoiceStore("william")
    if not store.exists():
        raise RuntimeError("Local voice 'william' not found. Please ensure voice is built.")

    profile_path = str(store.directory / "profile.json")
    sources = store.load_sources()
    raw_feats = store.load_features()

    included_train_keys = {
        k for k, r in sources.items()
        if r.inclusion == "include" and r.split == "train"
    }
    corpus_features = [
        DocumentFeatures.from_dict(raw_feats[k]["features"])
        for k in included_train_keys if k in raw_feats and "features" in raw_feats[k]
    ]
    print(f"Loaded {len(corpus_features)} training corpus feature vectors for 'william'.")

    pro_keys = {
        k for k, r in sources.items()
        if r.inclusion == "include" and r.split == "train" and r.context == "professional"
    }
    pro_features = [
        DocumentFeatures.from_dict(raw_feats[k]["features"])
        for k in pro_keys if k in raw_feats and "features" in raw_feats[k]
    ]
    print(f"Professional context slice contains {len(pro_features)} feature vectors.\n")

    baseline_results = []
    medium_results = []
    full_howl_results = []

    # Configure role providers via environment
    os.environ["HOWLPLANE_ROLE_WRITING_HUMANIZER"] = "agy"
    os.environ["HOWLPLANE_ROLE_WRITING_FINAL_REVIEWER"] = "codex"

    t0 = time.time()

    for idx, item in enumerate(PROMPTS, 1):
        pid = item["id"]
        cat = item["category"]
        text = item["sparse_text"]

        print(f"[{idx:02d}/{len(PROMPTS):02d}] Processing {pid}: {cat}...")

        # A. Baseline
        t_base_start = time.time()
        try:
            base_out = generate_baseline_output(text, provider="agy")
        except Exception as e:
            print(f"  [ERROR] Baseline failed: {e}")
            base_out = ""
        t_base = round(time.time() - t_base_start, 2)

        # B. Medium-Only
        t_med_start = time.time()
        try:
            med_out = generate_medium_only_output(text, provider="agy")
        except Exception as e:
            print(f"  [ERROR] Medium-only failed: {e}")
            med_out = ""
        t_med = round(time.time() - t_med_start, 2)

        # C. Full HowlWriter
        t_full_start = time.time()
        try:
            full_out = generate_full_howlwriter_output(
                text, profile_path, provider="agy", seed=idx
            )
        except Exception as e:
            print(f"  [ERROR] Full HowlWriter failed: {e}")
            full_out = ""
        t_full = round(time.time() - t_full_start, 2)

        print(f"  Done in (base={t_base}s, med={t_med}s, full={t_full}s)")

        baseline_results.append({
            "id": pid,
            "category": cat,
            "prompt": text,
            "output": base_out,
            "duration": t_base,
        })
        medium_results.append({
            "id": pid,
            "category": cat,
            "prompt": text,
            "output": med_out,
            "duration": t_med,
        })
        full_howl_results.append({
            "id": pid,
            "category": cat,
            "prompt": text,
            "output": full_out,
            "duration": t_full,
        })

    total_time = round(time.time() - t0, 2)
    print(f"\nCompleted all {len(PROMPTS)} generations in {total_time}s.\n")

    # Compute batch stats
    base_texts = [r["output"] for r in baseline_results if r["output"]]
    med_texts = [r["output"] for r in medium_results if r["output"]]
    full_texts = [r["output"] for r in full_howl_results if r["output"]]

    base_stats = compute_batch_stats(base_texts)
    med_stats = compute_batch_stats(med_texts)
    full_stats = compute_batch_stats(full_texts)

    # Compute diversity comparisons
    div_base = diversity_stage.compare(
        corpus_features,
        base_texts,
        context_corpus_features=pro_features if len(pro_features) >= 2 else None,
    )
    div_med = diversity_stage.compare(
        corpus_features,
        med_texts,
        context_corpus_features=pro_features if len(pro_features) >= 2 else None,
    )
    div_full = diversity_stage.compare(
        corpus_features,
        full_texts,
        context_corpus_features=pro_features if len(pro_features) >= 2 else None,
    )

    # Check structural symmetry rule matches across Full HowlWriter outputs
    cfg = default_config()
    cfg.banned_patterns = ["paragraph_length_symmetry", "repetitive_paragraph_structure"]
    lint_engine = LintEngine()
    full_symmetry_matches = []
    for r in full_howl_results:
        doc = Document.parse(r["output"], title=r["id"], mode=WritingMode.LINKEDIN)
        matches = lint_engine.run(doc, cfg)
        for m in matches:
            if m.rule_code in (
                "AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY",
                "AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE",
            ):
                full_symmetry_matches.append({
                    "id": r["id"],
                    "rule": m.rule_code,
                    "message": m.message,
                })

    report_payload = {
        "experiment": "Contextual Structural Variance v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_prompts": len(PROMPTS),
        "total_duration_seconds": total_time,
        "providers": {
            "humanizer": "agy",
            "reviewer": "codex",
        },
        "batch_stats": {
            "baseline": base_stats,
            "medium_only": med_stats,
            "full_howlwriter": full_stats,
        },
        "diversity_verdicts": {
            "baseline": _verdict_payload(div_base),
            "medium_only": _verdict_payload(div_med),
            "full_howlwriter": _verdict_payload(div_full),
        },
        "symmetry_rule_findings": full_symmetry_matches,
        "generations": {
            "baseline": baseline_results,
            "medium_only": medium_results,
            "full_howlwriter": full_howl_results,
        },
    }

    report_path = RESULTS_DIR / "structural_variance_dogfood_report.json"
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    print(f"Saved full experiment report to {report_path}")


if __name__ == "__main__":
    main()
