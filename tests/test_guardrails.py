import pytest

import config
from services import guardrails


@pytest.mark.parametrize(
    "text",
    ["You should buy this stock", "We recommend selling now", "Sell more shares", "buy now"],
)
def test_advice_is_detected(text):
    assert guardrails.contains_advice(text)


@pytest.mark.parametrize(
    "text",
    ["The company reported results above expectations.", "Analysts discussed a possible buyback."],
)
def test_ordinary_news_language_is_not_advice(text):
    assert not guardrails.contains_advice(text)


def test_numbers_are_normalised():
    assert guardrails.numbers_in("Revenue rose 5% to $1,200.5 million") == {"5", "1200.5"}


def test_numbers_must_appear_in_the_sources():
    allowed = ["Revenue rose 5% to 12.5 billion."]
    assert guardrails.ungrounded_numbers("Revenue rose 5%.", allowed) == set()
    assert guardrails.ungrounded_numbers("Revenue rose 7%.", allowed) == {"7"}


def test_citation_numbers_are_not_treated_as_financial_numbers():
    explanation = (
        "Visa reported earnings and an outlook for revenue growth [1, 4]. "
        "Analysts adjusted ratings and price targets [3, 7]."
    )
    allowed = ["Visa reported earnings and revenue growth."]

    assert guardrails.ungrounded_numbers(explanation, allowed) == set()


def test_real_unsupported_numbers_are_still_rejected():
    explanation = "Visa reported revenue growth of 25% [1]."
    allowed = ["Visa reported revenue growth."]

    assert guardrails.ungrounded_numbers(explanation, allowed) == {"25"}


def test_supported_financial_numbers_are_allowed():
    explanation = "Visa reported fiscal 2026 earnings [1]."
    allowed = ["Visa reported fiscal 2026 earnings."]

    assert guardrails.ungrounded_numbers(explanation, allowed) == set()


def test_multiple_citations_are_removed():
    explanation = "Visa reported strong earnings [1, 2, 4]."
    allowed = ["Visa reported strong earnings."]

    assert guardrails.ungrounded_numbers(explanation, allowed) == set()


def test_check_explanation_accepts_valid_citations():
    explanation = (
        "Visa reported fiscal first-quarter earnings [1, 4]. "
        "Analysts adjusted ratings following the earnings release [3, 7]."
    )
    allowed = [
        "Visa reported fiscal first-quarter earnings.",
        "Analysts adjusted ratings following the earnings release.",
    ]

    assert guardrails.check_explanation(explanation, allowed) is None


def test_check_reports_the_first_problem():
    allowed = ["Revenue rose 5%."]

    assert guardrails.check_explanation("Revenue rose 5%.", allowed) is None
    assert "empty" in guardrails.check_explanation("  ", allowed)
    assert "long" in guardrails.check_explanation("x" * (config.EXPLANATION_MAX_CHARS + 1), allowed)
    assert "advice" in guardrails.check_explanation("You should buy now.", allowed)
    assert "7" in guardrails.check_explanation("Revenue rose 7%.", allowed)
