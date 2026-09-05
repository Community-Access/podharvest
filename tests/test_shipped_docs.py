"""The documentation has to reach the people who install the app.

Both downloads used to disagree about this. The installer named its own
list of documents; the portable zip copied a README and nothing else. So
somebody who unzipped podHarvest got no changelog, no reference, and no
accessibility statement -- and REFERENCE.md linked to a SHARED.md that was
not there.

The build folder carries them now, and the installer copies that folder
wholesale, so there is one list instead of two that can drift.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")
ISS = (ROOT / "installer" / "podharvest.iss").read_text(encoding="utf-8")

#: What a person should find beside the app, however they got it.
EXPECTED_TOP = ("README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md")
EXPECTED_DOCS = ("GETTING_STARTED.md", "REFERENCE.md", "MODELS.md",
                 "ACCESSIBILITY.md", "SHARED.md")


class TestTheBuildCarriesThem:
    def test_the_top_level_files_are_copied(self):
        for name in EXPECTED_TOP:
            assert f'"{name}"' in BUILD, f"{name} is not copied into the build"

    def test_the_docs_are_copied(self):
        for name in EXPECTED_DOCS:
            assert f'"{name}"' in BUILD, f"docs/{name} is not copied"

    def test_every_named_document_actually_exists(self):
        """A build that names a missing file should be caught here, not there."""
        for name in EXPECTED_TOP:
            assert (ROOT / name).is_file(), name
        for name in EXPECTED_DOCS:
            assert (ROOT / "docs" / name).is_file(), f"docs/{name}"

    def test_a_missing_document_is_reported_rather_than_skipped(self):
        assert "Write-Warning" in BUILD


class TestTheInstallerDoesNotKeepASecondList:
    def test_it_does_not_name_the_docs_itself(self):
        """Two lists is how the zip and the installer drifted apart."""
        named = re.findall(r'^Source: "\.\.\\docs\\', ISS, flags=re.M)
        assert not named, "the installer should take docs from the build folder"

    def test_it_still_copies_the_build_folder_wholesale(self):
        assert r'Source: "..\dist\podharvest\*"' in ISS


class TestTheLinksInThemResolve:
    def test_reference_links_to_documents_that_ship(self):
        """A link to a file nobody ships is a dead end offline."""
        text = (ROOT / "docs" / "REFERENCE.md").read_text(encoding="utf-8")
        for target in re.findall(r"\]\((?!http)([A-Z_\-]+\.md)\)", text):
            assert (ROOT / "docs" / target).is_file(), target
            assert target in EXPECTED_DOCS or target == "CODE-REVIEW-2026-09.md", (
                f"REFERENCE.md links to {target}, which the build does not ship")
