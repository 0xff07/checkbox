#!/usr/bin/env python3

import re
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Tuple, Callable, Optional, Dict
from html.parser import HTMLParser

# type aliases
DfsCbRtn = Tuple[bool, str]
DfsCb = Callable[[ET.Element, List[str]], DfsCbRtn]
TagGetter = Callable[[ET.Element], str]


class USNVulnInfo:
    def __init__(self, package: str, version: str, need_ubuntu_pro: bool):
        self.package = package
        self.version = version
        self.need_ubuntu_pro = need_ubuntu_pro

    def __repr__(self):
        additional = "(Ubuntu Pro)" if self.need_ubuntu_pro else ""
        return f"{self.package} - {self.version} {additional}"


class HTMLProjectionElement:
    def __init__(
        self,
        tag: str,
        classes: List[str],
        parent: Optional["HTMLProjectionElement"] = None,
    ):
        self.tag = tag
        self.classes = classes
        self.parent = parent
        self._text = ""

    @property
    def text(self) -> str:
        return self._text

    def append_text(self, text: str):
        self._text += text
        if self.parent is not None:
            self.parent.append_text(text)

    @property
    def is_plist(self) -> bool:
        return self.tag == "ul" and "p-list" in self.classes

    @property
    def is_plist_item(self) -> bool:
        return self.tag == "li" and "p-list__item" in self.classes

    @property
    def published_date(self) -> Optional[datetime]:
        if self.tag != "p" or "p-muted-heading" not in self.classes:
            return None
        try:
            rgx = re.compile(r"(\d+) (\w+) (\d+)")
            match = rgx.match(self.text)
            if match is None:
                return None
            day, month, year = match.groups()
            parsable = f"{day} {month[:3]} {year}"
            published = datetime.strptime(parsable, "%d %b %Y")
            return published
        except ValueError:
            return None

    @property
    def series(self) -> Optional[float]:
        if self.tag != "h5" or self.classes:
            return None
        parts = self.text.split(" ")
        if len(parts) != 2 or parts[0] != "Ubuntu":
            return None
        try:
            return float(parts[1])
        except ValueError:
            return None


class SentinelElement(HTMLProjectionElement):
    def __init__(self):
        super().__init__("", [], self)

    def append_text(self, _: str):
        pass


class USNParser(HTMLParser):
    IGNORED_TAGS = set(["script", "style", "script", "noscript", "svg"])
    UNCLOSED_TAGS = set(
        [
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "keygen",
            "link",
            "menuitem",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        ]
    )

    def __init__(self):
        self._stack: List[HTMLProjectionElement] = []
        self._series: Optional[float] = None
        # key: Ubuntu series, e.g. "22.04"
        self.vulns: Dict[float, List[USNVulnInfo]] = {}
        self.published_date: Optional[datetime] = None
        super().__init__()

    def handle_starttag(self, tag, attrs):
        parent = self._current or SentinelElement()
        if tag == "br":
            parent.append_text("\n")
            return

        if (
            parent.tag == "head"
            or tag in self.IGNORED_TAGS
            or tag in self.UNCLOSED_TAGS
        ):
            return

        classes = []
        for key, value in attrs:
            if key != "class" or value is None:
                continue
            classes = value.split(" ")
            break

        elem = HTMLProjectionElement(tag, classes, parent)
        self._stack.append(elem)

    def handle_endtag(self, tag):
        elem = self._current
        if (
            elem is None
            or (elem.tag == "head" and tag != "head")
            or tag in self.IGNORED_TAGS
            or tag in self.UNCLOSED_TAGS
        ):
            return

        if elem.tag != tag:
            raise ValueError(
                f"HTMLParser: tag mismatch, expect {elem.tag}, got {tag}"
            )
        self._stack.pop()

        published_date = elem.published_date
        if self.published_date is None and published_date is not None:
            self.published_date = published_date

        series = elem.series
        if series is not None:
            self._series = series
            self.vulns[series] = []

        if self._series is None:
            return

        if elem.is_plist:
            self._series = None
        elif elem.is_plist_item and elem.parent.is_plist:  # pyright: ignore[reportOptionalMemberAccess] # noqa: E501
            rgx = re.compile(
                "([^ \n]+)[ \n]+-[ \n]+([^ \n]+)[ \n]+"
                + "(Available with Ubuntu Pro)?"
            )
            match = rgx.search(elem.text)
            if match is None:
                raise ValueError(
                    "HTMLParser: p-list item text mismatch, "
                    + f"got [{elem.text}], "
                    + "the format of the USN page has changed!"
                )
            package, version, need_ubuntu_pro = match.groups()
            vuln = USNVulnInfo(package, version, need_ubuntu_pro is not None)
            self.vulns[self._series].append(vuln)

    def handle_data(self, data):
        current = self._current
        if current is None:
            return
        current.append_text(data)

    @property
    def _current(self) -> Optional[HTMLProjectionElement]:
        return self._stack[-1] if len(self._stack) > 0 else None


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def ns_skipper(html: ET.Element) -> TagGetter:
    rgx = re.compile(r"^({http[s]?://(www.|)w3.org/[\w+/]+})?html$")
    match = rgx.match(html.tag)
    if match is None:
        raise ValueError('Root element\'s tag should be "html"!')
    ns_prefix = match.group(1)

    def real_tag(elem: ET.Element) -> str:
        tag = elem.tag
        return tag.replace(ns_prefix, "")

    return real_tag


