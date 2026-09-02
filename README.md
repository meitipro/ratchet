# Ratchet — a published commitment that can only ever be tightened

A reusable GenLayer primitive that decides whether a revision to a public
commitment **tightens** it, **restates** it, or **quietly loosens** it — dimension
by dimension, against a catalogue frozen when the commitment was opened. Only a
tightening is applied.

- **Contract:** [`contracts/ratchet.py`](contracts/ratchet.py)
- **Tests:** `pip install pytest && pytest tests/ -q` — nothing else to install
- **Deployed:** `{address}` on studionet ([explorer](https://explorer-studio.genlayer.com/address/{address}))
- **Deploying it yourself:** [DEPLOY.md](DEPLOY.md) — the contract, the demo, and the check to run before submitting
- **Verify a deployment:** `python scripts/verify_deployment.py 0x…` — diffs the
  on-chain source against this file
- **Specification:** [CONTRACTS.md](CONTRACTS.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **License:** MIT. Copy the agreement rule; that is what it is for.

---

## The problem

An organisation publishes:

> We retain personal data for at most 90 days, we never share it with third
> parties, and we notify affected users within 72 hours of a breach.

A year later it publishes a revision. The revision is longer, better written,
and adds a paragraph about encryption at rest. It also no longer mentions third
parties.

**Nothing was contradicted.** A clause was dropped, and dropping a clause is how
a commitment gets weaker without any sentence ever saying so. Read the revision
alone and it is an improvement. Only the pair carries the loss.

The two texts are prose, and prose is where consensus normally gives up. Ask
five nodes whether a document "is weaker" and you get five different sentences,
none of which can be compared to any other.

## How consensus is used

Ratchet never asks that question. The catalogue of dimensions is fixed when the
commitment is opened and belongs to the contract. The block sees the two texts
and the numbered catalogue, and answers **one of three tokens per dimension**.

> The judgment is hard. Read two policies, work out what each one actually binds
> its author to, and tell a real commitment from its paraphrase.
>
> **The thing that crosses consensus is a vector of three-valued tokens over a
> list the contract already holds.**

### The leader resolves its own uncertainty first

The block runs the comparison **twice** — once forward, once with the two texts
swapped — and the answers must mirror. If the revision is narrower on a
dimension, the original must be broader on that same dimension.

```python
def reconcile(forward, reverse):
    out = []
    for i in range(len(forward)):
        if mirrors(forward[i], reverse[i]):
            out.append(forward[i])
        else:
            out.append(UNCLEAR)     # <- the stored value, not a forgiven diff
    return out
```

A dimension whose two passes do not mirror becomes `unclear`, **and `unclear` is
what gets stored**. That ordering is the whole design. The alternative — keep a
precise stored value and let the agreement rule forgive a difference — produces a
record that reads decisive while the nodes privately disagreed.

**Uncertainty belongs in the value, never in the comparison.**

### The validator, in two layers

```python
# LAYER 1 -- structural honesty. Costs nothing, runs before any prompt.
#   The vector must have exactly one entry per catalogue dimension and every
#   entry must be a legal token. Checked against data the validator already
#   holds. A malformed proposal dies before any inference is spent on it.

# LAYER 2 -- exact equality on the whole vector.
#   Not "we both found a loosening somewhere". The same dimensions, the same
#   tokens, all of them. Two nodes that disagree about which clause got weaker
#   have not agreed about anything worth applying.
```

There is deliberately **no tolerance** anywhere in layer 2.

## Four outcomes, and they are different facts

| Verdict | Meaning | Applied |
|---|---|---|
| `tightened` | binds to more somewhere, to less nowhere | yes |
| `restated` | identical in effect, however differently worded | no |
| `broadened` | binds to less somewhere, including by dropping a clause | no |
| `indeterminate` | the leader could not answer the same question twice | no |

A loosening is **never** paid for by a tightening elsewhere. A ratchet that let
an author trade a weakened clause for a strengthened one would not be a ratchet.

## Why this is not a thin LLM wrapper

The model never decides an outcome. **It answers three-way multiple choice
against a list the contract owns, twice.** Everything else is deterministic: the
mirror rule, the reconciliation, the verdict derived from the vector, whether the
revision is applied, and whether it was even eligible to be judged.

Swap in a worse model and the mechanism still works. It produces more `unclear`,
which refuses more revisions, which is the correct response to a worse model.

## The ratchet only turns one way

A revision judged `tightened` **replaces** the commitment text and bumps its
version. Anything else is recorded against the revision and the text does not
move.

A revision written against an older version is refused rather than judged, so
two proposals cannot race each other into the same slot. That also makes
judgment a **pure function of two frozen texts and a frozen catalogue** — there
is no state a caller can move between proposing and judging.

## Who may write to a commitment

A verdict about an author is worth exactly as much as the record it was computed
from, so **the commitment has to be the author's own**. Every write is bound to
an address, and the registrar is the identity: `label` is a display string that
anybody could have typed.

| Call | Who |
|---|---|
| `open` | anyone. The caller becomes the registrar of the new commitment |
| `propose` | the registrar, or an address the registrar has authorised |
| `authorise` / `revoke` | the registrar alone |
| `close` | the registrar alone |
| `judge` | anyone, deliberately |

`propose()` is the load-bearing one: a revision that survives judgment replaces
the published text, so an unauthenticated write there lets a stranger rewrite
somebody else's commitment through the front door.

**A delegate may speak on a commitment but not own it.** It cannot authorise,
revoke, or close. Every revision stores the address that submitted it, readable
through `revision()` and `history()`.

`judge()` is open on purpose. The ratchet is a public promise, and an author who
could decide which of their own revisions got examined would only ever examine
the flattering ones.

## The API

```python
open(label, text, dimensions)      # anyone. caller becomes registrar
propose(commitment_id, text)       # registrar or authorised delegate
authorise(commitment_id, who)      # registrar only
revoke(commitment_id, who)         # registrar only
close(commitment_id)               # registrar only. freezes the text, not the verdicts
judge(revision_id)                 # anyone, deliberately

verdict(revision_id)     -> str    # tightened | restated | broadened | indeterminate | ""
loosened(revision_id)    -> str    # dimension indices it weakened, pipe joined
text(commitment_id)      -> str    # the commitment as it currently stands
revision(revision_id)    -> dict   # the verdict, the per-dimension tokens, the reason
commitment(id)           -> dict   # label, registrar, text, version, closed
history(commitment_id)   -> dict   # every revision, applied or not
ratchet(commitment_id)   -> dict   # how often this author tried to loosen
dimensions_of(id)        -> dict   # the frozen catalogue, numbered
registrar(id)            -> str    # the address that owns it
may_propose(id, who)     -> bool   # could that address write to it right now
delegation(id)           -> dict   # every address authorised, revoked ones too
```

## Using it from another contract

```python
@gl.contract_interface
class Ratchet:
    class View:
        def verdict(self, revision_id: int) -> str: ...
        def registrar(self, commitment_id: int) -> str: ...

r = Ratchet(RATCHET_ADDR).view()

# bind to the address, never to the label
if r.registrar(cid) != expected_owner:
    raise ...

# act only on a revision that was actually a tightening
if r.verdict(rid) == "tightened":
    self._proceed()
```

`verdict()` returns an empty string for an unjudged revision rather than raising,
so the caller has one branch to handle instead of two.

---

## Running the tests

```bash
pip install pytest
pytest tests/ -q
```

Nothing else is needed. `tests/glsim.py` is a small GenVM stand-in, so the unit
and end-to-end suites run with no Studio and no network. The integration suite
skips cleanly unless `genlayer-test` is installed.

<!-- measured:tests -->
`pytest tests/ -q` reports **171 passed, 1 skipped**, and every one of the **56** mutations below is caught.
<!-- /measured:tests -->

### The tests have teeth

A passing count is a claim. The table below is evidence: every row is a real edit
to the contract that removes a defence, and the test named beside it is the one
that failed. It is generated by `scripts/mutate.py`, which refuses to emit a
table if anything escapes.

<!-- measured:mutations -->
| Mutation | Caught by |
|---|---|
| the mirror accepts a direction that does not invert | `test_a_leader_that_fails_its_own_mirror_stores_unclear` |
| same is allowed to mirror anything | `test_direction_must_invert` |
| reconcile keeps the forward answer instead of marking it unclear | `test_a_leader_that_fails_its_own_mirror_stores_unclear` |
| the second pass never runs, so nothing is mirrored | `test_a_leader_that_fails_its_own_mirror_stores_unclear` |
| an unusable pass is read as agreement rather than as unclear | `test_an_unusable_pass_makes_every_dimension_unclear` |
| unclear no longer blocks a verdict | `test_a_leader_that_fails_its_own_mirror_stores_unclear` |
| a loosening can be paid for by a tightening | `test_a_dropped_clause_is_a_loosening_and_is_refused` |
| an empty vector is read as a restatement | `test_the_four_outcomes` |
| the loosened indices are not sorted | `test_every_lifted_function_is_identical_to_the_contract` |
| agreement loosened to "we both found something" | `test_nodes_naming_different_dimensions_do_not_agree` |
| one dimension forgiven, the Winnow defect | `test_one_differing_dimension_is_enough_to_refuse` |
| the free structural layer removed | `test_the_free_layer_is_actually_free` |
| a wrong length vector accepted | `test_the_free_layer_rejects_before_a_prompt_is_spent` |
| an illegal token accepted in a stored vector | `test_every_lifted_function_is_identical_to_the_contract` |
| unclear accepted straight from a prompt | `test_only_the_three_prompt_tokens_survive` |
| a partly unusable prompt answer read as same | `test_a_garbage_token_is_not_read_as_same` |
| the published text moves on any verdict | `test_a_restatement_is_accepted_and_moves_nothing` |
| the version does not move when the text does | `IndentationError at import` |
| a revision written against an older text is judged anyway | `test_nothing_is_written_when_a_judgment_fails` |
| re-judging allowed, so a verdict can be overwritten | `test_judging_twice_is_refused` |
| duplicate dimension names allowed | `test_two_dimensions_with_the_same_name_are_refused` |
| the dimension cap removed, so an unbounded prompt is built | `test_more_than_twelve_dimensions_is_refused` |
| a commitment allowed with no dimensions at all | `test_bad_dimension_lists_are_refused` |
| the catalogue filter dropped, so every commitment shares one | `test_each_commitment_is_judged_on_its_own_catalogue` |
| a refused revision consumes the base, so the author cannot try again | `test_a_restatement_is_accepted_and_moves_nothing` |
| a closed commitment's text still moves on a late tightening | `test_a_tightening_judged_after_closing_is_recorded_but_never_applied` |
| a refusal marks the commitment closed | `test_a_tightening_is_applied_and_bumps_the_version` |
| propose left unauthenticated, so anyone may rewrite any commitment | `test_a_stranger_cannot_propose_on_someone_elses_commitment` |
| the submitting address not recorded on the revision | `test_a_delegate_may_propose_and_the_record_names_them` |
| a revoked delegate still counted as authorised | `test_a_revoked_delegate_cannot_propose` |
| delegation not scoped to the commitment it was granted on | `test_delegation_is_scoped_to_one_commitment` |
| a delegate allowed to appoint further delegates | `test_a_delegate_may_not_authorise_revoke_or_close` |
| a delegate allowed to revoke | `test_a_delegate_may_not_authorise_revoke_or_close` |
| a delegate allowed to close the commitment | `test_a_delegate_may_not_authorise_revoke_or_close` |
| may_propose() drifting from the rule propose() enforces | `test_may_propose_answers_what_propose_enforces` |
| the cap not re-checked when a revoked delegate is reactivated | `test_the_cap_survives_a_revoke_and_reauthorise_cycle` |
| the cap counted in the same pass that finds the row | `test_the_cap_survives_a_revoke_and_reauthorise_cycle` |
| a malformed delegate address passed to Address() | `test_a_malformed_delegate_address_is_refused_cleanly` |
| a closed commitment still accepts revisions | `test_a_closed_commitment_takes_no_more_revisions` |
| the commitment bounds check removed | `test_a_read_with_a_nonexistent_id_is_a_user_error` |
| negative ids allowed through to Python list indexing | `test_a_read_with_a_negative_id_does_not_return_the_last_row` |
| the reason sanitiser disabled | `test_the_reason_is_sanitised_on_the_way_in` |
| control characters left in reasons | `test_control_characters_become_spaces` |
| the prompt fence removed, so a caller can forge a block | `test_the_author_label_is_fenced_too` |
| the fence deletes instead of replacing | `test_fence_replaces_rather_than_deletes` |
| only the opening bracket fenced | `test_fence_replaces_rather_than_deletes` |
| the revision text reaches the model unfenced | `test_every_lifted_function_is_identical_to_the_contract` |
| the dimension catalogue reaches the model unfenced | `test_every_lifted_function_is_identical_to_the_contract` |
| a caller string routed through the unfenced role argument | `test_a_tightening_is_applied_and_bumps_the_version` |
| the author label reaches the model unfenced | `test_every_lifted_function_is_identical_to_the_contract` |
| a nested mapping returned from the block | `test_a_tightening_is_applied_and_bumps_the_version` |
| a bool returned from the block | `test_a_tightening_is_applied_and_bumps_the_version` |
| a collection nested back into a storage dataclass | `TypeError at import` |
| an int storage field | `TypeError at import` |
| a storage field declared twice | `test_no_storage_field_is_declared_twice` |
| a prompt moved outside the block, which genvm-lint refuses | `test_a_tightening_is_applied_and_bumps_the_version` |
<!-- /measured:mutations -->

The simulator can also model **a leader that lies**: `set_leader_payload()` puts
a value on the wire that `leader_fn` would never return, which is the only way to
exercise the checks a validator runs against a peer it does not trust. Without
it, every one of those checks is unreachable in testing and a defence that cannot
be exercised looks identical to one that is not there.

## Design rules

- **The block returns tokens, never an outcome.** Three legal words per
  dimension, over a catalogue the contract froze.
- **Uncertainty enters the stored value.** `unclear` is visible in the vector, in
  the verdict, and in the refusal. It is never a forgiven difference.
- **Exact equality between nodes.** No tolerance, on any dimension.
- **Every write is bound to an address**, and a static test asserts it for the
  methods nobody has written yet.
- **Untrusted text is fenced at the prompt boundary.** Tagging it and telling the
  model it is data is not a fence on its own: `fence()` neutralises the
  characters that can close a tag, so a caller cannot forge a block. Replace,
  never delete, and at the boundary only — storage keeps what was written.
- **Refusing is designed.** `broadened` and `indeterminate` are the outputs this
  contract exists to produce.
- **No web access.** Every input is text the caller supplies, which removes an
  entire class of deployment failure.

## Further reading in this repository

- [CONTRACTS.md](CONTRACTS.md) — the full specification: purpose, consensus,
  state model, API, reuse
- [DECISIONS.md](DECISIONS.md) — engineering decisions and what they cost
- [lib/ratchet_consensus.py](lib/ratchet_consensus.py) — the agreement rules on
  their own, to be copied. Generated by `scripts/lift.py` and checked for drift
  by the suite

## Related work

Separate primitives, built to the same standard and submitted independently:
[Keystone](https://github.com/meitipro/keystone) — an ordering built one pair at
a time that cannot contradict itself.
[Recant](https://github.com/meitipro/recant) — self-consistency across a record
of statements.

They share an author and a discipline, not a codebase. Each deploys, tests and is
used entirely on its own.

---

Published by [InferNode](https://x.com/Infer_node).
