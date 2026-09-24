# AsBoljam design handoff

`index.ts` re-exports the actual web CSS token snapshot, route/state map and current KK/RU copy from `design/`.

Run `python scripts/generate_contracts.py` after changing the web styles, copy or data importer. The original design JSON and data manifest were not supplied; provenance explicitly identifies these files as reconstructed during implementation.

The web CSS currently remains the styling source. These exports are handoff artifacts and do not imply that every CSS declaration or native component consumes a shared runtime token.
