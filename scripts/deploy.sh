#!/usr/bin/env bash
#
# deploy.sh — deploy Ratchet and leave real consensus evidence on the explorer.
#
#   ./scripts/deploy.sh studionet
#
# A contract page showing only a deploy transaction proves the file compiles and
# nothing else. This deploys AND exercises the contract, so the explorer shows
# method calls with the leader's proposal and the validators' votes beside them.
#
# It deliberately leaves a REFUSAL on chain. A page showing only successes is a
# weaker demonstration than one showing the primitive decline to apply a
# revision that quietly dropped a clause.
#
# Deployment can also be done entirely by hand through the Studio web interface
# at studio.genlayer.com, which is the recommended route: paste the contract,
# deploy, and call the methods through the form. Never put a private key into a
# file or hand one to a tool.
#
# Requires: npm i -g genlayer

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NETWORK="${1:-studionet}"
gold() { printf '\033[33m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

gold "Ratchet -> $NETWORK"
# `network` is a command group, not a value: `genlayer network studionet`
# answers "unknown command" and exits 1, which under `set -e` kills the script
# on its first line.
genlayer network set "$NETWORK"

dim "linting"
# genvm-lint needs its subcommand, and utf-8 stdout: the linter prints a U+2713
# tick on success and dies encoding it under the cp1252 stdout Windows hands a
# child process, reporting a PASSING contract as failed.
PYTHONIOENCODING=utf-8 genvm-lint lint contracts/ratchet.py

ADDR=$(genlayer deploy --contract contracts/ratchet.py \
       | grep -oE '0x[0-9a-fA-F]{40}' | head -1)
gold "deployed at $ADDR"

ORIGINAL="We retain personal data for at most 90 days, we never share it with third parties, and we notify affected users within 72 hours of a breach."
TIGHTER="We retain personal data for at most 30 days, we never share it with any third party, and we notify affected users within 24 hours of a breach."
DROPPED="We retain personal data for at most 30 days and we notify affected users within 24 hours of any confirmed security breach."

# --args is variadic. A JSON array is ONE argument, not the argument list, so
# `--args '[0,"text"]'` passes a single two-item array where the method wanted
# two parameters. Every value below is a separate token.
dim "open()      a commitment, and freeze the catalogue it is judged on"
genlayer write "$ADDR" open --args \
  "Acme Data Ltd" "$ORIGINAL" "data retention|third party sharing|breach notice" >/dev/null

dim "propose()   a revision that tightens two dimensions and drops none"
genlayer write "$ADDR" propose --args 0 "$TIGHTER" >/dev/null

dim "judge(0)    expected TIGHTENED, and the published text moves"
genlayer write "$ADDR" judge --args 0
genlayer call  "$ADDR" revision --args 0
genlayer call  "$ADDR" text --args 0

# --- and now the refusal path, on chain -----------------------------------
dim "propose()   a revision that reads better and stops mentioning sharing"
genlayer write "$ADDR" propose --args 0 "$DROPPED" >/dev/null

dim "judge(1)    expected BROADENED -- nothing was contradicted, a clause is gone"
genlayer write "$ADDR" judge --args 1
genlayer call  "$ADDR" revision --args 1
genlayer call  "$ADDR" ratchet --args 0

# --- the provenance model, on chain ---------------------------------------
dim "authorise() a delegate, then revoke it"
genlayer write "$ADDR" authorise --args 0 "0x7777777777777777777777777777777777777777" >/dev/null
genlayer call  "$ADDR" delegation --args 0
genlayer write "$ADDR" revoke --args 0 "0x7777777777777777777777777777777777777777" >/dev/null

cat <<TXT

  Contract:  $ADDR
  Explorer:  https://explorer-studio.genlayer.com/address/$ADDR

Before submitting, prove the address is evidence for THIS repository:

  python scripts/verify_deployment.py $ADDR

It reads the source back out of the deploy transaction, diffs it against
contracts/ratchet.py, and lints those bytes. A correct repository proves nothing
on its own if the address points at an earlier draft.

Both paths should be on chain: revision 0 resolved tightened and moved the text,
revision 1 came back broadened and did not.

Then paste the address into README.md and SUBMISSION.md where {address} appears.

TXT
