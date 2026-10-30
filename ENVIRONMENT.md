# Recorded environment and replay boundary

Original source capture: CPython 3.10.11, Requests 2.32.3, verified HTTPS without credentials. Fourteen fixed records, 28 waveform/header files and nine integrity/metadata files total 30,255,876 bytes. All 28 waveform/header SHA-256 values match the two publisher inventories. Complete originals and publisher pages remain private.

Original waveform reconciliation: CPython 3.12.14, NumPy 2.2.5 and independent WFDB 4.3.1 with SciPy 1.15.3, SoundFile 0.13.1 and fsspec 2025.3.0 in a task-specific optional environment. No global Python packages were changed. The first import check exposed missing optional-environment dependencies; they were installed from PyPI before source checks. No source data or feature output changed to resolve that environment issue.

The initial clean-interval assertion incorrectly required absolute-voltage equality. Its failure is retained privately and documented in NATIVE_BINDING_NOTE.md. The publisher generator adds segment-specific constant offsets. The corrected source-shape check compares every native sample with WFDB and every scheduled clean interval with the original, allowing only the documented constant offset and one ADC unit of variation. No alignment, scale or outcome-based adjustment is fitted. No recording119 features or performance were produced during source qualification.

The public derived feature projection supports offline analysis replay. Re-extracting features and independently checking all raw samples requires the optional privately preserved originals and WFDB environment. A replay of public features alone is not a new raw-waveform validation. Actual feature, selection, replay and release checks are recorded as they execute; planned checks are not passing evidence.
