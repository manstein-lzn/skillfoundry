# Git Worktree Workflow

Status: standard workflow for parallel upgrade tracks

## Purpose

Use one git worktree per upgrade mainline so adaptive steering, product-grade,
Codexarium validation, ForgeUnit integration, and documentation experiments can
move independently without mixing dirty working trees.

The primary checkout should stay close to `main`. Feature work should happen in
sibling worktrees under:

```text
../skillfoundry-worktrees/<task-slug>/
```

## Default Rule

Start every substantial upgrade in a new worktree:

```bash
scripts/worktree_task.sh new <task-slug>
cd ../skillfoundry-worktrees/<task-slug>
```

Examples:

```bash
scripts/worktree_task.sh new adaptive-benchmark
scripts/worktree_task.sh new codexarium-live
scripts/worktree_task.sh new forgeunit-runtime-contracts
```

The script creates a branch named:

```text
work/<task-slug>
```

It refuses to create a new worktree if the primary checkout is dirty. Commit or
stash the current task first; do not let the script move uncommitted work.

## Bootstrap

Each worktree has its own `.venv`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e third_party/contextforge
.venv/bin/python -m pip install -e '.[test,forgeunit]'
```

Run focused checks inside that worktree:

```bash
scripts/dev_check.sh focused
```

For adaptive work, prefer the locked focused validator for the current task,
then run broader tests before merge.

## Parallel Mainlines

Recommended naming:

```text
work/adaptive-route-plan
work/adaptive-benchmark
work/codexarium-live-validation
work/product-grade-runtime
work/forgeunit-contracts
work/pi-inspired-context
```

Keep branches narrow:

- one mainline per worktree;
- one MetaLoop capsule per substantial task;
- no live Codex work in default deterministic branches;
- no shared `.local/`, `.metaloop/`, registry, or run artifacts across
  worktrees;
- do not modify another branch's worktree to "quick fix" it.

## Inspection

List worktrees:

```bash
scripts/worktree_task.sh list
```

Show branch and dirty state for every worktree:

```bash
scripts/worktree_task.sh status
```

Remove a finished clean worktree:

```bash
scripts/worktree_task.sh remove <task-slug>
```

## Merge Discipline

Before merging a worktree branch:

1. Run the task-specific locked validator.
2. Run any focused regression suite affected by the branch.
3. Verify MetaLoop status when used.
4. Rebase or merge from `main` only inside that worktree.
5. Open the final diff from that worktree, not from a mixed primary checkout.

If two mainlines conflict, resolve in a short integration worktree:

```bash
scripts/worktree_task.sh new integrate-adaptive-product
```

Then merge both branches there and run the combined validator.
