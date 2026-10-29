# Hosted cold start serves the landing page first (2026-10-30)

LAB-1548. The hosted app scales to zero, so the first visit after an idle spell starts a
container. Until now the server loaded the bundled 1 GB NER model before it answered
anything, and the platform's Readiness probe waited for the same load: the visitor saw a blank
page for about 30 s on Azure.

Now hosted loads the model in the background (the LAB-1303 path), and the Readiness probe asks
`/readyz?ner=loading`, which admits a replica whose model is still loading. The landing page,
the UI and `/healthz` answer as soon as the process is up. Detecting requests wait for the
model and then fail closed (`503 detector_loading` with `Retry-After`, or
`503 detection_unavailable` if the load failed), so nothing is detected without it or sent
unmasked. Full `/readyz` still waits for the model and stays the deploy smoke gate.

Local cold start, hosted layout, same model, three runs each *(ticket comment, LAB-1548)*:
first byte of `/` went from 8.4–9.7 s to 0.8–1.3 s; the model is ready (full `/readyz`) after
4.7–6.4 s. On Azure the probe periods (10 s) add to the first figure. Cost: none; scale to
zero stays on.
