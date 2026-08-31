"""Unit tests for the deterministic half.

Every function under test is pure, module level, and loaded FROM THE REAL
CONTRACT FILE rather than reimplemented here. A test suite that reimplements
the thing it tests proves the reimplementation works.

    pytest tests/test_logic.py -v
"""

import ast
import pathlib

import pytest

import glsim as S

CONTRACT_PATH = "contracts/ratchet.py"
LIB_PATH = "lib/ratchet_consensus.py"

M = S.load_contract(CONTRACT_PATH)


# ---------------------------------------------------------------------------
# tokens and parsing
# ---------------------------------------------------------------------------

class TestTokens:
    @pytest.mark.parametrize("raw,want", [
        ("narrower", "narrower"), ("SAME", "same"), ("  Broader ", "broader"),
        ("unclear", ""),          # legal to STORE, never legal from a prompt
        ("", ""), ("maybe", ""), ("narrow", ""), ("same-ish", ""),
        (None, ""), (3, ""),
    ])
    def test_only_the_three_prompt_tokens_survive(self, raw, want):
        assert M.normalise_token(raw) == want

    def test_unclear_is_not_something_a_prompt_may_return(self):
        """It is the contract's word for 'the leader contradicted itself', so a
        model that emitted it directly would be claiming a state only the
        reconciliation is allowed to produce."""
        assert M.normalise_token(M.UNCLEAR) == ""
        assert M.UNCLEAR in M.TOKENS
        assert M.UNCLEAR not in M.MODEL_TOKENS

    @pytest.mark.parametrize("text,n,want", [
        ("same|narrower", 2, ["same", "narrower"]),
        ("SAME | BROADER", 2, ["same", "broader"]),
        ("same", 1, ["same"]),
        ("same|narrower", 3, None),        # too few
        ("same|narrower|same", 2, None),   # too many
        ("same|nonsense", 2, None),        # one bad token poisons the vector
        ("same|", 2, None),
        ("", 2, None),
        ("same|unclear", 2, None),         # not from a prompt
    ])
    def test_parse_vector_is_all_or_nothing(self, text, n, want):
        assert M.parse_vector(text, n) == want

    def test_parse_stored_accepts_unclear_and_parse_vector_does_not(self):
        """Two readers, deliberately different. One reads a prompt, one reads a
        reconciled vector, and only the second may contain unclear."""
        assert M.parse_stored("same|unclear", 2) == ["same", "unclear"]
        assert M.parse_vector("same|unclear", 2) is None


# ---------------------------------------------------------------------------
# the mirror: the leader checking itself
# ---------------------------------------------------------------------------

class TestMirror:
    @pytest.mark.parametrize("f,r,want", [
        ("narrower", "broader", True),
        ("broader", "narrower", True),
        ("same", "same", True),
        ("narrower", "narrower", False),   # cannot be narrower both ways round
        ("broader", "broader", False),
        ("narrower", "same", False),
        ("same", "broader", False),
        ("unclear", "unclear", False),
    ])
    def test_direction_must_invert(self, f, r, want):
        assert M.mirrors(f, r) is want

    def test_a_dimension_the_leader_disagrees_with_itself_on_becomes_unclear(self):
        got = M.reconcile(["narrower", "same", "narrower"],
                          ["broader", "same", "narrower"])
        assert got == ["narrower", "same", "unclear"]

    def test_reconcile_keeps_the_forward_direction_when_the_passes_mirror(self):
        assert M.reconcile(["narrower", "broader", "same"],
                           ["broader", "narrower", "same"]) == \
               ["narrower", "broader", "same"]

    def test_reconcile_refuses_a_length_mismatch(self):
        assert M.reconcile(["same"], ["same", "same"]) is None

    def test_reconcile_is_not_symmetric_and_should_not_be(self):
        """Forward and reverse are different questions. Swapping them inverts
        the answer rather than preserving it, which is the whole point of
        asking twice."""
        a = M.reconcile(["narrower"], ["broader"])
        b = M.reconcile(["broader"], ["narrower"])
        assert a == ["narrower"] and b == ["broader"]


