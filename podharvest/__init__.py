"""podHarvest - a rich, dependency-light RSS/Atom feed archiver.

Extracts every scrap of content from a feed (text, metadata, enclosures,
transcripts, chapters, artwork) and renders it as Markdown, accessible HTML,
plain text, JSON and CSV.
"""

__version__ = "1.1.0"

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

__all__ = ["DISPLAY_NAME", "HOMEPAGE", "__version__"]
