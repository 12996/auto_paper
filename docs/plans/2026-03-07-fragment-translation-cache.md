# Fragment Translation Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add fragment-level translation cache reuse for the same paper, same model, and same prompts so reruns skip already translated fragments.

**Architecture:** Introduce a paper-scoped cache under `arxiv_cache/<arxiv_id>/translation/` keyed by fragment source text plus prompt/model inputs. `main.translate_arxiv_paper()` will resolve cache hits before calling `translate_batch()`, translate only misses, then persist successful fragment results immediately. Existing `merge_result.pkl` remains a compile-recovery artifact only.

**Tech Stack:** Python, Flask worker pipeline, local filesystem cache, `hashlib`, existing `llm_client.translate_batch()`, existing LaTeX merge flow

---

### Task 1: Document Current Behavior and Lock Acceptance Criteria

**Files:**
- Modify: `docs/plans/2026-03-07-fragment-translation-cache.md`
- Check: `main.py`
- Check: `llm_client/llm_client.py`
- Check: `worker/translate_job.py`

**Step 1: Record the exact current cache gap**

Write down these facts in the task notes:

- `use_cache=True` currently affects paper download reuse, not fragment translation reuse.
- `merge_result.pkl` is used for LaTeX compile repair, not cache lookup before LLM calls.
- `translate_batch()` currently sends every fragment to `translate_with_retry()` with no cache check.

**Step 2: Define acceptance criteria**

Acceptance criteria:

- First run of a paper with unchanged model and prompts produces cache entries for each successful fragment.
- Second run of the same paper with unchanged model and prompts skips cached fragments and only translates misses.
- Changing `model` or `more_requirement` causes fragment cache misses without affecting unrelated papers.
- Compile failure after translation does not delete fragment cache.

**Step 3: Verify the criteria against current code**

Run: `rg -n "translate_batch|merge_result.pkl|use_cache" main.py llm_client/llm_client.py worker/translate_job.py`

Expected: only download-level cache and compile-repair persistence exist.

**Step 4: Commit**

Do not commit yet. This repository is already dirty. Leave commits to the user or a later explicit request.


### Task 2: Add Cache Utility Layer

**Files:**
- Create: `translation_cache.py`
- Test: `tests/test_translation_cache.py`

**Step 1: Write the failing tests**

Add tests covering:

```python
def test_build_fragment_cache_key_changes_when_model_changes():
    key1 = build_fragment_cache_key(
        fragment_text="abc",
        system_prompt="sys",
        user_prompt="user",
        model="m1",
    )
    key2 = build_fragment_cache_key(
        fragment_text="abc",
        system_prompt="sys",
        user_prompt="user",
        model="m2",
    )
    assert key1 != key2


def test_fragment_cache_round_trip(tmp_path):
    cache = PaperTranslationCache(tmp_path)
    payload = {
        "fragment_text": "frag",
        "system_prompt": "sys",
        "user_prompt": "user",
        "model": "m",
        "result": "结果",
    }
    cache.write_entry("key", payload)
    loaded = cache.read_entry("key")
    assert loaded["result"] == "结果"


def test_fragment_cache_returns_none_for_missing_entry(tmp_path):
    cache = PaperTranslationCache(tmp_path)
    assert cache.read_entry("missing") is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_translation_cache.py -v`

Expected: FAIL because `translation_cache.py` and symbols do not exist.

**Step 3: Write minimal implementation**

Create a small utility module with:

- `build_fragment_cache_key(fragment_text, system_prompt, user_prompt, model) -> str`
- `PaperTranslationCache(cache_dir: Path | str)`
- `PaperTranslationCache.read_entry(key) -> dict | None`
- `PaperTranslationCache.write_entry(key, payload) -> Path`
- `PaperTranslationCache.cache_path(key) -> Path`

Implementation notes:

- Use `sha256` over exact raw strings.
- Store one JSON file per fragment key.
- Use ASCII-safe filenames: `<sha256>.json`.
- Keep payload metadata explicit so future debugging can inspect prompt/model mismatches.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_translation_cache.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit yet.


### Task 3: Resolve Cached and Uncached Fragments Before LLM Calls

**Files:**
- Modify: `main.py`
- Test: `tests/test_main_fragment_cache.py`

**Step 1: Write the failing tests**

Add a focused test around the orchestration logic:

```python
def test_translate_only_submits_uncached_fragments(monkeypatch, tmp_path):
    submitted = {}

    def fake_translate_batch(texts, system_prompts, user_prompts, llm_client, max_workers, callback, should_abort):
        submitted["texts"] = texts
        submitted["system_prompts"] = system_prompts
        submitted["user_prompts"] = user_prompts
        return ["new-result"]

    # Arrange one cached fragment and one miss, then assert only the miss is submitted.
```

Also cover:

```python
def test_cached_fragments_preserve_original_result_order(...):
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_fragment_cache.py -v`

Expected: FAIL because `main.py` always submits all fragments.

**Step 3: Write minimal implementation**

Refactor the fragment translation section in `main.translate_arxiv_paper()`:

