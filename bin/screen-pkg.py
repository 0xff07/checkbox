#!/usr/bin/python3

import argparse
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

import lsb_release
from apt.cache import Cache
from apt.package import Package


class Platform(NamedTuple):
    oem: str  # somerville
    oem_series: str  # jellyfish
    platform_with_release: str  # jellyfish-abc
    platform_in_metapkg: str  # abc

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


def get_platform() -> Platform:
    oem = (
        subprocess.run(
            [
                "/usr/lib/plainbox-provider-pc-sanity/bin/get-oem-info.sh",
                "--oem-codename",
            ],
            stdout=subprocess.PIPE,
        )
        .stdout.strip()
        .decode("utf-8")
    )
    if oem is None:
        raise Exception("oem name not found by get-oem-info.sh.")

    platform = (
        subprocess.run(
            [
                "/usr/lib/plainbox-provider-pc-sanity/bin/get-oem-info.sh",
                "--platform-codename",
            ],
            stdout=subprocess.PIPE,
        )
        .stdout.strip()
        .decode("utf-8")
    )
    if platform is None:
        raise Exception("platform name not found by get-oem-info.sh.")

    # Since Ubuntu 22.04, there is no group layer
    sys_ubuntu_codename = lsb_release.get_distro_information()["CODENAME"]

    oem_ubuntu_codename = None
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

    return Platform(oem, oem_ubuntu_codename, platform_with_release, platform)


class PackageNameWithVersion(NamedTuple):
    name: str
    version: str

    def __str__(self):
        return f"{self.name} {self.version}"


class AllowedPackage(NamedTuple):
    package: Union[str, PackageNameWithVersion]
    source: str
    comment: Optional[str]

    def __str__(self):
        note = f"({self.source})"
        if self.comment is not None:
            note += f" ({self.comment})"

        return f"{self.package} {note}"


AllowListInternal = Dict[Union[str, PackageNameWithVersion], AllowedPackage]


class AllowList:
    allowlist: AllowListInternal

    def __init__(self, allowlist: AllowListInternal):
        self.allowlist = allowlist

    def get(self, pkg: PackageNameWithVersion):
        item = self.allowlist.get(pkg.name)
        if item is not None:
            return item

        item = self.allowlist.get(pkg)
        if item is not None:
            return item

        return None


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

    allowed_packages: AllowListInternal = {}
    for filename in [
        "testtools",
        "common",
        f"{platform.oem}/common",
        f"{platform.oem}/{platform.oem_series}-common",
        f"{platform.oem}/{platform.platform_with_release}",
    ]:
        try:
            with open(os.path.join(allowlist_path, filename)) as file:
                for line in file:
                    # allow putting comments in allowlist, either by # in the
                    # beginning of the line, or # after package name.  The
                    # latter format will be shown in the message.
                    pkg_name_split = line.split("#", 1)
                    pkg = pkg_name_split[0].strip()
                    comment = None
                    if len(pkg_name_split) >= 2:
                        comment = pkg_name_split[1].strip()
                    if pkg == "":
                        continue

                    pkg_ver_split = pkg.split(" ", 1)
                    if len(pkg_ver_split) >= 2:
                        pkg_name = pkg_ver_split[0].strip()
                        pkg_ver = pkg_ver_split[1].strip()
                        pkg = PackageNameWithVersion(pkg_name, pkg_ver)

                    allowed_packages[pkg] = AllowedPackage(
                        pkg, filename, comment
                    )
                print(f"# allowlist {filename} loaded")
        except FileNotFoundError:
            print(f"# allowlist {filename} not found")
            pass

    return (AllowList(allowed_packages), repo_hash)


