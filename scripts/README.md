# Developer and study scripts

Scripts call the installed `savoroute` package. They do not provide separate ranking implementations.

| Script | Purpose |
| --- | --- |
| `run_offline_baselines.py` | Evaluate lexical methods on a fictional packaged benchmark |
| `evaluate_challenge.py` | Compare challenge-query behavior on a fictional relevance fixture |
| `study_pilot.py` | Verify a frozen OSM study, create isolated reviewer packages, audit progress, and summarize an existing analysis |

Examples:

```bash
python scripts/run_offline_baselines.py
python scripts/evaluate_challenge.py --help
python scripts/study_pilot.py --help
python scripts/study_pilot.py preflight --study-dir /path/to/frozen-study
```

`study_pilot.py` does not generate relevance labels or establish reviewer independence. Its reviewer ZIPs and completed study outputs are private artifacts; keep them under `data/generated/` or another access-controlled location. See [Boston pilot execution](../docs/studies/boston-pilot-execution.md).
