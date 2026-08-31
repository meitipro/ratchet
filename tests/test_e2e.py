"""
End-to-end tests. The real contract file, executed.

tests/test_logic.py covers the pure rules. This file covers everything they
cannot reach: the deterministic half, storage round-trips, the two-pass block,
the version guard, the authority rules, and every branch that only fires when
the leader and a validator see different things.

It runs on tests/glsim.py, a small GenVM stand-in, so it needs no Studio and no
network:

    pytest tests/test_e2e.py -v

The important property is that the leader and the validator get their own
independent mock answers. Every mocking framework feeds both nodes the same
data by default, which is exactly why a contract that quietly assumes both
nodes see identical bytes passes its suite and fails on a real network.
"""

import ast
import pathlib

import pytest

import glsim as S

CONTRACT_PATH = "contracts/ratchet.py"

LABEL = "Acme Data Ltd"
DIMS = "data retention|third party sharing|breach notice"

ORIGINAL = ("We retain personal data for at most 90 days, we never share it "
            "with third parties, and we notify affected users within 72 hours "
            "of a breach.")
TIGHTER = ("We retain personal data for at most 30 days, we never share it "
           "with third parties, and we notify affected users within 24 hours "
           "of a breach.")
DROPPED = ("We retain personal data for at most 30 days and we notify affected "
           "users within 24 hours of any confirmed security breach.")

# The two prompts differ only in which role each positional block carries, so a
# mock keys on that line. Keying on the text itself would not work: both texts
# appear in both prompts.
FWD = "<first> is THE PUBLISHED TEXT"
REV = "<first> is THE PROPOSED TEXT"


def passes(forward, reverse, because="the retention window is shorter"):
    """Mock both passes of one block.

    Written as two separate entries on purpose: a test that fed both passes the
    same answer would never exercise the mirror, and the mirror is the whole
    mechanism.
    """
    return {
        FWD: {"tokens": forward, "because": because},
        REV: {"tokens": reverse, "because": because},
    }


