"""Not doing work twice: existing transcripts and existing chapter markers.

The rules live in the vendored `reuse_core`, shared byte-for-byte with QUILL
Cast. These cover podHarvest's side — where files live, what counts as
"already there", and the cascade that decides whether a language model gets
asked at all.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from podharvest import reuse, reuse_core

MODULE = Path(reuse_core.__file__)
DIGEST_FILE = MODULE.with_suffix(".sha256")


class TestVendoring:
    def test_the_shared_module_has_not_drifted(self):
        expected = DIGEST_FILE.read_text(encoding="utf-8").split()[0].strip()
        actual = hashlib.sha256(MODULE.read_bytes()).hexdigest()
        assert actual == expected, (
            "reuse_core.py has changed. Copy the new file to "
            "quill/core/speech/reuse_core.py, update the digest in both repos, "
            "or podHarvest and QUILL Cast have silently diverged."
        )

    def test_the_line_endings_are_pinned(self):
        """`* text=auto eol=lf` would rewrite this file and break the digest.

        The digest test above passes in this working tree and would still have
        passed here on a fresh clone that normalised the file -- until the day
        somebody checked out on a machine that did. Pinning is the fix; this is
        what stops the pin being dropped again.
        """
        attributes = (MODULE.parent.parent / ".gitattributes").read_text(encoding="utf-8")
        assert "podharvest/reuse_core.py -text" in attributes

    def test_it_imports_nothing_from_either_host(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in {"quill", "podharvest"}, name


class TestTranscriptRanking:
    """Whoever wrote the feed's element order should not decide this."""

    def test_structured_formats_beat_the_words_alone(self):
        assert reuse_core.transcript_rank("application/json") < reuse_core.transcript_rank(
            "text/vtt"
        )
        assert reuse_core.transcript_rank("text/vtt") < reuse_core.transcript_rank("text/html")

    def test_an_unknown_type_is_kept_but_sorts_last(self):
        """Refusing it would lose the words in order to protect the timings."""
        assert reuse_core.transcript_rank("application/x-invented") == (
            reuse_core.TRANSCRIPT_UNKNOWN_RANK
        )

    def test_the_extension_is_the_fallback_when_no_type_is_declared(self):
        assert reuse_core.transcript_rank("", "https://x/e.vtt") == reuse_core.transcript_rank(
            "text/vtt"
        )

    def test_best_prefers_capability_over_feed_order(self):
        chosen = reuse_core.best_transcript(
            [("text/html", "a.html"), ("text/vtt", "b.vtt")]
        )
        assert chosen == ("text/vtt", "b.vtt")

    def test_ties_keep_the_publishers_order(self):
        chosen = reuse_core.best_transcript(
            [("text/vtt", "first.vtt"), ("text/vtt", "second.vtt")]
        )
        assert chosen == ("text/vtt", "first.vtt")

    def test_a_candidate_with_no_url_is_not_a_representation(self):
        assert reuse_core.best_transcript([("text/vtt", "")]) is None


class TestExistingTranscript:
    def test_a_previous_run_is_found(self, tmp_path):
        (tmp_path / "transcripts").mkdir()
        written = tmp_path / "transcripts" / "0001-episode.md"
        written.write_text("x" * 500, encoding="utf-8")
        assert reuse.existing_transcript(tmp_path, "0001-episode") == written

    def test_a_truncated_file_does_not_count_as_done(self, tmp_path):
        """An interrupted run should be redone, not treated as finished."""
        (tmp_path / "transcripts").mkdir()
        (tmp_path / "transcripts" / "0001-episode.md").write_text("", encoding="utf-8")
        assert reuse.existing_transcript(tmp_path, "0001-episode") is None

    def test_nothing_there_is_nothing(self, tmp_path):
        assert reuse.existing_transcript(tmp_path, "0001-episode") is None


class TestFeedTranscript:
    class _Enc:
        def __init__(self, url, mime):
            self.url, self.mime = url, mime

    class _Ep:
        def __init__(self, transcripts):
            self.transcripts = transcripts

    def test_the_best_offered_wins(self):
        ep = self._Ep([self._Enc("a.html", "text/html"), self._Enc("b.vtt", "text/vtt")])
        assert reuse.feed_transcript(ep) == ("b.vtt", "text/vtt")

    def test_no_tags_is_none(self):
        assert reuse.feed_transcript(self._Ep([])) is None


