<!-- Owner: Jana -->
# Model Card — concierge_classifier_ml_v1

Classical-ML candidate for the Concierge 5-class intent classifier bake-off.
ML side of the ML / DL / LLM three-way comparison.

## Identity
- **Name**: concierge_classifier_ml_v1
- **Type**: TF-IDF (word 1–2 grams) + Logistic Regression
- **Cleaning version**: strict
- **Random seed**: 42

## Class index map (ONNX output ordering)
| index | class |
|-------|-------|
| 0 | `ACCOUNT_OPS` |
| 1 | `FAQ` |
| 2 | `HARD_QUESTION` |
| 3 | `SPAM` |
| 4 | `UNKNOWN` |

## Hyperparameters (locked)
- **Vectorizer**: `TfidfVectorizer(analyzer='word', ngram_range=(1,2), sublinear_tf=True, norm='l2', stop_words=None, lowercase=True, min_df=2, max_df=0.95)`
- **Classifier**: `LogisticRegression(C=1.0, class_weight=None, max_iter=2000, random_state=42)`
- **Confidence threshold**: `0.30` — locked by val sweep ∈ [0.10, 0.50] step 0.05, tie-break = highest threshold maintaining max macro-F1

## Training data
See `modelserver/training/data/data_card.md` for full provenance.
- **Splits**: 2408 train / 512 val / 513 test, stratified, seed=42
- **Cleaning**: `strict` (lowercase + strip URLs/digits/currency/symbols)
- **Final fit**: train+val combined (2920 rows) after winner selection on val

## Evaluation
- **Selection metric**: macro-F1 with UNKNOWN as a real class
- **Val macro-F1** (train-only fit, threshold applied): **0.9626**
- **Test macro-F1** (train+val fit, threshold applied): **0.9848**

### Per-class test F1 (n=513)
| class | precision | recall | f1 | support |
|-------|-----------|--------|------|---------|
| ACCOUNT_OPS | 0.9808 | 0.9714 | 0.9761 | 105 |
| FAQ | 0.9904 | 0.9904 | 0.9904 | 104 |
| HARD_QUESTION | 1.0000 | 0.9906 | 0.9953 | 106 |
| SPAM | 1.0000 | 1.0000 | 1.0000 | 93 |
| UNKNOWN | 0.9533 | 0.9714 | 0.9623 | 105 |

### Confusion matrix (rows = true, cols = pred)
```
               ACCOUNT_OPS  FAQ  HARD_QUESTION  SPAM  UNKNOWN
ACCOUNT_OPS            102    0              0     0        3
FAQ                      0  103              0     0        1
HARD_QUESTION            0    0            105     0        1
SPAM                     0    0              0    93        0
UNKNOWN                  2    1              0     0      102
```
8 errors / 513. All 8 involve UNKNOWN: 5 real-class samples pushed to UNKNOWN
by the threshold (3 ACCOUNT_OPS, 1 FAQ, 1 HARD_QUESTION), and 3 UNKNOWN samples
misclassified as a real class (2 ACCOUNT_OPS, 1 FAQ).

## Known limitations (READ BEFORE PRODUCTION)
1. **HARD_QUESTION ≈ 1.0 is partly artifactual.** Bitext's HARD_QUESTION queries
   carry a source-style signature no other class shares. Inflates macro-F1 by
   ~1 point. On val it scored a perfect 1.0; test shows it is very easy but not
   magic (one sample lost to UNKNOWN).
2. **SPAM = 1.000 on test is the length shortcut.** SPAM mean char length is
   2.71× non-SPAM after strict cleaning. Will NOT hold on adversarial inputs
   (short SPAM, long non-SPAM). Do not treat this as a production estimate.
3. **No adversarial hold-out evaluated.** All numbers above are in-distribution
   upper bounds. A hand-written adversarial set (≥10–15 per class) MUST be
   evaluated before trusting this in production. Currently a roadmap gap.
4. **Source-class coupling.** Every class is 100% from one source dataset (see
   data_card.md). The bake-off measures relative shortcut-overfit between
   ML/DL/LLM methods, not absolute production performance.

## REQUIRED inference preprocessing
The ONNX model was trained on **strict-cleaned** text. The FastAPI service MUST
apply the same strict cleaning function from `prepare_data.ipynb` to user input
before invoking ONNX. Steps: lowercase; strip URLs; strip digit sequences; strip
currency symbols (£$€¥); strip other symbols (#%@&*+). Skipping this causes
silent misbehavior — the vectorizer sees OOV tokens it never trained on.

## Inference postprocessing
```python
proba  = onnx_session.run(None, {"text_input": [cleaned_text]})[1]  # output index 1
max_p  = proba.max(axis=1)
argmax = proba.argmax(axis=1)
label  = "UNKNOWN" if max_p[0] < 0.30 else class_names[argmax[0]]
return label, float(max_p[0])   # label + confidence for agent routing
```

## ONNX numerical fidelity
Export via skl2onnx, target_opset=15, zipmap=False. Probability values can drift
from sklearn `predict_proba` by up to ~0.12 absolute on a few long-text samples
(median 0.0000, p90 ≤ 0.03). This is floating-point accumulation order in the
sparse TF-IDF × weight product, not a math bug. Argmax and threshold-applied
predictions are 100% identical between sklearn and ONNX on the 513-sample test
set. The agent's routing should treat the confidence score as approximate at the
±0.05 level; predictions with max_proba in [0.25, 0.35] are an uncertainty band
around the 0.30 threshold.

## Artifacts (SHA-256)
Fill the full values from your actual local files: run `sha256sum *` in the
artifact directory. The 16-char prefixes below are from the Colab session that
produced the files — if your local `sha256sum` does not match these prefixes,
the download is corrupted.

| file | sha256 |
|------|--------|
| `classifier.onnx` | `56ba47ae3de32da8…` → FILL FULL VALUE |
| `classifier_metadata.json` | `fdf162861e502b5a…` → FILL FULL VALUE |
| `SHA256SUMS` | `f7a3d06216528088…` → FILL FULL VALUE |

## Bake-off context
ML candidate. The other two are produced in separate notebooks:
- `train_dl.ipynb` — small encoder fine-tune → ONNX
- `train_llm.ipynb` — zero-shot prompted
`evaluate_models.py` runs the cross-candidate comparison on test + adversarial
hold-out.

## Why strict over raw
strict_word and raw_word tied at val macro-F1 = 0.9626. Shipped strict because:
same in-distribution performance; cleaner vocabulary (raw's top features were
phone numbers and currency, strict's were content phrases); raw's shortcut
features are expected to fail harder on adversarial inputs. Defensive choice,
not a measured improvement on val.
