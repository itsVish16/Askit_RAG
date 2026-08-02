"""Tests for app/core/redact.py — PII redaction in chat_history (Bug #2).

Goal: prove the regex set masks the obvious PHI surfaces (email, SSN,
date, IP, phone) without eating normal biomedical text.
"""
from app.core.redact import redact_pii


def test_email_masked():
    out = redact_pii("Send to dr.smith@hospital.org and emily@ucsf.edu please")
    assert "dr.smith@hospital.org" not in out
    assert "emily@ucsf.edu" not in out
    assert out.count("[EMAIL]") == 2


def test_ssn_masked():
    assert redact_pii("SSN 123-45-6789 patient") == "SSN [SSN] patient"


def test_phone_masked():
    out = redact_pii("Phone +1 (415) 555-2671 verified")
    assert "+1 (415) 555-2671" not in out
    assert "[PHONE]" in out


def test_iso_date_not_mistagged_as_phone():
    """Order is load-bearing: DATE runs before PHONE so '2021-03-04' is
    tagged as [DATE], not swallowed by the phone regex."""
    out = redact_pii("Admitted 2021-03-04")
    assert out == "Admitted [DATE]"
    assert "[PHONE]" not in out


def test_us_date_YYYY():
    out = redact_pii("Visit 12 March 2021 — DOJ 03/04/2021")
    assert out.count("[DATE]") == 2


def test_ipv4_masked():
    out = redact_pii("Server IP 10.0.0.42 unreachable")
    assert "10.0.0.42" not in out
    assert "[IPV4]" in out


def test_no_false_positives_on_biomedical_text():
    """The whole point of conservative patterns: COVID-19, viral names,
    ages, dosages — none of these should be eaten by the PII regex."""
    bio = [
        "COVID-19 patients aged 45+ with comorbidities",
        "Patient received 1000mg acetaminophen every 6 hours for SARS-CoV-2",
        "SARS-CoV-2 PCR cycle threshold 28.7",
        "Norovirus vs SARS — both RNA viruses",
    ]
    for s in bio:
        assert redact_pii(s) == s, f"false positive on {s!r}"


def test_short_local_phone_intentionally_not_masked():
    """555-2671 looks like a 7-digit phone but the pattern requires 10+
    chars to avoid eating biomedical identifiers like COVID-19."""
    assert redact_pii("Call 555-2671") == "Call 555-2671"


def test_empty_string_passthrough():
    assert redact_pii("") == ""