class TestTranscriptParsing:
    def test_vtt_becomes_the_words(self):
        raw = b"WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\nHello there\n"
        assert reuse_core.parse_transcript(raw, "text/vtt") == "Hello there"

    def test_json_keeps_the_speaker(self):
        raw = b'{"segments":[{"speaker":"Alex","body":"Hi"}]}'
        assert reuse_core.parse_transcript(raw, "application/json") == "Alex: Hi"

    def test_bad_json_is_reported_not_swallowed(self):
        with pytest.raises(reuse_core.TranscriptParseError):
            reuse_core.parse_transcript(b"{not json", "application/json")

    def test_an_unknown_type_is_read_as_text(self):
        assert reuse_core.parse_transcript(b"  just words  ", "application/x-odd") == "just words"


class TestShowNoteChapters:
    def test_the_common_shape_is_read(self):
        notes = "00:00 Introduction\n12:30 The interview\n45:10 Listener questions"
        marks = reuse_core.marks_from_notes(notes)
        assert [t for _s, t in marks] == [
            "Introduction",
            "The interview",
            "Listener questions",
        ]
        assert [s for s, _t in marks] == [0, 750_000, 2_710_000]

    def test_a_trailing_timestamp_is_read_too(self):
        notes = "Introduction — 00:00\nThe interview — 12:30\nQuestions — 45:10"
        assert len(reuse_core.marks_from_notes(notes)) == 3

    def test_html_show_notes_are_read(self):
        notes = "<ul><li>00:00 Intro</li><li>10:00 Middle</li><li>20:00 End</li></ul>"
        assert len(reuse_core.marks_from_notes(notes)) == 3

    def test_one_bad_mark_loses_that_mark_not_the_list(self):
        """An outro sign-off must not cost a publisher all their chapters."""
        notes = (
            "00:00 Intro\n10:00 One\n20:00 Two\n30:00 Three\n"
            "40:00 Four\n50:00 Five\n50:10 Contact us"
        )
        marks = reuse_core.marks_from_notes(notes)
        assert len(marks) == 6
        assert "Contact us" not in [t for _s, t in marks]

    def test_a_page_that_merely_contains_times_is_refused(self):
        notes = "See 1:22:00 in episode 4, and 2:05:00 in episode 9."
        assert reuse_core.marks_from_notes(notes) == []

    def test_a_list_starting_an_hour_in_is_not_this_episodes(self):
        notes = "1:30:00 A thing\n2:00:00 Another thing\n2:30:00 A third"
        assert reuse_core.marks_from_notes(notes) == []

    def test_marks_past_the_end_are_dropped(self):
        """The row goes, the list stays -- while most of it survives."""
        notes = "\n".join([
            "00:00 Intro",
            "05:00 One",
            "10:00 Two",
            "15:00 Three",
            "20:00 Four",
            "99:00:00 Nonsense",
        ])
        marks = reuse_core.marks_from_notes(notes, total_ms=25 * 60 * 1000)
        assert [t for _s, t in marks] == ["Intro", "One", "Two", "Three", "Four"]

    def test_a_list_needing_too_much_repair_is_refused_entirely(self):
        """Dropping a third of the rows means it was never a chapter list."""
        notes = "00:00 Intro\n10:00 Middle\n99:00:00 Nonsense"
        assert reuse_core.marks_from_notes(notes, total_ms=20 * 60 * 1000) == []


class TestFreeChapters:
    def _file_marks(self):
        return [(0, "Opening"), (600_000, "The interview")]

    def test_the_file_wins_when_it_has_markers(self):
        found = reuse_core.free_chapters(
            from_file=self._file_marks,
            show_notes="00:00 Something else\n15:00 And another",
            total_ms=30 * 60 * 1000,
        )
        assert found.source == "file"
        assert found.label == "Chapters in the file"
        assert found.authored is True

    def test_show_notes_are_used_when_the_file_has_none(self):
        found = reuse_core.free_chapters(
            from_file=list,
            show_notes="00:00 Intro\n15:00 Middle\n25:00 End",
            total_ms=30 * 60 * 1000,
        )
        assert found.source == "show_notes"
        assert len(found.marks) == 3

    def test_nothing_free_is_falsy_so_the_caller_may_spend(self):
        found = reuse_core.free_chapters(from_file=list, show_notes="", total_ms=30 * 60 * 1000)
        assert not found
        assert found.source == ""

    def test_a_short_episode_is_not_worth_sectioning(self):
        found = reuse_core.free_chapters(from_file=self._file_marks, total_ms=60_000)
        assert not found

    def test_a_source_that_raises_is_treated_as_empty_not_as_an_error(self):
        def explode():
            raise OSError("the file went away")

        found = reuse_core.free_chapters(
            from_file=explode,
            show_notes="00:00 Intro\n15:00 Middle",
            total_ms=30 * 60 * 1000,
        )
        assert found.source == "show_notes"

    def test_one_marker_is_not_a_chapter_list(self):
        found = reuse_core.free_chapters(
            from_file=lambda: [(0, "Only one")], total_ms=30 * 60 * 1000
        )
        assert not found


