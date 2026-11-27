# SPDX-License-Identifier: GPL-3.0-only
# Older mapping selection adapted from X-zant/Repak-X (GPL-3.0), revision
# 1bb9c9398305673bb8426f32ca191394257a9ed5, repak-x/src/vfx_updater/commands.rs.
# Modified for Atelier on 26 November 2026.
"""The recent SpaceDepot build mappings available to a single repair job."""
import json
import os
import re
import tempfile
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from atelier import config, jobs


_DEPOT = "https://api.github.com/repos/SpaceDepot/rivals-depot/contents/usmap"
_MAPPING_NAME = re.compile(r"5\.3\.2-\d+\+\+\+depot_marvel\+S\d+\.\d+_release-Marvel\.usmap")
_MAX_OLDER_BUILDS = 8
_MAGIC = b"\xc4\x30"


def _is_mapping(path):
    try:
        with open(path, "rb") as stream:
            return stream.read(2) == _MAGIC
    except OSError:
        return False


def _depot_mapping(entry):
    if not isinstance(entry, dict) or entry.get("type") != "file":
        return None
    name, url = entry.get("name"), entry.get("download_url")
    if not isinstance(name, str) or not _MAPPING_NAME.fullmatch(name) or not isinstance(url, str):
        return None
    try:
        location = urlsplit(url)
    except ValueError:
        return None
    path = unquote(location.path)
    if (location.scheme != "https" or location.netloc != "raw.githubusercontent.com"
            or not path.startswith("/SpaceDepot/rivals-depot/") or not path.endswith("/usmap/" + name)):
        return None
    return name, url


def _listing():
    request = Request(_DEPOT, headers={"User-Agent": "Atelier/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            listing = json.load(response)
        return listing if isinstance(listing, list) else []
    except (OSError, ValueError):
        return []  # Cached mappings still work offline.


def _download(url, destination):
    request = Request(url, headers={"User-Agent": "Atelier/1.0"})
    try:
        with urlopen(request, timeout=60) as response:
            data = response.read()
        if not data.startswith(_MAGIC):
            return None
        parent = os.path.dirname(destination)
        os.makedirs(parent, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".mapping-", dir=parent, delete=False) as stream:
                temporary = stream.name
                stream.write(data)
            os.replace(temporary, destination)
        finally:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)
    except OSError:
        return None
    return destination


class OlderMappings:
    def __init__(self, current):
        self.current = current
        self.directory = os.path.join(config.TOOLS, "Mappings")
        self.current_build = -1
        self.cached = None
        self.depot = None
        self.resolved = {}

    def _find_cached(self):
        self.current_build = config._usmap_build(self.current)
        if self.current_build < 0:
            self.current_build = config._game_build()
        if self.current_build < 0:
            return {}

        current_file = os.path.normcase(os.path.realpath(self.current))
        cached = {}
        directories = {self.directory, os.path.dirname(self.current)}
        for directory in sorted(directories - {""}):
            for path in sorted(config.dir_glob(directory, "*.usmap")):
                build = config._usmap_build(path)
                if (0 < build < self.current_build and _MAPPING_NAME.fullmatch(os.path.basename(path))
                        and build not in cached and os.path.normcase(os.path.realpath(path)) != current_file
                        and _is_mapping(path)):
                    cached[build] = path
        return cached

    def _find_depot(self):
        candidates = {}
        for entry in _listing():
            mapping = _depot_mapping(entry)
            if mapping:
                name, url = mapping
                build = config._usmap_build(name)
                if 0 < build < self.current_build and build not in self.cached:
                    candidates.setdefault(build, (os.path.join(self.directory, name), url))
        return [candidates[build] for build in sorted(candidates, reverse=True)]

    def paths(self):
        if self.cached is None:
            self.cached = self._find_cached()
        cached_builds = sorted(self.cached, reverse=True)[:_MAX_OLDER_BUILDS]
        for build in cached_builds:
            jobs.checkpoint()
            yield self.cached[build]

        remaining = _MAX_OLDER_BUILDS - len(cached_builds)
        if remaining == 0 or self.current_build < 0:
            return
        if self.depot is None:
            jobs.checkpoint()
            self.depot = self._find_depot()
        for path, url in self.depot[:remaining]:
            jobs.checkpoint()
            if path not in self.resolved:
                self.resolved[path] = path if _is_mapping(path) else _download(url, path)
            if self.resolved[path]:
                yield self.resolved[path]
