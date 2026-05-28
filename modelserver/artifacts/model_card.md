<!-- Owner: Jana -->
---
artifact_filename: classifier.onnx
artifact_type: onnx
sha256: 56ba47ae3de32da812edf4a3e3bebdd08414fd8d6a66153eafade9d14aa6e8ea
training_data_revision: TBD
training_script_revision: TBD
intended_task: 5-class intent classification (SPAM/FAQ/ACCOUNT_OPS/HARD_QUESTION/UNKNOWN)
unknown_threshold: 0.25
hosted_model_identifier:
notes: ml_v1 — TF-IDF + LogisticRegression, test macro-F1 0.9848, exported to ONNX via skl2onnx
---
