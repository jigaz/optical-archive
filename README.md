# The optical-disc archive

**[archive.krouton.app](https://archive.krouton.app)**

Everything someone would need to burn a CD, DVD or Blu-ray disc years from now, when the software that does it today is gone. That means the standards, the command sets drives speak, the file-system specifications, the open-source programs and drivers that actually work, the research on how long discs last and how to look after them, and dated notes on who still makes drives and blanks. It's kept by the [Krouton](https://krouton.app) project.

## What is kept, and what is only linked

| | Kept as a copy | Linked only |
|---|---|---|
| Ecma standards: ISO 9660, CD-ROM, CD-R/RW, DVD±R/RW, DVD-RAM, archival lifetime | ✓ Ecma lets anyone republish its standards unchanged | |
| UDF 1.02 to 2.60 (Ecma TR/112) | ✓ Ecma's alternative copyright license | |
| Open-source burning software (libburnia, dvd+rw-tools, cdrdao) | ✓ GPL | |
| Longevity and care studies by NIST and the Library of Congress | ✓ U.S. government works are in the public domain | |
| dvdisaster (error correction for disc images) | ✓ GPL | |
| Other preservation tools (QPxTool, sg3_utils, redumper, Aaru, schilytools, VideoLAN libraries) | | ✓ links to the maintained source, for now |
| Canadian Conservation Institute notes, journal articles, vendor test summaries | | ✓ copyright reserved |
| Community databases (AccurateRip drive offsets, Redump, MusicBrainz) and industry news | | ✓ |
| Kernel drivers (Linux, FreeBSD), Apple's SCSI family | | ✓ (large trees; links to the canonical source) |
| MMC (T10/INCITS) and Mt. Fuji (SNIA) | | ✓ sold, or copyright reserved |
| Apple and Microsoft developer documentation | | ✓ copyright reserved |
| Red Book, DVD Books, Blu-ray specifications | | ✓ sold or licensed; never copied |

A license decides the column, not convenience. When in doubt, an item is link-only.

## How it works

* [`catalog/catalog.json`](catalog/catalog.json) lists every item: where it's published, its license, and whether we may copy it.
* [`tools/archive.py`](tools/archive.py) (Python standard library only) validates the catalog, checks every link, mirrors the copyable items with SHA-256 checksums, asks the Wayback Machine to snapshot everything, and renders the site.
* [`.github/workflows/mirror.yml`](.github/workflows/mirror.yml) runs it monthly. Copies are published as a **release** (`mirror-YYYY-MM-DD`), with a `SHA256SUMS` file and notes on anything that changed upstream. The site links to `releases/latest/download/…`.
* `state/` records the last link check, the checksum of every copy, and the Wayback snapshots.
* [`drives/`](drives/) is the open record of how real drives behave.

```sh
python3 tools/archive.py validate
python3 tools/archive.py check      # needs network
python3 tools/archive.py mirror     # downloads into dist/
python3 tools/archive.py site       # rewrites docs/index.html
```

## Adding something

Add an entry to `catalog/catalog.json`, run `python3 tools/archive.py site`, and open a pull request. Say where the document is published and quote the part of its license that allows copying. If you can't, set `"hosting": "link"`.

## Licenses

The tools are MIT licensed ([LICENSE](LICENSE)). The catalog, the drive reports and the site text are dedicated to the public domain under CC0 1.0 ([LICENSE-DATA.md](LICENSE-DATA.md)). Every archived document and program keeps its own license, shown next to it in the catalog.
