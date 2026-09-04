# podHarvest

**Keep your favourite podcasts. Read them as well as hear them.**

podHarvest downloads a podcast and turns every episode into something you can read, search
and keep: the audio file, a written transcript, a summary, and a tidy folder you own. It runs
on your own computer. No account, no subscription, no sending your listening habits anywhere.

Point it at a podcast. Go make a cup of tea. Come back to a library.

**It works just as well on audio you already have.** Switch **Source** to
**Local files**, add a file or a folder, and podHarvest will transcribe it,
summarise it, work out chapter markers and write them into the file — and let
you play it and edit every tag on it. No feed required. If all you want is a
keyboard-driven, screen-reader-friendly MP3 tag and chapter editor, that is a
perfectly good reason to install this.

## What you get

Give podHarvest a podcast address and it builds you a folder like this, one entry per episode:

- **The audio**, downloaded and named sensibly instead of `ep_final_FINAL_2.mp3`
- **A transcript** you can read, search, or paste into anything
- **A summary** of what the episode was actually about
- **Chapter markers** with times, so you can jump to the bit you wanted
- **Subtitle files** if you want to follow along while listening
- **The show notes**, saved as a web page, plain text and Markdown
- **Editable tags and chapters** — select any downloaded episode and press
  Ctrl+T (see below)

Everything is a normal file in a normal folder. Nothing is locked in an app. If you delete
podHarvest tomorrow, your library stays exactly where it is.

## Finding a podcast

You do not need to know a show's feed address. Press **Ctrl+K**, type the name
of the show, a presenter, or what it is about, and press Enter. Arrow the
results, press Enter again, and the feed address is filled in for you.

