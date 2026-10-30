# Test a signal-quality gate on another recording

A rule that rejects noisy ECG windows can also discard usable signal when the recording changes. This study will test that tradeoff on two fixed public benchmark recordings, keeping every noise level and a separate-recording evaluation.

**State: protocol before waveform retrieval.** No result, clinical accuracy, deployment or safety benefit is established. The [protocol](PROTOCOL.md) fixes the source files, calibration, small threshold search, untouched-recording boundary, sensitivity exercise and release checks. This is an offline signal-processing benchmark; it will not diagnose disease or suppress patient alarms.
