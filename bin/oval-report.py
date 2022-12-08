#!/usr/bin/env python3

import sys
import xml.etree.ElementTree as ET
from typing import List, Tuple, Callable

# type aliases
DfsCbRtn = Tuple[bool, str]
DfsCb = Callable[[ET.Element, List[str]], DfsCbRtn]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def ns_skipper(html: ET.Element) -> Callable[[ET.Element], str]:
    import re

    rgx = re.compile(r"^({http[s]?://(www.|)w3.org/[\w+/]+})?html$")
    match = rgx.match(html.tag)
    if match is None:
        raise ValueError('Root element\'s tag should be "html"!')
    ns_prefix = match.group(1)

    def real_tag(elem: ET.Element) -> str:
        tag = elem.tag
        return tag.replace(ns_prefix, "")

    return real_tag


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


def main(report: str):
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
                if elem.text.find(selector) < 0:
                    return False, tag
            return True, tag

        return validator

    is_valid = dfs(head, ["html"], has_css_classes(target_css))
    if not is_valid:
        raise ValueError(
            "Cannot find target css under <style>, it is very likely "
            + "that this script is outdated!"
        )

    def identify(elem: ET.Element) -> str:
        class_list = elem.attrib.get("class")
        tag = real_tag(elem)
        class_parts = [] if class_list is None else class_list.split(" ")
        return ".".join([tag] + class_parts)

    has_vuln = False

    def peek_vuln(elem: ET.Element, paths: List[str]) -> DfsCbRtn:
        ident = identify(elem)
        if (
            paths[-2:] != ["table", "tr.LightRow.Center"]
            or ident != "td.SmallText.resultbadB"
        ):
            return False, ident
        nonlocal has_vuln
        has_vuln = int(elem.text) > 0
        if has_vuln:
            eprint(f'[ERROR] {elem.attrib["title"]}: {elem.text}')
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
        ident = identify(elem)
        if paths[-1:] == ["table"] and ident in vuln_idents:
            if len(elem) > 0:
                eprint(elem[-1].text)
            if len(elem) > 1 and len(elem[-2]) > 0:
                anchor = elem[-2][0]
                if identify(anchor) == "a.Hover":
                    eprint(f"\t- {anchor.attrib['href']}")

        return False, ident

    dfs(body, ["html"], report_vuln)
    sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="oval-report")
    parser.add_argument("--report", metavar="report.html", required=True)
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.1.0"
    )
    args = parser.parse_args()
    main(args.report)
