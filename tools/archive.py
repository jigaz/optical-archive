#!/usr/bin/env python3
"""The optical-disc archive's one tool. Standard library only, so it still runs in ten years.

    archive.py validate          check catalog/catalog.json
    archive.py check             request every URL, resolve Ecma PDF links -> state/linkcheck.json
    archive.py mirror            download every hosting=copy item into dist/ with SHA-256 sums
    archive.py wayback           ask the Wayback Machine to snapshot every URL -> state/wayback.json
    archive.py site [--check]    render docs/index.html from the catalog and state

GitHub Actions runs check, mirror and wayback monthly (.github/workflows/mirror.yml), publishes
dist/ as a release, and commits state/ and docs/. Copies are linked through
releases/latest/download/<asset>, so the site never needs to know a release's name.
"""

import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog" / "catalog.json"
STATE = ROOT / "state"
DIST = ROOT / "dist"
DOCS = ROOT / "docs"
REPO = "jigaz/optical-archive"
AGENT = "krouton-optical-archive/1 (+https://archive.krouton.app)"
TIMEOUT = 60


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def load_state(name):
    path = STATE / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(name, data):
    STATE.mkdir(exist_ok=True)
    (STATE / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# MARK: - Validation


def validate(catalog):
    problems = []
    categories = {c["id"] for c in catalog["categories"]}
    seen = set()
    for item in catalog["items"]:
        where = item.get("id", "?")
        for field in ("id", "category", "title", "publisher", "url", "hosting", "license"):
            if not item.get(field):
                problems.append(f"{where}: missing {field}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", item.get("id", "")):
            problems.append(f"{where}: id must be lowercase letters, digits, dots and dashes")
        if item.get("id") in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(item.get("id"))
        if item.get("category") not in categories:
            problems.append(f"{where}: unknown category {item.get('category')!r}")
        if item.get("hosting") not in ("copy", "link"):
            problems.append(f"{where}: hosting must be copy or link")
        if not str(item.get("url", "")).startswith("https://"):
            problems.append(f"{where}: url must be https")
        if item.get("category") == "licensed" and item.get("hosting") == "copy":
            problems.append(f"{where}: licensed specifications are never copied")
    return problems


# MARK: - Network


def request(url, method="GET", limit=None, timeout=TIMEOUT, attempts=3):
    """GET (or HEAD) a URL. A server that says it is busy (429 or 503) is asked again after the
    wait it names, capped at two minutes, up to `attempts` times in all."""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read(limit) if limit else (b"" if method == "HEAD" else response.read())
                return response.status, response.geturl(), response.headers, body
        except urllib.error.HTTPError as error:
            if error.code not in (429, 503) or attempt == attempts:
                raise
            retry_after = error.headers.get("Retry-After", "")
            wait = min(int(retry_after), 120) if retry_after.isdigit() else 30 * attempt
            print(f"... {url}: HTTP {error.code}, trying again in {wait}s")
            time.sleep(wait)


def resolve_pdf(page_url, match):
    """The first PDF link on an Ecma standard's page whose URL contains `match`."""
    _, final, _, body = request(page_url)
    links = re.findall(r'href="([^"]+\.pdf)"', body.decode("utf-8", "replace"), flags=re.I)
    wanted = match.replace("-", "[-_]")
    for link in links:
        if re.search(wanted, link, flags=re.I):
            return urllib.parse.urljoin(final, html.unescape(link))
    return None


def check(catalog):
    results = {}
    for item in catalog["items"]:
        entry = {"checked": now()}
        try:
            status, final, headers, _ = request(item["url"], limit=1)
            entry.update(status=status, final_url=final, content_type=headers.get("Content-Type", ""))
            if item.get("fetch", {}).get("pdf_match"):
                entry["pdf_url"] = resolve_pdf(item["url"], item["fetch"]["pdf_match"])
                if not entry["pdf_url"]:
                    entry["problem"] = "no matching PDF link on the page"
        except (urllib.error.URLError, OSError, ValueError) as error:
            entry.update(status=getattr(error, "code", None), problem=str(error))
        results[item["id"]] = entry
        print(f"{'ok ' if not entry.get('problem') else 'BAD'} {item['id']}: {entry.get('problem') or entry.get('status')}")
        time.sleep(1)
    save_state("linkcheck", results)
    return sum(1 for e in results.values() if e.get("problem"))


# MARK: - Mirroring


def asset_name(item_id, url):
    name = Path(urllib.parse.urlparse(url).path).name or "download"
    name = re.sub(r"[^A-Za-z0-9._+-]", "_", urllib.parse.unquote(name))
    return f"{item_id}--{name}"


def keep_previous_copy(item_id, previous):
    """When upstream is gone, carry the last mirrored copy into the new release, so the site's
    releases/latest/download links keep working. Only a copy whose checksum still matches is kept."""
    if not previous:
        return False
    url = f"https://github.com/{REPO}/releases/latest/download/{previous['asset']}"
    try:
        _, _, _, body = request(url)
    except (urllib.error.URLError, OSError) as error:
        print(f"... {item_id}: previous copy unavailable: {error}")
        return False
    if hashlib.sha256(body).hexdigest() != previous["sha256"]:
        print(f"... {item_id}: previous copy does not match its checksum")
        return False
    (DIST / previous["asset"]).write_bytes(body)
    print(f"ok  {item_id}: upstream failed; kept the previous copy {previous['sha256'][:12]}")
    return True


def mirror(catalog):
    links = load_state("linkcheck")
    lock = load_state("lock")
    DIST.mkdir(exist_ok=True)
    failures, notes = 0, []
    for item in catalog["items"]:
        if item["hosting"] != "copy":
            continue
        primary = links.get(item["id"], {}).get("pdf_url") if item.get("fetch") else item["url"]
        candidates = [u for u in [primary, *item.get("fallback_urls", [])] if u]
        if not candidates:
            print(f"BAD {item['id']}: no source URL (run check first)")
            failures += 1
            continue
        body, source = None, None
        for candidate in candidates:
            try:
                _, _, _, body = request(candidate)
                source = candidate
                break
            except (urllib.error.URLError, OSError) as error:
                print(f"... {item['id']}: {candidate}: {error}")
        if body is None or source is None:
            if keep_previous_copy(item["id"], lock.get(item["id"])):
                notes.append(f"- {item['id']}: every source failed this month; the copy from the previous mirror is kept")
                continue
            print(f"BAD {item['id']}: every source failed")
            failures += 1
            continue
        name = asset_name(item["id"], source)
        (DIST / name).write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        previous = lock.get(item["id"], {})
        if previous.get("sha256") and previous["sha256"] != digest:
            notes.append(f"- {item['id']}: changed upstream (was {previous['sha256'][:12]}, now {digest[:12]})")
        lock[item["id"]] = {"asset": name, "source": source, "sha256": digest, "bytes": len(body), "fetched": now()}
        print(f"ok  {item['id']}: {len(body)} bytes {digest[:12]}")
        time.sleep(1)
    sums = "".join(f"{v['sha256']}  {v['asset']}\n" for _, v in sorted(lock.items()) if (DIST / v["asset"]).exists())
    (DIST / "SHA256SUMS").write_text(sums, encoding="utf-8")
    (DIST / "NOTES.md").write_text(
        "Verbatim copies of the redistributable items in catalog/catalog.json, with SHA-256 sums.\n\n"
        + ("\n".join(notes) if notes else "No item changed upstream since the previous mirror.") + "\n",
        encoding="utf-8",
    )
    save_state("lock", lock)
    return failures


# MARK: - Wayback Machine


def wayback(catalog):
    links = load_state("linkcheck")
    snapshots = load_state("wayback")
    urls = []
    for item in catalog["items"]:
        urls.append((item["id"], item["url"]))
        if links.get(item["id"], {}).get("pdf_url"):
            urls.append((item["id"] + ":pdf", links[item["id"]]["pdf_url"]))
    fresh_after = time.time() - 25 * 86400
    for key, url in urls:
        saved = snapshots.get(key, {})
        if saved.get("url") == url and saved.get("saved", "") >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(fresh_after)):
            continue  # snapshotted recently enough
        try:
            _, final, _, _ = request("https://web.archive.org/save/" + url, limit=1, timeout=45)
            snapshots[key] = {"url": url, "snapshot": final, "saved": now()}
            print(f"ok  {key}: {final}")
        except (urllib.error.URLError, OSError) as error:
            print(f"BAD {key}: {error}")
        time.sleep(20)  # the save API is rate-limited; be a polite guest
    save_state("wayback", snapshots)
    return 0


