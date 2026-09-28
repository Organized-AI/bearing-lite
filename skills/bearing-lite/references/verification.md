# Deterministic verification adapter

Decision source: `DEC-BDL-036`, `DEC-BDL-037`, `DEC-BDL-053`, `DES-BDL-008`,
`AC-BDL-009`, `CONTRACT-BDL-005`.

`hooks/verification.cjs` is the exact runtime evaluator of this contract. It
declares no hook class and registers no host event. A backend is never a role.
System One backends are optional profile configuration; this adapter
never downloads, installs, or calls them.

A **request** binds candidate, claim, backend, stage, authority, expected
result, and command/configuration, plus whether the backend is `selected` or
`required` for that claim. A **receipt** binds the same candidate, claim,
backend, version, command/configuration, and evidence digest. Status values
are `VERIFIED`, `REFUTED`, `INCONCLUSIVE`, and `ERROR`.

## Authority

- **diagnostic** — Implementer, Light Implementer, and Integration Engineer
  execution may emit diagnostic receipts. They help implementation and
  integration. They never satisfy an assurance gate.
- **assurance** — Test Engineer assurance independently reruns required claims
  against the exact stable candidate in a fresh session. Reviewer may request
  deterministic verification to adjudicate a specific suspected defect. The
  Orchestrator routes and records; it never treats a backend as a role.

Candidate authors cannot turn their own runs into an assurance PASS. An
independent assurance session must rerun required claims. Diagnostic and
assurance receipts remain distinguishable.

## Backend activation

Activation is selected OR required. Unavailability of an activated backend is a
typed gap (`ERROR` / `backend_unavailable`), not success and not invented
behavior. Required unavailability emits `proceed: "halt"`; enabled-only
unavailability emits `proceed: "proceed-with-note"`. Only unselected AND unrequired absence stays inactive and is not a
global failure. Assurance packets consume frozen `deterministic_verification`
from the Lifecycle snapshot, never the live catalog. Backend identity is `jev`,
`laya`, or `validator` and stays that name in every request, receipt, and gate
declaration. They are distinct identities: a generic name such as `system1`
must not stand in for an absent binding, and one backend never substitutes for
another inside an assurance receipt; switching backend is a new rubric, a new
binding, and a plan amendment, never a fallback. `validator` is a pinned
deterministic program (`tools/system1-validators/`), not a model and not the
retired Validator role. Profile `jev.enabled`, `laya.enabled`, and
`validator.enabled` record user configuration; availability does not select a
backend for any task. The Planning Test Engineer selects one only on a SEIT
claim that passes the eligibility test and the selection guide in
`references/system1-rubrics.md` (validator for rules expressible as code, Laya
for single-condition semantic questions, Jev for existing Jev rules) and binds
it to one frozen rubric (id, version, digest). Plan Integrator copies that
selection and must not invent V&V. `reverify` is a legacy identity: it may not
be enabled together with `jev`, `laya`, or `validator`.

## Gates

- Assurance gate: only an independent `assurance` receipt whose candidate,
  claim, backend, version, command/configuration, and evidence digest bind the
  current candidate, and whose status matches the expected result, may be
  `gate_eligible`. `INCONCLUSIVE` and `ERROR` cannot become PASS.
- Post-repair deterministic closure reruns required checks on the repaired
  candidate without a second review round. Author diagnostics and stale
  pre-repair evidence cannot close it. Automatic rereview is prohibited.

Stale evidence is a receipt bound to a prior candidate or to a pre-repair
evidence digest. Candidate mismatch fails closed.

## Receipt bridge

`hooks/verification-bridge.cjs` shapes the request and receipt this adapter
judges. It is a pure evaluator on the same terms: no `HOOK_CLASS`, no host
event, no download, and no process execution. It never runs a backend. The
caller runs the planned command and hands the output back.

Two steps, so request and receipt are built from one source and their
`command_configuration` stays deeply equal:

- `planVerification(spec)` validates the intent and returns the `request` plus
  a runnable `argv`. Activation, authority, stage, expected result, claim, and
  candidate must all be bound; nothing is defaulted.
- `sealVerification({ plan, output, produced_by })` returns the receipt.
  `backend_version` is read from the run, `evidence_digest` is SHA-256 over
  canonical JSON of the backend output, and `authority` is carried from the
  plan.

Three refusals carry the contract:

- **Generative operations are denied.** A backend operation that proposes
  claims returns `generative_backend_operation_denied`. An operation that
  proposes the claims it then verifies is circular, so it cannot produce
  independent evidence. An unlisted operation returns
  `backend_operation_unsupported` rather than being guessed.
- **Analysis-derived verdicts cannot close a gate.** When a backend marks its
  evidence as recovered rather than read, the receipt is sealed
  `INCONCLUSIVE` with `evidence_tier: derived`, and the raw `backend_verdict`
  stays visible. A heuristic answer is recorded, never promoted.
  Directly observed evidence seals at `evidence_tier: observed`.
- **A malformed claim is a typed rejection.** A claim the backend could not
  parse returns `claim_malformed` with the backend's own detail, and no
  receipt. Sealing it as `INCONCLUSIVE` would read as "not proven" and quietly
  weaken the gate.

For `jev` and `laya`, the backend output follows `schemas/system1.schema.json`
`backend_output`: one result whose `verdict` is mechanically derived from the
frozen rubric (thresholds, calibration, replay), and whose evidence records
rubric digest, model revision, checkpoint, gateway request and log ids, and
every replay run. A verdict reconstructed rather than read (for example from a
gateway log after a timeout) is marked `DERIVED` and seals INCONCLUSIVE.
Rubrics, thresholds, and the gate slot are defined in
`references/system1-rubrics.md`. For `validator`,
`tools/system1-validators/run.cjs` prints the same `backend_output` shape with a
program's evidence instead: the pinned-file digests, the raw and canonical
input digests, every control's observed verdict, the decision-record digest of
every fresh-process run, and the conditions that failed; it carries no
probability. An `assurance` plan for `jev`, `laya`, or `validator` must carry
its frozen rubric: `planVerification` refuses it as `rubric_missing`,
`rubric_digest_mismatch` (SHA-256 over `canonicalJson` of the rubric differs
from the claim's `rubric_digest`), `rubric_backend_mismatch`, or
`rubric_not_assurance_eligible`; a `diagnostic` plan may use a non-eligible
rubric.

These refusals are stated in engineering terms. An adopting project maps them
to whatever assurance standard it follows.

Authority is never defaulted because one backend serves both levels. An
Implementer, Light Implementer, or Integration Engineer execution run is
`diagnostic` and cannot pass a gate; only an independent Test Engineer
assurance session produces `assurance`.

## Gate-chain claim types

Deterministic gate-chain claims use the mutation, changed-line coverage, and
red-then-green claim types, each naming the target repository's own tool plus
its threshold; `method` stays a plain string, never a schema enum. Each claim
type defines a typed-gap outcome: a declared gate with a missing tool or a
`not_run` outcome is a typed gap, never PASS. The Assurance Test Engineer independently reruns the gate-chain at the declared cadence boundary; author gate-chain receipts are diagnostic and cannot satisfy an assurance gate. Every
red-then-green receipt binds the baseline failing run and the candidate passing run
over the same test ids.
