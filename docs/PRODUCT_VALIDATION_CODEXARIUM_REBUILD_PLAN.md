# SkillFoundry Product Validation 001

Status: planned manual product validation

PV001 is the first real product validation for SkillFoundry after the cleanup
baseline. The target is a clean-room rebuild of a Codexarium-like Codex Skill:
SkillFoundry should generate a high-quality skill package from product-level
requirements only, then the frozen candidate is compared against the existing
local Codexarium product as a sealed gold standard.

This is not a default CI gate. It is an opt-in live/manual validation designed
to answer one question:

```text
Can SkillFoundry turn a product-level request into a useful, governed Codex
Skill without seeing the original implementation?
```

## Why This Target

Codexarium is a good first product validation because it is not a toy skill.
It requires product identity, evidence discipline, local helper boundaries,
Markdown knowledge architecture, and curator behavior. Infrastructure success
is not enough; a candidate only matters if it preserves the product thesis and
rejects the wrong product shapes.

PV001 validates the current mainline:

```text
FrontDesk
  -> ContextForge Goal Runtime
  -> ForgeUnit SkillFoundry vNext
  -> Codex exec command boundary
  -> SkillFoundry Verifier
  -> Registry
  -> clean-room evaluation report
```

## Scope

The candidate output is a Codex Skill package. It may include:

- `SKILL.md`
- optional agent configuration
- optional helper scripts
- optional reference docs
- optional deterministic tests or smoke checks

The candidate must be installable or at least structurally reviewable as a
Codex Skill package.

## Non-Scope

PV001 does not require rebuilding:

- a full product repository;
- a Rust sidecar;
- an Obsidian plugin;
- a complete historical data importer;
- a production scheduler or daemon;
- a long-term memory file system.

Those may appear as product recommendations in the candidate, but they are not
required artifacts for a pass.

## Clean-Room Boundary

Original Codexarium implementation is sealed reference material.

During generation, SkillFoundry, ForgeUnit, Codex exec, FrontDesk, task packs,
worker inputs, candidate files, and external LLM judges must not receive the
original implementation.

Forbidden generation material includes:

- original source files;
- original helper script contents;
- original agent configuration contents;
- original sidecar or plugin source;
- original directory trees beyond generic artifact category names;
- long excerpts from original docs;
- copied command snippets that reveal implementation-specific behavior;
- local absolute paths to the original implementation.

Allowed generation material is only the product-level brief, acceptance
criteria, and generic Codex Skill packaging expectations.

The original product may be used only after the candidate is frozen, and only
by the local evaluator or human reviewer. Comparison output must describe
feature-level findings and score rationale; it must not quote source text or
publish original files.

## Product-Level Input

Create the PV001 input under:

```text
.local/product_validation/codexarium_rebuild_001/input/
```

Suggested `product_request.md`:

```markdown
Build a Codex skill called codexarium.

It should help the user maintain a structured personal LLM wiki from local
Codex collaboration history.

The skill should behave as a knowledge curator and personal research secretary.
It should preserve durable knowledge such as product ideas, decisions,
principles, experiments, conclusions, failures, open questions, project goals,
and recurring work patterns.

It should avoid raw log mirroring, activity diaries, secret collection, and
paraphrased chat-log dumps.

It may use local helper tools for health checks, project discovery, and compact
evidence scanning. It should prefer compact evidence bundles over raw session
logs. It should write structured Obsidian-friendly Markdown pages and keep
claims tied to compact evidence references.
```

Suggested `acceptance_criteria.yaml`:

```yaml
target: codexarium_like_codex_skill
must:
  - define a clear Codex Skill identity
  - preserve curator / personal research secretary behavior
  - define durable knowledge categories
  - reject raw log mirroring and daily diary behavior
  - explain compact evidence handling
  - define a structured Markdown wiki layout
  - include conflict, stale-claim, and thin-evidence handling
  - include practical install/use guidance
  - keep implementation small enough for a first usable package
must_not:
  - require access to the original implementation during generation
  - copy source text from the sealed reference
  - write raw secrets or raw session logs into a wiki
  - claim semantic truth from worker self-report alone
```

## Run Directory

Use one local run root:

```text
.local/product_validation/codexarium_rebuild_001/
  input/
    product_request.md
    acceptance_criteria.yaml
  generation/
    skillfoundry_run/
    frozen_candidate/
    candidate_manifest.json
  sealed_reference/
    reference_manifest.json
    file_hashes.json
    reference_root.local.txt
  comparison/
    leakage_report.json
    structure_comparison.json
    semantic_scorecard.json
    semantic_comparison.md
  PRODUCT_VALIDATION_REPORT.md
```

Everything under `.local/` is local operational state and must not be committed.
`sealed_reference/` must not copy original source files. It may contain local
manifest metadata, hashes, and an operator-only reference root pointer.

## Generation Flow

1. Create `product_request.md` and `acceptance_criteria.yaml` from the
   product-level input above.
2. Run a deterministic fake-mode smoke first to confirm the harness path still
   works.
3. Run the FrontDesk to approved/frozen job path using the product request.
4. Route the frozen job into ForgeUnit SkillFoundry vNext.
5. Use the explicit Codex exec command boundary for the live candidate build.
6. Let the SkillFoundry verifier and registry decide whether the candidate is
   structurally acceptable.
7. Freeze the candidate package before any sealed reference access.
8. Record candidate hashes and a candidate manifest.

The live run should follow the same manual/explicit policy as other live Codex
evals: no default tests or CI should invoke live Codex.

