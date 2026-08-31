# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Ratchet — a published commitment that can only ever be tightened
================================================================

WHAT IT IS
    A reusable primitive that decides whether a proposed revision to a public
    commitment TIGHTENS it, RESTATES it, or QUIETLY LOOSENS it — dimension by
    dimension, against a catalogue frozen when the commitment was opened. Only
    a tightening is applied. Everything else is recorded and refused.

THE PROBLEM IT SOLVES
    An organisation publishes "we retain your data for 90 days and never share
    it with third parties". A year later it publishes a revision. The revision
    is longer, better written, and adds a paragraph about security. It also no
    longer mentions third parties.

    Nothing was contradicted. A clause was DROPPED, and dropping a clause is
    how a commitment gets weaker without any sentence ever saying so. Read the
    revision alone and it is an improvement. Only the pair carries the loss.

    The two texts are prose, and prose is where consensus normally gives up.
    Asking five nodes to agree on whether a document "is weaker" invites five
    different sentences. Ratchet never asks that question.

HOW CONSENSUS IS USED  (this is the interesting part)
    The catalogue of dimensions is fixed at open() and belongs to the contract.
    The block sees the two texts and the numbered catalogue, and answers ONE OF
    THREE TOKENS PER DIMENSION: narrower, same, broader. Nothing else is a
    legal answer.

        The judgment is hard. Read two policies, work out what each one
        actually binds its author to, and tell one commitment from its
        paraphrase.

        The thing that crosses consensus is a vector of three-valued
        tokens over a list the contract already holds.

    THE LEADER RESOLVES ITS OWN UNCERTAINTY BEFORE ANYONE COMPARES ANYTHING.
    The block runs the comparison TWICE — once forward, once with the two texts
    swapped — and the answers must mirror: if the revision is narrower on a
    dimension, then the original must be broader on that same dimension. A
    dimension whose two passes do not mirror becomes `unclear`, and `unclear`
    IS THE STORED VALUE.

    That ordering matters more than it looks. The alternative — keep a precise
    stored value and let the agreement rule forgive a difference — produces a
    record that reads decisive while the nodes privately disagreed. Uncertainty
    belongs in the value, never in the comparison.

    The validator then has two layers:

      1. STRUCTURAL HONESTY, checked for free.
         The vector must have exactly one entry per catalogue dimension and
         every entry must be one of the four legal tokens. Checked against data
         the validator already holds, without running a single prompt. A
         malformed proposal dies before any inference is spent on it.

      2. EXACT EQUALITY ON THE WHOLE VECTOR.
         Not "we both found a loosening somewhere". The same dimensions, the
         same tokens, all of them. Two nodes that disagree about which clause
         got weaker have not agreed about anything worth applying.

WHY IT IS NOT A THIN LLM WRAPPER
    The model never decides an outcome. It answers three-way multiple choice
    against a list the contract owns, twice. Everything else is deterministic:
    the mirror rule, the reconciliation, the verdict derived from the vector,
    whether the revision is applied, and whether it was even eligible to be
    judged.

    Swap in a worse model and the mechanism still works. It produces more
    `unclear`, which refuses more revisions, which is the correct response to a
    worse model.

THE RATCHET ONLY TURNS ONE WAY
    A revision judged `tightened` REPLACES the commitment text and bumps its
    version. Anything else is recorded against the revision and the text does
    not move. A revision written against an older version is refused rather
    than judged, so two proposals cannot race each other into the same slot.

WHO MAY WRITE
    register / open       anyone. The caller becomes the registrar, and the
                          registrar IS the identity. The label proves nothing.
    propose               the registrar, or an address the registrar has
                          authorised. Nobody else can put words in somebody
                          else's commitment.
    authorise / revoke    the registrar alone.
    close                 the registrar alone.
    judge                 anyone, deliberately. The ratchet is a public
                          promise, and an author who could decide which of
                          their own revisions got examined would only ever
                          examine the flattering ones. Judging adds no text: it
                          can only reach the verdict the catalogue and the two
                          stored texts already imply, and it cannot run at all
                          on a revision written against a stale version.

    Every revision stores the address that submitted it, readable through
    revision() and history(). Delegation is visible rather than implied.
