#!/bin/bash

set -e
allowlist_git="https://git.launchpad.net/~oem-solutions-engineers/pc-enablement/+git/oem-gap-allow-list"
oem=""
platform=""
allowlst_folder=""
STATUS="pass"
clean() {
   rm -rf "$allowlst_folder"
   [ -z "$1" ] || exit "$1"
   [ "$STATUS" != "pass" ] && exit 1
   exit 0
}
prepare() {
    oem="$(grep -q sutton <(ubuntu-report show | grep DCD) && echo sutton)" ||\
    oem="$(grep -q stella <(ubuntu-report show | grep DCD) && echo stella)" ||\
    oem="$(grep -q somerville <(ubuntu-report show | grep DCD) && echo somerville)" ||\
    (>&2 echo "[ERROR][CODE]got an empty OEM codename in ${FUNCNAME[1]}" && clean 1)
    case "$oem" in
        "somerville")
            platform="$(ubuntu-report show | grep DCD | awk -F'+' '{print $2}')"
            ;;
        "sutton"|"stella")
            for pkg in $(dpkg-query -W -f='${Package}\n'  "oem-$oem.*-meta"); do
                _code_name=$(echo "${pkg}" | awk -F"-" '{print $3}')
                if [ "$_code_name" == "factory" ] ||
                    [ "$_code_name" == "meta" ]; then
                    continue
                fi
                oem="$(echo "$pkg" | cut -d'-' -f2 )"
                platform="$(echo "$pkg" | cut -d'-' -f3 )"
            done
            ;;
        *)
            >&2 echo "[ERROR][CODE]we should not be here in ${FUNCNAME[1]} : ${LINENO}" && clean 1
            ;;
    esac
    [ -z "$platform" ] && (>&2 echo "[ERROR][CODE]got an empty platform name for $oem in ${FUNCNAME[1]}" && clean 1)
    (sudo apt-get update > /dev/null || (>&2 echo "[ERROR]apt-get update failed, please check it." | exit 1)) && sudo apt-get install -y git > /dev/null
    echo "[INFO] getting allowlist from $allowlist_git."
    [ -n "$allowlist_git" ] &&\
    (git clone --depth=1 "$allowlist_git" || (>&2 echo "[ERROR]git clone ""$allowlist_git"" filed, please check it." | exit 1)) &&\
    allowlst_folder="$PWD"/"$(basename "$allowlist_git")"
    echo "[INFO] git hash of current allowlist: $(git -C "$allowlst_folder" rev-parse --short HEAD)"
}
pkg_need_allowing() {
    [ -z "$1" ] && >&2 echo "[ERROR][CODE]got an empty pkg in ${FUNCNAME[1]}" && clean 1
    >&2 echo "[ERROR] Please send a MP to $allowlist_git for manager review $1" && STATUS="failed"
}
pkg_need_update() {
    [ -z "$1" ] && >&2 echo "[ERROR][CODE]got an empty pkg in ${FUNCNAME[1]}" && clean 1
    >&2 echo "[ERROR] find a update-able pkg: $1 $2" && pkg_need_allowing "$1"
}
# return 0 for allowing
# return 1 for not allowing
if_allowing() {
    local allowed="NO"
    [ -z "$1" ] && >&2 echo "[ERROR][CODE]got an empty pkg in ${FUNCNAME[1]}" && clean 1

    # check if the pkg on allow list.
    for F in "$allowlst_folder"/testtools "$allowlst_folder"/common "$allowlst_folder"/"$oem"/common "$allowlst_folder"/"$oem"/"$platform"; do
       [ -f "$F" ] && while IFS= read -r green_light; do
       [ "$1" == "$green_light" ] && echo "[INFO] manager gave a greenlight for :" "$1" "$2" && allowed="YES"
       done < "$F"
    done
    if [ "$allowed" == "NO" ]; then
	   return 1
    else
	   return 0
    fi
}
pkg_not_public() {
    [ -z "$1" ] && >&2 echo "[ERROR][CODE]got an empty pkg in" "${FUNCNAME[1]}" && clean 1
    # check if the pkg on allow list.
    if_allowing "$1" || (>&2 echo "[ERROR] find a packge not on public archive:" "$1" "$2" && pkg_need_allowing "$1")
}
prepare
echo "[INFO] staring screen all installed packages."
while IFS= read -r pkgname; do
   progress=">""$progress"
   [ "${#progress}" == "70" ] && echo "$progress" && progress=""
   pkgver="$(dpkg-query -W -f='${Version}' "$pkgname")"
   pub_madison="$(apt-cache madison  "$pkgname")"
   can_pkgver="$(apt-cache policy  "$pkgname" | grep Candidate | awk '{print $2}')"
   if [ -z "${pkgname##oem-fix*}" ]; then
        if_allowing "$pkgname" || pkg_need_allowing "$pkgname"
   fi

   if [ -z "$pub_madison" ]; then
        pkg_not_public "$pkgname" "$pkgver"
   elif [ -n "${pub_madison##*$can_pkgver*}" ]; then
        pkg_not_public "$pkgname" "$pkgver"
   elif dpkg --compare-versions "$can_pkgver" "gt" "$pkgver"; then
        [ -z "${pkgver##*oem*}" ] || [ -z "${pkgver##*somerville*}" ] && pkg_need_update  "$pkgname" "$pkgver"
   fi
done < <(dpkg -l | grep 'ii' | awk '{print $2}')
clean