def identify(elem: ET.Element, tag_getter: Optional[TagGetter] = None) -> str:
    class_list = elem.attrib.get("class")
    tag = elem.tag if tag_getter is None else tag_getter(elem)
    class_parts = [] if class_list is None else class_list.split(" ")
    return ".".join([tag] + class_parts)


def dfs(elem: ET.Element, paths: List[str], cb: DfsCb) -> bool:
    early_stop, ident = cb(elem, paths)
    if early_stop:
        return True

    paths.append(ident)
    for child in elem:
        if dfs(child, paths, cb):
            paths.pop()
            return True

    paths.pop()
    return False


def main(
    report: str,
    buffer_days: int,
    ignore: Callable[[str], bool],
    series: float,
):
    tree = ET.parse(report)
    root = tree.getroot()
    real_tag = ns_skipper(root)

    head = None
    body = None

    for child in root:
        tag = real_tag(child)
        if tag == "head":
            head = child
        elif tag == "body":
            body = child

    if head is None or body is None:
        raise ValueError("Cannot locate <head> and <body> tags under <html>.")

    target_css = ["resultbadA", "resultbadB"]

    def has_css_classes(targets: List[str]) -> DfsCb:
        def validator(elem: ET.Element, paths: List[str]) -> DfsCbRtn:
            tag = real_tag(elem)
            if paths != ["html", "head"]:
                return False, tag
            if tag != "style":
                return False, tag
            for selector in (f".{t}" for t in targets):
                if elem.text is not None and elem.text.find(selector) < 0:
                    return False, tag
            return True, tag

        return validator

    is_valid = dfs(head, ["html"], has_css_classes(target_css))
    if not is_valid:
        raise ValueError(
            "Cannot find target css under <style>, it is very likely "
            + "that this script is outdated!"
        )

    has_vuln = False

    def peek_vuln(elem: ET.Element, paths: List[str]) -> DfsCbRtn:
        ident = identify(elem, real_tag)
        if (
            paths[-2:] != ["table", "tr.LightRow.Center"]
            or ident != "td.SmallText.resultbadB"
        ):
            return False, ident
        nonlocal has_vuln
        has_vuln = int(elem.text or 0) > 0
        if has_vuln:
            eprint(f'* {elem.attrib["title"]}: {elem.text}')
        return True, ident

    is_valid = dfs(body, ["html"], peek_vuln)
    if not is_valid:
        raise ValueError(
            "Cannot find target HTML element, it is very likely "
            + "that this script is outdated!"
        )
    if not has_vuln:
        print("All avaliable CVEs are patched!")
        sys.exit(0)

    vuln_idents = [f"tr.{c}" for c in target_css]

    def report_vuln(elem: ET.Element, paths: List[str]) -> DfsCbRtn:
        ident = identify(elem, real_tag)
        if paths[-1:] == ["table"] and ident in vuln_idents:
            if len(elem) > 0:
                eprint(elem[-1].text)
            if len(elem) > 1 and len(elem[-2]) > 0:
                anchor = elem[-2][0]
                report_vuln_detail(anchor, "\t")

        return False, ident

    def report_vuln_detail(elem: ET.Element, indent: str):
        from urllib import request

        if identify(elem, real_tag) != "a.Hover":
            return
        href = elem.attrib["href"]
        eprint(f"{indent}- {href}")
        if buffer_days == 0:
            return

        with request.urlopen(href) as fd:
            raw_html = fd.read().decode("utf-8")
        parser = USNParser()
        parser.feed(raw_html)

        if parser.published_date is None:
            raise ValueError("Cannot find published date!")

        need_fixing = False
        for vuln in parser.vulns.get(series, []):
            sign = "+"
            if ignore(vuln.package):
                sign = "-"
            elif not vuln.need_ubuntu_pro:
                need_fixing = True
            eprint(f"{indent}\t{sign} {vuln}")
        # end for vuln

        passed = datetime.now() - parser.published_date
        need_fixing = need_fixing and passed.days > buffer_days
        log_lvl = "ERROR" if need_fixing else "WARNING"
        display_date = parser.published_date.strftime("%d %B %Y")
        eprint(f"{indent}- [{log_lvl}] Published: {display_date}")

    dfs(body, ["html"], report_vuln)
    sys.exit(1)


def ignore_package(include_list_file: Optional[str]) -> Callable[[str], bool]:
    if include_list_file is None or not os.path.exists(include_list_file):
        return lambda _: False

    include_list = set()
    with open(include_list_file, "r") as fd:
        for line in fd:
            package = line.strip().split(":")[0]
            include_list.add(package)

    def ignore(package: str) -> bool:
        return package not in include_list

    return ignore


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="oval-report")
    parser.add_argument("--report", metavar="report.html", required=True)
    parser.add_argument("--buffer-days", type=int, default=7)
    parser.add_argument("--include-packages", metavar="dpkg.list")
    parser.add_argument("--series", type=float, default=22.04)
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.3.0"
    )

    args = parser.parse_args()
    main(
        args.report,
        args.buffer_days,
        ignore_package(args.include_packages),
        args.series,
    )
