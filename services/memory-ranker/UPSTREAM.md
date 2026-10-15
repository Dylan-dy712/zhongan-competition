# Vendored Semantix kernel subset

Source: https://github.com/Gnosil/semantix

Commit: `5e546dcb69b7545e9fba9f95f9464c0ddd6f9cff`

License: MIT; retained at `third_party/semantix/LICENSE`.

The BM25 implementation, CJK tokenizer, slice value types, fingerprint types and
BM25 tests are copied without behavioral changes. SHA-256 checksums of normalized
LF content are recorded in `upstream-sha256.json` and verified before building.
The two local go.mod files select this offline subset; no upstream harness,
automatic extraction, gateway, user-directory discovery or result reuse is run.

This is lexical BM25 retrieval, not model embeddings. The application authenticates
and filters the corpus before invoking this stateless process. Rank scores do not
prove authorization, medical truth or confidence calibrated for healthcare.
