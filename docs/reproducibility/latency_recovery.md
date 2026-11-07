# Latency output recovery and validation

The confirmatory latency benchmark completed measurements, scenario summaries, timer-overhead sampling, and paired inference before manifest creation failed. The frozen implementation then attempted to read a legacy top-level `source_tree_sha256` key from Freeze v2. Freeze v2 has no such top-level key: it records the research-source manifest hash, aggregate research-source hash, dependency-lock hash, and protocol version. Its nested Freeze v1 source hash is historical evidence and was not substituted.

The failure occurred while constructing `benchmark_manifest.json`, after the four measured outputs had been written. The benchmark was **not rerun**; no latency measurement or paired inference was recomputed. `confirmatory/recover_latency_manifest.py` produced `benchmark_manifest_recovered.json` from the existing outputs and Freeze v2 provenance. The original benchmark timestamp was not persisted and is recorded as unavailable rather than inferred from file modification times.

| Preserved output | Structural validation | SHA-256 |
|---|---|---|
| `raw_repetitions.csv` | 60,000 rows: 150 scenarios × 200 repetitions × 2 methods, forming 30,000 complete randomized pairs; 100 pairs in each method order per scenario | `6e557d4ec289a8debf044daac3dd1bf541229f4c01b597efea42e54d2c86cfa9` |
| `scenario_summary.csv` | 150 unique frozen scenario IDs, each present once, with 200 repetitions per method | `5ff058366ea929249a875a13eadd3cbd5dfbd4db4612bc8f2529a838852cbfd4` |
| `timer_overhead.csv` | 10,000 nonnegative samples | `38d77fe7a3972fed31b96169d35d68bd885e3b9a9d69fc4d71b9befad0a52ef7` |
| `paired_inference.json` | Valid JSON; 100,000 permutations, 10,000 bootstrap replicates, seed 20261018 | `6c8c27e67e782b70925c1920c6ec7a30c6af4e9a7392b12007665ab7d9e0062c` |

CSV headers and final newline-terminated records were checked; no malformed or partial records, missing repetitions, duplicate scenario IDs where uniqueness was expected, or incomplete pairs were found. The four output hashes matched before and after manifest recovery. The recovered manifest SHA-256 is `509911021f2c030910d8d2778a95337c65ea18a0d58810692611e9a2258dcd21`.

The measurements are in-process authorization-call timings. They exclude full agent/tool workflows and human approval time. See `confirmatory/results/latency/paired_inference.json` for the preserved inference, and `docs/reproducibility/provenance.md` for Freeze v2.
