# Exercise: rejecting a window is not detecting disease

Run the tests, inspect the full development table, and explain why the three candidate gates are ineligible even though they detect many added-noise windows. The constraint is on source-clean false rejections, not balanced accuracy alone. The fallback does not certify any window as clean.

For a one-column CSV named `mV` containing exactly 3,600 finite samples:

```sh
python src/check_window.py examples/authored_window.csv --sample-rate 360 --units mV
python src/check_window.py examples/authored_window.csv --sample-rate 360 --units mV --candidate q099
```

The first command uses the frozen selection. The second explicitly inspects an already rejected development candidate. It does not select that rule for use. Demonstration output includes the two dimensionless features and numerical threshold reasons, without a clinical quality label. Flat, nonfinite, wrong-length and malformed inputs are unavailable.

Use an authored waveform such as alternating +1/-1 mV values to check the analytical feature values B=0 and H=4. This is a numerical fixture, without a physiological interpretation. Adding a constant or multiplying by a positive gain should preserve both features; coarse quantization may not. Never label that transformation an actual device study.

For the evidence review, identify the repeated underlying windows across six noise levels. Explain why six copies of a clean interval must not become six independent negatives, and why hundreds of windows from one later recording do not provide hundreds of independent subjects. Identify the extra source evidence and expert quality labels needed before considering a real monitoring application.