# MARK: - Site


def render(catalog):
    lock, links, snaps = load_state("lock"), load_state("linkcheck"), load_state("wayback")
    e = html.escape
    sections = []
    for category in catalog["categories"]:
        rows = []
        for item in (i for i in catalog["items"] if i["category"] == category["id"]):
            title = e(item["title"]) + (f' <span class="note">({e(item["aka"])})</span>' if item.get("aka") else "")
            original = f'<a href="{e(item["url"])}">{e(item["publisher"])}</a>'
            if item.get("home"):
                original += f'<br><a href="{e(item["home"])}">Project home</a>'
            if item["hosting"] == "copy" and item["id"] in lock:
                got = lock[item["id"]]
                copy = (f'<a class="kept" href="https://github.com/{REPO}/releases/latest/download/{e(got["asset"])}">'
                        f'Copy kept here</a><br><span class="note">{got["bytes"] // 1024:,} KB, SHA-256 {got["sha256"][:12]}…</span>')
            elif item["hosting"] == "copy":
                copy = '<span class="linked">Copy pending first mirror run</span>'
            else:
                copy = '<span class="linked">Link only</span>'
            snap = snaps.get(item["id"], {}).get("snapshot")
            if snap:
                copy += f'<br><a class="note" href="{e(snap)}">Wayback snapshot</a>'
            broken = links.get(item["id"], {}).get("problem")
            status = f'<br><span class="note">Last check: {e(broken)}</span>' if broken else ""
            notes = f'<br><span class="note">{e(item["notes"])}</span>' if item.get("notes") else ""
            rows.append(f"<tr><td>{title}{notes}</td><td>{original}<br><span class=\"note\">{e(item['license'])}</span></td>"
                        f"<td>{copy}{status}</td></tr>")
        sections.append(f'<h2 id="{e(category["id"])}">{e(category["title"])}</h2>\n<p>{e(category["about"])}</p>\n'
                        '<table class="wide catalog"><thead><tr><th scope="col">Item</th><th scope="col">Original and license</th>'
                        '<th scope="col">Here</th></tr></thead><tbody>\n' + "\n".join(rows) + "\n</tbody></table>")
    template = (ROOT / "tools" / "site-template.html").read_text(encoding="utf-8")
    kept = sum(1 for i in catalog["items"] if i["hosting"] == "copy")
    return (template.replace("{{SECTIONS}}", "\n\n".join(sections))
            .replace("{{COUNT}}", str(len(catalog["items"])))
            .replace("{{KEPT}}", str(kept)))


def site(catalog, check_only):
    out = DOCS / "index.html"
    page = render(catalog)
    if check_only:
        if not out.exists() or out.read_text(encoding="utf-8") != page:
            print("docs/index.html is out of date: run tools/archive.py site")
            return 1
        return 0
    out.write_text(page, encoding="utf-8")
    return 0


def main(argv):
    command = argv[1] if len(argv) > 1 else "validate"
    catalog = load_catalog()
    problems = validate(catalog)
    if problems:
        print("\n".join(problems))
        return 1
    if command == "validate":
        print(f"catalog ok: {len(catalog['items'])} items")
        return 0
    if command == "check":
        return 1 if check(catalog) and "--strict" in argv else 0
    if command == "mirror":
        return 1 if mirror(catalog) and "--strict" in argv else 0
    if command == "wayback":
        return wayback(catalog)
    if command == "site":
        return site(catalog, "--check" in argv)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
