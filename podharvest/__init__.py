"""podharvest - a rich, dependency-light RSS/Atom feed archiver.

Extracts every scrap of content from a feed (text, metadata, enclosures,
transcripts, chapters, artwork) and renders it as Markdown, accessible HTML,
plain text, JSON and CSV.
"""

__version__ = "1.0.0"

#: Canonical project home. Used in the HTTP User-Agent (so feed hosts can see
#: who is polling them and get in touch), the installer metadata, and the
#: packaging metadata - defined once here so there is a single place to change.
HOMEPAGE = "https://github.com/community-access/podharvest"

__all__ = ["__version__", "HOMEPAGE"]
