# Confirmatory Analysis Method

## Scope and estimand

This is a prospective confirmatory path for the frozen purposive 150-scenario
synthetic benchmark. It does not reclassify the earlier exploratory run as
preregistered and does not support population-level generalization.

The same frozen scenarios are evaluated by the context-aware binary ABAC
comparator and the risk-adaptive mechanism. Authorization decisions are paired
by scenario identifier. The confirmatory decision run does not measure latency;
latency uses the separate microbenchmark protocol below.

## Outcomes

The two primary confirmatory comparisons are:

1. Unsafe Execution Rate (UER): predicted `ALLOW` among true-`DENY` scenarios.
2. Legitimate Direct Completion Rate (LDCR): predicted `ALLOW` among true-`ALLOW`
   scenarios.

For each primary outcome, an exact McNemar test compares the paired binary event
between methods. Raw p-values and Holm-adjusted p-values across the two-test
primary family are reported. The paired effect is risk-adaptive minus
context-aware ABAC.

Over-Escalation Rate (OER) and Correct Escalation Rate (CER) are descriptive
structural outcomes because binary ABAC cannot emit `ESCALATE`. No confirmatory
p-value is assigned to OER or CER. True-`ESCALATE` resolutions are separately
partitioned for both methods.

## Intervals and interpretation

Rate and paired-effect intervals use 10,000 fixed-seed resamples of complete
scenario rows. They are labeled **95% empirical scenario-resampling percentile
intervals**. They describe sensitivity to the empirical composition of this
frozen purposive benchmark; they are not population confidence intervals for
enterprise requests, organizations, or policies.

## Latency microbenchmark

Latency is measured only by `confirmatory.latency_benchmark` and never reused
from exploratory one-shot measurements. The prespecified defaults are 20 full
warm-up rounds, 200 timed repetitions per scenario and method, 10,000 empty
timer-overhead samples, 100,000 paired sign-flip permutations, and 10,000
scenario-cluster bootstrap replicates.

For each scenario, exactly half of repetitions execute ABAC first and half
execute risk-adaptive first. Within-scenario orders and the global pair schedule
are randomized using seed 20261018. Every raw repetition is retained.
`time.perf_counter_ns` measures only `authorize`; timer overhead is measured and
reported but not subtracted. Garbage collection is disabled during overhead and
timed measurements and restored afterward.

Each scenario contributes its median latency for each method. The prespecified
effect is the mean paired difference of those scenario medians (risk-adaptive
minus comparator). Inference uses a two-sided paired sign-flip permutation test
and a scenario-cluster percentile bootstrap interval. No Shapiro-Wilk or other
normality-based test selection is used.

## Reproducibility and stopping

The confirmatory runner verifies every input hash and the locked policy before
running, executes the complete test suite, and refuses to overwrite a nonempty
output directory. Manifests record relative paths, source-tree hash or Git
commit, Python and package versions, OS, CPU, command, UTC timestamp, input and
output hashes, and test outcome. Any freeze mismatch requires a new explicitly
versioned confirmatory freeze; the existing manifest must not be silently
updated after outcomes are inspected.


