# Final Dataset Validation Report

Scenario count: **150**

All labels were assigned by first-match evaluation of the qualitative policy matrix. No authorization algorithm was run.

## Class counts

| Value | Count |
| --- | ---: |
| ALLOW | 27 |
| DENY | 65 |
| ESCALATE | 58 |

## Role counts

| Value | Count |
| --- | ---: |
| ADMINISTRATOR | 50 |
| ANALYST | 50 |
| MANAGER | 50 |

## Tool counts

| Value | Count |
| --- | ---: |
| DELETE_RECORD | 30 |
| EXPORT_DATA | 30 |
| READ_RECORD | 30 |
| SEND_MESSAGE | 30 |
| UPDATE_RECORD | 30 |

## Sensitivity counts

| Value | Count |
| --- | ---: |
| CONFIDENTIAL | 49 |
| INTERNAL | 50 |
| RESTRICTED | 51 |

## Destination counts

| Value | Count |
| --- | ---: |
| CONTROLLED_EXTERNAL | 49 |
| EXTERNAL | 51 |
| INTERNAL | 50 |

## Context counts

| Value | Count |
| --- | ---: |
| ANOMALOUS | 36 |
| HIGH_VOLUME | 36 |
| NORMAL | 42 |
| UNUSUAL | 36 |

## Cross-tab summaries

### Ground Truth By Role

| Ground truth | ADMINISTRATOR | ANALYST | MANAGER |
| --- | ---: | ---: | ---: |
| ALLOW | 12 | 5 | 10 |
| ESCALATE | 19 | 18 | 21 |
| DENY | 19 | 27 | 19 |

### Ground Truth By Tool

| Ground truth | DELETE_RECORD | EXPORT_DATA | READ_RECORD | SEND_MESSAGE | UPDATE_RECORD |
| --- | ---: | ---: | ---: | ---: | ---: |
| ALLOW | 0 | 7 | 8 | 9 | 3 |
| ESCALATE | 7 | 10 | 14 | 12 | 15 |
| DENY | 23 | 13 | 8 | 9 | 12 |

### Ground Truth By Sensitivity

| Ground truth | CONFIDENTIAL | INTERNAL | RESTRICTED |
| --- | ---: | ---: | ---: |
| ALLOW | 8 | 16 | 3 |
| ESCALATE | 23 | 18 | 17 |
| DENY | 18 | 16 | 31 |

### Ground Truth By Destination

| Ground truth | CONTROLLED_EXTERNAL | EXTERNAL | INTERNAL |
| --- | ---: | ---: | ---: |
| ALLOW | 7 | 0 | 20 |
| ESCALATE | 23 | 18 | 17 |
| DENY | 19 | 33 | 13 |

### Ground Truth By Context Risk

| Ground truth | ANOMALOUS | HIGH_VOLUME | NORMAL | UNUSUAL |
| --- | ---: | ---: | ---: | ---: |
| ALLOW | 0 | 0 | 27 | 0 |
| ESCALATE | 9 | 22 | 3 | 24 |
| DENY | 27 | 14 | 12 | 12 |