# ---------------------------------------------------------------------------
# the verdict, derived from the vector
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize("vec,want", [
        (["same", "same"], "restated"),
        (["narrower", "same"], "tightened"),
        (["narrower", "narrower"], "tightened"),
        (["broader", "same"], "broadened"),
        (["narrower", "broader"], "broadened"),      # a loosening is not offset
        (["unclear", "same"], "indeterminate"),
        (["unclear", "broader"], "indeterminate"),   # unclear outranks broader
        (["narrower", "unclear"], "indeterminate"),
        ([], "indeterminate"),
    ])
    def test_the_four_outcomes(self, vec, want):
        assert M.classify(vec) == want

    def test_one_loosening_is_never_paid_for_by_a_tightening(self):
        """A ratchet that let an author trade a weakened clause for a
        strengthened one somewhere else would not be a ratchet."""
        assert M.classify(["narrower"] * 11 + ["broader"]) == "broadened"

    def test_unclear_outranks_everything(self):
        assert M.classify(["broader", "unclear"]) == "indeterminate"
        assert M.classify(["narrower", "unclear"]) == "indeterminate"

    def test_every_vector_of_legal_tokens_gets_a_legal_verdict(self):
        import itertools
        for combo in itertools.product(M.TOKENS, repeat=3):
            assert M.classify(list(combo)) in M.VERDICTS


class TestLoosened:
    def test_indices_are_sorted_so_two_nodes_produce_one_string(self):
        assert M.loosened_dimensions(["broader", "same", "broader"]) == [0, 2]

    def test_nothing_loosened_is_an_empty_list_not_a_zero(self):
        assert M.loosened_dimensions(["same", "narrower"]) == []


# ---------------------------------------------------------------------------
# agreement
# ---------------------------------------------------------------------------

class TestAgreement:
    def test_identical_vectors_agree(self):
        assert M.ratchet_agrees(["same", "narrower"], ["same", "narrower"], 2)

    def test_one_differing_dimension_is_a_disagreement(self):
        """No tolerance, deliberately. A rule that forgave one dimension would
        let two nodes settle on `tightened` while one of them believed a clause
        had been dropped."""
        assert not M.ratchet_agrees(["same", "narrower"], ["same", "same"], 2)

    def test_agreeing_that_something_loosened_is_not_agreeing_which(self):
        assert not M.ratchet_agrees(["broader", "same"], ["same", "broader"], 2)

    def test_unclear_on_both_sides_still_agrees(self):
        """Two nodes that both failed to resolve the same dimension HAVE
        agreed, and what they agreed is that the revision is not applicable."""
        assert M.ratchet_agrees(["unclear"], ["unclear"], 1)

    def test_unclear_against_a_decided_token_disagrees(self):
        assert not M.ratchet_agrees(["unclear"], ["same"], 1)

    def test_the_rule_is_symmetric(self):
        import itertools
        for a in itertools.product(M.TOKENS, repeat=2):
            for b in itertools.product(M.TOKENS, repeat=2):
                assert (M.ratchet_agrees(list(a), list(b), 2)
                        == M.ratchet_agrees(list(b), list(a), 2))

    def test_a_malformed_side_never_agrees_with_anything(self):
        assert not M.ratchet_agrees(None, ["same"], 1)
        assert not M.ratchet_agrees(["same"], None, 1)
        assert not M.ratchet_agrees("same|same", ["same"], 1)      # wrong length
        assert not M.ratchet_agrees(["same", "same"], ["same"], 1)

    def test_agreement_accepts_a_string_or_a_parsed_list(self):
        assert M.ratchet_agrees("same|narrower", ["same", "narrower"], 2)


class TestStructural:
    def test_the_free_layer_rejects_before_a_prompt_is_spent(self):
        assert M.structurally_sound(["same", "unclear"], 2)
        assert not M.structurally_sound(["same"], 2)
        assert not M.structurally_sound(["same", "nonsense"], 2)
        assert not M.structurally_sound(None, 2)
        assert not M.structurally_sound([], 0)


# ---------------------------------------------------------------------------
# sanitising and input handling
# ---------------------------------------------------------------------------

class TestSanitise:
    def test_markup_is_stripped(self):
        assert "<" not in M.sanitise_reason("<b>weaker</b> on retention")
        assert "`" not in M.sanitise_reason("look at `this`")
        assert "{" not in M.sanitise_reason("{\"injected\": true}")

    def test_control_characters_become_spaces(self):
        assert M.sanitise_reason("a\x00b\x1fc\x7fd") == "a b c d"

    def test_whitespace_is_collapsed(self):
        assert M.sanitise_reason("  two   words  ") == "two words"

    def test_it_is_capped(self):
        assert len(M.sanitise_reason("x" * 900)) == M.MAX_REASON

    def test_it_never_raises_on_anything(self):
        for raw in (None, 3, "", [], {}):
            M.sanitise_reason(raw)


