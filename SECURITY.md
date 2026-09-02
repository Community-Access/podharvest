# Security Policy

## Supported versions

The latest released version is supported. Fixes are made on `main` and released from there.

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/community-access/podharvest/security/advisories/new)
rather than opening a public issue.

Include what an attacker could achieve, the steps to reproduce, and the version and platform you tested on. You should get an initial response within a week.

## The trust model, and where the risk actually is

podHarvest fetches and parses **untrusted content**: feed XML from an arbitrary URL, and the enclosures that feed points at. Everything from a feed is treated as hostile input. The areas that matter most:

**Generated HTML.** Feed content is sanitized through an allow-list (`podharvest/convert.py`) before it is written into an archived page, and episode metadata is escaped separately in `podharvest/render.py`. Archived pages are typically opened from `file://`, so a script injection there runs with local-file privileges. Bypasses of `sanitize_html` or `is_dangerous_url` are in scope and are treated as high severity.

**Filesystem writes.** Feed values become folder and file names. `podharvest.util.safe_filename` and `slugify` guard against path traversal, Windows reserved device names, and over-long paths. A feed that can write outside its output directory is in scope.

**Network.** Only `http` and `https` are permitted, enforced in `podharvest.net.HttpClient`. Downloads are size-capped when `max_enclosure_mb` is set, and are verified against the length the server declared, so a truncated or duplicated transfer fails rather than being recorded as complete.

**XML parsing.** Feeds are parsed with `xml.etree.ElementTree`, which does not resolve external entities - but it is not hardened against entity-expansion ("billion laughs") denial of service. A hostile feed can therefore consume memory. If this matters in your deployment, run podHarvest only against feeds you trust, or install `defusedxml`. Hardening this is tracked as an open issue.

**On-demand package installation.** By design, podHarvest installs optional ASR and enrichment packages at first use with `pip install --target` into its own isolated folder (`podharvest/acquire.py`), never into your global environment. One install strategy adds an extra package index in order to obtain a prebuilt `llama-cpp-python` wheel on Windows. If you need a fully locked-down install, pre-install everything from `requirements-asr.txt` yourself; podHarvest uses whatever is already importable.

**Downloaded models** are checked for structural plausibility - expected filenames, size floors, magic bytes - rather than verified against pinned cryptographic hashes. Treat model downloads as carrying the trust of their upstream host. Hash pinning is an open enhancement.

## Out of scope

- Vulnerabilities in optional third-party ML dependencies. Please report those upstream.
- Denial of service from deliberately pointing the tool at a hostile feed, other than the XML expansion issue noted above, which is already acknowledged.
- The absence of a sandbox around locally-run model inference.
