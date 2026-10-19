# Build validation

Recorded 18 October 2026. These are software checks, not empirical model results.

| Check | Observed result |
| --- | --- |
| Offline unittest suite | 67 tests passed |
| Authorized-route validation | Local completion succeeded in all 60 policy cases |
| Public corpus integrity | 86 derived records; all pinned source and derived hashes verified |
| Three-actor diagnostic demo | 180 completed scripted episodes, no adapter errors |
| External command protocol | 5 completed offline episodes, no adapter errors |
| Real model evaluation | Not run; no paid model calls |

The scripted honest and threshold-blind actors each have threshold-tracking
slope 0. The explicitly programmed threshold-seeking actor has slope 1. These
values are expected construction checks and must not be described as AI findings.

Artifacts from this check are stored locally under the git-ignored `runs/` directory:

- `runs/demo-20261018/summary.md` and `summary.json`;
- one trace file and manifest per scripted actor in that directory;
- `runs/offline-adapter-check.jsonl` and its `.manifest.json`.

The run manifests preserve source/scenario hashes and execution schedules.
Commands for reproducing the checks are in the project README. Runs use fresh
output paths to preserve earlier results.
