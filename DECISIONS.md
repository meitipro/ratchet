# DECISIONS

What was chosen, what it cost, and what was found while building it. Written for
somebody deciding whether to copy the mechanism.

---

## The uncertainty goes into the value, not into the comparison

This is the whole design, and it was chosen because the opposite got a sibling
project rejected.

Two texts near a boundary genuinely can be read either way, and something has to
absorb that. There are two places to put it:

**In the agreement rule.** Keep a precise stored value and let the validator
forgive a difference: "one dimension may disagree, as long as one side said it
was uncertain". Consensus settles more often and the record reads decisive.

**In the value.** Make the leader resolve its own uncertainty first, store the
uncertainty as a token, and compare exactly.

The first one is a trap. A validator that votes agree while privately believing a
clause was dropped has not agreed, and the chain records a `tightened` that one of
the nodes did not accept. The record is *more* confident than the network was,
and nothing downstream can tell.

So `reconcile()` runs inside the leader's block, before any node compares
anything, and `unclear` is a stored token that appears in the vector, in the
verdict, and in the refusal.

## The block is asked twice, in both directions

The forward and reverse prompts come from **one template**, differing only in
which text is named first. A tested property, because an asymmetry in the wording
would look exactly like a model that cannot answer consistently: every dimension
would reconcile to `unclear` and every revision would be refused, and the cause
would be a sentence in a prompt.

`mirrors()` requires the direction to invert. `narrower` forward must be `broader`
reversed. A dimension answered `narrower` both ways round is not a close call — it
is a claim that cannot be true of any pair of texts.

## Saying nothing is broader

The rule is in the prompt, not only in the docs, and there is a test asserting
that. The failure this contract exists for is a **dropped clause**, and a model
that treated an unmentioned dimension as `same` would report `restated` on a
commitment that had just been gutted.

The mirror checks this too: if the revision no longer addresses a dimension, the
reverse pass should find the original `narrower` on it.

## The catalogue is frozen at open()

`open()` is the only method that may append a dimension, asserted by a static
test rather than by convention.

A catalogue that could be edited later would let an author drop the dimension
they were about to weaken. The verdict would then be computed against a yardstick
chosen after the fact, which is not a yardstick.

Capped at 12 per commitment. Duplicate names are refused because two identical
entries cannot be told apart in the numbered list the block sees, so a token
would be assigned to whichever the model happened to mean.

## A loosening is never paid for by a tightening

`classify()` checks `broader` before `narrower`, so a vector with both is
`broadened`. A ratchet that let an author trade a weakened clause for a
strengthened one somewhere else would not be a ratchet, and that trade is exactly
what a plausible revision looks like.

## The version guard

A revision records the commitment version it was written against, and `judge()`
refuses one whose base is stale.

Two proposals cannot race each other into the same slot, and the author is forced
to re-propose against the text that actually exists. The side effect is worth
more than the guard: judgment becomes a **pure function of two frozen texts and a
frozen catalogue**. There is no state a caller can move between proposing and
judging, which is why `judge()` can safely be open to anybody.

Only an APPLIED revision moves the version, so a refused proposal leaves its
siblings judgeable.

## judge() is open, and that is a decision

`ratchet()` publishes how often an author tried to loosen what they had promised.
If only the author could run the examination they would examine only the
flattering revisions and the number would mean nothing.

Judging adds no text. It can reach only the verdict the two stored texts and the
frozen catalogue already imply, and the version guard means the caller cannot
change what those are. The reasoning is written into the test, not just here, so
somebody tightening the contract later has to argue with a test rather than
delete a comment.

## Every write is bound to an address

`propose()` requires the registrar or an authorised delegate. A revision that
survives judgment **replaces the published text**, so an unauthenticated write
there would let a stranger rewrite somebody else's commitment through the front
door.

The delegation model is deliberate rather than minimal: a delegate may propose
and may not retract, authorise, revoke, or close. A delegate able to revoke could
remove every other delegate and become the only voice on a commitment it does not
own.

A static test asserts every `@gl.public.write` except `open` and `judge` reads
the sender. It covers the methods nobody has written yet: a new write added later
cannot be ungated by omission, only on purpose, in a diff.

## The reason string is leader-supplied

`why` is chosen by whichever node led, and is deliberately outside consensus: two
honest readers describe the same loosening differently, and comparing prose would
stall every judgment. It is sanitised on the way into storage and flagged in
`revision()`, but **nothing should build logic on it**.

## Why the tests are built the way they are

