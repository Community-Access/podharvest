# Your first podcast

This walks you through installing podHarvest and archiving your first show. It assumes no
technical knowledge at all. If anything here reads as jargon, that is a bug in this document,
and you are welcome to say so.

Total time: about ten minutes, most of which is waiting.

## Step 1: Install it

**The easy way, on Windows**

1. Download the file ending in `win64-portable.zip`.
2. Right-click it and choose **Extract All**.
3. Open the folder that appears and double-click **podharvest.exe**.

There is no installer to sit through and nothing to configure. The whole program lives in
that one folder. To uninstall it later, delete the folder.

**If you were given an installer instead**

Double-click `podharvest-setup.exe` and follow the prompts. It behaves like any other Windows
program after that.

## Step 2: Find your podcast's address

You need the address of the show. Either of these works:

- The show's ordinary web page, for example `https://acbda.org/podcast`
- The feed address, which often ends in `/feed` or `/rss`

Use the web page if you have it. podHarvest will find the feed on its own.

## Step 3: Run it

1. Paste the address into the **Feed URL** box at the top.
2. Press **Start**.

podHarvest reads the show's episode list, saves the show notes for every episode, and
downloads the audio. For a podcast with a long back catalogue this can take a while, because
it is downloading real audio files. The progress bar and the **Episodes** list keep you
informed throughout.

When it finishes, a message says so and the **Cancel** button becomes **Open output folder**.
Press it to see what you got.

## Step 4: Add transcripts

Transcripts are the good bit, so they get their own step.

1. Tick **Transcribe downloaded audio on-device**.
2. Look at the **About this model** box. It tells you which model will be used, how accurate
   it is, and roughly how long this podcast will take.
3. Press **Start**.

The very first time, podHarvest downloads the transcription model. That is a one-off download
of a couple of gigabytes, and it never happens again.

After that, each episode takes a few minutes. An hour of audio is about three and a half
minutes of work on an ordinary laptop. You do not have to watch. Go and do something else.

## What you end up with

Inside your output folder, one folder per podcast, containing:

| Folder | What is in it |
|---|---|
| `audio` | The episode audio files |
| `transcripts` | The transcripts, summaries and subtitle files |
| `markdown` | Show notes you can read in any text editor |
| `html` | Show notes as web pages |
| `text` | Show notes as plain text |
| `json` | The raw episode data, for anyone who wants it |

The transcripts folder holds up to four files per episode:

| File ending | What it is |
|---|---|
| `.md` | The transcript, nicely formatted |
| `.txt` | The transcript as plain text |
| `.summary.md` | A summary, and chapter markers if you asked for them |
| `.srt` | A subtitle file, for following along while listening |

## Things worth turning on

Open **Settings** with Ctrl+comma.

**Write a summary for each episode.** Gives you a paragraph on what the episode covered.
Slower, but it means you can find that one episode where they talked about the thing.

**Summarise the whole episode.** Without this, summaries cover roughly the first half of a
long episode. With it, they cover all of it and take a bit longer.

**Write chapter markers.** Adds a contents list with times at the top of each summary, so you
can skip straight to the part you wanted. Keep **Also add the chapters to the audio file**
ticked and they go into the episode itself, so your podcast player can jump between topics.
The audio is not re-encoded, so nothing is lost.

**Save a log file.** Keeps a record of each run, and lets you choose where it goes.

There is no limit on how long an episode can be. Three-hour episodes are fine. If you use a
cloud provider, podHarvest deals with their upload limits on your behalf without asking you
anything.

## If you get stuck

Press Ctrl+L to jump to the activity log. It explains what is happening in ordinary words,
including anything that went wrong.

The [README](../README.md) has a section on common problems. If your question is not answered
there, the log text is the single most useful thing to include when asking for help.

## Where next

- The [README](../README.md) covers everyday use
- The [technical reference](REFERENCE.md) covers the command line and every setting
- The [model catalogue](MODELS.md) explains the differences between transcription models