class TestExistingChaptersOnAFile:
    def test_markers_already_in_the_mp3_are_found(self, tmp_path):
        pytest.importorskip("mutagen")
        from podharvest import audio_tags_core as core

        path = tmp_path / "episode.mp3"
        path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40)
        core.write_mp3_chapters(path, [
            core.Chapter(index=0, title="Opening", start_ms=0, end_ms=600_000),
            core.Chapter(index=1, title="Interview", start_ms=600_000, end_ms=1_800_000),
        ])
        found = reuse.existing_chapters(path, total_ms=1_800_000)
        assert found.source == "file"
        assert [t for _s, t in found.marks] == ["Opening", "Interview"]

    def test_a_file_with_no_markers_falls_through_to_the_notes(self, tmp_path):
        pytest.importorskip("mutagen")
        path = tmp_path / "episode.mp3"
        path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40)
        found = reuse.existing_chapters(
            path, show_notes="00:00 Intro\n15:00 Middle", total_ms=1_800_000
        )
        assert found.source == "show_notes"

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        found = reuse.existing_chapters(tmp_path / "gone.mp3", total_ms=1_800_000)
        assert not found


class TestSettings:
    def test_reuse_is_on_by_default(self):
        """Doing the work twice should be the thing you opt into."""
        from podharvest.config import Settings

        s = Settings()
        assert s.reuse_transcripts is True
        assert s.use_feed_transcripts is True
        assert s.reuse_chapters is True


class TestPipelineWiring:
    def test_the_pipeline_checks_before_it_transcribes(self):
        import inspect

        from podharvest import harvest

        source = inspect.getsource(harvest._transcribe_episode)
        # `transcript_in` rather than `existing_transcript` since the local
        # files route arrived: the same check, told where to look, because a
        # local transcript sits beside its audio rather than in transcripts/.
        assert "transcript_in" in source
        assert "feed_transcript" in source
        # The checks must come before the engine is asked to do anything.
        assert source.index("transcript_in") < source.index("engine.transcribe")
        assert source.index("feed_transcript") < source.index("engine.transcribe")

    def test_chapters_are_checked_before_a_model_is_asked(self):
        import inspect

        from podharvest import harvest

        source = inspect.getsource(harvest._enrich_episode)
        assert "existing_chapters(" in source
        # The call site, not the import line at the top of the function.
        assert source.index("existing_chapters(") < source.index("_, chapters = write_enrichment(")

    def test_a_reused_transcript_still_gets_its_summary(self):
        """Skipping the transcription must not skip the summary.

        An episode whose transcript already existed may never have had a
        summary -- enrichment might have been off the day it was made -- so
        both routes into the pipeline run the same enrichment.
        """
        import inspect

        from podharvest import harvest

        source = inspect.getsource(harvest._transcribe_episode)
        reuse_call = source.index("_enrich_episode")
        transcribe_call = source.index("engine.transcribe")
        assert reuse_call < transcribe_call, (
            "the reuse path must enrich before it returns, not fall through"
        )
        assert source.count("_enrich_episode") == 2, (
            "both the reuse route and the transcribe route must enrich"
        )

    def test_the_reuse_path_does_not_pretend_to_have_segments(self):
        """No per-segment times means no inferred chapters -- but the free
        sources still work, so a published chapter list is still honoured."""
        import inspect

        from podharvest import harvest

        source = inspect.getsource(harvest._enrich_episode)
        assert "segments if has_times else None" in source
        assert "has_times = bool(segments) and len(segments) > 1" in source


