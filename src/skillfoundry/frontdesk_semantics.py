"""Front Desk product-intent distillation helpers."""

from __future__ import annotations

import re
from typing import Iterable

from .frontdesk_schema import ConversationTurn, ProductSemanticCoverageReport, ProductSemanticLock
from .frontdesk_workspace import (
    FRONTDESK_CONVERSATION_REF,
    FRONTDESK_PRODUCT_SEMANTIC_COVERAGE_REF,
    FRONTDESK_PRODUCT_SEMANTIC_LOCK_REF,
)
from .schema import JsonValue, sha256_bytes, sha256_json


_SECRETISH_TOKEN_RE = re.compile(r"\b[A-Z0-9_]{12,}\b")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|[;；]\s*|\n+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_DOMAIN_TERM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Codexarium", r"\bcodexarium\b"),
    ("EdaSkill", r"\bedaskill\b"),
    ("Codex", r"\bcodex\b"),
    ("skill", r"\bskill\b"),
    ("wiki", r"\bwiki\b"),
    ("Obsidian", r"\bobsidian\b"),
    ("Markdown", r"\bmarkdown\b"),
    ("Rust", r"\brust\b"),
    ("Cargo", r"\bcargo\b"),
    ("CLI", r"\bcli\b"),
    ("helper", r"\bhelper\b"),
    ("MCP", r"\bmcp\b"),
    ("API", r"\bapi\b"),
    ("database", r"\bdatabase\b"),
    ("PDF", r"\bpdf\b"),
    ("evidence", r"\bevidence\b"),
    ("manifest", r"\bmanifest\b"),
    ("fixtures", r"\bfixtures?\b"),
    ("synthetic", r"\bsynthetic\b"),
    ("conflict", r"\bconflicts?\b"),
    ("stale", r"\bstale\b"),
    ("thin evidence", r"\bthin evidence\b"),
    ("install guidance", r"\binstall(?:ation)?(?:/use| and use| use)? guidance\b|\binstall\b"),
    ("usage guidance", r"\busage\b|\buse guidance\b"),
    ("reference docs", r"\breference docs?\b|\breference documentation\b"),
)

_IMPLEMENTATION_KEYWORDS = (
    "api",
    "binary",
    "cargo",
    "cli",
    "code",
    "compile",
    "database",
    "helper",
    "implementation",
    "mcp",
    "python",
    "rust",
    "script",
    "service",
    "tool",
    "toolchain",
    "runtime",
)

_DELIVERY_KEYWORDS = (
    "codex skill",
    "deliver",
    "docs",
    "example",
    "fixture",
    "guidance",
    "install",
    "manifest",
    "package",
    "reference",
    "skill package",
    "test",
    "usage",
)

_NEGATION_KEYWORDS = (
    "avoid",
    "do not",
    "don't",
    "forbid",
    "forbids",
    "must not",
    "no ",
    "not ",
    "reject",
    "without exposing",
)


def sanitize_frontdesk_request(text: str) -> str:
    """Normalize and redact a Front Desk user request without truncating it."""

    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""
    return _SECRETISH_TOKEN_RE.sub("[redacted-token]", normalized).strip()


def compile_product_semantic_lock(
    *,
    job_id: str,
    turns: Iterable[ConversationTurn],
) -> ProductSemanticLock | None:
    """Compile user-facing Front Desk turns into a structured semantic lock.

    The compiler deliberately avoids fixed-length truncation. It keeps raw turns
    as provenance only and emits deduplicated requirement clauses as the
    canonical downstream product-intent surface.
    """

    user_turns = [turn for turn in turns if turn.role == "user"]
    if not user_turns:
        return None

    all_clauses: list[str] = []
    source_trace: list[dict[str, JsonValue]] = []
    source_turn_ids: list[str] = []
    source_char_count = 0
    sanitized_char_count = 0
    redaction_applied = False

    for turn in user_turns:
        source_turn_ids.append(turn.turn_id)
        source_char_count += len(turn.content)
        sanitized = sanitize_frontdesk_request(turn.content)
        if not sanitized:
            continue
        sanitized_char_count += len(sanitized)
        redaction_applied = redaction_applied or sanitized != re.sub(r"\s+", " ", turn.content).strip()
        clauses = _extract_requirement_clauses(sanitized)
        all_clauses.extend(clauses)
        source_trace.append(
            {
                "turn_id": turn.turn_id,
                "source_ref": FRONTDESK_CONVERSATION_REF,
                "source_char_count": len(turn.content),
                "sanitized_char_count": len(sanitized),
                "sanitized_sha256": sha256_bytes(sanitized.encode("utf-8")),
                "clause_count": len(clauses),
                "matched_terms": _matched_terms(sanitized),
            }
        )

    requirement_clauses = _dedupe_preserve_order(all_clauses)
    if not requirement_clauses:
        return None

    semantic_summary = " ".join(requirement_clauses).strip()
    return ProductSemanticLock(
        job_id=job_id,
        semantic_summary=semantic_summary,
        requirement_clauses=requirement_clauses,
        product_identity_terms=_product_identity_terms(semantic_summary),
        domain_terms=_matched_terms(semantic_summary),
        implementation_requirements=_filter_clauses(requirement_clauses, _IMPLEMENTATION_KEYWORDS),
        delivery_requirements=_filter_clauses(requirement_clauses, _DELIVERY_KEYWORDS),
        must_not=_filter_clauses(requirement_clauses, _NEGATION_KEYWORDS),
        source_ref=FRONTDESK_CONVERSATION_REF,
        source_turn_ids=source_turn_ids,
        source_char_count=source_char_count,
        sanitized_char_count=sanitized_char_count,
        redaction_applied=redaction_applied,
        truncated=False,
        omission_warnings=[],
        source_trace=source_trace,
    )


