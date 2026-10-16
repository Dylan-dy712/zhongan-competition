# Judge sample report latency

The current 13-page, four-PDF reviewed demo library previously repeated about
65 seconds of OCR for each new case. Existing checkpoints are deliberately
document-scoped and therefore did not help a newly uploaded copy. One recent
follow-up explanation also timed out after about 90 seconds before an 8-second
retry succeeded.

The Worker can now read a separately prepared, private recognition artifact only
for an active-consent case owned by a judge slot and bound to the reviewed sample
ID, immutable version, manifest notice, original bytes and parser/OCR fingerprint.
Ordinary uploads cannot use this shared artifact, even with identical bytes.
The artifact contains only parsed pages, blocks and recognition provenance;
evidence IDs, extraction, report generation and source review remain per case.
Low-confidence blocks and their warnings remain intact and excluded from facts.

Prepare the current reviewed library before a demonstration or after changing its
bytes, version or OCR/parser configuration:

```bash
cd /home/ubuntu/zhongan-app
.venv/bin/python -m scripts.warm_judge_recognition --from-worker-environment
```

The command reads the local Worker's OCR configuration without printing secrets.
It creates no accounts, cases, analysis tasks or reports. It writes private,
checksummed files under `/home/ubuntu/zhongan-data/judge-recognition`; subsequent
runs reuse the matching pages. Missing, changed or corrupt artifacts fall back to
the actual parser/OCR. User-uploaded inputs are still hash-verified and authorized.

Fidelity review now retries only timeout/connection failures once, sharing a
45-second request budget with a maximum 25-second read wait per attempt. Invalid
or rejected reviews do not count as approval; factual checks remain mandatory.

Validation includes real PostgreSQL judge/ordinary owner isolation, fresh evidence
IDs per upload, cache corruption and version invalidation, preservation of OCR
warnings and excluded blocks, and bounded review transport failure handling.
End-to-end timing must include report generation and final patient explanation;
OCR prewarming is reported separately and does not guarantee an external model's
latency under all load conditions.
