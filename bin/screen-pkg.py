#!/usr/bin/python3

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, NamedTuple, Optional, Tuple

from apt.cache import Cache
from apt.package import Package


class Platform(NamedTuple):
    oem: str
    platform: str
    platform_in_metapkg: str

    def get_metapkg_names(self):
        return [
            f"oem-{self.oem}-meta",
            f"oem-{self.oem}-factory-meta",
            f"oem-{self.oem}-{self.platform_in_metapkg}-meta",
            f"oem-{self.oem}-factory-{self.platform_in_metapkg}-meta",
        ]


oem_re = re.compile(r"canonical-oem-(\w+)-")
somerville_platform_re = re.compile(r"\+([\w-]+)\+")

ALLOWLIST_GIT_URL = "https://git.launchpad.net/~oem-solutions-engineers/pc-enablement/+git/oem-gap-allow-list"


def get_platform(apt_cache: Cache) -> Platform:
    report_json = subprocess.run(
        ["ubuntu-report", "show"], stdout=subprocess.PIPE
    ).stdout
    report = json.loads(report_json)
    try:
        dcd = report["OEM"]["DCD"]
    except KeyError:
        raise Exception(
            "DCD entry in ubuntu-report not found; required to look up for OEM name"
        )
    oem_match = oem_re.match(dcd)
    if oem_match == None:
        raise Exception("OEM name not found in DCD entry")
    oem = oem_match[1]

    if oem == "somerville":
        platform_match = somerville_platform_re.search(dcd)
        if platform_match == None:
            raise Exception("platform name not found in DCD entry")
        platform = platform_match[1]
        platform_in_metapkg = platform.split("-", 1)[1]
        return Platform(oem, platform, platform_in_metapkg)

    # search for something like oem-stella.cmit-marowak-meta, without -factory in it
    oem_meta_pkg_match = re.compile(
        r"oem-%s[^-]+(?!-factory)-[\w-]+-meta$" % re.escape(oem)
    )
    names = [
        pkg.shortname.split("-")
        for pkg in apt_cache
        if pkg.installed and oem_meta_pkg_match.match(pkg.shortname)
    ]
    if len(names) < 1:
        raise Exception("platform meta package is not installed")
    names = names[0]
    return Platform(names[1], names[2], names[2])


class AllowedPackage(NamedTuple):
    package: str
    source: str
    comment: Optional[str]

    def __str__(self):
        if self.comment != None:
            return f"{self.package} ({self.source}) ({self.comment})"
        return f"{self.package} ({self.source})"


AllowList = Dict[str, AllowedPackage]


