# Pytest Repair Offline Skill

Build a local Codex Skill that helps inspect a failing pytest run, identify the
smallest likely repair, and describe the verification evidence required before
acceptance.

The Skill must run entirely offline in WP7 using deterministic fixture behavior.
It must not call a real provider, use the network, start a production queue, or
invoke a real Codex worker.
