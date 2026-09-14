# Evaluation CLI help dependency

Classification: evaluation CLI, no online runtime/provider change. Full suite observed --help timeout at 15 seconds; standalone rerun passed. Source shows run_eval_suite imports run_retrieval_eval just for DEFAULT_DATASET_PATH, transitively loading app.config and the retrieval evaluation stack. Deterministic RED confirms app.config imported during --help.

Contract: read the same canonical current_evaluation.json dataset_path directly using the standard library. Do not alter dataset selection, provider defaults or timeout. Review default-path parity and help execution; focused CLI tests then final full suite. Commit separately from source metadata runtime changes.
