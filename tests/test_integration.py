"""Integration tests, run against GenLayer Studio with gltest.

    pip install genlayer-test
    pip install genlayer-test
    GENLAYER_STUDIO=1 gltest --network studionet tests/test_integration.py

They are opt in: without GENLAYER_STUDIO set they skip, so that
`pytest tests/ -q` stays clean on a machine that has genlayer-test
installed but no Studio to talk to.

These are slower than the other two suites and they prove something different:
that the contract deploys, that storage round-trips, that the deterministic
gates fire, and that the whole leader-plus-validator cycle completes against a
real runtime rather than against tests/glsim.py.

Everything here exercises the deterministic half, which needs no inference: a
commitment opens with a frozen catalogue, revisions are proposed, the authority
rules fire, and the version guard refuses a stale proposal. The judging path
costs two prompts and belongs in a manual Studio run.
"""

import os

import pytest

# gltest is only needed for this file. Skip cleanly when it is absent so that
# `pytest tests/` works out of the box on a machine with nothing installed but
# pytest, and still runs everything in test_logic.py and test_e2e.py.
gltest = pytest.importorskip(
    "gltest",
    reason="integration tests need genlayer-test and a running Studio: "
           "pip install genlayer-test, then GENLAYER_STUDIO=1 gltest",
)
from gltest import get_contract_factory, get_accounts        # noqa: E402
from gltest.assertions import tx_execution_succeeded         # noqa: E402


# The second half of the same guard, and it is the half that bites.
#
# importorskip above covers "genlayer-test is not installed". It does NOT cover
# "genlayer-test IS installed and there is no Studio to talk to", which is the
# common case for anybody who reviews GenLayer contracts: the plugin loads,
# collects this file, and every test in it fails on a connection error rather
# than skipping. `pytest tests/ -q` then reports a wall of ERRORs on a
# repository whose README promises a clean offline run, and the reader cannot
# tell an unreachable network from a broken contract.
#
# Detecting it does not work. A probe was tried first and thrown away: the
# transport failures here are INTERMITTENT rather than a clean threshold, so
# the probe passes and the deploy that follows it still dies. Something that
# answers correctly only most of the time is worse than no gate at all.
#
# So the gate is explicit. These tests need a live Studio, and you say so.
if not os.environ.get("GENLAYER_STUDIO"):
    pytest.skip(
        "integration tests run against a live GenLayer Studio and are opt in: "
        "set GENLAYER_STUDIO=1 to enable them. Everything else runs offline "
        "with pytest tests/ -q",
        allow_module_level=True,
    )


LABEL = "Acme Data Ltd"
DIMS = "data retention|third party sharing|breach notice"
ORIGINAL = ("We retain personal data for at most 90 days, we never share it "
            "with third parties, and we notify affected users within 72 hours "
            "of a breach.")
TIGHTER = ("We retain personal data for at most 30 days, we never share it "
           "with any third party, and we notify users within 24 hours.")


class TestRatchet:
    @pytest.fixture
    def contract(self):
        factory = get_contract_factory(contract_file_path="ratchet.py")
        return factory.deploy(args=[])

    def test_a_commitment_opens_with_a_frozen_catalogue(self, contract):
        tx = contract.open(args=[LABEL, ORIGINAL, DIMS])
        assert tx_execution_succeeded(tx)
        got = contract.commitment(args=[0])
        assert got["label"] == LABEL and got["version"] == 0
        names = [d["name"] for d in contract.dimensions_of(args=[0])["dimensions"]]
        assert names == ["data retention", "third party sharing", "breach notice"]

    def test_a_revision_lands_before_it_is_judged(self, contract):
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        assert tx_execution_succeeded(contract.propose(args=[0, TIGHTER]))
        # recording is not judging
        assert contract.verdict(args=[0]) == ""
        assert contract.revision(args=[0])["judged"] is False
        assert contract.text(args=[0]) == ORIGINAL

    def test_proposing_the_current_text_is_refused(self, contract):
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        with pytest.raises(Exception):
            contract.propose(args=[0, ORIGINAL])

    def test_duplicate_dimensions_are_refused(self, contract):
        with pytest.raises(Exception):
            contract.open(args=[LABEL, ORIGINAL, "retention|retention"])

    def test_a_closed_commitment_takes_no_revisions(self, contract):
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        assert tx_execution_succeeded(contract.close(args=[0]))
        with pytest.raises(Exception):
            contract.propose(args=[0, TIGHTER])

    def test_closing_twice_is_refused(self, contract):
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        contract.close(args=[0])
        with pytest.raises(Exception):
            contract.close(args=[0])

    def test_an_unknown_commitment_is_refused(self, contract):
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        with pytest.raises(Exception):
            contract.commitment(args=[9])

    def test_a_negative_id_does_not_return_the_newest_row(self, contract):
        # Python accepts -1 and hands back the last row, correctly formatted,
        # with nothing failing anywhere.
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        with pytest.raises(Exception):
            contract.commitment(args=[-1])


