# Deploying Ratchet

Everything you need is on this page. Deploy through the Studio web interface at
**studio.genlayer.com** — paste the contract, deploy, and call the methods
through the form. Never put a private key into a file or hand one to a tool.

---

## 1 · Get the contract

Open the raw file and copy all of it:

**https://raw.githubusercontent.com/meitipro/ratchet/main/contracts/ratchet.py**

Take it from that link, not from a local copy. What gets deployed has to be the
file in this repository, byte for byte — the reviewer reads the deployed source
back off the chain and diffs it, and a submission has been rejected for nothing
but a stale address with the fix already sitting in the repo.

Paste it into Studio and deploy. **The constructor takes no arguments.**

---

## 2 · Run the demo

Seven writes, in this order.

### Open a commitment against a frozen catalogue

| # | Method | Field | Value |
|---|---|---|---|
| 1 | `open` | `label` | `Acme Data Ltd` |
| | | `text` | `We retain personal data for at most 90 days, we never share it with third parties, and we notify affected users within 72 hours of a breach.` |
| | | `dimensions` | `data retention\|third party sharing\|breach notice` |

`dimensions` is **one string with pipe separators** — three dimensions. The
catalogue is frozen here and can never be edited, so an author cannot drop the
dimension they are about to weaken.

### A revision that tightens on every dimension

| # | Method | Field | Value |
|---|---|---|---|
| 2 | `propose` | `commitment_id` | `0` |
| | | `text` | `We retain personal data for at most 30 days, we never share it with any third party, and we notify affected users within 24 hours of a breach.` |
| 3 | `judge` | `revision_id` | `0` |

> ### ⛔ Stop here and read `revision(0)`
>
> Look at `verdict` and `per_dimension`.
>
> - **`tightened`** — the mirror worked. Carry on.
> - **`indeterminate`** — stop, and send me `per_dimension`. The model answered
>   the same question two different ways. The contract is right to refuse, but
>   the demo then shows nothing.
> - **`restated`** — stop, and tell me. 90 → 30 days should read as narrower.
>
> Then read `text(0)`: it must now be the 30-day version, and
> `commitment(0).version` must be `1`.

### A revision that quietly drops a clause

| # | Method | Field | Value |
|---|---|---|---|
| 4 | `propose` | `commitment_id` | `0` |
| | | `text` | `We retain personal data for at most 30 days and we notify affected users within 24 hours of any confirmed security breach.` |
| 5 | `judge` | `revision_id` | `1` |

Read it carefully: it contradicts nothing, it is shorter, and it never mentions
third party sharing again. Saying nothing is broader than making a promise, so
this comes back **`broadened`**, `loosened` names dimension `1`, and the
published text does **not** move. That refusal is the strongest single artifact
on the page.

### The provenance model, on chain

| # | Method | Field | Value |
|---|---|---|---|
| 6 | `authorise` | `commitment_id` | `0` |
| | | `who` | `0x7777777777777777777777777777777777777777` |
| 7 | `revoke` | `commitment_id` | `0` |
| | | `who` | `0x7777777777777777777777777777777777777777` |

---

## 3 · Reads — free, no transaction

| Call | Argument | Expect |
|---|---|---|
| `verdict` | `0` | `tightened` |
| `verdict` | `1` | `broadened` |
| `loosened` | `1` | `1` — third party sharing |
| `text` | `0` | the 30-day version from revision 0, unchanged by revision 1 |
| `ratchet` | `0` | `tightened 1, broadened 1` |
| `history` | `0` | both revisions, with `applied` true then false |
| `delegation` | `0` | the registrar, and one revoked delegate |

---

## 4 · Before the portal

```bash
python scripts/verify_deployment.py 0xYourAddress
```

Reads the source back out of the deploy transaction, diffs it against
`contracts/ratchet.py`, and runs `genvm-lint lint` on those bytes. It must print
**"The address is evidence for this repository. Safe to submit."**

If it prints anything else, do not submit that address.

---

## 5 · Send the address

Send it over and I will read the state back off the chain, confirm the outcomes
above, fill the `{address}` placeholders, write the on-chain section from what
the chain actually returned, and push.

**Nothing goes near the portal until that check is green.**
