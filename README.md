# CrossAudit

**One conversation, two adversarial agents, one replayable ledger.**

You speak plainly. The program routes each sentence to the generator, to the
auditor, or to the ledger; two models from **different vendors** keep each other
honest; and the whole supervision history lands in git, so when something goes
wrong you can say who, when, and under which version of the rules.

```bash
pip install "crossaudit @ git+https://github.com/dongzhaohe321418-lab/crossaudit_v2@main"
crossaudit init my-project
cd my-project && crossaudit console
```

> 中文版:**[README.zh-CN.md](README.zh-CN.md)**

---

## Contents

- [What this is](#what-this-is)
- [1. Install](#1-install)
- [2. Set up](#2-set-up)
- [3. Use it](#3-use-it)
- [4. The console](#4-the-console)
- [5. Customise](#5-customise)
- [6. Repositories and admission tiers](#6-repositories-and-admission-tiers)
- [Command reference](#command-reference)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [Design and protocol](#design-and-protocol)

---

## What this is

One AI writes. A second AI **from a different vendor** reviews it against rules
you stated in your own words. Work that fails review goes back to be rewritten,
and every round is a git commit. You deal with one text box.

| | |
|---|---|
| **Works for** | anything whose **output can be a file** and whose **standards can be stated as rules**: reviews, code, contract checking, financial models, copy, data pipelines |
| **You need** | Python 3.10+, git, and API keys from **two different vendors** |
| **You do not need** | to write a rules file, to know git, or to learn what an "increment" or a "receipt" is |

None of the eight invariants mentions science. Only two things are
domain-specific: the deterministic check pack (pluggable) and the content of the
rules (generated from what you say). **Where no domain pack exists, the
deterministic layer is down to four generic checks and the model audit carries
the rest — the program says so rather than glossing over it.**

---

## 1. Install

```bash
pip install "crossaudit @ git+https://github.com/dongzhaohe321418-lab/crossaudit_v2@main"
```

Installing does **nothing**: no network, no authentication, no files written.
That is deliberate. An audit tool that phones home the moment it is installed
has forfeited the trust it exists to provide. Everything interactive lives
behind `init`.

Check it:

```bash
crossaudit --version     # crossaudit 2.7.3 (receipt schema 2)
```

<details>
<summary><b>Want to try it in isolation first?</b></summary>

```bash
python3 -m venv ~/crossaudit-try && source ~/crossaudit-try/bin/activate
export CROSSAUDIT_KEYS_FILE=~/crossaudit-try/keys.env   # keep credentials inside too
pip install "crossaudit @ git+https://github.com/dongzhaohe321418-lab/crossaudit_v2@main"
```

Delete `~/crossaudit-try` and nothing remains. By default the program writes to
exactly one place outside your project — `~/.crossaudit-keys.env` — and the line
above redirects that into the sandbox.

</details>

**One dependency: PyYAML.** Model access is stdlib `urllib` with no vendor SDKs
— an audit tool's credibility rests on being small enough to read.

---

## 2. Set up

```bash
crossaudit init my-project
```

It **creates the directory, runs `git init`, and ignores the local state
directory** — an audit reads commits, so a project that is not a repository
cannot be audited at all. If the directory already exists, run `crossaudit init`
inside it.

The wizard asks four things, arrow keys to choose:

```
╭──────────────────────────────────────────────────────────────╮
│ CrossAudit — setting up a supervised project                 │
╰──────────────────────────────────────────────────────────────╯
  ✓ created my-project
  ✓ git init — the ledger is git, and an audit reads commits

  [1/4] Who audits
  ↑↓ to move · enter to choose
  ❯ anthropic  Claude
    openai     GPT
    google     Gemini
```

| Question | What it does |
|---|---|
| **1. Who audits** | pick the vendor, then the model, both from a list |
| **2. Who generates** | **must differ from the auditor** — choosing the same one is refused outright, because that is same-source supervision, the thing this protocol exists to prevent |
| **3. Two keys** | **visible as you type**, so a typo or a truncated paste is visible too; written to `~/.crossaudit-keys.env` (mode 600), **never into the repository**. `CROSSAUDIT_HIDE_KEYS=1` hides them |
| **4. What this is, and what would be a mistake** | you say it in plain language; the system distils it into numbered rules, **shows them, and commits them only if you agree** |

The fourth question is the important one:

```
  your project, in a sentence or three
  ❯ A review of the PV industry. Every figure must trace to a source,
    and the prose must not contradict the data files.

  ┌─ Drafted rules
  │ CA-SRC-001  [BLOCKER]  Every figure is sourced
  │     Each numeric claim names a source in the declared inputs.
  │     from you: "every figure must trace to a source"
  │ CA-TXT-001  [BLOCKER]  Prose matches data
  └─
  Commit these as the project's rules? [Y/n]
```

**You never write a line of markdown**, yet the rules exist, are versioned, and
can be cited by a receipt. Each rule carries **the fragment of your own words it
came from**, so you can check the translation yourself.

> With piped stdin, in CI, or on a terminal without `termios`, the wizard takes
> defaults and **never blocks on a keypress that cannot arrive**.

Then:

```bash
source ~/.crossaudit-keys.env
crossaudit doctor
```

`doctor` checks everything and ends by telling you the **admission tier you are
actually at** — measured, not hoped for.

Setup finishes by starting the console and opening it, because that is where the
work begins. On a headless machine, or with `--no-console`, it prints the URL
instead and the setup still succeeds — a missing browser is not a failed
install.

---

## 3. Use it

### The main line: say one sentence, the loop runs itself

```bash
crossaudit build "write a section on solar LCOE; the figures must match the data file"
```

```
  ── round 1 ──
  generator  3 file(s): work/lcoe/SUMMARY.md, …
  auditor    blocked
             [CA-TXT-001] the prose says 0.052 while the data file says 0.044
  loop       findings returned to the generator
  ── round 2 ──
  generator  3 file(s)  note: prose said 0.052; the data says 0.044. Fixed.
  auditor    passed
  Done in 2 round(s).
```

The generator writes, the auditor judges, blocked findings go back for another
attempt — until it passes or the round budget hands it to you (three by
default). **Every round is a commit; every verdict has a report and a receipt.**

### The rest of the time: talk to one box

```bash
crossaudit talk "from now on check the edition of every source"   # → the standards
crossaudit talk "section three is too long, cut it down"          # → the work
crossaudit talk "where are we"                                    # → read-only
crossaudit talk "that finding is wrong, 0.052 was a quotation"    # → a dispute
```

The program decides which lane a sentence belongs to. **When it is unsure it
asks; it never guesses** — guessing the direction of a change would contaminate
either the rulebook or the work.

<details>
<summary><b>What the six lanes do</b></summary>

| Lane | Sounds like | Materialises as |
|---|---|---|
| `project` | describing what the project is | a task and a first draft of the rules |
| `generator` | "too long", "add a section", "rewrite this" | the generator runs; a new increment commit |
| `amendment` | "from now on…", "that rule is too strict" | a drafted rule change → confirmed → effective **from the next cycle** |
| `dispute` | "that finding was wrong" | **one** trip back to the auditor, by rule ID, with grounds |
| `resolve` | "let it through", "drop it" | a human ruling on an escalation |
| `query` | "where are we" | read-only; changes nothing |

</details>

---

## 4. The console

```bash
crossaudit console
```

An overview you can read at a glance:

```
┌ Audits 12 ┬ Passed 8 75% ┬ Blocked 3 ┬ Waiting on you 1 ┬ Admitted 6 ┐
├─ The loop ────────────────────────────────────────────────────────────┤
│ ✓ Commit  →  ✓ Checks  →  ✓ Audit  →  ✕ Verdict  →  · Admission      │
├─ Generator (the work) ──────┬─ Auditor (the judgement) ──────────────┤
│ …                           │ …                                      │
├─ Waiting on you ─┬─ What the rules caught ─┬─ Disputes ──────────────┤
└─ [ Say what you want — the box decides who hears it… ]      [ Send ] ─┘
```

- **Updates are pushed** — a frame goes out only when something actually
  changed; a connection light sits in the top bar, and polling covers any gap
- **Build progress is visible as it happens** — which files were written, which
  rule blocked it, which round, how long
- **Closing the window does not stop a build**, and `crossaudit console` brings
  you back to the same URL

```bash
crossaudit console --status   # is one running? pid and URL
crossaudit console --stop     # stop it
```

<details>
<summary><b>Security (opening a port deserves care)</b></summary>

| Measure | What it stops |
|---|---|
| binds `127.0.0.1` only | anything off this machine |
| a token on every request, **no cookies at all** | CSRF — there is no credential the browser attaches for an attacker to ride |
| `Host` must be localhost | DNS rebinding |
| strict CSP, everything inline | injected scripts and exfiltration |
| **the input box is the only write path** | every other POST is a 404 |
| keys reported present or absent, never rendered | a key leaking through the page |
| idle shutdown, **but never while a build runs** | a forgotten port; a closed window killing work |

Each one has a test that fails if the defence goes away.

</details>

**Three things the dashboard will not do:** show "0" for something never
measured (it says *not measured*), colour a step green before it happened (a
step nobody reached is *pending*, not *passed*), or imply it acted on its own —
every action runs the same CLI verb.

---

## 5. Customise

### Give the generator a skill

```bash
crossaudit skills --new house-style   # write a starter
crossaudit skills                     # what is in force
```

Edit `skills/house-style.md`: house style, domain conventions, worked examples,
steps to take before calling something finished. An optional `applies_to: work/`
in the front matter scopes it to rounds that touch those paths.

**The boundary is hard: a skill changes *how* the generator writes, never *what*
it may write or *who* judges it.** The auditor never sees skills — one that
could speak to the auditor would be an unversioned rule. A skill saying "you may
also edit the rules file" achieves nothing: **the path guard decides**, and that
round is refused on the spot. A skill's hash goes into the receipt, so changing
one makes it a different round.

### Change the rules

```bash
crossaudit amend "from now on, every claim must name its source edition"
```

Drafted → shown → confirmed → committed. **Effective only between cycles**: work
already under audit is judged by the rules it started under, never by a standard
that moved underneath it.

---

## 6. Repositories and admission tiers

```bash
crossaudit pair               # print the plan; touches nothing
crossaudit pair --apply       # actually create them (needs gh, logged in)
```

**Two repositories are not about research; they are about privilege
separation**: the generator cannot reach the rules or the reports, which is what
lets the ledger hold the two agents to account against each other.

The four tiers `doctor` reports are **measured**, never inferred from
configuration:

| Tier | What it means | Requires |
|---|---|---|
| `local` | self-review only — the history is yours to rewrite | local git |
| `remote` | you can be held to your own record | pushed to a remote |
| `paired` | the two agents can be held to account against each other | two repositories, privilege separated |
| `enforced` | **a failed audit refuses the merge** | a persistent atomic controller, a required check bound to a verified App, no direct push, no admin bypass |

Anything short of all four is named `verified-notification`. **Publishing a
verdict is not refusing a merge**, and letting the first borrow the second's
name is worse than saying nothing: it manufactures confidence the ledger cannot
support.

---

## Command reference

| Command | What it does |
|---|---|
| `crossaudit init [name]` | create the directory, `git init`, run the wizard, draft the rules from what you say |
| `crossaudit doctor` | preflight and the real admission tier; `--online` probes GitHub |
| `crossaudit build "…"` | say what to build; the loop writes and audits it |
| `crossaudit talk "…"` | talk to the box; it routes to one of six lanes |
| `crossaudit console` | the dashboard in a browser, in the background; `--status` / `--stop` |
| `crossaudit amend "…"` | change the rules |
| `crossaudit skills [--new NAME]` | house guidance for the generator |
| `crossaudit check` | the deterministic layer alone; no model involved |
| `crossaudit run` | audit the latest commit (the audit half of `build`) |
| `crossaudit verify <receipt> [--admit]` | re-derive every binding; `--admit` consumes it, once |
| `crossaudit status` / `watch` / `routing` | open the box: cycles, the exchange, every routing decision |
| `crossaudit resolve <cycle> --reopen --because "…"` | rule on an escalation (interactive terminals only) |
| `crossaudit pair [--apply]` | create the two repositories |

**Exit codes are a contract**, and every command supports `--json`:

| Code | Meaning |
|---|---|
| `0` | the good outcome (PASS / verified / consumed) |
| `10` | BLOCKED |
| `11` | escalated, or deterministic-layer only (DCL_ONLY) |
| `20` | configuration or environment refused the run |
| `21` | receipt or integrity refused |
| `22` | network or provider failure |

<details>
<summary><b>Environment variables</b></summary>

| Variable | Purpose |
|---|---|
| `CROSSAUDIT_AUDITOR_KEY` | the auditor's key (required) |
| `CROSSAUDIT_GENERATOR_KEY` | the generator's key (required by `build`) |
| `CROSSAUDIT_GENERATOR_MODEL` | the generator's model name (required by `build`) |
| `CROSSAUDIT_GENERATOR_PROVIDER` | the generator's provider (inferred from the vendor by default) |
| `CROSSAUDIT_GENERATOR_BASE_URL` | a custom endpoint for the generator |
| `CROSSAUDIT_KEYS_FILE` | where credentials are stored (useful for sandboxes) |
| `CROSSAUDIT_HIDE_KEYS` | hide keys as you type; visible by default so a typo is visible too |
| `CROSSAUDIT_CA_BUNDLE` | a root certificate to trust, for a network that inspects TLS; verification is never skipped |
| `CROSSAUDIT_ALLOW_CUSTOM_ENDPOINT` | permit a non-builtin origin — **this sends your key there**, so it must be explicit |

</details>

---

## Troubleshooting

| Symptom | Cause and cure |
|---|---|
| `DENIED (config): no crossaudit.yml found` | you are not in a project, or have not run `crossaudit init` |
| `I1 violated: auditor vendor 'x' equals generator vendor 'x'` | both ends are the same vendor — this refusal is **deliberate**; change one |
| the verdict is `DCL_ONLY` | no model audited it. Check `$CROSSAUDIT_AUDITOR_KEY`; `doctor` will point at it |
| `$… is not set in this process, though …keys.env has it` | the key is stored but this process started before it was. `source ~/.crossaudit-keys.env`, or restart the console with `crossaudit console --stop && crossaudit console` |
| `certificate verify failed: unable to get local issuer certificate` | this Python's trust store is empty. `pip install certifi`, or on a python.org build run `/Applications/Python 3.x/Install Certificates.command`. `crossaudit doctor` reports it as **tls trust store** before you ever call a model |
| `HTTP 400 — it said: model: …` | the model id, not your key: this account cannot use it. Edit `model:` in `crossaudit.yml`, or re-run `crossaudit init` and pick from the list |
| `HTTP 401 — it said: …` | the key was rejected. `crossaudit doctor` prints its length and last four characters — enough to spot a truncated paste or a key for the other vendor |
| `HTTP 429` | the vendor's rate limit or an empty balance, not a CrossAudit limit |
| `endpoint … is not this provider's built-in origin` | a custom `base_url` needs an explicit `--allow-custom-endpoint` |
| `install mode source/editable may verify but never admit` | such an install can change its code after reporting its own digest. Install the wheel to admit |
| the console returns 403 | wrong token, or `Host` is not localhost. Get the right URL from `crossaudit console --status` |
| a build was interrupted | reopening the console **says so**; the rounds it committed are all there, and repeating the sentence carries on |

`crossaudit doctor` is the first stop — it names what is missing and how to fix
each item.

---

## Uninstall

```bash
pip uninstall crossaudit
```

The program writes to exactly two places outside your project:
`~/.crossaudit-keys.env` and the pip cache. Inside a project, `.crossaudit/`
(local state) and `cycles/` (the ledger) travel with it — **the ledger is the
record, so think before deleting it**.

---

## Design and protocol

- **[DESIGN.md](DESIGN.md)** — the design core, bilingual: the three pillars,
  the router, the limits of domain generality, why git is mandatory, the console
  layout, and the milestones
- **[the v1 repository](https://github.com/dongzhaohe321418-lab/crossaudit)** —
  the protocol itself, the position paper, the registered ablation, and six
  rounds of audit history (a research record, which does not chase the product)

Three principles run through all of it:

1. **The audit reads committed content only.** All four requirements of
   accountability — what was audited, whether it changed afterwards, who and
   when, and the ordering of report and receipt — are supplied by commits. In
   v2 committing happens inside the box, so you never touch git.
2. **Conversation is the input; the ledger is the form.** What you say becomes,
   once confirmed, a versioned rule with a commit hash, and audits always run
   against the committed version.
3. **The box is opaque to interact with, not opaque in its records.** Every
   routing decision, revision and finding is committed. You *need not* look
   inside, and you *can always* look inside.

---

## Status

`2.7.3`, 191 tests. Landed: spoken-rule distillation, the six-lane router, the
closed `build` loop, the one-shot dispute channel, domain-neutral checks,
allowlisted check-pack plugins, the paired-repository wizard, evidence-based
admission tiering, a live-pushed browser dashboard, and a console that outlives
its window. Not yet: evidence from a real enforced deployment, and PyPI
distribution.

## License

[MIT](LICENSE) © 2026 Zhaohe Dong, Yuhao Chen
