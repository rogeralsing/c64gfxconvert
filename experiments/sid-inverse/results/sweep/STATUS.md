# Initial cached-reset experiment

All 27 planned runs completed: 16,200 candidate evaluations, with no process failures.

These are superseded exploratory results from the renderer snapshot in `source-snapshot/`. Later repeated two-voice evaluations exposed greater variability than expected. Investigation found that the native SID filter's reset does not clear every analog state variable. Therefore these results must not be used as a final equal-condition optimizer comparison because the completed reset/predecessor diagnosis confirmed hidden-state leakage.

Preserve these receipts as evidence of the experiment and the discovered limitation. Do not silently mix them with results from a corrected renderer.