The search asks Apple's podcast directory — free, no account, the same one the
podcast apps use. You can narrow what your words are matched against (the
show's name, the presenter, keywords, the description) and choose which
country's store to ask, since stores carry different shows: a local programme
may only appear in its own. The default is the United States store, which is
the largest; change it in **Settings ▸ Finding podcasts**.

**Show episodes** (**Ctrl+Shift+E**) reads a feed and lists what is in it —
titles, dates, lengths, and whether each episode has audio or a published
transcript — *without downloading anything*. It is the way to see what a show
has before deciding to harvest it. A pasted `podcasts.apple.com` link works
here too; podHarvest turns it into the feed address for you.

## Favourite podcasts

Found something worth keeping? **Add to favourites**. **Ctrl+Shift+K** brings
the list back up, and Enter on one puts its feed address in the box.

**These are bookmarks, not subscriptions.** podHarvest never checks them for
new episodes, never downloads anything on its own, and never notifies you.
Removing a favourite removes the bookmark only — anything you have already
harvested from that show stays exactly where it is. The list is a plain JSON
file in your app space, so it travels with a portable install and can be read
or edited without podHarvest.

## Importing a list of podcasts

If you already have a list — exported from another podcast app, or published
by a network — **Ctrl+Shift+I** reads it. OPML is the format apps use to hand
each other a list of shows, and every podcast app can export one.

The window shows what is in the list with a tick box against each show. **Tick
the new ones** ticks only what is not already in your favourites, which is what
you want when re-reading a list you have imported before. **Add ticked to
favourites** saves them; **Use this one now** takes a single show straight to
the main window instead.

There is a **Try the ACB Media network** button, because "find an OPML file"
is not a useful instruction when you have never seen one. It loads a real,
public list of 41 shows.

**Importing is not subscribing.** It adds bookmarks. Nothing is checked for new
episodes, nothing is downloaded, and nothing happens on a schedule — what you
harvest from the list is a separate decision you make afterwards.

## Two ways in: a feed, or files you already have

At the top of the window is **Source**, a pair of radio buttons:

- **Podcast feed** — the original job. Paste an address, get a library.
- **Local files** — audio already on this machine.

Everything below the radio applies to whichever you pick: the same models, the
same transcript options, the same summaries and chapter markers, the same
player, the same editor, the same progress reporting. The only thing that
differs is that a local file has nothing to download.

Your choice is remembered, so if podHarvest is your tag editor it opens as your
tag editor.

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

## Working on audio you already have

Say you have a folder of recorded lectures, an audiobook that came without
chapter marks, or a decade of podcasts downloaded before podHarvest existed.

1. Set **Source** to **Local files** (or press **Ctrl+O**, which switches for
   you).
2. **Add files...** for a few, or **Add a folder...** for everything in one —
   subfolders included, unless you turn that off in Settings.
3. They appear in the **Episodes** list with what each already has: a
   transcript, a summary, how many chapter markers, how long it runs.
4. You can stop right there. **Ctrl+P** plays a file and **Ctrl+T** edits its
   tags and chapters — you do not have to press Start first, and nothing is
   written until you ask for it.
5. Or press **Start on these files** to transcribe them, summarise them and
   give them chapter markers.

**Where the transcripts go.** Beside the audio: `lecture.mp3` gets
`lecture.md` next to it, so the two stay together if you move the folder later.
If you would rather podHarvest never wrote into your own folders, untick
**Write transcripts beside the audio file** in Settings and they go into a
`Local files` folder inside your output folder instead.

**Nothing is copied, moved, renamed or converted.** **Remove** takes a file out
of the list; it does not touch the file. The only writes to your audio are the
tag and chapter edits you ask for, and those rewrite the tag block rather than
the sound.

**Work already done is not done again.** A file that already has a transcript
beside it is left alone, and chapter markers already in the file are kept rather
than replaced by inferred ones. Both are the same rules a re-run of a feed
follows.

**From the command line**, the same thing:

```bash
podharvest local "D:\Lectures"                 # a folder, subfolders included
podharvest local one.mp3 two.m4b --model small.en
podharvest local "D:\Audio" --no-beside       # transcripts into the library folder
```

## Fixing up an episode

Select any downloaded episode and press **Ctrl+T** (or just press Enter on it) to
open the **Tag and Chapter Editor**.

Six pages, reachable with Control+Tab. Five of them hold every tag the file can
carry — title, artist, album, track and disc numbers, composer, publisher,
copyright, language, sort-order fields, embedded cover art, and the rest —
twenty-six fields in all, each with a sentence saying what it is for.

The sixth page is the chapters. Add one at the playhead or at a time you type;
delete one (the marker only — the audio is never touched); type an exact start
and end; or play a single chapter and stop at its end. And when a boundary lands
mid-sentence, **nudge** it: **Alt+Left** and **Alt+Right** move it by one step,
Shift with them moves ten, and **Hear boundary** plays three seconds either side
so you can tell. The step is yours to pick, from a tenth of a second to ten
seconds.

That page has a player: **Play**, **Stop**, **Rewind** and **Forward** ten
seconds, a **volume** you set once and a **mute** that remembers it, and a
**speed** control offering the same speeds as the main window, set in Settings.
Slowing down is the useful direction here — at 0.75x it is far easier to hear
exactly where a sentence starts, which is the whole job when placing a marker.

Every nudge speaks the new time and nothing else, because a whole sentence
repeated at key-repeat speed is unusable; the full description follows once you
stop moving.

## Shared with QUILL Audio Studio

podHarvest's tag and chapter editor is the same editor QUILL Audio Studio has,
running the same code: the same fields, the same operations, the same keys. A
file edited in one app is a file the other reads back exactly as it was left. If
you use both, you only have to learn this once.

## How long will it take?

Transcribing is the slow part, and podHarvest tells you before you commit. Select any model
and the **About this model** box gives you a straight answer for the podcast you have loaded:
something like "About 3 hours 8 minutes (measured on this machine)".

Roughly, on an ordinary laptop with no graphics card, an hour-long episode takes about three
and a half minutes to transcribe. A hundred episodes is an afternoon. Start it and walk away.

While it runs, the **Episodes** list shows every episode and how far along each one is. You
can arrow through it at any point to hear exactly where things stand. When the whole thing
finishes, a message tells you so, and the Cancel button turns into **Open output folder**.

When nothing is running, that same list is **your library**: every episode you
have harvested, with the podcast it came from, what you have for each (audio,
transcript, summary), when it was published and how long it is. It is there when
you open podHarvest, and it is rebuilt when a run finishes. Ctrl+Shift+R lists it
again if you have moved files about.

**A long run can get out of the way.** Ctrl+Shift+M tucks the window into the
notification area and the run carries on; the tray icon brings it back. Closing
the window still quits, because a window that vanishes when you press close is
one people think they have quit.

## Reading and playing what you harvested

Open podHarvest and your library is already listed. Arrow to an episode, then:

- **Ctrl+P** plays it.
- **Ctrl+Shift+T** opens the transcript, with a Find box that tells you which
  occurrence you are on — the useful thing to do with an hour of speech is find
  a passage, not scroll through it.
- **Ctrl+T** opens its tags and chapters.

## Playing an episode

Select an episode — or a local file — and press **Ctrl+P**. You do not have to
open anything: the player sits under the episode list, with **Rewind** and
**Forward**, a **volume** and **mute**, and a **speed** control.

**The speeds are yours to set.** Out of the box: 0.5x, 0.75x, 1x, 1.25x, 1.5x,
1.75x, 2x, 2.5x and 3x. Change the list in Settings — **Playback speeds**,
written as numbers separated by commas — and anything from 0.25x to 5x is
allowed. 3x is a normal way through a backlog; 0.5x is how a fast speaker
becomes followable; 0.75x is the one to use when you are listening for exactly
where a sentence starts, which is the whole job when placing a chapter marker.
1x is always kept on the list, so there is always a way back to normal.

Not every media backend will play at every speed. If yours refuses one,
podHarvest says so — naming the speed — rather than quietly carrying on at the
old one.

Rewind and forward are set separately in Settings, because going back is usually
about a sentence you missed and going forward is usually about clearing an advert
break. Ten seconds each to start with, anything from one second to five minutes.

podHarvest remembers where you stopped in each episode and picks it up there next
time, saying so when it does. An episode you played to the end starts from the
beginning again, because finishing is not a place you were coming back to. Turn
it off in Settings if you would rather always start at the top.

## Do I need to pay for anything?

No. Everything works on your own machine, for free, forever.

There is an optional extra: if you already have an account with OpenAI, Google Gemini,
Groq, ElevenLabs, OpenRouter, Ollama Cloud or Azure, you can paste in your API key and use
their models instead. That can be faster on an older computer; Groq and Gemini both have free
tiers, Groq runs full-size Whisper for about four cents an hour, and Google's and ElevenLabs'
models are rather good at working out who is speaking. You pay them directly for what you use, usually a few dollars for a whole podcast
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

### Only the episodes about one thing

Put a word or two in **Only episodes matching** and podHarvest takes only the
episodes whose titles contain them — all the words, any order, ignoring case.
It runs *before* the episode limit, so "5 episodes matching badger" means five
about badgers rather than however many badgers happen to be in the latest five.

On the command line: `podharvest fetch <url> --match badger --limit 5`.

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

## The status bar

Along the bottom is a row you can actually get to. **F6** puts focus in it,
**Left** and **Right** move between cells, **Home** and **End** jump to the
ends, **Enter** does the useful thing for whichever cell you are on, and **F6**
or **Escape** hands focus back where it came from. The context menu key offers
the same action, plus copying the value.

| Cell | Shows | Enter |
|---|---|---|
| Activity | What podHarvest is doing | Jumps to the activity log |
| Progress | How far through a run | Says the whole sentence |
| Source | Which source, and what it points at | Jumps to that box |
| Model | The model, and whether it is downloaded | Downloads it, or jumps to the picker |
| Library | How much is in the Episodes list | Jumps to the list |
| Time | The time | Says the full date and time |

**View ▸ Show the status bar** hides it if you would rather not have it.

This replaces wx's own status bar, which could not take focus at all — so
nothing could read it on demand, and nothing announced when it changed. That is
why podHarvest used to sit claiming it was detecting hardware long after it had
finished: nobody could see the message, so nobody noticed it was stale.

## Using a keyboard

podHarvest is built to be driven entirely from the keyboard, and to work properly with a
screen reader. Nothing needs a mouse.

**The key to remember is F1.** It explains the window you are in and the control you are on,
anywhere in the program. You do not have to remember the rest of this table — you can ask.

| Key | What it does |
|---|---|
| Ctrl+R | Start |
| Escape | Stop the current run |
| F6 | Go to the status bar (F6 or Escape comes back) |
| Ctrl+K | Find a podcast |
| Ctrl+Shift+K | Favourite podcasts |
| Ctrl+Shift+I | Import a list of podcasts (OPML) |
| Ctrl+Shift+E | Show the episodes in this feed |
| Ctrl+O | Add local files |
| Ctrl+Shift+F | Add a local folder |
| Ctrl+E | Jump to the episode list |
| Ctrl+P | Play or pause the selected episode |
| Ctrl+B | Rewind |
| Ctrl+F | Forward |
| Ctrl+Shift+T | Read the selected episode's transcript |
| Ctrl+Shift+R | List your library again |
| Ctrl+T | Edit the selected episode's tags and chapters |
| Ctrl+L | Jump to the activity log |
| Ctrl+Shift+M | Minimise to the notification area |
| F1 | Explain this window, and the control you are on |
| Ctrl+comma | Settings |
| Ctrl+Shift+O | Open the output folder |
| Ctrl+D | Check your hardware again |
| Alt or F10 | Open the menus |

The [accessibility statement](docs/ACCESSIBILITY.md) says plainly what has been tested and
what has not. It is honest about the gaps rather than reassuring about them.

## Is it going to work? Ask before you start

The first run of any transcription model has to fetch two things: the engine's
Python packages, and the model itself. Together that can be several minutes and
a few gigabytes, and until now the only way to find out whether you had them was
to start a run and wait.

Beside the model description there is now a line that says plainly whether the
selected model is **Ready**, or what is still missing, and a **Download model**
button that fetches it there and then. Press it whenever you like: anything
already downloaded is kept.

From the command line, `podharvest doctor` answers the same question and more:

```
podharvest doctor                    # every engine
podharvest doctor --engine vosk      # just one
```

It prints where everything lives, whether FFmpeg is present, whether podHarvest
can install packages at all, and for each engine whether its packages are
downloaded **and whether they actually load** — which are different questions.
It is written to be pasted straight into a bug report.

## Hearing a run without watching it

podHarvest's activity log cannot announce itself to a screen reader. That is a
real limitation of the toolkit, not an oversight, and it is written up honestly
in the [accessibility statement](docs/ACCESSIBILITY.md). It means a long run is
otherwise silent: an hour of transcription finishes, or fails on the third
episode of forty, and nothing says so unless you happen to be reading the log.

Turn on **Play a short sound as each episode finishes** in Settings and you get
four cues you can tell apart by ear while doing something else:

| Sound | What it means |
|---|---|
| One short tone | An episode finished |
| A rising pair | The whole run finished |
| A low tone | Something failed |
| A falling pair | You stopped the run |

Off by default, because a sound nobody asked for is an intrusion.

## When something goes wrong

**It says it cannot set up an engine.** Run `podharvest doctor`. It will say
whether the problem is a missing download (fixable with **Download model**) or
something that will not load (a bug — please send the output in).

**It looks frozen.** It probably is not. Transcribing an hour of audio takes minutes. Check
the **Episodes** list, which updates as it goes, and the percentage beside the progress bar.

**The transcript has times in it and I turned timestamps off.** Check which file you opened.
The `.srt` and `.vtt` files are subtitle files, and subtitles are made of timestamps. The
transcript itself is the `.md` or `.txt` file. You can turn subtitle files off in Settings.

**It says it cannot find the podcast.** Try the show's normal web page address instead of the
feed address. podHarvest will hunt for the feed.

**Summaries only cover the first half.** Turn on **Summarise the whole episode** in Settings.
It takes longer but covers everything.

**Something else.** Two things answer most of it without leaving the app: **F1** on whatever
you were doing explains what that control is for, and **Ctrl+L** opens the activity log, which
says what happened in plain words. If that is not enough,
[support@community-access.org](mailto:support@community-access.org) — and **Help ▸ Report a
bug** will put together everything worth sending.

## Help, documentation and support

### The help is in the app

**Press F1.** Anywhere, on anything.

podHarvest answers with what the window you are in is for, and then what the
control you are actually on does — its name, a sentence written for it, and how
to drive a control of that kind. Every focusable control in the program has that
sentence — including every checkbox and every setting, on both sources — and the
sentences carry the units and the defaults, because those are the things you
cannot see by looking at the label.

That help ships inside the program. It needs no internet, no browser and no
second window, and it is the same whether you are reading the screen or hearing
it. A control that nobody has written a sentence for still answers with its name
and its keys, because an F1 that does nothing cannot be told from an F1 that is
broken — and a build check refuses to compile if a new control arrives without
one, so the coverage cannot quietly rot.

Two more things the app will tell you itself:

- **Ctrl+L** opens the activity log, which says in ordinary words what is
  happening and anything that went wrong.
- **Help ▸ Media tools** says whether FFmpeg is installed and what it is used
  for — worth asking, because everything that needs it fails quietly.

### The written documentation

Six documents, each with a job. None of them is a dumping ground.

| Document | What it is for | Who it is for |
|---|---|---|
| [Your first podcast](docs/GETTING_STARTED.md) | A walkthrough of one complete run, from installing to what ends up on disk, then how to come back to it later | Someone who has just installed it |
| This README | Everyday use: what you get, playing and reading, the keyboard, what to do when something goes wrong | Everyone, and the first place to look |
| [Technical reference](docs/REFERENCE.md) | Every command, flag, setting and output format; the library, the editor, the reuse rules; how to build an installer | Someone scripting it, tuning it or packaging it |
| [Model catalogue](docs/MODELS.md) | Each transcription model, its accuracy, its speed, its size and its licence | Someone choosing a model, or checking one is safe to use commercially |
| [Accessibility statement](docs/ACCESSIBILITY.md) | What has been verified with which screen reader, and — plainly — what has not | Someone deciding whether this will work for them |
| [Code review, September 2026](docs/CODE-REVIEW-2026-09.md) | What a full review of the engines and pipeline found, fixed, added and deliberately left alone | Someone judging the code's honesty, or proposing a new provider |

And for the project itself: [Contributing](CONTRIBUTING.md), the
[Changelog](CHANGELOG.md), and the [Security policy](SECURITY.md), which
explains the trust model and where the real risk is.

Every one of these ships with the installed app as well, under the program's
folder and in its Start Menu group. Documentation you cannot reach offline is
documentation you do not have.

### Support

**support@community-access.org.** A real address, read by people.

The most useful thing you can send is the activity log. **Help ▸ Report a bug**
gathers it for you along with the version, the platform, whether FFmpeg is
found, your hardware, and the settings you have changed — then **shows you the
whole thing before anything is sent**, with API keys, home folder names and
email addresses already removed. Copy it, save it, or have it open a message
ready to go. podHarvest never sends anything on its own.

Bugs and feature requests can also go to
[GitHub issues](https://github.com/community-access/podharvest/issues).
Security problems should go through
[GitHub Security Advisories](https://github.com/community-access/podharvest/security/advisories/new)
rather than a public issue — see the [security policy](SECURITY.md).

## For the technically minded

There is a command-line version, a benchmarking tool for comparing transcription models on
your own audio, and a great deal of configuration. None of it is required — see the
[technical reference](docs/REFERENCE.md).

## Licence

podHarvest is free and open source under the [MIT licence](LICENSE). The transcription models
it downloads each carry their own licence: see the [model catalogue](docs/MODELS.md) before
using one commercially.
