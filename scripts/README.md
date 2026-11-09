# Scripts

`run_offline_baselines.py` evaluates both lexical rankers against the packaged synthetic benchmark. It imports the same evaluation functions as the CLI and does not train or download models.

```bash
python scripts/run_offline_baselines.py
python scripts/run_offline_baselines.py --at-k 3 --output outputs/phase0-metrics.json
```

The output is JSON. `outputs/` is excluded from version control. See [evaluation](../docs/evaluation.md) for metric definitions and limitations.
