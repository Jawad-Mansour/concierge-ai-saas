# Concierge Classifier — Data Card

**Dataset:** Concierge intent classifier training data v1.0
**Owner:** Jana (modelserver / classifier slice)
**Generated:** 2026-05-27
**Notebook:** `Week8Day1_cleaning.ipynb`

---

## Overview

3,442 short English text messages labeled with one of 5 Concierge intent classes. Derived from three public datasets, merged and relabeled into the Concierge taxonomy. Two cleaning variants are shipped: `raw` for production-realistic evaluation and `strict` for fair ML/DL/LLM bake-off comparison.

---

## Source Provenance

| Source dataset | Rows | Class(es) it feeds |
|---|---|---|
| Bitext Customer Support Intent Dataset | 2,100 | FAQ / ACCOUNT_OPS / HARD_QUESTION |
| CLINC OOS Dataset (train + validation + test subsets) | 700 | UNKNOWN |
| UCI SMS Spam Collection | 642 | SPAM |

---

## Class Definitions

| Label | Count | Definition |
|---|---|---|
| FAQ | 691 | Informational / how-to questions about products and services |
| ACCOUNT_OPS | 700 | Transactional operations on an existing account: orders, invoices, refunds, payments, subscriptions |
| HARD_QUESTION | 709 | Explicit user request to escalate to a human agent |
| UNKNOWN | 700 | Out-of-scope / off-topic messages the bot cannot handle |
| SPAM | 642 | Unsolicited promotional or scam content |

**Class imbalance:** ratio max/min = 1.10 (HARD_QUESTION / SPAM). Mild. No resampling or class weighting applied.

---

## Schema (all 6 CSV files)

| Column | Type | Description |
|---|---|---|
| `row_id` | int | Stable ID matching the original merged dataset row. The same `row_id` identifies the same source row in both `raw` and `strict` versions. |
| `text` | str | Cleaned message text |
| `label` | str | One of {SPAM, FAQ, ACCOUNT_OPS, HARD_QUESTION, UNKNOWN} |
| `source` | str | Original dataset name (for traceability) |
| `original_label` | str | Original label / intent string from the source dataset |

---

## Splits

- **70 / 15 / 15** split (train / val / test)
- Stratified by `label`, `random_state = 42`
- **Aligned across cleaning versions:** identical `row_id` sets in each split across `raw` and `strict`. This enables apples-to-apples bake-off comparison — every model is evaluated on the same row identities regardless of cleaning version.

| Split | Rows |
|---|---|
| Train | 2,408 |
| Val | 512 |
| Test | 513 |
| **Total** | **3,433** |

Total < 3,442 because 9 rows were dropped from val/test after splitting (see Known Limitations §4).

---

## Cleaning Pipelines

Two variants. Models in the bake-off train on both and report results separately.

### `raw` — production-realistic

Removes only synthetic / encoding artifacts that would never appear in real customer input.

1. Strip `{{...}}` placeholders (Bitext synthetic template tokens)
2. Fix `Â£`-style mojibake (UTF-8 bytes mis-decoded as latin-1)
3. Strip control characters (`\x00`–`\x1f`, `\x7f`)
4. Collapse whitespace, trim

### `strict` — bake-off-fair

All of `raw`, plus aggressive shortcut neutralization to force the model to learn intent semantics rather than source style.

5. Strip URLs (`https?://...`, `www....`)
6. Strip all digit runs
7. Strip currency / marker symbols: `£ $ € ¥ # % @ & * +`
8. Lowercase everything
9. Re-normalize whitespace

### Deliberately NOT done in either version

- No stopword removal (modern models handle this; stopwords carry signal in short text)
- No stemming or lemmatization
- No spelling correction (typos like "acoumt", "uhelp" are realistic user behavior)

---

## Known Limitations

### 1. Severe source–class coupling (the headline confound)

Every class is sourced from exactly one dataset:

| Class | Source |
|---|---|
| SPAM | 100% UCI SMS |
| UNKNOWN | 100% CLINC OOS |
| FAQ / ACCOUNT_OPS / HARD_QUESTION | 100% Bitext |

A sufficiently expressive model trained on this data will learn source-style features (writing register, character composition, length distribution) instead of true intent semantics. **In-distribution test metrics overestimate real-world performance.**

The `strict` pipeline mitigates lexical source markers (caps, digits, currency symbols) but does **not** eliminate the residual **length confound**: SPAM remains ~2.6× longer than other classes even after strict cleaning (mean 116 chars vs ~43 chars for everything else). A length-based rule alone would still classify SPAM with high accuracy.

