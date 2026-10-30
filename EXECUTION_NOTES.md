# Retained execution evidence

Development analysis executed twice before dependency freeze. The second invocation followed the code change that adds the explicitly documented secondary later audit; that branch does not change development logic. Both printed identical candidate confusion counts and the accept-all selection. The task trace retains both outputs. The current development execution JSON records the second invocation; the first invocation's separate runtime was not retained and is unavailable. No favorable candidate was chosen between them.

The analysis command now refuses to overwrite a nonempty output directory. All subsequent replays use separate paths. Deterministic tables/selection and source bytes will be compared; timestamps and measured runtimes remain execution observations rather than deterministic replay targets.
