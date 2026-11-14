#!/usr/bin/env python3
"""Offline format-1 checks for this repository's Git bundle index.

Only Python's standard library and read-only local Git commands are used.
This is not the DSH validator: npm-name, URL and SemVer syntax are conservative
local checks, not implementations of npm parsers or WHATWG URL serialization.
Only Git sources can have their manifest verified offline in this repository.
"""

import argparse
import base64
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urljoin, urlsplit


REPO = Path(__file__).resolve().parents[1]
INDEX_URL = "https://softdevfz.github.io/dsh-plugin-index/index.json"
LANGUAGE = re.compile(r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*")
NAME = re.compile(r"(?:@[a-z0-9-][a-z0-9._-]*/)?[a-z0-9-][a-z0-9._-]*")
NUMBER = r"(?:0|[1-9][0-9]*)"
IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SUFFIX = rf"(?:-{IDENTIFIER}(?:\.{IDENTIFIER})*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
SEMVER = re.compile(rf"{NUMBER}\.{NUMBER}\.{NUMBER}{SUFFIX}")
PARTIAL = rf"(?:{NUMBER}|[xX*])(?:\.(?:{NUMBER}|[xX*])){{0,2}}{SUFFIX}"
COMPARATOR = re.compile(rf"(?:[<>]=?|[=~^])?\s*v?{PARTIAL}")
DIRECTORY = re.compile(r"[A-Za-z0-9._@+-]+(?:/[A-Za-z0-9._@+-]+)*")


def require(condition, location, message):
    if not condition:
        raise ValueError(f"{location}: {message}")


def obj(value, location):
    require(isinstance(value, dict), location, "must be an object")
    return value


def array(value, location):
    require(isinstance(value, list), location, "must be an array")
    return value


def text(value, location):
    require(isinstance(value, str) and bool(value.strip()), location,
            "must be a non-blank string")
    return value


def localized(value, location):
    if isinstance(value, str):
        text(value, location)
        return
    obj(value, location)
    require("en" in value, location, "must contain en")
    for language, translation in value.items():
        require(LANGUAGE.fullmatch(language), location, "invalid lowercase language id")
        text(translation, f"{location}.{language}")


def directory(value, location):
    text(value, location)
    require(DIRECTORY.fullmatch(value) and
            all(segment not in (".", "..") for segment in value.split("/")),
            location, "must be a safe relative directory; . and .. are forbidden")


def web_url(value, location, git=False, plain=False):
    text(value, location)
    require(not re.search(r"[\s\\\x00-\x20\x7f]", value), location,
            "URL contains whitespace, a control character, or backslash")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ValueError(f"{location}: invalid URL: {error}") from error
    require(parts.scheme in (("https",) if git else ("http", "https")) and parts.hostname,
            location, "must be an absolute HTTP(S) URL (HTTPS for Git)")
    if plain or git:
        require(parts.username is None and parts.password is None and
                "?" not in value and "#" not in value, location,
                "credentials, query, and fragment are forbidden")
    if git:
        require(parts.netloc == parts.netloc.lower() and parts.hostname.isascii() and
                port != 443 and value.startswith("https://"), location,
                "must have canonical HTTPS spelling, host, and port")
        require(len([s for s in parts.path.split("/") if s]) >= 2 and
                not parts.path.endswith(("/", ".git", ".tgz", ".tar.gz")),
                location, "needs two path segments and no trailing /, .git, or tarball suffix")
        require(all(s not in (".", "..") and
                    s.lower() not in ("%2e", "%2e%2e", ".%2e", "%2e.")
                    for s in parts.path.split("/")) and
                not re.search(r"[^\x21-\x7e]|[\"<>`{}]|%(?![0-9a-fA-F]{2})", value),
                location, "must use canonical encoded URL path syntax")
    return parts


def semver_range(value, location):
    text(value, location)
    for branch in value.strip().split("||"):
        branch = branch.strip()
        require(bool(branch), location, "empty SemVer range branch")
        hyphen = re.fullmatch(rf"({PARTIAL})\s+-\s+({PARTIAL})", branch)
        if hyphen:
            continue
        tokens = re.sub(r"([<>]=?|[=~^])\s+", r"\1", branch).split()
        require(all(COMPARATOR.fullmatch(token) for token in tokens), location,
                "invalid or unsupported SemVer range syntax")


def git(*args):
    result = subprocess.run(
        ["git", "--no-optional-locks", "--no-replace-objects", "-C", str(REPO), *args],
        text=True, capture_output=True, check=False,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1"))
    if result.returncode:
        raise ValueError("local Git check failed: " + result.stderr.strip())
    return result.stdout


def declarations(root):
    metadata = obj(root.get("metadata", {}), "$.metadata")
    maps = {}
    for field in ("categories", "labels", "sortKeys"):
        location = f"$.metadata.{field}"
        maps[field] = obj(metadata.get(field, {}), location)
        for key, declaration in maps[field].items():
            text(key, location)
            item = obj(declaration, f"{location}.{key}")
            localized(item.get("title"), f"{location}.{key}.title")
            if field == "sortKeys":
                require(item.get("order") in ("asc", "desc"), location,
                        "sort order must be asc or desc")
    return maps


def plugin_metadata(value, maps, location):
    value = obj(value if value is not None else {}, location)
    category = value.get("category")
    require(category is None or isinstance(category, str) and category in maps["categories"],
            location, "undeclared category")
    labels = array(value.get("labels") if value.get("labels") is not None else [],
                   location + ".labels")
    require(all(isinstance(label, str) and label in maps["labels"] for label in labels) and
            len(labels) == len(set(labels)), location, "undeclared or duplicate labels")
    keywords = array(value.get("keywords") if value.get("keywords") is not None else [],
                     location + ".keywords")
    require(all(isinstance(word, str) for word in keywords), location, "keywords must be strings")
    values = obj(value.get("sortKeys") if value.get("sortKeys") is not None else {},
                 location + ".sortKeys")
    for key, metric in values.items():
        require(key in maps["sortKeys"], location, "undeclared sort key")
        require(metric is None or type(metric) in (int, float) and math.isfinite(metric),
                location, "sort values must be finite numbers or null")
        if metric is not None and key in ("github_stars", "npm_weekly_downloads"):
            require(type(metric) is int and metric >= 0, location, "count must be a nonnegative integer")


def icon(value, location):
    text(value, location)
    if value.startswith("data:"):
        match = re.fullmatch(r"data:image/(?:svg\+xml|png|jpeg|webp);base64,([A-Za-z0-9+/]*={0,2})", value)
        require(match, location, "invalid inline icon type or encoding")
        try:
            payload = base64.b64decode(match[1], validate=True)
        except ValueError as error:
            raise ValueError(f"{location}: invalid base64") from error
        require(base64.b64encode(payload).decode() == match[1] and len(payload) <= 32768,
                location, "base64 must be canonical and decoded icon at most 32 KiB")
    else:
        web_url(urljoin(INDEX_URL, value), location, git=False)
        require(urlsplit(urljoin(INDEX_URL, value)).scheme == "https", location,
                "icon must resolve to HTTPS for this HTTPS index")


def check(document):
    root = obj(document, "$")
    require(type(root.get("format")) is int and root["format"] == 1, "$.format", "must be integer 1")
    localized(root.get("title"), "$.title")
    if "description" in root:
        localized(root["description"], "$.description")
    maps = declarations(root)
    names = set()
    count = 0
    for i, plugin in enumerate(array(root.get("plugins"), "$.plugins")):
        p = f"$.plugins[{i}]"
        obj(plugin, p)
        name = text(plugin.get("name"), p + ".name")
        require(len(name) <= 214 and NAME.fullmatch(name) and
                name not in ("node_modules", "favicon.ico"), p + ".name",
                "invalid or unsupported new npm package name")
        require(name not in names, p + ".name", "duplicate package name")
        names.add(name)
        for field in ("title", "description"):
            if field in plugin:
                localized(plugin[field], p + "." + field)
        if "author" in plugin:
            text(plugin["author"], p + ".author")
        if "homepage" in plugin:
            web_url(plugin["homepage"], p + ".homepage")
        if "icon" in plugin:
            icon(plugin["icon"], p + ".icon")
        if "repository" in plugin:
            repository = obj(plugin["repository"], p + ".repository")
            web_url(repository.get("url"), p + ".repository.url", plain=True)
            if "directory" in repository:
                directory(repository["directory"], p + ".repository.directory")
        if "metadata" in plugin:
            plugin_metadata(plugin["metadata"], maps, p + ".metadata")
        versions = array(plugin.get("versions"), p + ".versions")
        require(bool(versions), p + ".versions", "must not be empty")
        seen = set()
        for j, version in enumerate(versions):
            v = f"{p}.versions[{j}]"
            obj(version, v)
            number = text(version.get("version"), v + ".version")
            require(SEMVER.fullmatch(number), v + ".version", "must be an exact SemVer version")
            require(number not in seen, v + ".version", "duplicate exact version")
            seen.add(number)
            timestamp = version.get("publishTimestamp")
            require(type(timestamp) is int and 0 <= timestamp < 10**11,
                    v + ".publishTimestamp", "must be integer Unix seconds in [0, 10^11)")
            engines = obj(version.get("engines"), v + ".engines")
            semver_range(engines.get("dsh"), v + ".engines.dsh")
            source = obj(version.get("source"), v + ".source")
            require(source.get("type") == "git", v + ".source.type",
                    "this offline repository checker requires a Git source with a local manifest")
            web_url(source.get("url"), v + ".source.url", git=True)
            commit = text(source.get("commit"), v + ".source.commit")
            require(re.fullmatch(r"[0-9a-f]{40}", commit), v + ".source.commit",
                    "must contain exactly 40 lowercase hexadecimal digits")
            subdir = source.get("path")
            if "path" in source:
                directory(subdir, v + ".source.path")
            require(git("cat-file", "-t", commit).strip() == "commit", v + ".source.commit",
                    "must name a local commit object")
            prefix = subdir + "/" if subdir is not None else ""
            manifest = obj(json.loads(git("show", f"{commit}:{prefix}package.json")), v + ".manifest")
            require(manifest.get("name") == name and manifest.get("version") == number,
                    v + ".manifest", "pinned package name/version must equal index")
            require(obj(manifest.get("engines"), v + ".manifest.engines").get("dsh") == engines["dsh"],
                    v + ".engines.dsh", "must copy the pinned manifest unchanged")
            require(int(git("show", "-s", "--format=%ct", commit)) == timestamp,
                    v + ".publishTimestamp", "must equal the pinned commit's committer time")
            require(manifest.get("private") is not True, v + ".manifest.private", "private bundle")
            bundle = obj(obj(manifest.get("dsh"), v + ".manifest.dsh").get("bundle"),
                         v + ".manifest.dsh.bundle")
            patch = text(bundle.get("patch"), v + ".manifest.dsh.bundle.patch")
            directory(patch.removeprefix("./"), v + ".manifest.dsh.bundle.patch")
            require(git("cat-file", "-t", f"{commit}:{prefix}{patch.removeprefix('./')}").strip() == "blob",
                    v + ".manifest.dsh.bundle.patch", "patch must be a file in the pinned tree")
            count += 1
        if "dist-tags" in plugin:
            for tag, target in obj(plugin["dist-tags"], p + ".dist-tags").items():
                require(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9._-]*", tag) and
                        isinstance(target, str) and target in seen, p + ".dist-tags",
                        "invalid or unsupported tag name, or unlisted exact target")
    return len(names), count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=Path, default=REPO / "index.json")
    args = parser.parse_args()
    try:
        plugins, versions = check(json.loads(args.index.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"OK: {plugins} plugin(s), {versions} version(s); format and local pinned manifest checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
