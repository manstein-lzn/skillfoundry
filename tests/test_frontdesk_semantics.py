from skillfoundry.frontdesk_schema import ConversationTurn, ProductSemanticLock
from skillfoundry.frontdesk_semantics import (
    build_product_semantic_coverage_report,
    compile_product_semantic_lock,
)


def test_product_semantic_coverage_fails_when_lock_drops_key_source_terms():
    turn = ConversationTurn(
        turn_id="turn-001",
        role="user",
        content=(
            "Build Codexarium with an Obsidian-friendly Markdown workflow and a Rust Cargo helper. "
            "It must preserve compact evidence and conflict proposals."
        ),
    )
    incomplete_lock = ProductSemanticLock(
        job_id="semantic-coverage-demo",
        semantic_summary="Build Codexarium with a Markdown workflow.",
        requirement_clauses=["Build Codexarium with a Markdown workflow."],
        product_identity_terms=["Codexarium"],
        domain_terms=["Codexarium", "Markdown"],
        source_turn_ids=["turn-001"],
        source_char_count=len(turn.content),
        sanitized_char_count=len(turn.content),
    )

    report = build_product_semantic_coverage_report(
        job_id="semantic-coverage-demo",
        turns=[turn],
        semantic_lock=incomplete_lock,
    )

    assert report.status == "failed"
    assert "Obsidian" in report.missing_terms
    assert "Rust" in report.missing_terms
    assert "Cargo" in report.missing_terms


def test_product_semantic_coverage_passes_for_compiled_lock():
    turn = ConversationTurn(
        turn_id="turn-001",
        role="user",
        content=(
            "Build Codexarium with an Obsidian-friendly Markdown workflow and a Rust Cargo helper. "
            "It must preserve compact evidence and conflict proposals."
        ),
    )
    lock = compile_product_semantic_lock(job_id="semantic-coverage-demo", turns=[turn])
    assert lock is not None

    report = build_product_semantic_coverage_report(
        job_id="semantic-coverage-demo",
        turns=[turn],
        semantic_lock=lock,
    )

    assert report.status == "passed"
    assert report.missing_terms == []
    assert report.coverage_ratio == 1.0