**Recommended mitigation:** build a small adversarial hold-out set (10–15 hand-written examples per class in styles that don't match the source dataset) and report metrics on it separately from in-distribution test metrics.

### 2. FEEDBACK rows in FAQ (~121 rows)

Bitext's FEEDBACK category (customer complaints and reviews) was bundled into FAQ during merging. Complaints and reviews are not strictly "questions" — they are sentiment / feedback. Kept as FAQ because the Concierge spec does not define a FEEDBACK class and recategorizing would cascade into other owners' work. Acknowledged data-design choice.

### 3. `sales_or_contact → ACCOUNT_OPS` relabel

The original merged label `sales_or_contact` was found via `original_label` inspection to contain ~70% transactional / billing intents (invoices, refunds, payments, order management) and ~30% sales-leaning intents (newsletter signup, place order, check payment methods).

Calling this class **CONTACT_LEAD** (per the initial spec) would route billing questions to the sales team in production. Renamed to **ACCOUNT_OPS** during EDA. `classifier_SPEC.md` and `SECURITY.md` updated to reflect the rename. Downstream owners (agent/RAG, tenancy, widget) informed.

### 4. 9-row deduplication after splitting

Strict cleaning collapsed 9 near-duplicate SMS-spam template variants (different phone numbers / expiry codes, otherwise identical boilerplate) into exact duplicates that crossed train↔val and train↔test boundaries. Without intervention, this would have inflated strict test accuracy.

Resolved by dropping the val/test instances (training set kept). The same row drops were applied to `raw` for Path C alignment, even though `raw` had zero leakage — this preserves the apples-to-apples guarantee.

- 5 rows dropped from val
- 4 rows dropped from test
- Final post-cleaning sizes: 2,408 train / 512 val / 513 test

### 5. CLINC OOS original splits are ignored

The `source` column distinguishes `CLINC OOS Dataset (train)` / `(test)` / `(validation)` — these are the original CLINC split assignments. They are **not respected** in our split; all CLINC rows are pooled and re-split via our own stratified 70/15/15. This is intentional: we want our own seeded split for reproducibility, not someone else's.

### 6. Single language (English) and narrow spam genre

All text is English. Spam content is exclusively UK-style SMS spam (phone numbers, `£` currency, SMS shorthand). Models trained on this data are not directly applicable to other languages or to non-SMS spam formats (e.g. email spam, comment spam, voice transcripts).

---

## Files

All paths relative to `modelserver/data/cleaned/`.

| File | Rows | SHA-256 |
|---|---|---|
| `clean_raw_train.csv` | 2,408 | `9c0526f42448453ce5c52e91d3f889114d713ca0ff9e26871b50f86954628460` |
| `clean_raw_val.csv` | 512 | `033b8fd1436a6c6c5d5fe2ac0c6046850c3ee25b9ae46c523b830ad883087410` |
| `clean_raw_test.csv` | 513 | `d69fb075f4f6e264ad701c17773d946481e0c4f0c4390e7121008a48430e10b2` |
| `clean_strict_train.csv` | 2,408 | `fcb2c86d4bd897d88a653432085baf22914db44973152be0c18c709b213cffcc` |
| `clean_strict_val.csv` | 512 | `4678aed0ec6354e268d0819be828773cdcd583d69068b01f8fe0df7f8602a991` |
| `clean_strict_test.csv` | 513 | `9404439fb59a5fbc700a72d8981d8e95bd06a5620fe4ff7e98d7635f21f9d283` |
| `cleaning_metadata.json` | — | `21ab59f6cab1a33669469a2fc10367a4d48d668b1fc3c1eaf983ec7039a18b27` |

**Source merged file:** `raw_merged.csv`, SHA-256 `4fb092710fa9f22a230ed30233624ccb65abf48ff8c27c0507ee64e2ec4d431c`.

---

## Intended Use

- **Bake-off (use `strict`):** ML / DL / LLM intent classification comparison. Each model evaluated on the strict test set + adversarial hold-out.
- **Production-readiness simulation (use `raw`):** estimate behavior on a more realistic input distribution. Not a substitute for real user telemetry.

---

## Out of Scope

- Not for training a standalone spam filter (spam content is single-source, single-genre UK SMS).
- Not for generative tasks — text is short, label-driven, and templated in parts.
- Not for direct production deployment without a separate adversarial evaluation set.
- Not for languages other than English.

---

## Reproducibility

- **Notebook:** `Week8Day1_cleaning.ipynb`
- **Random seed:** `42` (applied to `random`, `numpy.random`, `sklearn.model_selection.train_test_split`)
- All cleaning operations are deterministic functions of input bytes. Given the same source CSV, the pipeline produces byte-identical outputs.
- Machine-readable record of pipeline steps + file hashes: `cleaning_metadata.json`.

---

## Maintenance

| Action | Trigger | Owner |
|---|---|---|
| Re-run cleaning pipeline | Source dataset updated or pipeline changed | Jana |
| Update file hashes in this card | After any re-run | Jana |
| Bump version (v1.1+) | Material change to classes, splits, or cleaning logic | Jana |

---

## Changelog

- **v1.0** — 2026-05-27 — Initial cleaned dataset. 5 classes. Raw + strict variants. 70/15/15 stratified split. 9 leak rows removed post-split.