def check_public_scanning(
    apt_cache: Cache, platform: Platform, allowlist: AllowList
) -> bool:
    metapkg_names = platform.get_metapkg_names()

    class PkgTuple(NamedTuple):
        k: PackageNameWithVersion
        pkg: Package

    pkgs_installed = [
        PkgTuple(PackageNameWithVersion(pkg.name, pkg.installed.version), pkg)
        for pkg in apt_cache
        if pkg.installed is not None
    ]

    pkgs_not_public = [
        item
        for item in pkgs_installed
        if not pkg_is_public(item.pkg) and item.k.name not in metapkg_names
    ]

    pkgs_not_allowed = [
        item for item in pkgs_not_public if allowlist.get(item.k) is None
    ]
    if pkgs_not_allowed:
        print(
            "\n"
            "The following packages are not in public archive. "
            "Please send an MP to\n"
            f"{ALLOWLIST_GIT_URL}\n"
            "to review by manager:"
        )
        for item in pkgs_not_allowed:
            print(f" - {item.k}")

    pkgs_metapkg_not_uploaded = [
        item
        for item in pkgs_installed
        if item.k.name in metapkg_names
        and not pkg_is_uploaded_metapkg(item.pkg, metapkg_names)
    ]
    if pkgs_metapkg_not_uploaded:
        print("\n" "The following metapackages are not uploaded:")
        for item in pkgs_metapkg_not_uploaded:
            print(f" - {item.k}")

    # TODO: Replace this in Python 3.8+ for Walrus (:=) operator:
    # pkgs_allowed = [
    #     allowlist_item
    #     for item in pkgs_not_public
    #     if (allowlist_item := allowlist.get(item.k)) is not None
    # ]
    pkgs_allowed = [
        allowlist_item
        for allowlist_item in [
            allowlist.get(item.k) for item in pkgs_not_public
        ]
        if allowlist_item is not None
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


def check_component_scanning(
    apt_cache: Cache, platform: Platform, allowlist: AllowList, only_manual: bool = True
) -> bool:
    metapkg_names = platform.get_metapkg_names()
    pkgs_filtered = [
        pkg
        for pkg in apt_cache
        if pkg.installed != None
        and ((not only_manual) or pkg_is_manually_installed(pkg))
        and not pkg_in_component(pkg, ["main", "restricted"])
        and pkg.name not in metapkg_names
    ]

    pkgs_not_allowed = [
        (
            pkg.name,
            pkg.installed.version,
            set(origin.component for origin in pkg.installed.origins),
        )
        for pkg in pkgs_filtered
        if pkg.name not in allowlist and pkg.installed != None
    ]
    if pkgs_not_allowed:
        print(
            f"""
The following packages are not in main or restricted component. Send an MP to
{ALLOWLIST_GIT_URL}
to review by manager:"""
        )
        for (name, version, components) in pkgs_not_allowed:
            components.remove("now")
            if len(components) == 0:
                components.add("local")
            components_str = ", ".join(components)
            print(f" - {name} {version} ({components_str})")

    pkgs_allowed = [
        allowpkg
        for pkg in pkgs_filtered
        if (allowpkg := allowlist.get(pkg.name)) != None and pkg.installed != None
    ]
    if pkgs_allowed:
        print(
            """
The following packages are not in main or restricted component, but greenlit
from manager:"""
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
            "security.ubuntu.com" in origin.site
            or "archive.ubuntu.com" in origin.site
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


def pkg_in_component(pkg: Package, components: List[str]) -> bool:
    ver = pkg.installed
    if ver and ver.origins[0].component == "now" and pkg.is_upgradable:
        # this package is upgradable to a package in the archive
        ver = pkg.candidate
    if ver == None:
        raise Exception("package is not installed")
    for origin in ver.origins:
        if origin.component in components:
            return True
    return False


def pkg_is_manually_installed(pkg: Package) -> bool:
    # either package is not auto_installed, or is auto_removable, so that
    # the listed pacakges are not installed by dependency.
    return (not pkg.is_auto_installed) or pkg.is_auto_removable


def check_public(args):
    apt_cache = Cache()

    print("# updating apt")
    apt_cache.update()
    apt_cache.open()

    platform = get_platform()
    print(f"# platform: {platform.oem}-{platform.platform_with_release}")

    print("# getting allowlist")
    (allowlist, repo_hash) = get_allowlist(platform, outdir=args.out)
    print(f"# allowlist hash: {repo_hash}")

    print("# scanning packages")
    ok = check_public_scanning(apt_cache, platform, allowlist)
    if not ok:
        sys.exit("# check-public FAIL")

    sys.exit()


def check_component(args):
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
    ok = check_component_scanning(
        apt_cache, platform, allowlist, only_manual=args.only_manual
    )
    if not ok:
        sys.exit("# check-component FAIL")

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
    subparsers.add_parser("check-public", help="Screen non-public packages")
    check_component_args_parser = subparsers.add_parser(
        "check-component", help="Screen packages not in main or restricted components"
    )
    check_component_args_parser.add_argument(
        "--only-manual",
        action="store_true",
        help="Only check packages that are manually installed",
    )
    args = parser.parse_args()

    if args.cmd == "check-public":
        check_public(args)
    elif args.cmd == "check-component":
        check_component(args)