def build_product_semantic_coverage_report(
    *,
    job_id: str,
    turns: Iterable[ConversationTurn],
    semantic_lock: ProductSemanticLock,
) -> ProductSemanticCoverageReport:
    """Verify key source signals are represented in the semantic lock."""

    user_turns = [turn for turn in turns if turn.role == "user"]
    source_text = " ".join(sanitize_frontdesk_request(turn.content) for turn in user_turns).strip()
    lock_text = _lock_search_text(semantic_lock)
    required_terms = _coverage_required_terms(source_text)
    matched_terms = [term for term in required_terms if _contains_term(lock_text, term)]
    missing_terms = [term for term in required_terms if term not in matched_terms]
    checks = [
        _coverage_check(
            "semantic_lock_not_truncated",
            not semantic_lock.truncated,
            "product_semantic_lock.truncated must be false for governed build inputs.",
        ),
        _coverage_check(
            "semantic_summary_nonempty",
            bool(semantic_lock.semantic_summary.strip()),
            "product_semantic_lock.semantic_summary must be non-empty.",
        ),
        _coverage_check(
            "source_turns_accounted",
            set(turn.turn_id for turn in user_turns).issubset(set(semantic_lock.source_turn_ids)),
            "All user turn ids must be represented in product_semantic_lock.source_turn_ids.",
        ),
        _coverage_check(
            "required_terms_covered",
            not missing_terms,
            "All key product/domain/implementation terms found at the source boundary must appear in the semantic lock.",
            {"missing_terms": missing_terms},
        ),
    ]
    passed = all(bool(check["passed"]) for check in checks)
    ratio = 1.0 if not required_terms else len(matched_terms) / len(required_terms)
    return ProductSemanticCoverageReport(
        job_id=job_id,
        status="passed" if passed else "failed",
        semantic_lock_ref=FRONTDESK_PRODUCT_SEMANTIC_LOCK_REF,
        source_ref=FRONTDESK_CONVERSATION_REF,
        required_terms=required_terms,
        matched_terms=matched_terms,
        missing_terms=missing_terms,
        source_turn_ids=[turn.turn_id for turn in user_turns],
        source_char_count=sum(len(turn.content) for turn in user_turns),
        semantic_summary_char_count=len(semantic_lock.semantic_summary),
        truncated=semantic_lock.truncated,
        coverage_ratio=ratio,
        checks=checks,
        source_sha256=sha256_bytes(source_text.encode("utf-8")) if source_text else None,
        semantic_lock_sha256=sha256_json(semantic_lock),
    )


