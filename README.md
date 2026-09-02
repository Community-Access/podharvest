# podHarvest

**Keep your favourite podcasts. Read them as well as hear them.**

podHarvest downloads a podcast and turns every episode into something you can read, search
and keep: the audio file, a written transcript, a summary, and a tidy folder you own. It runs
on your own computer. No account, no subscription, no sending your listening habits anywhere.

Point it at a podcast. Go make a cup of tea. Come back to a library.

## What you get

Give podHarvest a podcast address and it builds you a folder like this, one entry per episode:

- **The audio**, downloaded and named sensibly instead of `ep_final_FINAL_2.mp3`
- **A transcript** you can read, search, or paste into anything
- **A summary** of what the episode was actually about
- **Chapter markers** with times, so you can jump to the bit you wanted
- **Subtitle files** if you want to follow along while listening
- **The show notes**, saved as a web page, plain text and Markdown

Everything is a normal file in a normal folder. Nothing is locked in an app. If you delete
podHarvest tomorrow, your library stays exactly where it is.

## Getting started

1. Open podHarvest.
2. Paste the podcast's address into the **Feed URL** box. The show's ordinary web page usually
   works, and podHarvest will find the feed itself.
3. Check **Transcribe downloaded audio** if you want transcripts as well as audio.
4. Press **Start**.

That is genuinely it. podHarvest works out what your computer can handle and picks a suitable
transcription model on its own. The first run downloads that model, so it takes a few minutes
longer than every run after it.

Want more detail, including how to install it? See the
[step by step guide for your first run](docs/GETTING_STARTED.md).

## How long will it take?

Transcribing is the slow part, and podHarvest tells you before you commit. Select any model
and the **About this model** box gives you a straight answer for the podcast you have loaded:
something like "About 3 hours 8 minutes (measured on this machine)".

Roughly, on an ordinary laptop with no graphics card, an hour-long episode takes about three
and a half minutes to transcribe. A hundred episodes is an afternoon. Start it and walk away.

While it runs, the **Episodes** list shows every episode and how far along each one is. You
can arrow through it at any point to hear exactly where things stand. When the whole thing
finishes, a message tells you so, and the Cancel button turns into **Open output folder**.

## Do I need to pay for anything?

No. Everything works on your own machine, for free, forever.

There is an optional extra: if you already have an account with OpenAI, Google Gemini,
OpenRouter or Ollama Cloud, you can paste in your API key and use their models instead. That
can be faster on an older computer, and Google's models are rather good at working out who is
speaking. You pay them directly for what you use, usually a few dollars for a whole podcast
back catalogue. podHarvest shows a rough cost before you start, but treat it as a
ballpark: providers change their prices and most do not publish them in a form an app
can read, so the figure is a dated snapshot with a link to check the current rate.

You do not need this. The free model that runs on your own computer was the most accurate of
everything tested, cloud services included. The cloud option is there if you want it, not
because you need it.

If you never add a key, podHarvest never contacts any of them, and your audio never leaves
your computer.

### What about really long episodes?

They just work. You do not have to do anything.

Transcribing on your own computer has no length limit at all. A three-hour episode is fine.

Cloud providers do have a size limit on what you can send them in one go, usually around
25 MB, and a typical hour-long episode is twice that. podHarvest handles it for you: before
uploading it makes a compact copy of the audio tuned for speech, which brings an hour down to
about 7 MB, so nearly every episode fits in one piece. If something is still too big, it is
split into parts at natural pauses in the speech, never in the middle of a word, and the
pieces are joined back into one transcript with the times lined up correctly.

Your original audio file is never touched by any of this. The compact copy is made for the
upload and thrown away afterwards.

## Common things people want to do

### Just the audio, no transcripts

Uncheck **Transcribe downloaded audio**. podHarvest becomes a straightforward podcast
downloader that also saves the show notes properly.

### Only the last few episodes

Set **Limit episodes** to the number you want. Leave it at 0 for the entire series.

### Find out who said what

Check **Identify speakers**. Transcripts then read "Deborah: ..." rather than running every
voice together. If you use a Google Gemini model, this happens automatically and it sometimes
works out people's actual names from the recording.

### Jump to the interesting part

Check **Write chapter markers with start and end times**. Each summary then opens with a
contents list:

```text
00:00:00 - 00:00:34   Welcome to the show
00:00:34 - 00:01:09   Introducing this week's guest
00:01:09 - 00:15:30   Cooking without sight
```

Leave **Also add the chapters to the audio file** checked and those chapters go into the
episode itself. Your podcast player then shows them as a list you can skip through with its
own next-chapter and previous-chapter controls, so you can move around an hour-long episode
by topic instead of dragging a progress bar. Apple Podcasts, Overcast, Pocket Casts and VLC
all read them.

The audio is copied rather than re-encoded, so nothing is lost and the file grows by about
eighty bytes.

### Change where things are saved

Type a folder into **Output folder**, or press **Browse** and pick one.

### Keep a record of what happened

podHarvest saves a log of every run. Choose where it goes in **Settings**, under
**Activity log**. Handy if something goes wrong and you want to say what.

## Using a keyboard

podHarvest is built to be driven entirely from the keyboard, and to work properly with a
screen reader. Nothing needs a mouse.

| Key | What it does |
|---|---|
| Ctrl+R | Start |
| Escape | Stop the current run |
| Ctrl+E | Jump to the episode list |
| Ctrl+L | Jump to the activity log |
| Ctrl+comma | Settings |
| Ctrl+Shift+O | Open the output folder |
| Ctrl+D | Check your hardware again |
| Alt or F10 | Open the menus |

The [accessibility statement](docs/ACCESSIBILITY.md) says plainly what has been tested and
what has not. It is honest about the gaps rather than reassuring about them.

## When something goes wrong

**It looks frozen.** It probably is not. Transcribing an hour of audio takes minutes. Check
the **Episodes** list, which updates as it goes, and the percentage beside the progress bar.

**The transcript has times in it and I turned timestamps off.** Check which file you opened.
The `.srt` and `.vtt` files are subtitle files, and subtitles are made of timestamps. The
transcript itself is the `.md` or `.txt` file. You can turn subtitle files off in Settings.

**It says it cannot find the podcast.** Try the show's normal web page address instead of the
feed address. podHarvest will hunt for the feed.

**Summaries only cover the first half.** Turn on **Summarise the whole episode** in Settings.
It takes longer but covers everything.

**Something else.** Open the activity log (Ctrl+L). It says what happened in plain words.

## For the technically minded

There is a command-line version, a benchmarking tool for comparing transcription models on
your own audio, and a great deal of configuration. None of it is required.

- [Technical reference](docs/REFERENCE.md) covers every command, flag and setting
- [Model catalogue](docs/MODELS.md) covers each model, its licence and its trade-offs
- [Accessibility statement](docs/ACCESSIBILITY.md) covers what has been verified
- [Contributing](CONTRIBUTING.md) covers how to help

## Licence

podHarvest is free and open source under the [MIT licence](LICENSE). The transcription models
it downloads each carry their own licence: see the [model catalogue](docs/MODELS.md) before
using one commercially.
