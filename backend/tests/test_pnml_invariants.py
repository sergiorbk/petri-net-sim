"""Direct unit tests for services/petri/exporter/invariants.py's
assert_invariants, the invariant checker shared by both PNML exporters.

Hand-built minimal XML strings rather than going through either exporter's
domain model or template: every case here is either a bug an exporter's own
output could have (a dangling arc reference, an id that only looks valid
under `.match`), not something either exporter's public API can be driven to
produce, or a regex edge case that is easiest to pin down directly against
the function under test.
"""

from __future__ import annotations

import pytest

from src.services.petri.exporter.invariants import assert_invariants

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">\n'
    '  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">\n'
)
_FOOTER = "  </net>\n</pnml>\n"


class TestNCNameTrailingNewline:
    """`NCNAME_RE` used to be checked with `.match`, and `$` matches right
    before a final newline rather than only at the true end of string, so an
    id like "p1\\n" used to pass. `&#10;` is a character reference, not a
    literal newline in the source, so it survives XML attribute-value
    normalization intact instead of being collapsed to a space, and lets this
    test reach the exact "id ends with a newline" case."""

    def test_id_ending_in_newline_is_rejected(self):
        xml = (
            _HEADER
            + '    <page id="page1">\n'
            + '      <place id="p1&#10;"><name><text>P1</text></name></place>\n'
            + "    </page>\n"
            + _FOOTER
        )
        with pytest.raises(ValueError, match="not a valid XML NCName"):
            assert_invariants(xml, exporter_name="PNML")


class TestDanglingArcEndpoint:
    """A dangling arc endpoint (an id that is not a node anywhere in the
    document) is a different, more specific failure than a same-page
    violation (an id that IS a node, just on the wrong page), and must be
    reported as such."""

    def test_missing_endpoint_names_the_missing_node(self):
        xml = (
            _HEADER
            + '    <page id="page1">\n'
            + '      <place id="p1"><name><text>P1</text></name></place>\n'
            + '      <arc id="a1" source="p1" target="missing_t">'
            + "<inscription><text>1</text></inscription></arc>\n"
            + "    </page>\n"
            + _FOOTER
        )
        with pytest.raises(
            ValueError, match=r"arc 'a1' references missing node 'missing_t'"
        ):
            assert_invariants(xml, exporter_name="PNML")

    def test_endpoints_that_exist_on_a_different_page_keep_the_same_page_wording(self):
        xml = (
            _HEADER
            + '    <page id="page1">\n'
            + '      <place id="p1"><name><text>P1</text></name></place>\n'
            + '      <arc id="a1" source="p1" target="t1">'
            + "<inscription><text>1</text></inscription></arc>\n"
            + "    </page>\n"
            + '    <page id="page2">\n'
            + '      <transition id="t1"><name><text>T1</text></name></transition>\n'
            + "    </page>\n"
            + _FOOTER
        )
        with pytest.raises(
            ValueError, match=r"arc 'a1' endpoints \(p1 -> t1\) are not both on page 'page1'"
        ):
            assert_invariants(xml, exporter_name="PNML")
