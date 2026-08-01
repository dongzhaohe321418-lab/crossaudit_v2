# Constitution — <PROJECT>

Version this file in git. Every audit cites the commit that carried it, so a
rule change is dated and attributable, and it takes effect only *between*
cycles: no increment is judged against a target that moved under it.

Each rule needs a stable ID and a decidable criterion. If a reviewer could
argue either way about whether a rule was met, it is not decidable yet — put
the judgement in an ADVISORY rule, or sharpen the criterion.

Severities are two, and only two. **BLOCKER** is an objective defect and gates
the increment. **ADVISORY** is judgement, is recorded, and never gates.

---

### CA-META-001
**BLOCKER.** Every increment declares `metadata.yml` (with `code_version` and
`inputs`) and `results.json` (with a `quantities` list). Both must parse.

### CA-META-002
**BLOCKER.** An audit report cites the rule IDs it applied. A report that cites
nothing is invalid.

### CA-TASK-001
**BLOCKER.** When a committed `TASK.md` exists, the increment satisfies every
objectively testable requirement it states. Substituting a different value,
file, command, or declared environment is a defect even when the produced files
are internally consistent. If the task conflicts with this Constitution, the
auditor escalates instead of choosing one silently.

### CA-DATA-001
**BLOCKER.** Every numeric entry in the results file carries a unit and a
source.

### CA-DATA-002
**BLOCKER.** Prose and data agree. A summary that states a sign, magnitude, or
conclusion the results file contradicts is a defect in the increment.

### CA-DATA-003
**BLOCKER.** A quantity's source is among the declared inputs, at the declared
code version.

### CA-METH-002
**BLOCKER.** Unconverged numbers are not results: a quantity whose convergence
block reports `converged: false`, or whose achieved value exceeds its own
threshold, cannot be reported as final.

### CA-REPRO-001
**ADVISORY.** Each increment should carry enough to re-run it: the command, the
environment, and the random seed where one applies.

---

<!-- Add your field's rules below. Keep the ID scheme: CA-<AREA>-<NNN>, one
     heading per rule, severity in the first line, criterion after it. The
     check layer and the model auditor both read this file; the deterministic
     checks implement the mechanisable subset, and the model is asked for the
     rest. -->
