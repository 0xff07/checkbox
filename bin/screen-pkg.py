#!/usr/bin/python3

import argparse
import os
import re
import shutil
import subprocess
import sys
import lsb_release
from typing import Dict, List, NamedTuple, Optional, Tuple

from apt.cache import Cache
from apt.package import Package


class Platform(NamedTuple):
    oem: str                    # somerville
    platform_with_release: str  # fossa-abc
    platform_in_metapkg: str    # abc

    def get_metapkg_names(self):
        return [
            f"oem-{self.oem}-meta",
            f"oem-{self.oem}-factory-meta",
            f"oem-{self.oem}-{self.platform_in_metapkg}-meta",
            f"oem-{self.oem}-factory-{self.platform_in_metapkg}-meta",
        ]


oem_re = re.compile(r"canonical-oem-(\w+)-")
somerville_platform_re = re.compile(r"\+([\w-]+)\+")

ALLOWLIST_GIT_URL = "https://git.launchpad.net/~oem-solutions-engineers/pc-enablement/+git/oem-gap-allow-list"  # noqa: E501


def get_platform(apt_cache: Cache) -> Platform:
    oem = subprocess.run(
        ["/usr/lib/plainbox-provider-pc-sanity/bin/get-oem-info.sh",
         "--oem-codename"],
        stdout=subprocess.PIPE).stdout.strip().decode("utf-8")
    if oem is None:
        raise Exception("oem name not found by get-oem-info.sh.")

    platform = subprocess.run(
        ["/usr/lib/plainbox-provider-pc-sanity/bin/get-oem-info.sh",
         "--platform-codename"],
        stdout=subprocess.PIPE).stdout.strip().decode("utf-8")
    if platform is None:
        raise Exception("platform name not found by get-oem-info.sh.")

    # Since Ubuntu 22.04, there is no group layer
    sys_ubuntu_codename = lsb_release.get_distro_information()['CODENAME']

    if sys_ubuntu_codename == "focal":
        oem_ubuntu_codename = "fossa"
    elif sys_ubuntu_codename == "jammy":
        oem_ubuntu_codename = "jellyfish"
    if oem_ubuntu_codename is None:
        raise Exception("oem ubuntu codename is empty.")

    if oem == "somerville":
        platform_with_release = oem_ubuntu_codename + "-" + platform
    else:
        # non-somerville
        # In 20.04, allowing list is read from
        # stella.cmit/abc
        # in 22.04, allowing list is read from
        # stella/jellyfish-abc
        if sys_ubuntu_codename == "focal":
            platform_with_release = platform
        else:
            # Since 22.04, seperate allowing packages by release.
            platform_with_release = oem_ubuntu_codename + "-" + platform
    if platform_with_release is None:
        raise Exception("platform_with_release is empty.")

    return Platform(oem, platform_with_release, platform)


class AllowedPackage(NamedTuple):
    package: str
    source: str
    comment: Optional[str]

    def __str__(self):
        if self.comment is not None:
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

    cmd = ["git", "clone", "--depth=1", ALLOWLIST_GIT_URL, allowlist_path]
    subprocess.run(cmd)
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
        f"{platform.oem}/{platform.platform_with_release}",
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
    pkgs_installed = [pkg for pkg in apt_cache if pkg.installed is not None]
    pkgs_not_public = [
        pkg
        for pkg in pkgs_installed
        if not pkg_is_public(pkg) and pkg.name not in metapkg_names
    ]

    pkgs_not_allowed = [
        (pkg.name, pkg.installed.version)
        for pkg in pkgs_not_public
        if pkg.name not in allowlist and pkg.installed is not None
    ]
    if pkgs_not_allowed:
        print(
            "\n"
            "The following packages are not in public archive."
            "Please send an MP to\n"
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
        and pkg.installed is not None
    ]
    if pkgs_metapkg_not_uploaded:
        print("\n" "The following metapackages are not uploaded:")
        for (name, version) in pkgs_metapkg_not_uploaded:
            print(f" - {name} {version}")

    pkgs_allowed = [
        allowlist[pkg.name] for pkg in pkgs_not_public if pkg.name in allowlist
    ]
    if pkgs_allowed:
        print(
            "\n"
            "The following packages are not in public archive, "
            "but greenlit from manager:"
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
    if ver is None:
        raise Exception("package is not installed")
    for origin in ver.origins:
        if (
            "security.ubuntu.com" in origin.site or
            "archive.ubuntu.com" in origin.site
        ) and origin.trusted:
            return True
    return False


def pkg_is_uploaded_metapkg(pkg: Package, metapkg_names: List[str]) -> bool:
    ver = pkg.installed
    if ver and ver.origins[0].component == "now" and pkg.is_upgradable:
        # this package is upgradable to a package in the archive
        # XXX: should we look up for the newer package in the archive?
        ver = pkg.candidate
    if ver is None:
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
    print(f"# platform: {platform.oem}-{platform.platform_with_release}")

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
