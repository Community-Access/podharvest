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

## Coming back to what you harvested

Open podHarvest again tomorrow and your library is already listed: every episode
you have, which podcast it came from, and what you have for each. Arrow to one
and you can play it (**Ctrl+P**), read its transcript (**Ctrl+Shift+T**), or fix
its tags and chapters (**Ctrl+T**) — none of which needs a run in progress.

The transcript reader has a **Find** box, which is the thing you actually want
for an hour of speech: type a word, press Enter, and it tells you which of the
occurrences you are on.

The player sits under the list: **Ctrl+B** rewinds, **Ctrl+F** goes forward, and
there is a volume and a speed. The speeds run from 0.5x to 3x out of the box and
the list is yours to change in Settings — **Playback speeds**, written as numbers
separated by commas, anywhere from 0.25x to 5x. podHarvest also remembers where
you stopped in each episode and picks it up there next time.

## Fixing up an episode

Once a run has finished, you have real files — and sometimes one of them needs a
correction. Select an episode in the list and press **Ctrl+T**, or just press
Enter on it, and the **Tag and Chapter Editor** opens.

Six pages, moved between with Control+Tab:

- **Main, Details, Publishing and Sort order** hold every tag the file can
  carry: the title and artist you would expect, and also track and disc numbers,
  composer, publisher, copyright, language, and the sort-order fields that
  decide how a player files the episode without changing what it displays. Each
  field says what it is for.
- **Cover art** shows what the file currently carries — described in words
  first, so a screen reader can read it, with the picture beside — and lets you
  load a JPEG or PNG, save the existing one out, or remove it.
- **Chapters** is the interesting one. Add a marker at the playhead or at a time
  you type. Delete one — the marker only; the audio is never cut. Type an exact
  start and end. Play a single chapter and stop at its end.

The part worth learning is **nudging**. When a chapter boundary lands halfway
through a sentence, select the chapter and press **Alt+Left** or **Alt+Right**:
the marker moves by one step. Hold Shift as well and it moves ten. Press **Hear
boundary** and you get three seconds before the marker and two after it, then
silence — enough to tell whether it lands where a listener would want it. Tick
**Hear after each nudge** and that happens automatically after every press.

Each nudge speaks only the new time, because a full sentence repeated as fast as
you can press a key is unusable. About half a second after you stop, the whole
description arrives. If you run a marker up against its neighbour it stops there
and says so once, rather than refusing on every press.

The player on that page has **Play**, **Stop**, **Rewind** and **Forward** ten
seconds, a **volume** you set once and a **mute** that remembers it, and a
**speed** control. Slowing to 0.75x is the useful direction: it is far easier to
hear exactly where a sentence begins, which is the whole job.

Press **Save** and the tags and chapters go into the file. For an MP3 that is
instant: only the tag block is rewritten and the audio is untouched.

## Audio you already have

You do not need a podcast feed to use podHarvest. If what you have is a folder
of recordings, an audiobook with no chapter marks, or MP3s whose tags are a
mess, this is the same program.

1. At the top of the window, set **Source** to **Local files**. (**Ctrl+O** does
   it and opens the file chooser in one go.)
2. **Add files...** picks a few; **Add a folder...** takes everything in one,
   subfolders included.
3. They appear in the **Episodes** list with what each already has — a
   transcript, a summary, how many chapter markers, how long it runs.
4. Arrow to one and press **Ctrl+P** to play it, or **Ctrl+T** to edit its tags
   and chapter markers. Nothing has been written yet, and you never have to
   press Start if editing is all you came for.
5. Press **Start on these files** to transcribe them, summarise them and work
   out chapter markers.

Transcripts are written beside the audio — `lecture.mp3` gets `lecture.md` next
to it — so the two stay together. If you would rather podHarvest never wrote
into your own folders, untick **Write transcripts beside the audio file** in
Settings.

Your files are never copied, moved, renamed or converted. **Remove** takes a
file out of the list; the file itself is untouched.

## If you get stuck

**Press F1.** Wherever you are, on whatever control you are on, it explains what that window
is for and what that control does. Every control in podHarvest has an explanation written for
it — including every checkbox and every setting, with the units and the defaults, which are the
things a label cannot tell you. It works offline, because it ships inside the program.

**Press Ctrl+L** to jump to the activity log. It explains what is happening in ordinary words,
including anything that went wrong.

The [README](../README.md) has a section on common problems. If your question is not answered
there, write to [support@community-access.org](mailto:support@community-access.org). **Help ▸
Report a bug** will assemble everything worth sending — the log, your version, your hardware,
the settings you changed — show you all of it first, and remove anything private before you
send it.

## Where next

The documentation is meant to be read, not searched in desperation. Each piece has a job:

- The [README](../README.md) covers everyday use: playing, reading, the keyboard, and what to
  do when something goes wrong. Start there.
- The [technical reference](REFERENCE.md) covers every command, flag and setting, plus the
  library, the tag and chapter editor, and how to build an installer.
- The [model catalogue](MODELS.md) explains the differences between transcription models,
  including their licences.
- The [accessibility statement](ACCESSIBILITY.md) says what has been verified with which
  screen reader — and, plainly, what has not.

All of them are installed alongside the program and listed in its Start Menu group, so you have
them whether or not you are online.