"""

from genlayer import *
import typing
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Deterministic helpers. Pure, module level, unit tested in tests/test_logic.py
# ---------------------------------------------------------------------------

NARROWER = "narrower"   # the revision binds its author to more on this point
SAME = "same"           # unchanged in effect, however it is worded
BROADER = "broader"     # binds to less, INCLUDING by no longer saying anything
UNCLEAR = "unclear"     # the leader's own two passes did not mirror

TOKENS = (NARROWER, SAME, BROADER, UNCLEAR)
MODEL_TOKENS = (NARROWER, SAME, BROADER)   # what a prompt may legally return

TIGHTENED = "tightened"     # at least one dimension narrower, none loosened
RESTATED = "restated"       # every dimension the same. valid, changes nothing
BROADENED = "broadened"     # at least one dimension loosened. refused
INDETERMINATE = "indeterminate"   # at least one dimension unclear. refused

VERDICTS = (TIGHTENED, RESTATED, BROADENED, INDETERMINATE)

MAX_DIMENSIONS = 12     # per commitment, so one prompt stays bounded
MAX_DELEGATES = 16      # per commitment, so the authority scan stays bounded
MAX_TEXT = 800
MAX_LABEL = 120
MAX_DIMENSION = 80
MAX_REASON = 160


def looks_like_address(raw):
    """Is this a 20 byte hex address, before anything tries to parse it?

    Address() raises a bare Exception on a malformed value, which the runtime
    reports as a contract error rather than as the caller's mistake. Checking
    the shape first turns "the contract crashed" into "that is not an address",
    which is the difference between a bug report and a typo.
    """
    s = str(raw).strip()
    if len(s) != 42 or not s.startswith("0x"):
        return False
    for ch in s[2:]:
        if ch not in "0123456789abcdefABCDEF":
            return False
    return True


def normalise_token(raw):
    """One model answer to a legal token, or empty for anything unusable.

    Empty rather than a guess. A token invented here would be indistinguishable
    downstream from one the model actually returned, and it would be wrong on
    exactly the dimensions the model found hardest.
    """
    s = str(raw).strip().lower()
    if s in MODEL_TOKENS:
        return s
    return ""


def parse_vector(text, n):
    """Pipe joined tokens to a list of length n, or None if it is unusable.

    None is not the same as a vector of empties: it means the answer did not
    have the right shape at all, and a validator must reject it rather than
    compare it.
    """
    parts = str(text).split("|")
    if len(parts) != n:
        return None
    out = []
    for p in parts:
        t = normalise_token(p)
        if t == "":
            return None
        out.append(t)
    return out


def mirrors(forward, reverse):
    """The two passes agree about direction, read from opposite ends.

    If the revision is narrower on a dimension then the original must be
    broader on that same dimension. Anything else means the leader answered
    the same question two different ways, and no amount of consensus between
    NODES can repair a leader that does not agree with itself.
    """
    if forward == NARROWER:
        return reverse == BROADER
    if forward == BROADER:
        return reverse == NARROWER
    if forward == SAME:
        return reverse == SAME
    return False


def reconcile(forward, reverse):
    """Fold the leader's own two passes into ONE stored token per dimension.

    This is the whole design in four lines. A dimension the leader is not
    self-consistent about becomes `unclear` HERE, before any node compares
    anything, so the uncertainty is carried by the value that gets stored
    rather than by a tolerance in the agreement rule.

    A tolerant agreement rule would let two nodes settle while privately
    holding different views of what the caller should do, and the record would
    look decisive. This cannot: `unclear` is visible in the vector, in the
    verdict, and in the refusal.
    """
    if len(forward) != len(reverse):
        return None
    out = []
    for i in range(len(forward)):
        if mirrors(forward[i], reverse[i]):
            out.append(forward[i])
        else:
            out.append(UNCLEAR)
    return out


def classify(vector):
    """Turn a reconciled vector into a verdict. Pure and total.

    The four outcomes are not degrees of one thing. They are different facts
    about the pair of texts:

        tightened      binds to more somewhere and to less nowhere
        restated       identical in effect, however differently it is worded
        broadened      binds to less somewhere, which is what a ratchet exists
                       to catch, INCLUDING when it happens by dropping a clause
                       rather than by contradicting one
        indeterminate  the leader could not answer the same question the same
                       way twice on some dimension
    """
    if len(vector) == 0:
        return INDETERMINATE
    if UNCLEAR in vector:
        return INDETERMINATE
    if BROADER in vector:
        return BROADENED
    if NARROWER in vector:
        return TIGHTENED
    return RESTATED


def loosened_dimensions(vector):
    """Indices of the dimensions that got weaker. Sorted, for a stable string.

    Sorted rather than in discovery order: two nodes finding the same set in a
    different order must produce the same stored value, or banding the answer
    achieves nothing.
    """
    out = []
    for i in range(len(vector)):
        if vector[i] == BROADER:
            out.append(i)
    return sorted(out)


def structurally_sound(vector, n):
    """Layer 1 of the validator. Costs nothing, runs before any prompt.

    Two ways a proposal is malformed regardless of what any model thinks: the
    wrong number of dimensions, or a token that is not one a prompt may return.
    `unclear` is legal in a STORED vector and is not legal here, because a
    validator receives the leader's reconciled answer and must be able to tell
    "the leader was unsure" from "the leader sent rubbish".
    """
    if vector is None:
        return False
    if len(vector) != n or n == 0:
        return False
    for t in vector:
        if t not in TOKENS:
            return False
    return True


def ratchet_agrees(mine, theirs, n):
    """Layer 2. Exact equality on the whole vector, and nothing else.

    Symmetric by construction: both sides go down the same parse and the
    comparison is an equality, so agrees(a, b) == agrees(b, a). An asymmetric
    agreement rule makes consensus depend on who happened to be elected leader,
    which is a subtle and very unpleasant bug.

    There is deliberately no tolerance here. A rule that forgave one dimension
    would let two nodes settle on a record that says `tightened` while one of
    them believed a clause had been dropped.
    """
    a = mine if isinstance(mine, list) else parse_stored(mine, n)
    b = theirs if isinstance(theirs, list) else parse_stored(theirs, n)
    if not structurally_sound(a, n) or not structurally_sound(b, n):
        return False
    return a == b


def parse_stored(text, n):
    """Like parse_vector, but `unclear` is legal: this reads a RECONCILED vector."""
    parts = str(text).split("|")
    if len(parts) != n:
        return None
    out = []
    for p in parts:
        s = str(p).strip().lower()
        if s not in TOKENS:
            return None
        out.append(s)
    return out


def sanitise_reason(raw, limit=MAX_REASON):
    """Clean a leader supplied explanation before it is stored.

    These strings are NOT part of consensus, deliberately: two honest readers
    describe the same loosening differently, and comparing prose would stall
    every judgment. That means a leader chooses them freely, so they are
    treated as untrusted text on the way IN rather than on the way out.
    Nothing in this contract acts on them.
    """
    out = []
    for ch in str(raw):
        if ch in "<>{}\\`":
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            ch = " "
        out.append(ch)
    return " ".join("".join(out).split())[:limit]


def clean_line(raw, limit):
    """A single line of caller text, whitespace collapsed, capped."""
    return " ".join(str(raw).split())[:limit]


def split_dimensions(text):
    """Pipe joined dimension names to a list, empties dropped."""
    out = []
    for part in str(text).split("|"):
        s = clean_line(part, MAX_DIMENSION)
        if s != "":
            out.append(s)
    return out


def build_prompt(label, numbered_dimensions, first_text, second_text, first_name, second_name):
    """One comparison, in one direction.

    The direction is carried by which text is named first, and the two calls
    differ ONLY in that. Building both directions from one template is what
    makes the mirror test meaningful: an asymmetry in the wording would show up
    as a disagreement the leader can never resolve, and every dimension would
    come back unclear.
    """
    return f"""You are comparing two versions of a public commitment made by {label}.