def product_semantic_lock_markdown(
    lock: ProductSemanticLock,
    coverage: ProductSemanticCoverageReport | None = None,
) -> str:
    """Render a human-readable clarification summary from the semantic lock."""

    lines = [
        "# Clarification Summary",
        "",
        "This governed summary preserves the user's task semantics for Front Desk planning.",
        "It is derived from frontdesk/product_semantic_lock.json and is not the raw conversation transcript.",
        "No fixed character truncation is applied to the semantic chain.",
        "",
        "## Current User Request",
        lock.semantic_summary,
        "",
        "## Locked Requirement Clauses",
    ]
    lines.extend(f"- {clause}" for clause in lock.requirement_clauses)
    lines.extend(
        [
            "",
            "## Product Semantic Lock",
            f"- Ref: frontdesk/product_semantic_lock.json",
            f"- Source: {lock.source_ref}",
            f"- Source turns: {', '.join(lock.source_turn_ids)}",
            f"- Source characters: {lock.source_char_count}",
            f"- Sanitized characters: {lock.sanitized_char_count}",
            f"- Truncated: {str(lock.truncated).lower()}",
        ]
    )
    if coverage is not None:
        lines.extend(
            [
                "",
                "## Semantic Coverage",
                f"- Ref: {FRONTDESK_PRODUCT_SEMANTIC_COVERAGE_REF}",
                f"- Status: {coverage.status}",
                f"- Required terms: {len(coverage.required_terms)}",
                f"- Matched terms: {len(coverage.matched_terms)}",
                f"- Missing terms: {', '.join(coverage.missing_terms) if coverage.missing_terms else 'none'}",
            ]
        )
    if lock.product_identity_terms:
        lines.append(f"- Product identity terms: {', '.join(lock.product_identity_terms)}")
    if lock.domain_terms:
        lines.append(f"- Domain terms: {', '.join(lock.domain_terms)}")
    if lock.implementation_requirements:
        lines.extend(["", "## Implementation Requirements"])
        lines.extend(f"- {item}" for item in lock.implementation_requirements)
    if lock.delivery_requirements:
        lines.extend(["", "## Delivery Requirements"])
        lines.extend(f"- {item}" for item in lock.delivery_requirements)
    if lock.must_not:
        lines.extend(["", "## Must Not"])
        lines.extend(f"- {item}" for item in lock.must_not)
    lines.extend(
        [
            "",
            "## Privacy Boundary",
            "- Raw conversation turns remain in frontdesk/conversation.jsonl as provenance only.",
            "- Goal Harness nodes consume governed semantic lock, summary, and refs, not the raw transcript.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _extract_requirement_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    for rough in _CLAUSE_SPLIT_RE.split(text):
        cleaned = rough.strip(" -\t\r\n")
        if not cleaned:
            continue
        clauses.extend(_split_long_clause(cleaned))
    return clauses


def _split_long_clause(clause: str, *, max_chars: int = 1200) -> list[str]:
    if len(clause) <= max_chars:
        return [clause]
    chunks: list[str] = []
    words = clause.split()
    current: list[str] = []
    current_len = 0
    for word in words:
        projected = current_len + len(word) + (1 if current else 0)
        if current and projected > max_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
            continue
        current.append(word)
        current_len = projected
    if current:
        chunks.append(" ".join(current))
    return chunks


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _NON_ALNUM_RE.sub(" ", value.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _matched_terms(text: str) -> list[str]:
    terms: list[str] = []
    for label, pattern in _DOMAIN_TERM_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE) and label not in terms:
            terms.append(label)
    return terms


def _coverage_required_terms(source_text: str) -> list[str]:
    terms: list[str] = []
    terms.extend(_matched_terms(source_text))
    terms.extend(_product_identity_terms(source_text))
    return _dedupe_preserve_order(terms)


def _lock_search_text(lock: ProductSemanticLock) -> str:
    return "\n".join(
        [
            lock.semantic_summary,
            "\n".join(lock.requirement_clauses),
            "\n".join(lock.product_identity_terms),
            "\n".join(lock.domain_terms),
            "\n".join(lock.implementation_requirements),
            "\n".join(lock.delivery_requirements),
            "\n".join(lock.must_not),
        ]
    )


def _contains_term(text: str, term: str) -> bool:
    normalized_text = _marker_key(text)
    normalized_term = _marker_key(term)
    return bool(normalized_term and normalized_term in normalized_text)


def _marker_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _coverage_check(
    check_id: str,
    passed: bool,
    description: str,
    details: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "check_id": check_id,
        "passed": passed,
        "description": description,
    }
    if details:
        payload["details"] = details
    return payload


def _product_identity_terms(text: str) -> list[str]:
    terms: list[str] = []
    for candidate in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*\b", text):
        if candidate in {"Build", "Create", "Please", "Codex", "Skill"}:
            continue
        if candidate not in terms:
            terms.append(candidate)
    for label in _matched_terms(text):
        if label in {"Codexarium", "EdaSkill"} and label not in terms:
            terms.append(label)
    return terms


def _filter_clauses(clauses: Iterable[str], keywords: Iterable[str]) -> list[str]:
    keyword_list = [keyword.lower() for keyword in keywords]
    result: list[str] = []
    for clause in clauses:
        lower = clause.lower()
        if any(keyword in lower for keyword in keyword_list):
            result.append(clause)
    return _dedupe_preserve_order(result)