def get_allowlist(
    platform: Platform,
    outdir: str = os.getcwd(),
) -> Tuple[AllowList, str]:
    allowlist_path = os.path.join(outdir, "oem-gap-allow-list")
    try:
        shutil.rmtree(allowlist_path)
    except FileNotFoundError:
        pass

    subprocess.run(["git", "clone", "--depth=1", ALLOWLIST_GIT_URL, allowlist_path])
    repo_hash = (
        subprocess.run(
            ["git", "-C", allowlist_path, "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
        )
        .stdout.decode("utf-8")
        .rstrip()
    )

    allowed_packages = {}
    for filename in [
        "testtools",
        "common",
        f"{platform.oem}/common",
        f"{platform.oem}/{platform.platform}",
    ]:
        try:
            with open(os.path.join(allowlist_path, filename)) as file:
                for pkg_name in file:
                    # allow putting comments in allowlist, either by # in the
                    # beginning of the line, or # after package name.  The
                    # latter format will be shown in the message.
                    pkg_name_split = pkg_name.split("#", 1)
                    pkg_name = pkg_name_split[0].strip()
                    comment = None
                    if len(pkg_name_split) >= 2:
                        comment = pkg_name_split[1].strip()
                    if pkg_name == "":
                        continue
                    allowed_packages[pkg_name] = AllowedPackage(
                        pkg_name, filename, comment
                    )
        except FileNotFoundError:
            pass

    return (allowed_packages, repo_hash)


def check_public_scanning(
    apt_cache: Cache, platform: Platform, allowlist: AllowList
) -> bool:
    metapkg_names = platform.get_metapkg_names()
    pkgs_installed = [pkg for pkg in apt_cache if pkg.installed != None]
    pkgs_not_public = [
        pkg
        for pkg in pkgs_installed
        if not pkg_is_public(pkg) and pkg.name not in metapkg_names
    ]

    pkgs_not_allowed = [
        (pkg.name, pkg.installed.version)
        for pkg in pkgs_not_public
        if pkg.name not in allowlist and pkg.installed != None
    ]
    if pkgs_not_allowed:
        print(
            "\n"
            "The following packages are not in public archive. Please send an MP to\n"
            f"{ALLOWLIST_GIT_URL}\n"
            "to review by manager:"
        )
        for (name, version) in pkgs_not_allowed:
            print(f" - {name} {version}")

    pkgs_metapkg_not_uploaded = [
        (pkg.name, pkg.installed.version)
        for pkg in pkgs_installed
        if pkg.name in metapkg_names
        and not pkg_is_uploaded_metapkg(pkg, metapkg_names)
        and pkg.installed != None
    ]
    if pkgs_metapkg_not_uploaded:
        print("\n" "The following metapackages are not uploaded:")
        for (name, version) in pkgs_metapkg_not_uploaded:
            print(f" - {name} {version}")

    pkgs_allowed = [
        allowpkg
        for pkg in pkgs_not_public
        if (allowpkg := allowlist.get(pkg.name)) != None
    ]
    if pkgs_allowed:
        print(
            "\n"
            "The following packages are not in public archive, but greenlit from manager:"
        )
        for allowpkg in pkgs_allowed:
            print(f" - {allowpkg}")

    print()

    return len(pkgs_not_allowed) == 0


def pkg_is_public(pkg: Package) -> bool:
    ver = pkg.installed
    if ver and ver.origins[0].component == "now" and pkg.is_upgradable:
        # this package is upgradable to a package in the archive
        ver = pkg.candidate
    if ver == None:
        raise Exception("package is not installed")
    for origin in ver.origins:
        if (
            "security.ubuntu.com" in origin.site or "archive.ubuntu.com" in origin.site
        ) and origin.trusted:
            return True
    return False


def pkg_is_uploaded_metapkg(pkg: Package, metapkg_names: List[str]) -> bool:
    ver = pkg.installed
    if ver and ver.origins[0].component == "now" and pkg.is_upgradable:
        # this package is upgradable to a package in the archive
        # XXX: should we look up for the newer package in the archive?
        ver = pkg.candidate
    if ver == None:
        raise Exception("package is not installed")
    if pkg.name not in metapkg_names:
        return False
    for origin in ver.origins:
        if "archive.canonical.com" in origin.site and origin.trusted:
            return True
    return False


def check_public(args):
    apt_cache = Cache()

    print("# updating apt")
    apt_cache.update()
    apt_cache.open()

    platform = get_platform(apt_cache)
    print(f"# platform: {platform.oem}-{platform.platform}")

    print("# getting allowlist")
    (allowlist, repo_hash) = get_allowlist(platform, outdir=args.out)
    print(f"# allowlist hash: {repo_hash}")

    print("# scanning packages")
    ok = check_public_scanning(apt_cache, platform, allowlist)
    if not ok:
        sys.exit("# check-public FAIL")

    sys.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=os.getcwd(),
        help="Define the folder for generated data. The default is $PWD",
    )
    subparsers = parser.add_subparsers(
        metavar="command",
        dest="cmd",
        required=True,
    )
    subparsers.add_parser("check-public", help="screen non-public packages")
    args = parser.parse_args()

    if args.cmd == "check-public":
        check_public(args)
