# Ratchet — specification

One standalone GenLayer Intelligent Contract.
[`contracts/ratchet.py`](contracts/ratchet.py), deployed exactly as written, no
build step.

Runner pinned in the header:
`py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`

---

## Purpose

Decide whether a proposed revision to a published commitment **tightens**,
**restates**, or **loosens** it, dimension by dimension, against a catalogue
frozen when the commitment was opened. Only a tightening is applied.

The failure it catches is not a contradiction. It is a **dropped clause**: a
revision that reads as an improvement and quietly stops promising something. No
sentence says the commitment got weaker, and only the pair of texts carries the
loss.

## Consensus

`gl.vm.run_nondet_unsafe`. **Two prompts in one block**, forward and reversed.

The block receives the two texts and the numbered catalogue and returns, per
dimension, one of three tokens:

| Token | Meaning |
|---|---|
| `narrower` | binds the author to more: a stricter limit, fewer exceptions |
| `same` | no difference in what the author is bound to |
| `broader` | binds to less, **including by no longer addressing it at all** |

`unclear` is a fourth token that a prompt may never return. It is the contract's
word for "the leader contradicted itself", produced only by `reconcile()`.

### The mirror

The second pass asks the same question with the texts swapped. The answers must
invert:

| forward | must be reversed |
|---|---|
| `narrower` | `broader` |
| `broader` | `narrower` |
| `same` | `same` |

A dimension whose two passes do not mirror reconciles to `unclear`, and that is
**the value that gets stored**. The uncertainty is carried by the answer, never
by a tolerance in the agreement rule.

### The validator

1. **Structural honesty, free.** The vector must have exactly one entry per
   catalogue dimension and every entry must be a legal token. Runs before any
   prompt is spent.
2. **Exact equality on the whole vector.** No tolerance on any dimension.

`ratchet_agrees(a, b) == ratchet_agrees(b, a)`, by construction: both sides go
down the same parse and the comparison is an equality.

## The four verdicts

Derived deterministically from the reconciled vector, in this order:

| Verdict | Condition | Text moves |
|---|---|---|
| `indeterminate` | any dimension `unclear` | no |
| `broadened` | any dimension `broader` | no |
| `tightened` | at least one `narrower`, none loosened | **yes** |
| `restated` | every dimension `same` | no |

`unclear` outranks `broader` because a leader that could not answer the question
has not established that anything loosened either.

## State

Every collection is a **top level contract field**. No storage dataclass contains
a collection, because GenVM cannot construct one: `DynArray[T]()` is refused, and
`gl.storage.inmem_allocate` is for generic dataclasses rather than for
collections. Children carry a parent id.

| Field | Type | Note |
|---|---|---|
| `commitments` | `DynArray[Commitment]` | append only |
| `dimensions` | `DynArray[Dimension]` | flat, each carries `commitment_id` |
| `revisions` | `DynArray[Revision]` | flat, each carries `commitment_id` |
| `delegates` | `DynArray[Delegate]` | flat, each carries `commitment_id` |
| `Commitment.registrar` | `Address` | owns it. The identity, not the label |
| `Commitment.text` | `str` | moves only on a `tightened` verdict |
| `Commitment.version` | `u256` | bumped with the text, never separately |
| `Revision.by` | `Address` | the account that submitted this revision |
| `Revision.base_version` | `u256` | the version it was written against |
| `Revision.vector` | `str` | pipe joined reconciled tokens |
| `Revision.why` | `str` | leader supplied, sanitised, **not** consensus |
| `Delegate.active` | `bool` | cleared on revoke, the row is kept |

### The frozen catalogue

`open()` is the only method that may append to `dimensions`, and a static test
asserts it. A catalogue that could be edited later would let an author drop the
dimension they were about to weaken, and the next revision would come back
`restated` on a commitment that had just been gutted.

Capped at **12** dimensions per commitment, so one prompt stays bounded.
Duplicate names are refused: two identical names cannot be told apart in the
numbered list the block sees.

### The version guard

`judge()` refuses a revision whose `base_version` is not the commitment's current
version. Two proposals cannot race each other into the same slot, and judgment
becomes a **pure function of two frozen texts and a frozen catalogue** — there is
no state a caller can move between proposing and judging.

## Authority

A verdict about an author is worth exactly as much as the record it was computed
from. `open()` sets `registrar` to the caller and that address is the identity;
`label` is a display string and proves nothing.

| Call | Who | Why |
|---|---|---|
| `open` | anyone | no earlier owner to check against |
| `propose` | registrar or active delegate | a surviving revision replaces the published text |
| `authorise` / `revoke` | registrar | otherwise one delegation takes the commitment over |
| `close` | registrar | it is the author's commitment to stop revising |
| `judge` | anyone | an author who chose which revisions got examined would examine only the flattering ones |

A delegate may propose and may not retract, authorise, revoke, or close.
Delegates are capped at **16 active** per commitment, because `propose()` scans
them on every call.

## API

```python
open(label: str, text: str, dimensions: str)   # pipe joined dimension names
propose(commitment_id: u256, text: str)
authorise(commitment_id: u256, who: str)
revoke(commitment_id: u256, who: str)
close(commitment_id: u256)
judge(revision_id: u256)

verdict(revision_id)          -> str
loosened(revision_id)         -> str
text(commitment_id)           -> str
registrar(commitment_id)      -> str
may_propose(commitment_id, who: str) -> bool
delegation(commitment_id)     -> dict
dimensions_of(commitment_id)  -> dict
commitment(commitment_id)     -> dict
revision(revision_id)         -> dict
history(commitment_id)        -> dict
ratchet(commitment_id)        -> dict
count() / revision_count()    -> u256
```

Every view returns an empty string or an empty list rather than raising for a
state that has not been reached yet, so a consuming contract has one branch to
handle instead of two. Reads with an out-of-range **or negative** id raise a
`UserError`: Python list indexing accepts `-1` and returns the newest row, which
would hand a caller a different record with nothing failing anywhere.

## Reuse

[`lib/ratchet_consensus.py`](lib/ratchet_consensus.py) holds the pure rules with
no storage and no contract around them. It is **generated** by
`scripts/lift.py` from the contract, and `tests/test_logic.py` compares the two
parsed trees function by function, so a copied rule is always one a deployed
contract actually runs.

The idea worth lifting is `reconcile()`: ask in both directions inside the
leader's own block, and fold the leader's disagreement with itself into the
stored value before any node compares anything.