class TestRatchet:
    REGISTRAR = "0x" + "11" * 20
    AGENT = "0x" + "77" * 20
    STRANGER = "0x" + "99" * 20

    def deploy(self, label=LABEL, text=ORIGINAL, dims=DIMS):
        c = S.deploy(CONTRACT_PATH)
        S.call(c, "open", label, text, dims)
        return c

    def mocks(self, prompts, v_prompts=None):
        S.set_mocks(leader_pages={}, leader_prompts=prompts,
                    validator_pages={},
                    validator_prompts=v_prompts if v_prompts is not None else prompts)

    # -- the commitment -----------------------------------------------------

    def test_a_commitment_opens_with_a_frozen_catalogue(self):
        c = self.deploy()
        got = c.commitment(0)
        assert got["label"] == LABEL
        assert got["text"] == ORIGINAL
        assert got["version"] == 0
        assert got["dimensions"] == 3
        assert [d["name"] for d in c.dimensions_of(0)["dimensions"]] == [
            "data retention", "third party sharing", "breach notice"]

    # -- the ratchet turning ------------------------------------------------

    def test_a_tightening_is_applied_and_bumps_the_version(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("narrower|same|narrower", "broader|same|broader"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "tightened"
        assert c.revision(0)["applied"] is True
        assert c.text(0) == TIGHTER
        assert c.commitment(0)["version"] == 1

    def test_a_restatement_is_accepted_and_moves_nothing(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|same|same", "same|same|same"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "restated"
        assert c.revision(0)["applied"] is False
        assert c.text(0) == ORIGINAL
        assert c.commitment(0)["version"] == 0

    def test_a_dropped_clause_is_a_loosening_and_is_refused(self):
        """The failure this contract exists for. Nothing is contradicted: a
        clause is simply gone, and the revision reads as an improvement."""
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("narrower|broader|narrower", "broader|narrower|broader"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "broadened"
        assert c.loosened(0) == "1"
        assert c.revision(0)["applied"] is False
        assert c.text(0) == ORIGINAL

    def test_a_tightening_elsewhere_does_not_pay_for_a_loosening(self):
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("narrower|broader|narrower", "broader|narrower|broader"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "broadened"

    def test_the_named_dimension_is_the_one_that_loosened(self):
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("same|broader|same", "same|narrower|same"))
        S.call(c, "judge", 0)
        rows = c.revision(0)["per_dimension"]
        assert rows[1]["name"] == "third party sharing"
        assert rows[1]["token"] == "broader"

    # -- the leader disagreeing with itself ---------------------------------

    def test_a_leader_that_fails_its_own_mirror_stores_unclear(self):
        """The Winnow lesson, applied from the first commit. The uncertainty
        goes into the STORED value, not into a tolerance in the agreement
        rule, so the record never reads decisive where the leader was not."""
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        # dimension 1: narrower forward AND narrower backward, which cannot
        # both be true of the same pair of texts.
        self.mocks(passes("narrower|narrower|same", "broader|narrower|same"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "indeterminate"
        assert [r["token"] for r in c.revision(0)["per_dimension"]] == [
            "narrower", "unclear", "same"]
        assert c.text(0) == ORIGINAL

    def test_unclear_outranks_a_loosening(self):
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("broader|same|same", "broader|same|same"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "indeterminate"

    def test_an_unusable_pass_makes_every_dimension_unclear(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("narrower|same", "broader|same|same"))   # wrong length
        S.call(c, "judge", 0)
        assert c.verdict(0) == "indeterminate"
        assert [r["token"] for r in c.revision(0)["per_dimension"]] == [
            "unclear", "unclear", "unclear"]

    def test_a_garbage_token_is_not_read_as_same(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("narrower|nonsense|same", "broader|same|same"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "indeterminate"

    # -- consensus ----------------------------------------------------------

    def test_nodes_naming_different_dimensions_do_not_agree(self):
        """Recording 'something loosened' would be worse than recording
        nothing, so this must fail rather than settle."""
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("broader|same|same", "narrower|same|same"),
                   v_prompts=passes("same|broader|same", "same|narrower|same"))
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)
        assert c.verdict(0) == ""

    def test_one_differing_dimension_is_enough_to_refuse(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("narrower|same|same", "broader|same|same"),
                   v_prompts=passes("narrower|same|narrower", "broader|same|broader"))
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)

    def test_two_nodes_that_both_reach_unclear_have_agreed(self):
        """What they agreed is that the revision is not applicable, which is a
        real outcome and gets recorded as one."""
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("narrower|narrower|same", "narrower|narrower|same"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "indeterminate"

    def test_nothing_is_written_when_a_judgment_fails(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("narrower|same|same", "broader|same|same"))
        S.call(c, "judge", 0)
        assert c.commitment(0)["version"] == 1
        # revision 1 is now stale, so it cannot be judged at all
        with pytest.raises(S.UserError, match="older version"):
            S.call(c, "judge", 1)
        assert c.ratchet(0)["judged"] == 1

    # -- a leader that does not play by its own rules ------------------------
    #
    # What reaches a validator is whatever the leader put on the wire, and that
    # need not be anything the leader's own code could produce: a patched node,
    # a different build, a deliberate lie. Every shape check in validator_fn
    # exists for this case and for no other, so it can only be tested by
    # putting a payload on the wire that leader_fn would never return.

    def test_a_leader_sending_the_wrong_number_of_dimensions_is_rejected(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|same|same", "same|same|same"))
        S.set_leader_payload({"vector": "same|same", "because": "short"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert c.verdict(0) == ""

    def test_a_leader_sending_an_invented_token_is_rejected(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|same|same", "same|same|same"))
        S.set_leader_payload({"vector": "same|definitely|same", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)

    def test_the_free_layer_is_actually_free(self):
        """Layer 1 rejects a malformed proposal BEFORE the validator spends two
        prompts on it. Remove it and the contract still refuses, because the
        agreement rule checks the shape as well, so the only difference the
        removal makes is the cost -- and the cost IS the reason layer 1 exists.
        A defence whose only effect is unmeasured is a defence nobody will keep."""
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|same|same", "same|same|same"))
        S.set_leader_payload({"vector": "same|same", "because": "short"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 0

        # and for contrast: a well formed proposal it disagrees with DOES cost
        # the validator its two prompts, because there is no way to know
        # without asking.
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("same|same|same", "same|same|same"),
                   v_prompts=passes("narrower|same|same", "broader|same|same"))
        with pytest.raises(S.UserError):
            S.call(c, "judge", 1)
        assert S.validator_prompt_calls() == 2

    def test_a_leader_cannot_smuggle_a_verdict_past_the_deterministic_half(self):
        """The block returns tokens, never an outcome. A leader that tried to
        send `tightened` sends an illegal token, not a decision."""
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|same|same", "same|same|same"))
        S.set_leader_payload({"vector": "tightened|same|same", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert c.text(0) == ORIGINAL

    # -- the version guard --------------------------------------------------

    def test_a_revision_written_against_an_older_text_is_refused(self):
        """Two proposals cannot race each other into the same slot. The second
        was written against a text that no longer exists, so judging it would
        compare it against something its author never saw."""
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("narrower|same|same", "broader|same|same"))
        S.call(c, "judge", 0)
        with pytest.raises(S.UserError, match="older version"):
            S.call(c, "judge", 1)

    def test_a_refused_revision_does_not_stale_its_siblings(self):
        """Only an APPLIED revision moves the version, so a rejected one leaves
        every other pending proposal judgeable."""
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|broader|same", "same|narrower|same"))
        S.call(c, "judge", 0)
        assert c.commitment(0)["version"] == 0
        self.mocks(passes("narrower|same|narrower", "broader|same|broader"))
        S.call(c, "judge", 1)
        assert c.verdict(1) == "tightened"

    def test_reproposing_after_a_tightening_works(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("narrower|same|same", "broader|same|same"))
        S.call(c, "judge", 0)
        S.call(c, "propose", 0, DROPPED)
        assert c.revision(1)["base_version"] == 1
        self.mocks(passes("same|broader|same", "same|narrower|same"))
        S.call(c, "judge", 1)
        assert c.verdict(1) == "broadened"

    def test_judging_twice_is_refused(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|same|same", "same|same|same"))
        S.call(c, "judge", 0)
        with pytest.raises(S.UserError, match="already judged"):
            S.call(c, "judge", 0)

    # -- authority ----------------------------------------------------------

    def test_a_stranger_cannot_propose_on_someone_elses_commitment(self):
        """A revision that survives judgment REPLACES the published text, so an
        unauthenticated propose() lets a stranger rewrite somebody else's
        commitment through the front door."""
        c = self.deploy()
        S.set_sender(self.STRANGER)
        try:
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "propose", 0, TIGHTER)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.revision_count() == 0

    def test_holding_a_commitment_grants_nothing_over_another_one(self):
        c = self.deploy()
        S.set_sender(self.STRANGER)
        try:
            S.call(c, "open", "Impostor Ltd", ORIGINAL, DIMS)
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "propose", 0, TIGHTER)
            S.call(c, "propose", 1, TIGHTER)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.history(0)["revisions"] == []
        assert len(c.history(1)["revisions"]) == 1

    def test_a_delegate_may_propose_and_the_record_names_them(self):
        c = self.deploy()
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            S.call(c, "propose", 0, TIGHTER)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.revision(0)["by"].lower() == self.AGENT
        assert c.commitment(0)["registrar"].lower() == self.REGISTRAR

    def test_a_revoked_delegate_cannot_propose(self):
        c = self.deploy()
        S.call(c, "authorise", 0, self.AGENT)
        S.call(c, "revoke", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "propose", 0, TIGHTER)
        finally:
            S.set_sender(self.REGISTRAR)

    def test_revoking_does_not_erase_what_was_already_proposed(self):
        c = self.deploy()
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            S.call(c, "propose", 0, TIGHTER)
        finally:
            S.set_sender(self.REGISTRAR)
        S.call(c, "revoke", 0, self.AGENT)
        assert c.revision(0)["by"].lower() == self.AGENT
        assert c.revision(0)["text"] == TIGHTER

    def test_only_the_registrar_may_authorise_revoke_or_close(self):
        c = self.deploy()
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.STRANGER)
        try:
            for call, args in (("authorise", (0, self.STRANGER)),
                               ("revoke", (0, self.AGENT)),
                               ("close", (0,))):
                with pytest.raises(S.UserError, match="registrar"):
                    S.call(c, call, *args)
        finally:
            S.set_sender(self.REGISTRAR)

    def test_a_delegate_may_not_authorise_revoke_or_close(self):
        """A delegate speaks on the commitment. It does not own it, and a
        delegate able to revoke could remove every other delegate and become
        the only voice on a commitment it does not own."""
        c = self.deploy()
        other = "0x" + "55" * 20
        S.call(c, "authorise", 0, self.AGENT)
        S.call(c, "authorise", 0, other)
        S.set_sender(self.AGENT)
        try:
            for call, args in (("authorise", (0, self.STRANGER)),
                               ("revoke", (0, other)),
                               ("revoke", (0, self.AGENT)),
                               ("close", (0,))):
                with pytest.raises(S.UserError, match="registrar"):
                    S.call(c, call, *args)
        finally:
            S.set_sender(self.REGISTRAR)
        assert [d["active"] for d in c.delegation(0)["delegates"]] == [True, True]

    def test_an_address_is_matched_by_value_not_by_spelling(self):
        """On chain an Address is 20 raw bytes and case carries no meaning."""
        c = self.deploy()
        S.call(c, "authorise", 0, "0x" + "AB" * 20)
        S.set_sender("0x" + "ab" * 20)
        try:
            S.call(c, "propose", 0, TIGHTER)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.revision_count() == 1

    def test_may_propose_answers_what_propose_enforces(self):
        c = self.deploy()
        S.call(c, "authorise", 0, self.AGENT)
        assert c.may_propose(0, self.REGISTRAR) is True
        assert c.may_propose(0, self.AGENT) is True
        assert c.may_propose(0, self.STRANGER) is False
        assert c.may_propose(0, "not-an-address") is False
        for who in (self.REGISTRAR, self.AGENT, self.STRANGER):
            S.set_sender(who)
            try:
                if c.may_propose(0, who):
                    S.call(c, "propose", 0, TIGHTER)
                else:
                    with pytest.raises(S.UserError):
                        S.call(c, "propose", 0, TIGHTER)
            finally:
                S.set_sender(self.REGISTRAR)

    @pytest.mark.parametrize("bad", ["", "0x", "not-an-address", "0x" + "z" * 40,
                                     "0x" + "11" * 19, "0x" + "11" * 21])
    def test_a_malformed_delegate_address_is_refused_cleanly(self, bad):
        c = self.deploy()
        with pytest.raises(S.UserError, match="not a 20 byte hex address"):
            S.call(c, "authorise", 0, bad)

    def test_the_delegate_cap_counts_active_rows(self):
        c = self.deploy()
        addrs = ["0x" + ("%02x" % (i + 32)) * 20 for i in range(16)]
        for a in addrs:
            S.call(c, "authorise", 0, a)
        with pytest.raises(S.UserError, match="capped at 16"):
            S.call(c, "authorise", 0, self.AGENT)
        S.call(c, "revoke", 0, addrs[0])
        S.call(c, "authorise", 0, self.AGENT)

    def test_the_cap_survives_a_revoke_and_reauthorise_cycle(self):
        """Counting and matching in one pass looks equivalent to counting first
        and is not: the match can be found before the count is finished, so
        reactivating a revoked row decides against a partial count."""
        c = self.deploy()
        addrs = ["0x" + ("%02x" % (i + 32)) * 20 for i in range(16)]
        for a in addrs:
            S.call(c, "authorise", 0, a)
        S.call(c, "revoke", 0, addrs[0])
        S.call(c, "authorise", 0, self.AGENT)
        with pytest.raises(S.UserError, match="capped at 16"):
            S.call(c, "authorise", 0, addrs[0])
        assert len([d for d in c.delegation(0)["delegates"] if d["active"]]) == 16

    def test_re_authorising_reuses_the_row(self):
        c = self.deploy()
        for _ in range(3):
            S.call(c, "authorise", 0, self.AGENT)
            S.call(c, "revoke", 0, self.AGENT)
        assert len(c.delegation(0)["delegates"]) == 1
        with pytest.raises(S.UserError, match="already revoked"):
            S.call(c, "revoke", 0, self.AGENT)

    def test_delegation_is_scoped_to_one_commitment(self):
        c = self.deploy()
        S.call(c, "open", "Beta Corp", ORIGINAL, DIMS)
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            S.call(c, "propose", 0, TIGHTER)
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "propose", 1, TIGHTER)
        finally:
            S.set_sender(self.REGISTRAR)

    def test_anyone_may_judge_and_that_is_deliberate(self):
        """The ratchet is a public promise. An author who could decide which of
        their own revisions got examined would only ever examine the flattering
        ones. Judging adds no text and, because the version guard pins both
        texts, it is a pure function of state the caller cannot move."""
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("same|broader|same", "same|narrower|same"))
        S.set_sender(self.STRANGER)
        try:
            S.call(c, "judge", 0)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.verdict(0) == "broadened"
        assert c.revision(0)["by"].lower() == self.REGISTRAR

    # -- closing ------------------------------------------------------------

    def test_a_closed_commitment_takes_no_more_revisions(self):
        c = self.deploy()
        S.call(c, "close", 0)
        with pytest.raises(S.UserError, match="closed"):
            S.call(c, "propose", 0, TIGHTER)

    def test_closing_does_not_delete(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        S.call(c, "close", 0)
        assert c.commitment(0)["text"] == ORIGINAL
        assert len(c.history(0)["revisions"]) == 1
        assert c.commitment(0)["closed"] is True

    def test_a_pending_revision_can_still_be_judged_after_closing(self):
        """Closing stops new proposals. It does not erase the ones already
        made, and refusing to judge them would let an author escape a verdict
        by closing the commitment the moment it looked bad."""
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        S.call(c, "close", 0)
        self.mocks(passes("same|broader|same", "same|narrower|same"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "broadened"

    def test_closing_twice_is_refused(self):
        c = self.deploy()
        S.call(c, "close", 0)
        with pytest.raises(S.UserError, match="already closed"):
            S.call(c, "close", 0)

    # -- the record ---------------------------------------------------------

    def test_the_counters_are_what_the_contract_publishes(self):
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("same|broader|same", "same|narrower|same"))
        S.call(c, "judge", 0)
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("narrower|same|same", "broader|same|same"))
        S.call(c, "judge", 1)
        got = c.ratchet(0)
        assert got["proposed"] == 2 and got["judged"] == 2
        assert got["tightened"] == 1 and got["broadened"] == 1
        assert got["loosening_pct"] == 50
        assert got["version"] == 1

    def test_history_lists_every_revision_applied_or_not(self):
        c = self.deploy()
        S.call(c, "propose", 0, DROPPED)
        self.mocks(passes("same|broader|same", "same|narrower|same"))
        S.call(c, "judge", 0)
        rows = c.history(0)["revisions"]
        assert len(rows) == 1
        assert rows[0]["verdict"] == "broadened" and rows[0]["applied"] is False

    def test_a_view_is_safe_before_any_judgment(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        assert c.verdict(0) == ""
        assert c.loosened(0) == ""
        assert c.revision(0)["judged"] is False
        assert c.revision(0)["per_dimension"] == []

    def test_the_reason_is_sanitised_on_the_way_in(self):
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        self.mocks(passes("same|same|same", "same|same|same",
                          because="<script>alert(1)</script> `x` {y}"))
        S.call(c, "judge", 0)
        why = c.revision(0)["why"]
        for ch in "<>{}`\\":
            assert ch not in why

    # -- validation ---------------------------------------------------------

    @pytest.mark.parametrize("text", ["short", "", "   ", "x" * 900])
    def test_bad_commitment_text_is_refused(self, text):
        c = S.deploy(CONTRACT_PATH)
        with pytest.raises(S.UserError):
            S.call(c, "open", LABEL, text, DIMS)
        assert c.count() == 0

    @pytest.mark.parametrize("dims", ["", "   ", "|||", "a|" * 20])
    def test_bad_dimension_lists_are_refused(self, dims):
        c = S.deploy(CONTRACT_PATH)
        with pytest.raises(S.UserError):
            S.call(c, "open", LABEL, ORIGINAL, dims)
        assert c.count() == 0

    def test_more_than_twelve_dimensions_is_refused(self):
        """Distinct names on purpose. A list of thirteen identical names is
        refused by the duplicate rule instead, which leaves the cap untested
        while looking like it is covered."""
        c = S.deploy(CONTRACT_PATH)
        thirteen = "|".join("dimension %d" % i for i in range(13))
        with pytest.raises(S.UserError, match="capped at 12"):
            S.call(c, "open", LABEL, ORIGINAL, thirteen)
        twelve = "|".join("dimension %d" % i for i in range(12))
        S.call(c, "open", LABEL, ORIGINAL, twelve)
        assert c.commitment(0)["dimensions"] == 12

    def test_each_commitment_is_judged_on_its_own_catalogue(self):
        """Two commitments share one flat array of dimensions, so the filter is
        the only thing keeping their yardsticks apart. Without it every
        commitment is judged on every dimension ever registered."""
        c = self.deploy(dims="data retention|third party sharing|breach notice")
        S.call(c, "open", "Beta Corp", ORIGINAL, "uptime|support hours")
        assert [d["name"] for d in c.dimensions_of(1)["dimensions"]] == [
            "uptime", "support hours"]
        assert c.commitment(1)["dimensions"] == 2
        S.call(c, "propose", 1, TIGHTER)
        self.mocks(passes("narrower|same", "broader|same"))
        S.call(c, "judge", 0)
        assert c.verdict(0) == "tightened"
        assert [r["name"] for r in c.revision(0)["per_dimension"]] == [
            "uptime", "support hours"]

    def test_two_dimensions_with_the_same_name_are_refused(self):
        """Two identical names cannot be told apart in the numbered list the
        block sees, so a token would be assigned to whichever the model
        happened to mean."""
        c = S.deploy(CONTRACT_PATH)
        with pytest.raises(S.UserError, match="same name"):
            S.call(c, "open", LABEL, ORIGINAL, "retention|retention")

    def test_proposing_the_current_text_is_refused(self):
        c = self.deploy()
        with pytest.raises(S.UserError, match="the current text"):
            S.call(c, "propose", 0, ORIGINAL)

    def test_a_read_with_a_nonexistent_id_is_a_user_error(self):
        """Not a raw IndexError. GenVM reports an uncaught Python exception as
        a contract error, which tells a caller nothing about what went wrong."""
        c = self.deploy()
        S.call(c, "propose", 0, TIGHTER)
        for m in ("verdict", "loosened", "revision"):
            with pytest.raises(S.UserError, match="no such revision"):
                getattr(c, m)(99)
        for m in ("commitment", "history", "ratchet", "text", "registrar"):
            with pytest.raises(S.UserError, match="no such commitment"):
                getattr(c, m)(99)

    def test_a_read_with_a_negative_id_does_not_return_the_last_row(self):
        """The dangerous half. Python list indexing accepts -1 and returns the
        newest row, so a caller asking for -1 would silently receive a
        different one and never know."""
        c = self.deploy()
        S.call(c, "open", "Beta Corp", ORIGINAL, DIMS)
        S.call(c, "propose", 0, TIGHTER)
        for m in ("verdict", "loosened", "revision"):
            with pytest.raises(S.UserError, match="no such revision"):
                getattr(c, m)(-1)
        for m in ("commitment", "history", "ratchet", "text", "registrar"):
            with pytest.raises(S.UserError, match="no such commitment"):
                getattr(c, m)(-1)


# ===========================================================================
# GenVM storage and boundary rules, by static analysis.
#
# Not tests of behaviour. Tests of SHAPE, and each corresponds to a real
# failure that behaviour tests cannot see.
# ===========================================================================

def c_module_writes():
    """The public write methods of the contract, by name."""
    tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
    cls = [x for x in tree.body if isinstance(x, ast.ClassDef)
           and any("gl.Contract" in ast.unparse(b) for b in x.bases)][0]
    return {m.name: m for m in cls.body if isinstance(m, ast.FunctionDef)
            and any("gl.public.write" in ast.unparse(d) for d in m.decorator_list)}


class TestShape:
    def test_the_contract_imports_under_genvm_storage_rules(self):
        mod = S.load_contract(CONTRACT_PATH)
        assert hasattr(mod, "Contract")

    def test_no_storage_dataclass_holds_a_collection(self):
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            if "allow_storage" not in " ".join(
                    ast.unparse(d) for d in cls.decorator_list):
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert "DynArray" not in ann and "TreeMap" not in ann

    def test_no_forbidden_storage_types(self):
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            decs = " ".join(ast.unparse(d) for d in cls.decorator_list)
            is_contract = any("gl.Contract" in ast.unparse(b) for b in cls.bases)
            if "allow_storage" not in decs and not is_contract:
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert ann not in ("int", "float", "list", "dict", "tuple")
                    assert not ann.startswith(("list[", "dict[", "tuple["))

    def test_no_storage_field_is_declared_twice(self):
        import collections
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            names = [st.target.id for st in cls.body
                     if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)]
            dupes = [n for n, c in collections.Counter(names).items() if c > 1]
            assert not dupes, f"{cls.name} declares {dupes} more than once"

    def test_no_method_is_defined_twice(self):
        """A duplicated method silently shadows the first one. Python allows it
        and says nothing at all."""
        import collections
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            names = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
            dupes = [n for n, c in collections.Counter(names).items() if c > 1]
            assert not dupes, f"{cls.name} defines {dupes} more than once"
        names = [x.name for x in tree.body
                 if isinstance(x, (ast.FunctionDef, ast.ClassDef))]
        dupes = [n for n, c in collections.Counter(names).items() if c > 1]
        assert not dupes

    def test_every_persistent_field_is_declared_in_the_class_body(self):
        """A field created with self.x = value and never declared is NOT
        persistent. It is silently discarded when execution ends."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        cls = [x for x in tree.body if isinstance(x, ast.ClassDef)
               and any("gl.Contract" in ast.unparse(b) for b in x.bases)][0]
        declared = {st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)}
        for m in [x for x in cls.body if isinstance(x, ast.FunctionDef)]:
            for node in ast.walk(m):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target] if isinstance(node, ast.AugAssign) else [])
                for tg in targets:
                    if (isinstance(tg, ast.Attribute)
                            and isinstance(tg.value, ast.Name)
                            and tg.value.id == "self"):
                        assert tg.attr in declared, (
                            f"{m.name} assigns self.{tg.attr}, undeclared, will not persist")

    def test_the_block_boundary_carries_flat_strings_only(self):
        """A nested mapping or a bool here fails inside the calldata encoder,
        which is OUTSIDE the contract, so it produces Result Code <unknown>
        with no stderr and no traceback at all."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        blocks = [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                  and x.name == "leader_fn"]
        assert blocks
        for blk in blocks:
            returns = [n for n in ast.walk(blk) if isinstance(n, ast.Return)]
            assert returns
            for r in returns:
                assert isinstance(r.value, ast.Dict)
                for k, v in zip(r.value.keys, r.value.values):
                    assert isinstance(k, ast.Constant) and isinstance(k.value, str)
                    assert not isinstance(v, (ast.Dict, ast.List, ast.Set, ast.Tuple))
                    assert not isinstance(v, (ast.Compare, ast.BoolOp))
                    if isinstance(v, ast.UnaryOp):
                        assert not isinstance(v.op, ast.Not)

    def test_every_nondet_call_sits_inside_a_block(self):
        """gl.nondet.* outside a closure the consensus flow recognises fails
        genvm-lint with 'not reachable from equivalence principle block'. A
        GenLayer submission has been rejected for having this in its DEPLOYED
        source while the repository version was clean."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        inner = set()
        for fn in [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                   and x.name in ("leader_fn", "validator_fn")]:
            for n in ast.walk(fn):
                inner.add(id(n))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and ast.unparse(node).startswith("gl.nondet"):
                assert id(node) in inner, (
                    f"{ast.unparse(node)} is outside leader_fn/validator_fn")

    def test_the_two_unfenced_prompt_arguments_are_always_literals(self):
        """build_prompt takes two arguments that are NOT fenced, because they
        name which role each block carries and the contract writes them. That
        exemption is only sound while every call site passes a literal: an edit
        that routed a caller string through one of them would hand the model an
        unfenced value with a test still saying the prompt is fenced."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "build_prompt"]
        assert len(calls) == 2, "expected one call per presentation order"
        for call in calls:
            for arg in call.args[4:]:
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                    "a non-literal reaches the model unfenced: %s" % ast.unparse(arg))

    def test_every_write_that_touches_a_commitment_checks_the_sender(self):
        """This covers the methods nobody has written yet: a new public write
        added later without an authority check fails here, and the only way to
        pass is to gate it or to add it to the list below on purpose, which is
        a decision somebody has to make in a diff rather than by omission.

          open   creates the commitment and becomes its registrar, so there is
                 no earlier owner to check against
          judge  deliberately open. The ratchet is a public promise, and an
                 author who chose which of their own revisions got examined
                 would examine only the flattering ones. It adds no text, and
                 the version guard pins both texts, so it is a pure function of
                 state the caller cannot move.
        """
        UNGATED = {"open", "judge"}
        gated = c_module_writes()
        assert gated, "no public writes found, the walk is broken"
        for name, m in gated.items():
            if name in UNGATED:
                continue
            body = ast.unparse(m)
            assert "sender_address" in body or "_may_propose" in body, (
                f"{name} is a public write with no authority check")

    def test_the_catalogue_is_frozen(self):
        """Only open() may append to self.dimensions. A method that could add
        or rename one would let an author drop the dimension they were about to
        weaken, and the next revision would come back restated."""
        for name, m in c_module_writes().items():
            src = ast.unparse(m)
            if name == "open":
                continue
            assert "self.dimensions.append" not in src, f"{name} edits the catalogue"
            assert ".name =" not in src, f"{name} renames a dimension"

    def test_only_a_tightening_moves_the_published_text(self):
        """The ratchet turns one way. An assignment to c.text anywhere outside
        the TIGHTENED branch would make it turn both ways, silently."""
        src = pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8")
        assert src.count("c.text = ") == 1
        tree = ast.parse(src)
        judge = [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                 and x.name == "judge"][0]
        for node in ast.walk(judge):
            if not isinstance(node, ast.If):
                continue
            body = ast.unparse(node.body)
            if "c.text = " in body:
                assert "TIGHTENED" in ast.unparse(node.test)
                return
        raise AssertionError("no branch assigns the published text")
