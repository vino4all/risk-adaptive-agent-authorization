# Freeze and provenance

The operational reproducibility record is Freeze v2 (`confirmatory/freeze_manifest_v2.json`), created on 2026-09-25 before confirmatory authorization or latency outcomes existed. It was created after the first independent reviewer agreement was observed. Reviewer judgments were not used to change scenarios, labels, policy, component mappings, weights, thresholds, comparator rules, statistics, or latency methods. The research-source allowlist contains 19 files; `confirmatory/research_source_manifest_v2.json` records their byte hashes. The dependency lock is `requirements.lock`.

Freeze v1 (`confirmatory/freeze_manifest.json`) is retained as historical evidence. Its repository-wide source hash covered changing documentation, reviewer workflow, and other non-mechanism files, and the original per-file source inventory is unavailable. It is not treated as a verifiable replacement for Freeze v2. Freeze v2 does not claim to reconstruct the historical v1 source tree.

| Provenance artifact | SHA-256 |
|---|---|
| Freeze v2 manifest | `4b23f50d8a0c9562bba7ea536be1da5524e9fc2ead83f848604d1e5a3c50e4e7` |
| Research-source manifest | `60b11f69b2aca12364078f425d746a0bae0adc26e74020a5b557373529bc6c22` |
| Aggregate allowlisted source digest (recorded in Freeze v2) | `7bc9b72187b8a24bee6d5409666cb64ca2ab3464a8591059566988d1a3f808bb` |
| Dependency lock | `961d54767779c96a0fd51aa9c41804170a7945df866f969c4dd43b6a3358a4c1` |
| Blinded outbound sample | `a09644c5ae8137fbde064aaba01c7de6d48c976cc91ab3c80e838143d7735c65` |

Historical private-repository tags were `confirmatory-freeze-v2` at `93b12adff1155893b056be6ba965170cb95ef5bd` and `confirmatory-results-v1` at `425192e5db6a324955a7e54f09dacf61f43d7f55`. They are references to the private history, not tags to copy into a new public repository. The source manifest and preserved output hashes are the appropriate public verification anchors. The reviewer outbound hash is retained here; the old local Git hash transcript and reviewer-transfer hash note are redundant bookkeeping and are excluded.

Verify the existing frozen inputs and allowlisted source without requiring an empty completed-results directory:

```sh
python -c "from confirmatory.provenance import verify_freeze; verify_freeze(require_empty_authorization=False); print('Freeze v2 verified')"
```

The original `python -m confirmatory.runner` performs a pre-execution empty-output check, even without `--execute`. It will refuse a completed results directory. Do not use `--execute` on this published artifact. For an independent authorization replay, use `python -m analysis.public_reproduction ../authorization-replay` with a new empty directory outside the repository. This does not replace primary outputs.