### The simulator gives each node its own world

`tests/glsim.py` hands the leader and the validator separate mock tables. Every
mocking framework feeds both nodes the same data by default, which is exactly why
a contract that quietly assumes both nodes see identical bytes passes its suite
and fails on a real network.

### The simulator can model a leader that lies

What reaches a validator is whatever the leader put on the wire, and that need
not be anything the leader's own code could produce: a patched node, a different
build, a deliberate lie. `set_leader_payload()` puts such a value on the wire.

Without it, **every shape check in `validator_fn` is unreachable in testing**,
and a defence that cannot be exercised looks identical to one that is not there.
Two mutations escaped before this existed, and both were real defences.

`glsim` also returns what consensus settled on rather than the leader's honest
internal state, because returning the latter would quietly repair a lie the
validators had already let through.

### The free layer is only worth having if it is free

Layer 1 rejects a malformed proposal before the validator spends two prompts on
it. Remove it and the contract still refuses, because the agreement rule checks
the shape too — so the only observable difference is the cost, and the cost is
the entire reason layer 1 exists.

`validator_prompt_calls()` makes that measurable, and there is a test asserting
zero prompts for a malformed proposal and two for a well-formed one the validator
disagrees with.

### The lifted module is generated

`lib/ratchet_consensus.py` claims to be the agreement rules as the contract runs
them. Maintaining that by hand makes it false the first time somebody edits one
side, and a copied rule that no deployed contract uses is worse than no copy: it
is a rule with a provenance it has not earned.

So `scripts/lift.py` generates it and `TestLibParity` compares the two parsed
trees function by function. It has already caught one real drift, within an hour
of being written.

### Mutation testing, because passing tests prove nothing

`scripts/mutate.py` breaks each defence on purpose and records which test noticed.
The table in the README is generated from the run, so a number there is one that
was measured.

Four mutations escaped on the first pass. Every one was a finding:

- **Two were defences the simulator could not reach at all** — the validator's
  shape checks. Fixed by teaching glsim to model a dishonest leader, which is a
  capability gap rather than a missing test.
- **The dimension cap looked covered and was not.** The test used thirteen
  identical names, so the *duplicate* rule refused them first and the cap was
  never exercised. Fixed with thirteen distinct names.
- **The catalogue filter had no test**, because every other test used one
  commitment. Two commitments now have different dimensions and the second is
  judged on its own.

### One mutation is deliberately not in the table

Dropping the post-consensus shape check changes no outcome any single mutation
can reach: `leader_fn` has already normalised an unusable answer to a full length
vector of `UNCLEAR`, layer 1 has rejected a malformed proposal off the wire, and
layer 2 re-checks both sides. No test can catch it, and claiming one would be a
lie. It stays in the contract as the backstop for both validator layers being
wrong at once, and it is documented here rather than dropped.

A test that cannot fail is worse than no test, because it reports coverage it
does not provide.

## GenVM constraints this contract obeys

Each of these cost a failed deployment or a failed transaction in a previous
project in this line. None produce a helpful error. One produces no error at all.

- **No collection inside a storage dataclass.** `DynArray[T]()` fails with
  `this class can't be instantiated by user`, and
  `gl.storage.inmem_allocate(DynArray[T])` does not rescue it. Everything here is
  flat; children carry a parent id.
- **No `int`, `list`, `dict` or `tuple` as a storage field type.** Rejected at
  deploy.
- **Every persistent field declared in the class body.** `self.x = value` on an
  undeclared field is silently discarded when execution ends.
- **The block boundary carries a flat dict of strings.** A nested mapping or a
  bool fails inside the calldata encoder, which is OUTSIDE the contract, so it
  produces `Result Code: <unknown>` with no stderr and no traceback.
- **Never compare a storage object by identity.** `DynArray.__getitem__` builds a
  fresh view on every access, so `self.rows[i] is obj` is always False on a node
  and fails silently. Everything here carries indices.
- **`gl.nondet.*` only inside a closure the consensus flow recognises.** Outside
  one, `genvm-lint lint` reports *not reachable from equivalence principle
  block*. A GenLayer submission has been rejected for having this in its
  **deployed** source while the repository version was clean, so there is a
  static test for it here and `scripts/verify_deployment.py` lints the bytes that
  came off the chain.

## Not upgradable

No admin method, no pause, no owner beyond the per-commitment registrar.
Deliberate for a primitive whose value is that its rules cannot move after
somebody depends on them, and it means a bug found later requires a new
deployment.