class TestDimensions:
    def test_pipe_joined_names_become_a_list(self):
        assert M.split_dimensions("retention|sharing") == ["retention", "sharing"]

    def test_empties_are_dropped_not_kept_as_blanks(self):
        assert M.split_dimensions("a||b|") == ["a", "b"]

    def test_whitespace_is_collapsed_within_a_name(self):
        assert M.split_dimensions("  data   retention  ") == ["data retention"]

    def test_a_long_name_is_capped_not_rejected(self):
        assert len(M.split_dimensions("x" * 500)[0]) == M.MAX_DIMENSION


class TestAddressShape:
    @pytest.mark.parametrize("raw,want", [
        ("0x" + "ab" * 20, True),
        ("0x" + "AB" * 20, True),
        ("0x" + "ab" * 19, False),
        ("0x" + "ab" * 21, False),
        ("0x" + "zz" * 20, False),
        ("", False), ("0x", False), ("not-an-address", False),
        ("ab" * 20, False),
    ])
    def test_shape_is_checked_before_Address_is_constructed(self, raw, want):
        assert M.looks_like_address(raw) is want


# ---------------------------------------------------------------------------
# the prompt
# ---------------------------------------------------------------------------

class TestPrompt:
    def test_both_directions_come_from_one_template(self):
        """An asymmetry in the wording would look exactly like a model that
        cannot answer consistently: every dimension would reconcile to unclear
        and every revision would be refused."""
        a = M.build_prompt("Acme", "[0] retention", "ORIG", "REV", "FIRST", "SECOND")
        b = M.build_prompt("Acme", "[0] retention", "REV", "ORIG", "SECOND", "FIRST")
        assert a.replace("ORIG", "\x01").replace("REV", "\x02").replace("FIRST", "\x03").replace("SECOND", "\x04") == \
               b.replace("REV", "\x01").replace("ORIG", "\x02").replace("SECOND", "\x03").replace("FIRST", "\x04")

    def test_it_names_the_three_legal_tokens_and_not_the_fourth(self):
        p = M.build_prompt("Acme", "[0] retention", "a", "b", "X", "Y")
        for t in M.MODEL_TOKENS:
            assert t in p
        assert M.UNCLEAR not in p

    def test_it_says_that_saying_nothing_is_broader(self):
        """The failure this contract exists for is a dropped clause, so the
        rule has to be in the prompt rather than only in the docs."""
        p = M.build_prompt("Acme", "[0] retention", "a", "b", "X", "Y")
        assert "no longer addresses" in p and "Saying nothing is broader" in p


# ---------------------------------------------------------------------------
# lib/ parity
# ---------------------------------------------------------------------------

class TestLibParity:
    """lib/ratchet_consensus.py claims to be these rules, lifted out to be
    copied. If it drifts, somebody copies a rule this contract does not use."""

    def _defs(self, path):
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        return {n.name: ast.dump(n) for n in tree.body
                if isinstance(n, ast.FunctionDef)}

    def test_every_lifted_function_is_identical_to_the_contract(self):
        contract = self._defs(CONTRACT_PATH)
        lib = self._defs(LIB_PATH)
        assert lib, "the lifted module has no functions in it"
        for name, dumped in lib.items():
            assert name in contract, f"{name} is in lib/ and not in the contract"
            assert dumped == contract[name], f"{name} has drifted from the contract"

    def test_it_lifts_the_rules_that_matter(self):
        lib = self._defs(LIB_PATH)
        for name in ("mirrors", "reconcile", "classify", "ratchet_agrees",
                     "structurally_sound", "build_prompt"):
            assert name in lib

    def test_the_lifted_module_holds_no_storage_and_no_contract(self):
        """Checked against the parsed tree, not against the text. A substring
        search hits the word 'itself.' in a docstring and fails a clean file,
        which is a test that cries wolf until somebody deletes it."""
        tree = ast.parse(pathlib.Path(LIB_PATH).read_text(encoding="utf-8"))
        assert not [n for n in tree.body if isinstance(n, ast.ClassDef)]
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                src = ast.unparse(node)
                assert not src.startswith("self."), f"{src} touches storage"
                assert not src.startswith("gl."), f"{src} is not pure"
            if isinstance(node, ast.Name):
                assert node.id not in ("DynArray", "TreeMap", "allow_storage")
