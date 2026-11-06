import pytest

from services.evidence import is_not_found, normalize_for_match, verify_evidence

RESUME = """Jane Doe
Senior Software Engineer — Acme Corp (2019–2024)
• Built   high-throughput REST APIs in Python/FastAPI serving 2M requests/day.
• Led migration of 40 services to Kubernetes on AWS (EKS), cutting costs by 30%.
Skills: Python, PostgreSQL, Docker, Terraform
"""


def test_exact_quote_verified() -> None:
    r = verify_evidence("Led migration of 40 services to Kubernetes on AWS (EKS)", RESUME)
    assert (r.status, r.match) == ("verified", 100.0)


def test_whitespace_case_and_punctuation_normalised() -> None:
    # Extra spaces in the resume, different case, curly quotes and en-dash vs hyphen.
    assert verify_evidence("built high-throughput rest apis in python/fastapi", RESUME).status == "verified"
    assert verify_evidence("“Senior Software Engineer - Acme Corp (2019-2024)”", RESUME).status == "verified"


def test_minor_typo_is_fuzzy() -> None:
    r = verify_evidence("Led migration of 40 service to Kubernetes on AWS (EKS), cutting cost by 30%", RESUME)
    assert r.status == "fuzzy"
    assert 90 <= r.match < 100


def test_fabricated_quote_unverified() -> None:
    r = verify_evidence("Managed a team of 12 engineers and owned the hiring process", RESUME)
    assert r.status == "unverified"
    assert r.match < 90


def test_paraphrase_unverified() -> None:
    assert verify_evidence("Moved forty microservices onto Kubernetes in Amazon", RESUME).status == "unverified"


def test_short_quote_requires_exact_match() -> None:
    assert verify_evidence("Docker", RESUME).status == "verified"
    assert verify_evidence("Dockre", RESUME).status == "unverified"


def test_ellipsis_joined_fragments_all_must_match() -> None:
    ok = "Built high-throughput REST APIs ... cutting costs by 30%"
    bad = "Built high-throughput REST APIs … managed a team of twelve engineers"
    assert verify_evidence(ok, RESUME).status == "verified"
    assert verify_evidence(bad, RESUME).status == "unverified"


@pytest.mark.parametrize("value", ["not found", "Not Found.", "N/A", "", "  none ", '"not found"'])
def test_not_found_variants(value: str) -> None:
    assert is_not_found(value)
    assert verify_evidence(value, RESUME).status == "not_found"


def test_normalize_for_match() -> None:
    assert normalize_for_match("  A B\n\tC — “D” ") == 'a b c - "d"'
