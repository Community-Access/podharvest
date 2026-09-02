# Benchmark fixtures

`podharvest benchmark` compares ASR engines on the same audio and scores them against a
reference transcript. This folder holds the fixtures used for the numbers quoted in the
main README.

## What is and is not committed

| File | Committed | Why |
|---|---|---|
| `run_benchmark.py` | yes | The harness. |
| `comparison-report.md` | yes | The generated report from a past run. |
| `ep1-clip.txt` | yes | Reference transcript - a few KB of text, needed to compute WER. |
| `ep*-clip.mp3` | **no** | Audio is gitignored. See below. |

The audio clips are excerpts from [ACB Diabetics in Action](https://acbda.org/podcast), a
podcast produced by the American Council of the Blind. They are third-party content and are
**not redistributed with this repository** - `.gitignore` excludes `bench/*.mp3`.

`ep1-clip.txt` is a short transcript excerpt of the corresponding clip, kept because a WER
score is meaningless without a reference. It is included for research and benchmarking
purposes only.

## Regenerating the clips

To reproduce the benchmark, fetch the feed and cut your own clips:

```bash
podharvest fetch https://acbda.org/podcast --limit 3
ffmpeg -i <downloaded.mp3> -t 300 -c copy bench/ep1-clip.mp3
```

Then run:

```bash
podharvest benchmark bench/ep1-clip.mp3 --reference-dir bench \
    --model faster-whisper:tiny.en --model faster-whisper:small.en
```

Any audio works - the fixtures here are not special, they are just what the quoted figures
were measured against. If you are adding benchmark numbers to the docs, say which clip and
which machine they came from; a real-time factor is meaningless without both.
