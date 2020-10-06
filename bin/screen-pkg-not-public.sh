#!/bin/bash

set -e
pkg_pass="0"
pkg_failed="1"
allowlist_git="https://git.launchpad.net/~oem-solutions-engineers/pc-enablement/+git/oem-gap-allow-list"
pf_meta_pkg=""
pf_factory_meta_pkg=""
oem=""
platform=""
allowlst_folder=""
JOB_STATUS="pass"
clean() {
   rm -rf "$allowlst_folder"
   [ -z "$1" ] || exit "$1"
   [ "$JOB_STATUS" != "pass" ] && exit 1
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
    pf_meta_pkg="$(dpkg -S /etc/apt/sources.list.d/oem-"${oem}"-*-meta.list | awk '{print $1}' | sed 's/://Ig')" || pf_meta_pkg=""
    pf_factory_meta_pkg="${pf_meta_pkg/oem-${oem}-/oem-${oem}-factory-}" || pf_factory_meta_pkg=""
    echo "[INFO] getting allowlist from $allowlist_git."
    [ -n "$allowlist_git" ] &&\
    allowlst_folder="$PWD"/"$(basename "$allowlist_git")" &&\
    rm -rf $allowlst_folder &&\
    (git clone --depth=1 "$allowlist_git" || (>&2 echo "[ERROR]git clone ""$allowlist_git"" failed, please check it." | exit 1))
    echo "[INFO] git hash of current allowlist: $(git -C "$allowlst_folder" rev-parse --short HEAD)"
}
pkg_need_allowing() {
    [ -z "$1" ] && >&2 echo "[ERROR][CODE]got an empty pkg in ${FUNCNAME[1]}" && clean 1
    >&2 echo "[ERROR] Please send a MP to $allowlist_git for manager review $1" && JOB_STATUS="failed"
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
    if_allowing "$1" || (>&2 echo "[ERROR] find a packge not on public archive:" "$1" "$2" && pkg_need_allowing "$1" && return $pkg_failed)
}
screen_pkg() {
    [ -n "$1" ] || (>&2 echo "[ERROR][CODE]got an empty input in" "${FUNCNAME[1]}" && clean 1)
    line="$1"
        pkg_name="$(echo "${line}" | awk '{print $2}')"
        pkg_ver="$(echo "${line}" | awk '{print $3}')"
        pkg_curr_madison="$(apt-cache madison "${pkg_name}" | grep "$pkg_ver" || true)"
        # FIXME: I don't think the upgradable is need to in "id: miscellanea/screen-pkg-not-public"
        # Should have the other something like "id: miscellanea/check-oem-pkg-updatable"
        # Remove this section can speed up this test scope
        # Alarm if package is old
        # TODO: detect somerville only?
        if [ -z "${pkg_ver##*oem*}" ] || [ -z "${pkg_ver##*somerville*}" ]; then
            if if_allowing "$pkg_name"; then
                return $pkg_pass
            else
                can_pkg_ver="$(apt-cache policy "$pkg_name" | grep Candidate | awk '{print $2}')"
                if dpkg --compare-versions "$can_pkg_ver" "gt" "$pkg_ver"; then
                    pkg_need_update "$pkg_name" "$pkg_ver"
                fi
            fi
        fi
    
        # If empty then meaning on one know where is this package come from
        # (e.g. a package only in CESG)
        if [ -z "${pkg_curr_madison}" ]; then
            can_pkg_ver="$(apt-cache policy "$pkg_name" | grep Candidate | awk '{print $2}')"
            pkg_can_madison="$(apt-cache madison "${pkg_name}" | grep "$can_pkg_ver" || true)"
            # If the candidate version is from ubuntu-archive then it'll be
            #  covered by SRU process.
            if [ -n "${pkg_can_madison}" ] &&
                { [ -z "${pkg_can_madison##*security.ubuntu.com/ubuntu*}" ] ||
                [ -z "${pkg_can_madison##*archive.ubuntu.com/ubuntu*}" ]; }; then
                return $pkg_pass
            fi
            pkg_not_public "$pkg_name" "$pkg_ver" || return $pkg_failed
        fi
    
        # If the installed package is from ubuntu-archive then we're good
        # (no matter which version is candidate because we expected the
        #  all source list are under control at lease before GM)
        if [ -z "${pkg_curr_madison##*security.ubuntu.com/ubuntu*}" ] ||
            [ -z "${pkg_curr_madison##*archive.ubuntu.com/ubuntu*}" ]; then
            >&2 echo "echo [INFO] perfect passs"
            #return $pkg_pass
            return 0
        fi
    
        # If the installed package is from canonical-archive then we need to
        #  make sure the packages were review.
        if [ -z "${pkg_curr_madison##*archive.canonical.com*}" ]; then
            # If the package is platform meta package then it should be control by meta generator
            if [ "$pkg_name" == "$pf_meta_pkg" ] || [ "$pkg_name" == "$pf_factory_meta_pkg" ]; then
                return $pkg_pass
            fi
            # Otherwise, need to review
            pkg_not_public "$pkg_name" "$pkg_ver" || return $pkg_failed
        fi
        # For unkown source of package (e.g. from a ppa), then review
        pkg_not_public "$pkg_name" "$pkg_ver" || return $pkg_failed
        #if [ "$JOB_STATUS" = "pass" ]; then
        #    >&2 echo "function failed."
        #    return $pkg_failed
        #else
        #    >&2 echo "function passed."
        #fi
}

run_main() {
    prepare
    >&2 echo "[INFO] staring screen all installed packages."
    while IFS= read -r line; do
        progress=">""$progress"
        [ "${#progress}" == "70" ] && echo "$progress" && progress=""
        screen_pkg $line
    done < <(dpkg -l | grep 'ii')
    clean
}
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  >&2 echo "entering run_main"
  run_main
fi