## Sealed Reference Use

Sealed reference access starts only after candidate freeze.

The evaluator may inspect the local gold standard to build:

- expected feature inventory;
- structural artifact comparison;
- semantic scorecard;
- gap taxonomy;
- final product validation report.

The evaluator must not:

- copy original source files into the run;
- paste original code or long prose into the report;
- send original implementation text to an external LLM judge;
- use original code to patch the candidate before scoring;
- include local original paths in public or committed artifacts.

If an external judge is useful, give it only:

- the product-level request;
- the acceptance criteria;
- the frozen candidate package;
- the redacted feature-level comparison notes.

## Leakage Gates

PV001 fails immediately if any of these are true:

- generation input contains original implementation text;
- worker input contains original implementation text;
- ForgeUnit task pack contains original implementation text;
- candidate package contains copied source or long copied prose;
- comparison report quotes original source;
- external judge receives original implementation text;
- committed files contain local absolute reference paths;
- sealed reference files are copied into the candidate or registry artifact.

Required leakage checks:

- scan generation inputs for forbidden local reference paths and source-shaped
  excerpts;
- scan worker input and task pack before live run;
- hash candidate files and compare against sealed reference hashes;
- run long common-substring or n-gram overlap checks between candidate and
  sealed reference;
- scan final report for original path strings and long source excerpts;
- verify `.local/product_validation/` remains untracked.

Hash equality against an original source file is an automatic fail unless the
file is a trivial generic artifact such as an empty placeholder.

## Structure Comparison

After candidate freeze, compare at the artifact level:

- skill entry document;
- command or helper integration surface;
- optional agent configuration;
- optional reference docs;
- safety and boundary instructions;
- install/use flow;
- test or smoke support.

The comparison should classify each area:

- `matched`: candidate covers the same product need in its own words and shape;
- `partial`: candidate recognizes the need but lacks enough operational detail;
- `missing`: candidate omits an important product need;
- `wrong_direction`: candidate implements a product shape the target rejects;
- `unsafe`: candidate violates a hard boundary.

## Semantic Scorecard

Score the frozen candidate out of 100:

| Area | Points | What To Check |
| --- | ---: | --- |
| Product identity | 15 | Clear Codexarium-like thesis: knowledge curator and research secretary, not a raw log viewer. |
| Hard rules and safety | 15 | Rejects raw log mirroring, diary output, secrets, raw dumps, and unsupported claims. |
| Wiki information architecture | 15 | Defines useful Markdown page families for projects, concepts, decisions, experiments, playbooks, questions, reviews, evidence, and index navigation. |
| Workflow completeness | 15 | Covers discovery, evidence selection, page update, conflict review, thin-evidence questions, and final reporting. |
| Helper boundary | 10 | Treats helpers as evidence scanners or health checks, not semantic truth engines. |
| Secretary behavior | 10 | Asks clarifying questions, tracks open issues, surfaces stale or conflicting claims. |
| Evidence discipline | 10 | Uses compact source refs and refuses claims without enough support. |
| Practical usability | 5 | Gives clear install/use guidance for a Codex Skill. |
| Maintainability | 5 | Keeps the package understandable and small enough to iterate. |

## Pass/Fail

Final judgment:

```text
score >= 85: pass
70 <= score < 85: conditional pass
score < 70: fail
any hard leakage failure: fail
any unsafe raw-secret/raw-log behavior: fail
```

A conditional pass must include a concrete repair list and a second-run plan.
A pass does not mean SkillFoundry is generally solved; it means this product
validation target was handled well enough to justify the next real target.

## Final Report

Write:

```text
.local/product_validation/codexarium_rebuild_001/PRODUCT_VALIDATION_REPORT.md
```

The report should contain:

- run id and timestamps;
- SkillFoundry commit and ForgeUnit version;
- ContextForge submodule commit;
- Codex command boundary used, redacted if necessary;
- candidate manifest and hashes;
- leakage gate result;
- structure comparison summary;
- semantic scorecard;
- pass/fail result;
- top product gaps;
- top infrastructure gaps discovered in SkillFoundry;
- recommended next action.

Do not paste raw worker stdout, raw prompts, raw transcripts, package body, or
sealed reference source into the report. Link or reference local artifacts by
manifest id where needed.

## Expected Failure Taxonomy

Use this taxonomy when PV001 fails:

- `identity_flattening`: candidate becomes a generic wiki skill.
- `log_mirroring`: candidate mirrors sessions instead of curating knowledge.
- `diary_bias`: candidate summarizes daily activity rather than durable ideas.
- `evidence_overexposure`: candidate asks for or writes raw logs/secrets.
- `weak_wiki_architecture`: candidate lacks canonical page families.
- `missing_secretary_mode`: candidate does not ask questions or track unknowns.
- `helper_overreach`: helper scripts are treated as semantic authorities.
- `verifier_gap`: SkillFoundry verifier approved a semantically weak candidate.
- `registry_gap`: registry accepted an unsafe or badly scoped package.
- `leakage`: clean-room boundary was violated.

## First Execution Recommendation

Do not start with a broad benchmark suite. Start with this single PV001 run:

1. run deterministic smoke;
2. run one live clean-room Codex exec generation;
3. freeze candidate;
4. run leakage gates;
5. compare with sealed reference;
6. write the report;
7. decide whether to repair SkillFoundry or run PV002.

This keeps the validation aligned with the current philosophy: small core,
real product pressure, fast feedback, and repair based on observed failure
rather than speculative architecture.
