"""Transcript accuracy scoring: Word Error Rate (WER) and related metrics.

Standard ASR evaluation metric: WER = (substitutions + deletions + insertions)
/ (words in the reference), computed via word-level Levenshtein alignment.
Lower is better; 0.0 is a perfect match. Used by `podharvest.benchmark` to
compare engines/models against a human-verified reference transcript, not
just timing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_words(text: str) -> list[str]:
    """Lowercase, strip punctuation, collapse whitespace - the standard WER
    normalization so `"Hello, world!"` and `"hello world"` match."""
    text = text.lower()
    text = re.sub(r"[^\w\s']", " ", text)
    return text.split()


@dataclass
class WerResult:
    reference_words: int
    substitutions: int
    deletions: int
    insertions: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def wer(self) -> float:
        return round(self.errors / self.reference_words, 4) if self.reference_words else 0.0

    @property
    def accuracy(self) -> float:
        return round(max(0.0, 1.0 - self.wer), 4)


def word_error_rate(reference: str, hypothesis: str) -> WerResult:
    """Classic DP word-alignment WER (same algorithm used by sclite/jiwer)."""
    ref = normalize_words(reference)
    hyp = normalize_words(hypothesis)
    n, m = len(ref), len(hyp)

    # dp[i][j] = edit distance between ref[:i] and hyp[:j]
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    # Backtrack to classify each edit as a substitution, deletion or insertion.
    i, j = n, m
    subs = dels = ins = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            subs += 1
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1

    return WerResult(reference_words=n, substitutions=subs, deletions=dels, insertions=ins)