DIRECTION: judge {second_name} against {first_name}.

{first_name}:
{first_text}

{second_name}:
{second_text}

For each numbered dimension below, decide what {second_name} does compared to the
other text:

{numbered_dimensions}

Answer with exactly one word per dimension:

  narrower  {second_name} binds the author to MORE on this dimension: a
            stricter limit, a firmer promise, fewer exceptions.
  same      no difference in what the author is bound to, however differently
            it is worded.
  broader   {second_name} binds the author to LESS on this dimension: a looser
            limit, more exceptions, OR it no longer addresses this dimension
            at all. Saying nothing is broader than making a promise.

Judge only what the author is bound to. Tone, length, formatting and
readability are not dimensions of a commitment.

Return json: {{"tokens": "same|narrower|...", "because": "<= 25 words"}}
with exactly one token per dimension, in order, joined by a pipe."""


# ---------------------------------------------------------------------------
# Storage
#
# GenVM storage forbids `list`, `dict` and `int`, and only fully specialised
# generics are allowed. Every field below is a scalar; every collection is a
# top level contract field. A storage dataclass cannot contain a collection, so
# nothing here nests: a Dimension carries the commitment id it belongs to.
# ---------------------------------------------------------------------------

@allow_storage
@dataclass
class Commitment:
    registrar: Address
    label: str
    text: str
    version: u256
    n_dimensions: u256
    n_proposed: u256
    n_tightened: u256
    n_restated: u256
    n_broadened: u256
    n_indeterminate: u256
    closed: bool


@allow_storage
@dataclass
class Dimension:
    commitment_id: u256
    name: str


@allow_storage
@dataclass
class Revision:
    commitment_id: u256
    by: Address             # the account that submitted it, not merely the owner
    text: str
    at: str
    base_version: u256      # the commitment version this was written against
    judged: bool
    verdict: str
    vector: str             # pipe joined reconciled tokens, "" until judged
    loosened: str           # pipe joined dimension indices, "" when none
    why: str                # leader supplied, sanitised, NOT consensus
    applied: bool


@allow_storage
@dataclass
class Delegate:
    """One address the registrar has authorised to propose on one commitment.

    Flat, with the commitment id on the row, for the same reason Revision is: a
    storage dataclass cannot hold a collection. Revoking clears the flag rather
    than removing the row, so a revoked delegation stays visible.
    """
    commitment_id: u256
    who: Address
    active: bool


class Contract(gl.Contract):
    commitments: DynArray[Commitment]
    dimensions: DynArray[Dimension]
    revisions: DynArray[Revision]
    delegates: DynArray[Delegate]

    def __init__(self):
        pass

    # -- internal ---------------------------------------------------------

    def _commitment(self, commitment_id: u256):
        """Bounds checked lookup, used by every read.

        Two things go wrong without it. An id past the end raises a raw
        IndexError, which the runtime reports as a contract error rather than a
        readable user error. And a NEGATIVE id silently returns the last row,
        so asking for commitment -1 hands back the newest one as if it were the
        one requested. The second is worse, because nothing fails.
        """
        i = int(commitment_id)
        if i < 0 or i >= len(self.commitments):
            raise gl.vm.UserError("no such commitment")
        return self.commitments[i]

    def _revision(self, revision_id: u256):
        i = int(revision_id)
        if i < 0 or i >= len(self.revisions):
            raise gl.vm.UserError("no such revision")
        return self.revisions[i]

    def _dimension_names(self, commitment_id: u256):
        """The frozen catalogue for one commitment, in registration order."""
        target = int(commitment_id)
        out = []
        for i in range(len(self.dimensions)):
            d = self.dimensions[i]
            if int(d.commitment_id) == target:
                out.append(str(d.name))
        return out

    def _delegated(self, commitment_id: u256, who) -> bool:
        """Is `who` an ACTIVE delegate of this commitment?

        A linear scan bounded by MAX_DELEGATES. Revoked rows are still present
        and must not count, so the active flag is read here and never assumed
        from the row existing.
        """
        target = int(commitment_id)
        for i in range(len(self.delegates)):
            d = self.delegates[i]
            if int(d.commitment_id) == target and d.who == who and bool(d.active):
                return True
        return False

    def _may_propose(self, commitment_id: u256, c, who) -> bool:
        """Who may put words into this commitment.

        The registrar, or an address the registrar authorised. Nobody else,
        ever: a revision attributed to an author who did not write it would be
        judged, counted, and — if it happened to tighten — APPLIED, replacing
        the author's own published text with a stranger's.
        """
        return who == c.registrar or self._delegated(commitment_id, who)

    # -- writes -----------------------------------------------------------

    @gl.public.write
    def open(self, label: str, text: str, dimensions: str) -> None:
        """Open a commitment and FREEZE the catalogue it will be judged against.

        The catalogue cannot change afterwards, and that is the point. A
        dimension list that could be edited later would let an author drop the
        dimension they were about to weaken, and the ratchet would report
        `restated` on a commitment that had just been gutted.
        """
        lab = clean_line(label, MAX_LABEL + 1)
        body = " ".join(str(text).split())
        if len(lab) < 2 or len(lab) > MAX_LABEL:
            raise gl.vm.UserError("a commitment needs a label")
        if len(body) < 20:
            raise gl.vm.UserError("a commitment needs to be a sentence, not a fragment")
        if len(body) > MAX_TEXT:
            raise gl.vm.UserError(
                f"a commitment longer than {MAX_TEXT} characters is several commitments"
            )
        names = split_dimensions(dimensions)
        if len(names) == 0:
            raise gl.vm.UserError("a commitment needs at least one dimension to be judged on")
        if len(names) > MAX_DIMENSIONS:
            raise gl.vm.UserError(
                f"a commitment is capped at {MAX_DIMENSIONS} dimensions"
            )
        if len(set(names)) != len(names):
            raise gl.vm.UserError("two dimensions with the same name cannot be told apart")

        cid = len(self.commitments)
        self.commitments.append(
            Commitment(
                registrar=gl.message.sender_address,
                label=lab,
                text=body,
                version=u256(0),
                n_dimensions=u256(len(names)),
                n_proposed=u256(0),
                n_tightened=u256(0),
                n_restated=u256(0),
                n_broadened=u256(0),
                n_indeterminate=u256(0),
                closed=False,
            )
        )
        for name in names:
            self.dimensions.append(Dimension(commitment_id=u256(cid), name=name))

    @gl.public.write
    def propose(self, commitment_id: u256, text: str) -> None:
        """Offer a replacement text. Judged separately, by judge().

        Proposing and judging are two transactions on purpose. A revision is a
        fact about what an author tried to publish, whether or not anybody has
        got around to examining it, and a contract that refused to record what
        it could not immediately judge would have gaps exactly where the
        interesting revisions are.

        The caller must be the registrar or an authorised delegate. This is the
        load bearing check: a revision that survives judgment REPLACES the
        published text, so an unauthenticated write here would let a stranger
        rewrite somebody else's commitment through the front door.
        """
        c = self._commitment(commitment_id)
        if not self._may_propose(commitment_id, c, gl.message.sender_address):
            raise gl.vm.UserError(
                "only the registrar or an authorised delegate may propose a revision"
            )
        if bool(c.closed):
            raise gl.vm.UserError("this commitment is closed to revisions")

        body = " ".join(str(text).split())
        if len(body) < 20:
            raise gl.vm.UserError("a revision needs to be a sentence, not a fragment")
        if len(body) > MAX_TEXT:
            raise gl.vm.UserError(
                f"a revision longer than {MAX_TEXT} characters is several revisions"
            )
        if body == str(c.text):
            raise gl.vm.UserError("this revision is the current text")

        self.revisions.append(
            Revision(
                commitment_id=u256(int(commitment_id)),
                by=gl.message.sender_address,
                text=body,
                at=gl.message_raw["datetime"],
                base_version=c.version,
                judged=False,
                verdict="",
                vector="",
                loosened="",
                why="",
                applied=False,
            )
        )
        c.n_proposed = c.n_proposed + u256(1)

    @gl.public.write
    def authorise(self, commitment_id: u256, who: str) -> None:
        """Let another address propose on this commitment. Registrar only.

        Taken as a hex string rather than as an Address so that a malformed
        value is refused as the caller's mistake instead of raising inside the
        type constructor, where it surfaces as a contract error.
        """
        c = self._commitment(commitment_id)
        if gl.message.sender_address != c.registrar:
            raise gl.vm.UserError("only the registrar may authorise a delegate")
        if not looks_like_address(who):
            raise gl.vm.UserError("that is not a 20 byte hex address")
        addr = Address(str(who).strip())
        if addr == c.registrar:
            raise gl.vm.UserError("the registrar already proposes on this commitment")

        # Count the whole commitment BEFORE deciding anything. Counting and
        # matching in one pass looks equivalent and is not: the match can be
        # found before the count has finished, and reactivating a revoked row
        # on a partial count walks straight past the cap.
        target = int(commitment_id)
        live = 0
        found = -1
        for i in range(len(self.delegates)):
            d = self.delegates[i]
            if int(d.commitment_id) != target:
                continue
            if bool(d.active):
                live = live + 1
            if d.who == addr:
                found = i

        if found >= 0:
            row = self.delegates[found]
            if bool(row.active):
                raise gl.vm.UserError("already authorised")
            if live >= MAX_DELEGATES:
                raise gl.vm.UserError(
                    f"a commitment is capped at {MAX_DELEGATES} active delegates"
                )
            row.active = True
            return

        if live >= MAX_DELEGATES:
            raise gl.vm.UserError(
                f"a commitment is capped at {MAX_DELEGATES} active delegates"
            )
        self.delegates.append(
            Delegate(commitment_id=u256(target), who=addr, active=True)
        )

    @gl.public.write
    def revoke(self, commitment_id: u256, who: str) -> None:
        """Withdraw a delegation. Registrar only.

        Revisions the delegate already proposed stay on the record and keep
        naming the address that proposed them. Revoking removes the authority
        to propose from now on; it does not rewrite what was already offered.
        """
        c = self._commitment(commitment_id)
        if gl.message.sender_address != c.registrar:
            raise gl.vm.UserError("only the registrar may revoke a delegate")
        if not looks_like_address(who):
            raise gl.vm.UserError("that is not a 20 byte hex address")
        addr = Address(str(who).strip())

        target = int(commitment_id)
        for i in range(len(self.delegates)):
            d = self.delegates[i]
            if int(d.commitment_id) == target and d.who == addr:
                if not bool(d.active):
                    raise gl.vm.UserError("already revoked")
                d.active = False
                return
        raise gl.vm.UserError("that address is not a delegate of this commitment")

    @gl.public.write
    def close(self, commitment_id: u256) -> None:
        """Stop accepting revisions. Registrar only, and permanent.

        Closing does not delete: the text, the catalogue and every revision
        ever proposed stay readable. A commitment that was made and then closed
        is a different fact from one never made.
        """
        c = self._commitment(commitment_id)
        if gl.message.sender_address != c.registrar:
            raise gl.vm.UserError("only the registrar may close a commitment")
        if bool(c.closed):
            raise gl.vm.UserError("already closed")
        c.closed = True

    @gl.public.write
    def judge(self, revision_id: u256) -> None:
        """Compare a revision against the current text, dimension by dimension."""
        r = self._revision(revision_id)
        if bool(r.judged):
            raise gl.vm.UserError("already judged")

        c = self._commitment(r.commitment_id)
        if int(r.base_version) != int(c.version):
            # Two revisions cannot race each other into the same slot. The
            # second was written against a text that no longer exists, so
            # judging it would compare it to something its author never saw.
            raise gl.vm.UserError(
                "this revision was written against an older version of the commitment"
            )

        names = self._dimension_names(r.commitment_id)
        n = len(names)
        if n == 0:
            raise gl.vm.UserError("this commitment has no dimensions to judge on")

        # Everything the block needs, as plain strings. A block cannot read
        # storage at all, so nothing storage resident may cross this line.
        label = str(c.label)
        original = str(c.text)
        revised = str(r.text)
        numbered = "\n".join(f"[{k}] {name}" for k, name in enumerate(names))

        # ------------------------------------------------------------------
        # non-deterministic half. no storage write, no transfer, no message,
        # no nested block. two prompts, forward and reversed.
        # ------------------------------------------------------------------
        def leader_fn():
            fwd_raw = gl.nondet.exec_prompt(
                build_prompt(label, numbered, original, revised,
                             "THE PUBLISHED TEXT", "THE PROPOSED TEXT"),
                response_format="json",
            )
            rev_raw = gl.nondet.exec_prompt(
                build_prompt(label, numbered, revised, original,
                             "THE PROPOSED TEXT", "THE PUBLISHED TEXT"),
                response_format="json",
            )
            fwd = parse_vector(fwd_raw.get("tokens", ""), n)
            rev = parse_vector(rev_raw.get("tokens", ""), n)
            if fwd is None or rev is None:
                # Unusable shape from either pass. Not an error: every
                # dimension is unclear, which the contract will refuse.
                merged = [UNCLEAR] * n
            else:
                merged = reconcile(fwd, rev)
                if merged is None:
                    merged = [UNCLEAR] * n
            # Everything crossing this boundary is a plain string in a flat
            # dict. A nested mapping or a bool here fails inside the calldata
            # encoder, OUTSIDE the contract, producing an unknown result code
            # and no traceback at all.
            return {
                "vector": "|".join(merged),
                "because": sanitise_reason(fwd_raw.get("because", "")),
            }

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            theirs = leaders_res.calldata
            if not isinstance(theirs, dict):
                return False

            # Layer 1 costs nothing and runs first, so a malformed proposal is
            # rejected before this validator spends two prompts on it.
            their_vec = parse_stored(theirs.get("vector", ""), n)
            if not structurally_sound(their_vec, n):
                return False

            mine = parse_stored(leader_fn()["vector"], n)
            return ratchet_agrees(mine, their_vec, n)

        res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        # ------------------------------------------------------------------
        # deterministic half. the verdict is derived here, from the vector and
        # from storage the block never saw. The model answered multiple choice;
        # the contract decides what that means and whether the text moves.
        # ------------------------------------------------------------------
        vector = parse_stored(res.get("vector", ""), n)
        if not structurally_sound(vector, n):
            raise gl.vm.UserError("the answer does not cover the frozen dimensions")

        verdict = classify(vector)
        loose = loosened_dimensions(vector)

        r.judged = True
        r.verdict = verdict
        r.vector = "|".join(vector)
        r.loosened = "|".join(str(i) for i in loose)
        r.why = sanitise_reason(res.get("because", ""))

        if verdict == TIGHTENED:
            # The ratchet turns. This is the only path that moves the text.
            c.text = str(r.text)
            c.version = c.version + u256(1)
            r.applied = True
            c.n_tightened = c.n_tightened + u256(1)
        elif verdict == RESTATED:
            c.n_restated = c.n_restated + u256(1)
        elif verdict == BROADENED:
            c.n_broadened = c.n_broadened + u256(1)
        else:
            c.n_indeterminate = c.n_indeterminate + u256(1)

    # -- reads ------------------------------------------------------------

    @gl.public.view
    def count(self) -> u256:
        return u256(len(self.commitments))

    @gl.public.view
    def revision_count(self) -> u256:
        return u256(len(self.revisions))

    @gl.public.view
    def verdict(self, revision_id: u256) -> str:
        """One line read for another contract.

        Returns an empty string for an unjudged revision rather than raising,
        so a consuming contract has one branch to handle instead of two.
        """
        return str(self._revision(revision_id).verdict)

    @gl.public.view
    def loosened(self, revision_id: u256) -> str:
        """The dimension indices this revision weakened, pipe joined, or empty."""
        return str(self._revision(revision_id).loosened)

    @gl.public.view
    def text(self, commitment_id: u256) -> str:
        """The commitment as it currently stands, after every applied tightening."""
        return str(self._commitment(commitment_id).text)

    @gl.public.view
    def registrar(self, commitment_id: u256) -> str:
        """The address that owns this commitment.

        The identity of an author IS this address. `label` is a display string
        that anybody could have typed, so a consumer deciding whether a
        commitment belongs to somebody must compare this and not the label.
        """
        return str(self._commitment(commitment_id).registrar)

    @gl.public.view
    def may_propose(self, commitment_id: u256, who: str) -> bool:
        """Could this address propose a revision right now?

        Exposed so a consuming contract can check authority without replaying
        the delegation rules, and so the answer it gets is the same one
        propose() enforces.
        """
        if not looks_like_address(who):
            return False
        c = self._commitment(commitment_id)
        return self._may_propose(commitment_id, c, Address(str(who).strip()))

    @gl.public.view
    def delegation(self, commitment_id: u256) -> dict:
        """Every address ever authorised here, revoked ones included."""
        c = self._commitment(commitment_id)
        target = int(commitment_id)
        rows = []
        for i in range(len(self.delegates)):
            d = self.delegates[i]
            if int(d.commitment_id) != target:
                continue
            rows.append({"who": str(d.who), "active": bool(d.active)})
        return {"registrar": str(c.registrar), "delegates": rows}

    @gl.public.view
    def dimensions_of(self, commitment_id: u256) -> dict:
        """The frozen catalogue, numbered as the block sees it."""
        self._commitment(commitment_id)
        names = self._dimension_names(commitment_id)
        return {
            "dimensions": [{"index": i, "name": names[i]} for i in range(len(names))],
        }

    @gl.public.view
    def commitment(self, commitment_id: u256) -> dict:
        c = self._commitment(commitment_id)
        return {
            "label": str(c.label),
            "registrar": str(c.registrar),
            "text": str(c.text),
            "version": int(c.version),
            "dimensions": int(c.n_dimensions),
            "closed": bool(c.closed),
        }

    @gl.public.view
    def revision(self, revision_id: u256) -> dict:
        r = self._revision(revision_id)
        c = self._commitment(r.commitment_id)
        names = self._dimension_names(r.commitment_id)
        vec = parse_stored(str(r.vector), len(names)) or []
        return {
            "commitment": int(r.commitment_id),
            "label": str(c.label),
            "by": str(r.by),
            "text": str(r.text),
            "at": str(r.at),
            "base_version": int(r.base_version),
            "judged": bool(r.judged),
            "verdict": str(r.verdict),
            "applied": bool(r.applied),
            "loosened": str(r.loosened),
            "why": str(r.why),
            # the why string comes from the leader and is NOT part of
            # consensus. nothing in this contract acts on it.
            "reason_is_leader_supplied": True,
            "per_dimension": [
                {"index": i, "name": names[i], "token": vec[i]}
                for i in range(len(vec))
            ],
        }

    @gl.public.view
    def history(self, commitment_id: u256) -> dict:
        """Every revision ever proposed here, oldest first, applied or not."""
        c = self._commitment(commitment_id)
        target = int(commitment_id)
        rows = []
        for i in range(len(self.revisions)):
            r = self.revisions[i]
            if int(r.commitment_id) != target:
                continue
            rows.append({
                "id": i,
                "by": str(r.by),
                "verdict": str(r.verdict),
                "applied": bool(r.applied),
                "loosened": str(r.loosened),
            })
        return {
            "label": str(c.label),
            "registrar": str(c.registrar),
            "version": int(c.version),
            "revisions": rows,
        }

    @gl.public.view
    def ratchet(self, commitment_id: u256) -> dict:
        """How often this author tried to loosen what they had promised.

        A high refusal rate is a statement about the author, not about the
        network, and it is the number this contract exists to publish.
        """
        c = self._commitment(commitment_id)
        judged = (int(c.n_tightened) + int(c.n_restated)
                  + int(c.n_broadened) + int(c.n_indeterminate))
        return {
            "proposed": int(c.n_proposed),
            "judged": judged,
            "tightened": int(c.n_tightened),
            "restated": int(c.n_restated),
            "broadened": int(c.n_broadened),
            "indeterminate": int(c.n_indeterminate),
            "version": int(c.version),
            "loosening_pct": (int(c.n_broadened) * 100 // judged) if judged else 0,
        }