class TestAuthority:
    """The authorisation rules, against a real runtime.

    These matter more than the rest of this file. tests/glsim.py models
    gl.message.sender_address with a variable a test can set; a node derives it
    from a signature. A rule that holds in the simulator and not on chain would
    be invisible to every other test here.
    """

    @pytest.fixture
    def two(self):
        accounts = get_accounts()
        if len(accounts) < 2:
            pytest.skip(
                "needs two configured accounts on this network, so that a "
                "refusal is a refusal and not an unfunded sender"
            )
        return accounts[0], accounts[1]

    @pytest.fixture
    def contract(self, two):
        owner, _ = two
        factory = get_contract_factory(contract_file_path="ratchet.py")
        return factory.deploy(args=[], account=owner)

    def test_a_stranger_cannot_propose_on_someone_elses_commitment(self, contract, two):
        _, stranger = two
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        with pytest.raises(Exception):
            contract.connect(stranger).propose(args=[0, TIGHTER])
        assert contract.history(args=[0])["revisions"] == []

    def test_a_delegate_may_propose_and_the_record_names_them(self, contract, two):
        _, agent = two
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        assert tx_execution_succeeded(contract.authorise(args=[0, agent.address]))
        assert tx_execution_succeeded(
            contract.connect(agent).propose(args=[0, TIGHTER]))
        assert contract.revision(args=[0])["by"].lower() == agent.address.lower()

    def test_a_revoked_delegate_cannot_propose(self, contract, two):
        _, agent = two
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        contract.authorise(args=[0, agent.address])
        assert tx_execution_succeeded(contract.revoke(args=[0, agent.address]))
        with pytest.raises(Exception):
            contract.connect(agent).propose(args=[0, TIGHTER])

    def test_a_delegate_may_not_authorise_revoke_or_close(self, contract, two):
        _, agent = two
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        contract.authorise(args=[0, agent.address])
        for call, args in (("authorise", [0, agent.address]),
                           ("revoke", [0, agent.address]),
                           ("close", [0])):
            with pytest.raises(Exception):
                getattr(contract.connect(agent), call)(args=args)

    def test_may_propose_answers_what_propose_enforces(self, contract, two):
        owner, agent = two
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        assert contract.may_propose(args=[0, owner.address]) is True
        assert contract.may_propose(args=[0, agent.address]) is False
        contract.authorise(args=[0, agent.address])
        assert contract.may_propose(args=[0, agent.address]) is True

    def test_an_address_is_matched_by_value_not_by_spelling(self, contract, two):
        """An Address is 20 raw bytes on chain, so case carries no meaning."""
        _, agent = two
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        contract.authorise(args=[0, agent.address.lower()])
        upper = "0x" + agent.address[2:].upper()
        assert contract.may_propose(args=[0, upper]) is True

    def test_a_malformed_delegate_address_is_refused(self, contract):
        contract.open(args=[LABEL, ORIGINAL, DIMS])
        with pytest.raises(Exception):
            contract.authorise(args=[0, "not-an-address"])
