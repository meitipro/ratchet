"""Mutation pass: break every safety property on purpose, confirm a test notices.

Passing tests prove nothing on their own. Each entry below is a small edit to
the contract that removes a defence. The suite must fail for every one of them,
and this script records WHICH test caught it, so the table in the README is
measured rather than claimed.

    python scripts/mutate.py            # run them all, print what caught what
    python scripts/mutate.py --md       # emit the markdown table for the README

An escaping mutation is a finding, not a nuisance. It means either a missing
test, or a later defence strict enough to cover a case an earlier test was
supposed to catch -- which leaves that earlier test unable to fail. A test that
cannot fail is worse than no test, because it reports coverage it does not
provide.

Run it with the same interpreter the suite uses. A global genlayer-test install
hijacks plain pytest collection and turns every result here into an unnamed
failure, which looks like success at a glance because everything is "caught".
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = "ratchet.py"

MUTATIONS = [
    # -- the mirror. The leader resolving its own uncertainty is the whole
    # -- design, and every way of skipping it produces a record that reads
    # -- decisive where the leader was not.
    (
        "the mirror accepts a direction that does not invert",
        "    if forward == NARROWER:\n        return reverse == BROADER",
        "    if forward == NARROWER:\n        return True",
    ),
    (
        "same is allowed to mirror anything",
        "    if forward == SAME:\n        return reverse == SAME\n    return False",
        "    if forward == SAME:\n        return True\n    return False",
    ),
    (
        "reconcile keeps the forward answer instead of marking it unclear",
        "        if mirrors(forward[i], reverse[i]):\n"
        "            out.append(forward[i])\n"
        "        else:\n"
        "            out.append(UNCLEAR)",
        "        out.append(forward[i])",
    ),
    (
        "the second pass never runs, so nothing is mirrored",
        "            rev = parse_vector(rev_raw.get(\"tokens\", \"\"), n)",
        "            rev = None if fwd is None else [{NARROWER: BROADER, "
        "BROADER: NARROWER, SAME: SAME}[t] for t in fwd]",
    ),
    (
        "an unusable pass is read as agreement rather than as unclear",
        "                merged = [UNCLEAR] * n\n            else:",
        "                merged = [SAME] * n\n            else:",
    ),

    # -- the verdict derived from the vector
    (
        "unclear no longer blocks a verdict",
        "    if UNCLEAR in vector:\n        return INDETERMINATE\n",
        "",
    ),
    (
        "a loosening can be paid for by a tightening",
        "    if BROADER in vector:\n        return BROADENED\n"
        "    if NARROWER in vector:\n        return TIGHTENED",
        "    if NARROWER in vector:\n        return TIGHTENED\n"
        "    if BROADER in vector:\n        return BROADENED",
    ),
    (
        "an empty vector is read as a restatement",
        "    if len(vector) == 0:\n        return INDETERMINATE",
        "    if len(vector) == 0:\n        return RESTATED",
    ),
    (
        "the loosened indices are not sorted",
        "    return sorted(out)",
        "    return out",
    ),

    # -- agreement between nodes
    (
        "agreement loosened to \"we both found something\"",
        "    return a == b",
        "    return (BROADER in a) == (BROADER in b)",
    ),
    (
        "one dimension forgiven, the Winnow defect",
        "    return a == b",
        "    return sum(1 for i in range(n) if a[i] != b[i]) <= 1",
    ),
    (
        "the free structural layer removed",
        "            if not structurally_sound(their_vec, n):\n                return False\n",
        "",
    ),
    (
        "a wrong length vector accepted",
        "    if len(vector) != n or n == 0:\n        return False",
        "    if False:\n        return False",
    ),
    (
        "an illegal token accepted in a stored vector",
        "        if s not in TOKENS:\n            return None",
        "        if False:\n            return None",
    ),
    (
        "unclear accepted straight from a prompt",
        "    if s in MODEL_TOKENS:\n        return s",
        "    if s in TOKENS:\n        return s",
    ),
    (
        "a partly unusable prompt answer read as same",
        "        t = normalise_token(p)\n        if t == \"\":\n            return None",
        "        t = normalise_token(p)\n        if t == \"\":\n            t = SAME",
    ),

    # -- the ratchet itself
    (
        "the published text moves on any verdict",
        "        if verdict == TIGHTENED:",
        "        if verdict != INDETERMINATE:",
    ),
    (
        "the version does not move when the text does",
        "            c.version = c.version + u256(1)\n",
        "",
    ),
    (
        "a revision written against an older text is judged anyway",
        "        if int(r.base_version) != int(c.version):",
        "        if False:",
    ),
    (
        "re-judging allowed, so a verdict can be overwritten",
        "        if bool(r.judged):\n            raise gl.vm.UserError(\"already judged\")\n",
        "",
    ),
    # NOT listed: "the post-consensus shape check dropped". By the time the
    # deterministic half runs, leader_fn has already normalised any unusable
    # answer to a full length vector of UNCLEAR, the validator's layer 1 has
    # rejected a malformed proposal that arrived over the wire, and layer 2 has
    # re-checked the shape of both sides. Removing it changes no outcome any
    # single mutation can reach, so no test can catch it and claiming one would
    # be a lie. It stays in the contract as the backstop for the case where
    # both validator layers are wrong at once. See DECISIONS.md.

    # -- the frozen catalogue
    (
        "duplicate dimension names allowed",
        "        if len(set(names)) != len(names):\n"
        "            raise gl.vm.UserError(\"two dimensions with the same name cannot be told apart\")\n",
        "",
    ),
    (
        "the dimension cap removed, so an unbounded prompt is built",
        "        if len(names) > MAX_DIMENSIONS:",
        "        if False:",
    ),
    (
        "a commitment allowed with no dimensions at all",
        "        if len(names) == 0:\n"
        "            raise gl.vm.UserError(\"a commitment needs at least one dimension to be judged on\")\n",
        "",
    ),
    (
        "the catalogue filter dropped, so every commitment shares one",
        "            if int(d.commitment_id) == target:\n                out.append(str(d.name))",
        "            if True:\n                out.append(str(d.name))",
    ),

    # -- authority
    # -- recourse. A refusal has to leave the refused party somewhere to go.
    (
        "a refused revision consumes the base, so the author cannot try again",
        "        if verdict == TIGHTENED:",
        "        if True:",
    ),
    (
        "a closed commitment's text still moves on a late tightening",
        "            if not bool(c.closed):\n                c.text = str(r.text)",
        "            if True:\n                c.text = str(r.text)",
    ),
    (
        "a refusal marks the commitment closed",
        "        r.judged = True",
        "        r.judged = True\n        c.closed = True",
    ),
    (
        "propose left unauthenticated, so anyone may rewrite any commitment",
        "        if not self._may_propose(commitment_id, c, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\n"
        "                \"only the registrar or an authorised delegate may propose a revision\"\n"
        "            )\n",
        "",
    ),
    (
        "the submitting address not recorded on the revision",
        "                by=gl.message.sender_address,",
        "                by=c.registrar,",
    ),
    (
        "a revoked delegate still counted as authorised",
        "            if int(d.commitment_id) == target and d.who == who and bool(d.active):",
        "            if int(d.commitment_id) == target and d.who == who:",
    ),
    (
        "delegation not scoped to the commitment it was granted on",
        "            if int(d.commitment_id) == target and d.who == who and bool(d.active):",
        "            if d.who == who and bool(d.active):",
    ),
    (
        "a delegate allowed to appoint further delegates",
        "        if gl.message.sender_address != c.registrar:\n"
        "            raise gl.vm.UserError(\"only the registrar may authorise a delegate\")",
        "        if not self._may_propose(commitment_id, c, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\"only the registrar may authorise a delegate\")",
    ),
    (
        "a delegate allowed to revoke",
        "        if gl.message.sender_address != c.registrar:\n"
        "            raise gl.vm.UserError(\"only the registrar may revoke a delegate\")",
        "        if not self._may_propose(commitment_id, c, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\"only the registrar may revoke a delegate\")",
    ),
    (
        "a delegate allowed to close the commitment",
        "        if gl.message.sender_address != c.registrar:\n"
        "            raise gl.vm.UserError(\"only the registrar may close a commitment\")",
        "        if not self._may_propose(commitment_id, c, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\"only the registrar may close a commitment\")",
    ),
    (
        "may_propose() drifting from the rule propose() enforces",
        "        c = self._commitment(commitment_id)\n"
        "        return self._may_propose(commitment_id, c, Address(str(who).strip()))",
        "        self._commitment(commitment_id)\n        return True",
    ),
    (
        "the cap not re-checked when a revoked delegate is reactivated",
        "            if live >= MAX_DELEGATES:\n"
        "                raise gl.vm.UserError(\n"
        "                    f\"a commitment is capped at {MAX_DELEGATES} active delegates\"\n"
        "                )\n"
        "            row.active = True",
        "            row.active = True",
    ),
    (
        "the cap counted in the same pass that finds the row",
        "            if d.who == addr:\n                found = i\n",
        "            if d.who == addr:\n                found = i\n                break\n",
    ),
    (
        "a malformed delegate address passed to Address()",
        "        if not looks_like_address(who):\n"
        "            raise gl.vm.UserError(\"that is not a 20 byte hex address\")\n"
        "        addr = Address(str(who).strip())\n"
        "        if addr == c.registrar:",
        "        addr = Address(str(who).strip())\n        if addr == c.registrar:",
    ),
    (
        "a closed commitment still accepts revisions",
        "        if bool(c.closed):\n"
        "            raise gl.vm.UserError(\"this commitment is closed to revisions\")\n",
        "",
    ),

    # -- reads and bounds
    (
        "the commitment bounds check removed",
        "        if i < 0 or i >= len(self.commitments):\n"
        "            raise gl.vm.UserError(\"no such commitment\")\n",
        "",
    ),
    (
        "negative ids allowed through to Python list indexing",
        "        if i < 0 or i >= len(self.revisions):",
        "        if i >= len(self.revisions):",
    ),
    (
        "the reason sanitiser disabled",
        "        if ch in \"<>{}\\\\`\":\n            continue\n",
        "",
    ),
    (
        "control characters left in reasons",
        "        if ord(ch) < 32 or ord(ch) == 127:\n            ch = \" \"\n",
        "",
    ),

    # -- the prompt boundary. Tagging untrusted text is not a fence unless
    # -- the characters that close a tag are neutralised too.
    (
        "the prompt fence removed, so a caller can forge a block",
        '    return str(raw).replace("<", "(").replace(">", ")")',
        "    return str(raw)",
    ),
    (
        "the fence deletes instead of replacing",
        '    return str(raw).replace("<", "(").replace(">", ")")',
        '    return str(raw).replace("<", "").replace(">", "")',
    ),
    (
        "only the opening bracket fenced",
        '    return str(raw).replace("<", "(").replace(">", ")")',
        '    return str(raw).replace("<", "(")',
    ),
    (
        "the revision text reaches the model unfenced",
        "{fence(second_text)}",
        "{second_text}",
    ),
    (
        "the dimension catalogue reaches the model unfenced",
        "{fence(numbered_dimensions)}",
        "{numbered_dimensions}",
    ),
    (
        "a caller string routed through the unfenced role argument",
        '                             "THE PUBLISHED TEXT", "THE PROPOSED TEXT"),',
        "                             label, \"THE PROPOSED TEXT\"),",
    ),
    (
        "the author label reaches the model unfenced",
        "{fence(label)}",
        "{label}",
    ),
    # -- shape rules the runtime enforces and a green suite cannot see
    (
        "a nested mapping returned from the block",
        "                \"because\": sanitise_reason(fwd_raw.get(\"because\", \"\")),",
        "                \"because\": {\"text\": sanitise_reason(fwd_raw.get(\"because\", \"\"))},",
    ),
    (
        "a bool returned from the block",
        "                \"vector\": \"|\".join(merged),",
        "                \"decided\": UNCLEAR not in merged,\n"
        "                \"vector\": \"|\".join(merged),",
    ),
    (
        "a collection nested back into a storage dataclass",
        "@allow_storage\n@dataclass\nclass Dimension:\n    commitment_id: u256",
        "@allow_storage\n@dataclass\nclass Dimension:\n    tags: DynArray[str]\n    commitment_id: u256",
    ),
    (
        "an int storage field",
        "    commitment_id: u256\n    name: str",
        "    commitment_id: int\n    name: str",
    ),
    (
        "a storage field declared twice",
        "    revisions: DynArray[Revision]\n    delegates: DynArray[Delegate]",
        "    revisions: DynArray[Revision]\n    delegates: DynArray[Delegate]\n"
        "    delegates: DynArray[Delegate]",
    ),
    (
        "a prompt moved outside the block, which genvm-lint refuses",
        "        def leader_fn():\n            fwd_raw = gl.nondet.exec_prompt(",
        "        fwd_raw = gl.nondet.exec_prompt(\n"
        "            build_prompt(label, numbered, original, revised, \"A\", \"B\"),\n"
        "            response_format=\"json\")\n\n"
        "        def leader_fn():\n            fwd_raw = gl.nondet.exec_prompt(",
    ),
]


def run_one(label, find, replace):
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "repo"
        shutil.copytree(
            ROOT, dst,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git",
                                          "artifacts", "*.pyc"),
        )
        target = dst / "contracts" / TARGET
        src = target.read_text(encoding="utf-8")
        if find not in src:
            return "PATTERN NOT FOUND", None
        target.write_text(src.replace(find, replace, 1), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=dst, capture_output=True, text=True,
        )
        if proc.returncode == 0:
            return "ESCAPED", None

        text = proc.stdout + proc.stderr
        # A collection error counts as caught: a contract that will not import
        # is a contract that will not deploy.
        m = re.search(r"^(?:FAILED|ERROR) (\S+?)::(\S+?)(?:\[|\s|$)", text, re.M)
        if m:
            return "caught", m.group(2).split("::")[-1]
        m = re.search(r"^E\s+(\w*(?:Error|Exception))", text, re.M)
        if m:
            return "caught", m.group(1) + " at import"
        return "caught", "unnamed failure"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="emit the README table")
    args = ap.parse_args()

    rows, escaped = [], []
    for label, find, replace in MUTATIONS:
        status, test = run_one(label, find, replace)
        if status == "caught":
            rows.append((label, test))
            if not args.md:
                print("  caught   %-62s %s" % (label, test))
        else:
            escaped.append((label, status))
            print("  %-8s %s" % (status, label), file=sys.stderr)

    if args.md:
        print("| Mutation | Caught by |")
        print("|---|---|")
        for label, test in rows:
            print("| %s | `%s` |" % (label, test))
    else:
        print()
        print("  %d mutations, %d caught, %d escaped"
              % (len(MUTATIONS), len(rows), len(escaped)))

    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