class TestMediaHealth:
    """Every FFmpeg feature here fails by producing a plausible result.

    That is the whole reason this exists: the episode downloads and simply has
    no chapter markers, which is indistinguishable from an episode that never
    had any. Nobody notices, so nobody reports it.
    """

    def test_a_healthy_install_says_nothing_at_startup(self):
        """A startup that reports good news every time is one people ignore."""
        from podharvest.media_health import MediaHealth

        assert MediaHealth(ffmpeg=True).summary() == ""
        assert MediaHealth(ffmpeg=True).notice() == ""
        assert MediaHealth(ffmpeg=True).repair_hint() == ""

    def test_asking_always_gets_an_answer(self):
        """Silence from a menu item reads as a broken menu item."""
        from podharvest.media_health import MediaHealth

        assert MediaHealth(ffmpeg=True).readout()
        assert MediaHealth(ffmpeg=False).readout()

    def test_a_missing_tool_names_what_it_costs(self):
        from podharvest.media_health import FFMPEG_CAPABILITIES, MediaHealth

        notice = MediaHealth(ffmpeg=False).notice()
        for capability in FFMPEG_CAPABILITIES:
            assert capability in notice
        assert "PATH" in notice, "it must say what to do about it"

    def test_it_does_not_overstate_the_damage(self):
        """Downloading and local transcription work fine without FFmpeg."""
        from podharvest.media_health import MediaHealth

        assert "still download" in MediaHealth(ffmpeg=False).summary()

    def test_the_capabilities_are_only_lost_when_it_is_missing(self):
        from podharvest.media_health import MediaHealth

        assert MediaHealth(ffmpeg=True).lost_capabilities == ()
        assert MediaHealth(ffmpeg=False).lost_capabilities

    def test_the_signature_distinguishes_the_two_states(self):
        """Repaired then broken again must be told again, not suppressed."""
        from podharvest.media_health import MediaHealth

        assert MediaHealth(ffmpeg=True).signature() != MediaHealth(ffmpeg=False).signature()

    def test_the_list_reads_aloud_rather_than_punctuates(self):
        from podharvest.media_health import _join

        assert _join(("one",)) == "one"
        assert _join(("one", "two")) == "one and two"
        assert _join(("one", "two", "three")) == "one, two and three"
        assert _join(()) == ""

    def test_check_never_raises(self):
        from podharvest import media_health

        assert isinstance(media_health.check().ffmpeg, bool)

    def test_it_is_said_once_and_reachable_when_asked(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui)
        assert "_report_media_health" in source
        assert "media_health_last_notice" in source
        assert "Media tools" in source


class TestBugReport:
    """podHarvest's promise is that what you listen to stays on your machine.

    A bug reporter that uploaded on your behalf would break that promise in
    the one place people would least expect it, so this one builds the report
    and hands it over. Nothing here touches the network.
    """

    def test_nothing_in_it_reaches_the_network(self):
        """The strongest claim in this module, so it is the one under test."""
        import ast
        from pathlib import Path

        from podharvest import feedback

        source = Path(feedback.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"urllib.request", "http", "requests", "socket", "podharvest.net"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name not in forbidden, f"{name} would let the report leave"

    def test_a_named_secret_is_removed_whatever_it_looks_like(self):
        from podharvest.feedback import redact

        assert "hunter2" not in redact("password = hunter2")
        assert "abc" not in redact("api_key: abc")

    def test_a_bare_key_is_removed_on_its_shape_alone(self):
        from podharvest.feedback import redact

        assert "sk-abc123def456ghi789jkl012mno345pq" not in redact(
            "Using sk-abc123def456ghi789jkl012mno345pq for this run")
        assert "0123456789abcdef0123456789abcdef" not in redact(
            "token 0123456789abcdef0123456789abcdef")

    def test_a_home_folder_does_not_name_the_person(self):
        from podharvest.feedback import redact

        out = redact(r"Writing to C:\Users\alice\Podcasts")
        assert "alice" not in out
        assert "Podcasts" in out, "the useful part of the path must survive"

    def test_email_addresses_are_removed(self):
        from podharvest.feedback import redact

        assert "@example.com" not in redact("write to me at bob@example.com")

    def test_the_report_says_what_matters(self, tmp_path):
        from podharvest.config import Settings
        from podharvest.feedback import build_report

        settings = Settings()
        settings.episode_limit = 5
        report = build_report(
            settings=settings,
            hardware_summary="8 cores, 16 GB",
            log_text="Started a run.",
            what_happened="It stopped after three episodes.",
        )
        assert "It stopped after three episodes." in report
        assert "8 cores, 16 GB" in report
        assert "episode_limit = 5" in report
        assert "Started a run." in report
        assert "FFmpeg" in report

    def test_only_changed_settings_are_reported(self):
        """The whole file would be noise, and would carry paths nobody needs."""
        from podharvest.config import Settings
        from podharvest.feedback import build_report

        report = build_report(settings=Settings(), log_text="x")
        assert "(all defaults)" in report

    def test_secret_settings_are_never_reported_even_when_changed(self):
        from podharvest.config import Settings
        from podharvest.feedback import build_report

        settings = Settings()
        settings.hf_token = "hf_abcdefghijklmnopqrstuvwxyz012345"
        report = build_report(settings=settings, log_text="x")
        assert "hf_token" not in report

    def test_the_mailto_goes_to_the_support_address(self):
        from podharvest import SUPPORT_EMAIL
        from podharvest.feedback import mailto_url

        url = mailto_url("a report")
        assert url.startswith(f"mailto:{SUPPORT_EMAIL}")

    def test_the_mailto_body_stays_short_enough_to_survive(self):
        """Mail clients truncate long bodies; the clipboard carries the rest."""
        from podharvest.feedback import mailto_url

        url = mailto_url("x" * 50_000)
        assert len(url) < 4_000

    def test_it_is_reachable_from_the_help_menu(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui)
        assert "Report a bug" in source
        assert "_BugReportDialog" in source
