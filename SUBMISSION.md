# Submission

One submission, under **Builder → Intelligent Contracts**. This repository is one
standalone primitive.

---

## Before you submit, in order

1. **Measure, do not estimate.**

   ```bash
   python scripts/measure.py --write
   ```

   Runs the suite, runs the full mutation pass, and writes both numbers into
   README.md. It refuses to write anything if the suite is red or a mutation
   escapes, so a number in the README is always one that was checked.

2. **Deploy and exercise.** Through the Studio web interface at
   studio.genlayer.com, or `./scripts/deploy.sh studionet` for the CLI route.
   Never put a private key into a file.

3. **Put a refusal on chain, not only a success.** The story the script tells is
   the submission: a revision that tightens two dimensions is applied and moves
   the published text, then a revision that reads better and stops mentioning
   third-party sharing comes back `broadened` and does not. A page showing only
   successes proves the file compiles and nothing else.

4. **Prove the address is evidence for this repository.**

   ```bash
   python scripts/verify_deployment.py 0xYourAddress
   ```

   Reads the source back out of the deploy transaction on chain, diffs it against
   `contracts/ratchet.py`, and runs `genvm-lint lint` on those bytes. **A
   submission is judged on the deployed source**, so a correct repository proves
   nothing on its own if the address points at an earlier draft. Exits non-zero
   if either check fails.

5. **Open the explorer page and check it.** It must show a Deploy transaction
   **and** method calls with a Consensus Result beside them, and no failed or
   abandoned transaction.

6. **Paste the address** into README.md and into this file, then push.

7. **Upload `brand/social.png`** under Settings → General → Social preview, if
   the repository has one. GitHub has no API for this.

---

## On chain

Deployed and exercised on studionet at
[`0x69c326973af9E735B2c2Ed96689D42736eB2C33f`](https://explorer-studio.genlayer.com/address/0x69c326973af9E735B2c2Ed96689D42736eB2C33f).
Twelve transactions, every one `FINALIZED`, no failed or abandoned transaction
on the page. Every value below was read back from the chain with view calls
afterwards, not copied from a local run.

| # | Transaction | Result |
|---|---|---|
| 1 | deploy | finalized |
| 2 | `open("Acme Data Ltd", …, "data retention\|third party sharing\|breach notice")` | catalogue frozen at three dimensions |
| 3-4 | `propose` + `judge(0)` | **`tightened`**, applied. `text` moves, `version` -> 1 |
| 5-6 | `propose` + `judge(1)` | `indeterminate`, `loosened: 1` |
| 7-8 | `authorise` + `revoke` | delegate added, then deactivated with the row kept |
| 9-10 | `propose` + `judge(2)` | `indeterminate` again, the identical vector |
| 11-12 | `propose` + `judge(3)` | **`broadened`**, `loosened: 1` |

### The four verdicts, and why

| Revision | Vector | Verdict |
|---|---|---|
| 0 | `narrower \| same \| narrower` | `tightened`, **applied** |
| 1 | `same \| broader \| unclear` | `indeterminate` |
| 2 | `same \| broader \| unclear` | `indeterminate` |
| 3 | `same \| broader \| same` | `broadened` |

Revision 0 is the only path that moves the published text.

Revision 3 is the failure this contract exists for: a revision that contradicts
nothing, is shorter, and silently stops mentioning third party sharing. The
model marked that dimension `broader` and the contract refused to apply it.

Revisions 1 and 2 drop the same promise, but that draft also changed "of a
breach" to "of any confirmed security breach". That narrows what counts as a
breach, so the dimension reads one way forward and another in reverse, the
leader could not mirror it, and `unclear` blocked a confident verdict. **Judged
twice in two separate consensus rounds it returned the identical vector**, so
the refusal is a property of the text rather than noise.

Revisions 2 and 3 drop exactly the same clause and land on different verdicts.
The difference is one edit elsewhere in the sentence, and the contract is right
about both.

`ratchet(0)`:

```json
{"proposed": 4, "judged": 4, "tightened": 1, "broadened": 1,
 "restated": 0, "indeterminate": 2, "loosening_pct": 25, "version": 1}
```

`delegation(0)`:

```json
{"registrar": "0x3e1D268c8B1Ba7d042968ab713467C5631831513",
 "delegates": [{"who": "0x7777777777777777777777777777777777777777", "active": false}]}
```

A revoked delegate keeps its row, so a delegation that existed stays visible.
Every revision also carries the address that proposed it.

### Reproducing the check

```bash
python scripts/verify_deployment.py 0x69c326973af9E735B2c2Ed96689D42736eB2C33f
```

Reads the source out of the deploy transaction, compares it to
`contracts/ratchet.py`, and runs `genvm-lint lint` on those bytes. It reports
the deployed source as identical: pasting into the Studio editor rewrote the
line endings and dropped the final newline, and nothing runs either of those.

---

## Title

```
Ratchet: a published commitment that can only ever be tightened
```

## Notes

```
Ratchet decides whether a revision to a published commitment tightens it, restates it, or quietly loosens it, dimension by dimension against a catalogue frozen when the commitment was opened, and only a tightening is applied. The failure it catches is a dropped clause: a revision that reads as an improvement and simply stops promising something, where nothing is contradicted and only the pair of texts carries the loss. The block answers one of three tokens per dimension over a list the contract already holds, and it answers twice, once with the texts swapped, so a dimension whose two passes do not mirror is stored as unclear rather than forgiven at comparison time. Validators then compare the whole vector for exact equality, with no tolerance anywhere. A commitment belongs to the address that opened it, only that address or a delegate it authorised may propose, and every revision stores the account that submitted it.
```

## Links

```
GitHub:   https://github.com/meitipro/ratchet
Contract: https://github.com/meitipro/ratchet/blob/main/contracts/ratchet.py
Spec:     https://github.com/meitipro/ratchet/blob/main/CONTRACTS.md
Decisions https://github.com/meitipro/ratchet/blob/main/DECISIONS.md
Tests:    https://github.com/meitipro/ratchet/tree/main/tests
Explorer: https://explorer-studio.genlayer.com/address/0x69c326973af9E735B2c2Ed96689D42736eB2C33f
```

---

## What clears the bar, line by line

The category rejects "thin LLM wrappers" and "generic AI decides X demos".

- **The model never decides.** It answers three-way multiple choice against a
  catalogue the contract froze, twice. Which dimensions exist, whether the two
  passes mirror, what the vector means, whether the revision is applied, and
  whether it was even eligible to be judged are all deterministic.
- **Uncertainty is in the value, not the comparison.** `unclear` is a stored
  token, visible in the vector, the verdict and the refusal. There is no
  tolerance anywhere in the agreement rule, on any dimension.
- **The validator function is the contribution.** A free structural check before
  any prompt, then exact equality on the whole vector. Explained in
  [CONTRACTS.md](CONTRACTS.md) with the code.
- **Refusing is designed.** `broadened` and `indeterminate` are the outputs this
  primitive exists to produce, and both are better than a confident wrong apply.
- **Every write is bound to an address.** A static test asserts it for the
  methods nobody has written yet.
- **The tests have teeth.** The mutation table in the README is generated by a
  script that refuses to emit a table if anything escapes, and the simulator can
  model a leader that lies, which is the only way to exercise the checks a
  validator runs against a peer it does not trust.
- **It runs with nothing installed.** `pip install pytest && pytest tests/ -q`.
  A reviewer with two minutes can verify the whole thing.

## The one line worth putting first

**The judgment is hard and the thing crossing consensus is a vector of
three-valued tokens over a list the contract already holds.** Everything else in
the design follows from it.
