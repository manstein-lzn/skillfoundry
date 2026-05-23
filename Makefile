.DEFAULT_GOAL := help

.PHONY: help focused test fresh-clone-smoke all-checks live-semantic-eval-help

help:
	@printf '%s\n' 'SkillFoundry developer commands:'
	@printf '%s\n' '  make focused                 Fast deterministic FrontDesk/ForgeUnit checks'
	@printf '%s\n' '  make test                    Full deterministic pytest suite'
	@printf '%s\n' '  make fresh-clone-smoke       Fresh clone offline smoke; network/Git, no live Codex'
	@printf '%s\n' '  make all-checks              Full pytest plus fresh clone offline smoke'
	@printf '%s\n' '  make live-semantic-eval-help Print manual live Codex eval guidance'

focused:
	@PYTHON="$(PYTHON)" scripts/dev_check.sh focused

test:
	@PYTHON="$(PYTHON)" scripts/dev_check.sh full

fresh-clone-smoke:
	@PYTHON="$(PYTHON)" scripts/dev_check.sh fresh-clone

all-checks:
	@PYTHON="$(PYTHON)" scripts/dev_check.sh all

live-semantic-eval-help:
	@scripts/dev_check.sh live-help
