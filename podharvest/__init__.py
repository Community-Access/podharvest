"""podHarvest - a rich, dependency-light RSS/Atom feed archiver.

Extracts every scrap of content from a feed (text, metadata, enclosures,
transcripts, chapters, artwork) and renders it as Markdown, accessible HTML,
plain text, JSON and CSV.
"""

__version__ = "1.0.0"

#: How the name is written wherever a person will read or hear it. The camel
#: case is deliberate and load-bearing: a screen reader given "podharvest" says
#: it as one unpronounceable blob, while "podHarvest" is spoken as the two words
#: it actually is. The lowercase form stays as the import name, the console
#: command and the app-directory name, where it is typed rather than spoken and
#: where changing it would break existing installs.
DISPLAY_NAME = "podHarvest"

#: Canonical project home. Used in the HTTP User-Agent (so feed hosts can see
#: who is polling them and get in touch), the installer metadata, and the
#: packaging metadata - defined once here so there is a single place to change.
HOMEPAGE = "https://github.com/community-access/podharvest"
#: Where to write when something is wrong. Named here rather than typed
#: into a dialog so it is the same address everywhere it appears.
SUPPORT_EMAIL = "support@community-access.org"

__all__ = ["DISPLAY_NAME", "HOMEPAGE", "SUPPORT_EMAIL", "__version__"]
