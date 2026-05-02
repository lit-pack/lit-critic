"""Tests for platform legacy/contract mapping helpers."""

from orchestrator.mappers import contract_to_finding, finding_to_contract
from orchestrator.runtime.models import Finding


def test_finding_to_contract_maps_fields():
    finding = Finding(
        number=3,
        severity="minor",
        lens="clarity",
        location="Paragraph 4",
        evidence="Unclear pronoun",
        impact="Reader uncertainty",
        options=["Name subject"],
        flagged_by=["clarity"],
    )

    contract = finding_to_contract(finding)
    assert contract.number == 3
    assert contract.lens == "clarity"


def test_contract_to_finding_maps_fields():
    original = Finding(
        number=1,
        severity="major",
        lens="prose",
        location="Paragraph 1",
        evidence="Repeated starts",
        impact="Monotony",
        options=["Vary openings"],
        flagged_by=["prose"],
    )
    contract = finding_to_contract(original)

    finding = contract_to_finding(contract)
    assert finding.number == 1
    assert finding.severity == "major"
    assert finding.options == ["Vary openings"]