- Build cache directory as `Path(cache_dir) / arxiv_id / "translation"`.
- Compute cache key for each fragment from:
  - fragment text
  - corresponding `system_prompt`
  - corresponding `user_prompt`
  - `model`
- Pre-fill a `results` list with cache hits.
- Build compact arrays for misses only.
- If there are no misses, skip `translate_batch()` entirely.
- After translation, merge miss results back into original order.

Implementation guardrails:

- Do not include `arxiv_id` inside the hash; directory scoping already isolates papers.
- Keep `translate_batch()` call signature unchanged.
- Log hit and miss counts clearly.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_fragment_cache.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit yet.


### Task 4: Persist Successful Fragment Results During Translation

**Files:**
- Modify: `main.py`
- Possibly Modify: `llm_client/llm_client.py`
- Test: `tests/test_main_fragment_cache.py`

**Step 1: Write the failing test**

Add tests for persistence:

```python
def test_successful_miss_is_written_to_cache(monkeypatch, tmp_path):
    ...


def test_cached_result_survives_compile_failure(monkeypatch, tmp_path):
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_fragment_cache.py -v`

Expected: FAIL because misses are not persisted as fragment cache entries.

**Step 3: Write minimal implementation**

Persist fragment results immediately after a successful translation response is mapped back:

- For each miss result, write a cache JSON file with:
  - `key`
  - `model`
  - `system_prompt`
  - `user_prompt`
  - `fragment_text`
  - `result`
  - `created_at`
- Only cache successful results.
- Do not cache fallback behavior when `translate_batch()` returns original source text for failures.

Decision point:

- Prefer handling persistence in `main.py`, where cache scope and `arxiv_id` are already available.
- Avoid pushing paper-specific filesystem behavior into `llm_client.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_fragment_cache.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit yet.


### Task 5: Make Cache Layout Observable and Consistent With Existing Paths

**Files:**
- Modify: `worker/translate_job.py`
- Modify: `arxiv_translator/arxiv_downloader/downloader.py`
- Test: `tests/test_translation_cache.py`

**Step 1: Write the failing tests**

Add tests that pin the expected paper cache directory:

```python
def test_paper_translation_cache_uses_arxiv_translation_directory(tmp_path):
    cache_dir = tmp_path / "arxiv_cache" / "1234.56789" / "translation"
    cache = PaperTranslationCache(cache_dir)
    assert cache.cache_path("abc").parent == cache_dir
```

If updating downloader behavior:

```python
def test_download_cache_check_does_not_assume_only_translate_zh_pdf(...):
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_translation_cache.py -v`

Expected: FAIL if current assumptions conflict with the new cache layout.

**Step 3: Write minimal implementation**

Make the layout explicit:

- Ensure `worker/translate_job.py` still passes the same `cache_dir`, so fragment cache lives under `arxiv_cache/<id>/translation/`.
- Review `downloader._check_cache()` and decide whether it should:
  - remain PDF-only, or
  - be updated to avoid implying that `translation/` contains only `translate_zh.pdf`

Recommended minimal behavior:

- Keep downloader PDF check backward-compatible.
- Do not make downloader depend on fragment cache files.
- Add a comment explaining that `translation/` now stores both final outputs and fragment cache artifacts.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_translation_cache.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit yet.


### Task 6: Add Logging and Verification for Real Rerun Behavior

**Files:**
- Modify: `main.py`
- Test: `tests/test_main_fragment_cache.py`

**Step 1: Write the failing test**

Add assertions for observability:

```python
def test_logs_fragment_cache_hit_miss_counts(caplog, ...):
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_fragment_cache.py -v`

Expected: FAIL because cache hit/miss counts are not logged.

**Step 3: Write minimal implementation**

Add log lines around cache resolution:

- `fragment cache: 68 hit, 3 miss`
- `fragment cache: all fragments hit, skipping LLM batch`
- `fragment cache: wrote 3 new entries`

Keep logs concise and deterministic.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_fragment_cache.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit yet.


### Task 7: End-to-End Verification

**Files:**
- Check: `main.py`
- Check: `translation_cache.py`
- Check: `worker/translate_job.py`
- Check: `tests/test_translation_cache.py`
- Check: `tests/test_main_fragment_cache.py`

**Step 1: Run targeted tests**

Run: `pytest tests/test_translation_cache.py tests/test_main_fragment_cache.py -v`

Expected: PASS.

**Step 2: Run a same-paper rerun smoke test**

Use one known paper ID in a safe environment where LLM calls are acceptable.

Suggested manual verification:

1. Run translation once and note log line `fragment cache: 0 hit, N miss`
2. Run translation again with identical model and prompts
3. Verify log line becomes `fragment cache: N hit, 0 miss`
4. Verify no per-fragment progress logs appear for cached fragments

**Step 3: Inspect output directories**

Check that:

- `arxiv_cache/<arxiv_id>/translation/*.json` exists
- `output/<arxiv_id>/<paper>.tex` still exists
- `workfolder/merge_result.pkl` still exists and remains separate from fragment cache

**Step 4: Regression check**

Run: `pytest -q`

Expected: no regressions. If the suite is too large or unavailable, document that limitation explicitly.

**Step 5: Commit**

Do not commit yet.
