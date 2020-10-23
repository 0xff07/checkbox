#!/usr/bin/env bash

# execute this test file by `bats test/test-screen-pkg-not-public.bat`
BIN_FOLDER="bin"

function if_allowing() {
    return 1
}

function setup() {
    source "$BIN_FOLDER"/screen-pkg-not-public.sh
    oem="somerville"
    platform="fossa-melisa"
}

function teardown() {
    >&2 echo "JOB_STATUS="$JOB_STATUS
}

@test "run_main() reflect the JOB_STATUS" {
    status_failed=1
    status_passed=0
    function screen_pkg(){
        return "$status_simulate"
    }
    function prepare(){
        echo "empty"
    }
    function clean(){
        echo "empty"
    }
    function dpkg(){
        echo "ii"
    }

    status_simulate=$status_passed
    # we expect it pass.
    run_main
    [ "$JOB_STATUS" == "pass" ]

    status_simulate=$status_failed
    # we expect it failed.
    run_main
    [ "$JOB_STATUS" == "failed" ]

}

function apt-cache() {
   case "$1" in
    "madison")
    echo "$aptcache_medison_string"
    ;;
    "policy")
    echo "$apt_cache_policy_string"
    ;;
    *)
    return 1;
    ;;
   esac
}

@test "allow pkgs came from ubuntu archive" {
    set -e
    aptcache_medison_string="
    ubuntu-desktop |    1.450.2 | http://archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages
    ubuntu-desktop |      1.450 | http://archive.ubuntu.com/ubuntu focal/main amd64 Packages
    "
    apt_cache_policy_string="\
    ubuntu-desktop:\
      Installed: 1.450.2\
      Candidate: 1.450.2\
      Version table:\
     *** 1.450.2 500\
            500 http://archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages\
            100 /var/lib/dpkg/status\
         1.450 500\
            500 http://archive.ubuntu.com/ubuntu focal/main amd64 Packages\
    "
    export -f apt-cache
    # we expect it passed.
    screen_pkg "ii  ubuntu-desktop                                1.450.2                                     amd64        The Ubuntu desktop system"
    [ "$?" == "0" ]
    unset -f apt-cache

}

@test "screen out pkgs we hacked" {
    set -e
    dpkg_list_string="ii  ubiquity                                      20.04.15.2somerville2                       amd64        Ubuntu live CD installer"
    aptcache_medison_string="
    ubiquity | 20.04.15.2 | http://archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages
    ubiquity |   20.04.15 | http://archive.ubuntu.com/ubuntu focal/main amd64 Packages
    "
    apt_cache_policy_string="
    ubiquity:
      Installed: 20.04.15.2somerville2
      Candidate: 20.04.15.2somerville2
      Version table:
     *** 20.04.15.2somerville2 100
            100 /var/lib/dpkg/status
         20.04.15.2 500
            500 http://archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages
         20.04.15 500
            500 http://archive.ubuntu.com/ubuntu focal/main amd64 Packages
    "
    export -f apt-cache
    # we expect it failed.
    ! screen_pkg "$dpkg_list_string"
    unset -f apt-cache
}

@test "screen out pkgs only in unexpected archive." {
    set -e
    dpkg_list_string="ii  fwts                                          20.09.00-0ubuntu1~f                         amd64        FirmWare Test Suite"
    aptcache_medison_string="
    fwts | 20.09.00-0ubuntu1~f | http://ppa.launchpad.net/checkbox-dev/ppa/ubuntu focal/main amd64 Packages
    fwts | 20.03.00-0ubuntu1 | http://archive.ubuntu.com/ubuntu focal/universe amd64 Packages
    "
    apt_cache_policy_string="
    fwts:
      Installed: 20.09.00-0ubuntu1~f
      Candidate: 20.09.00-0ubuntu1~f
      Version table:
     *** 20.09.00-0ubuntu1~f 500
            500 http://ppa.launchpad.net/checkbox-dev/ppa/ubuntu focal/main amd64 Packages
            100 /var/lib/dpkg/status
         20.03.00-0ubuntu1 500
            500 http://archive.ubuntu.com/ubuntu focal/universe amd64 Packages
    "

    export -f apt-cache
    # we expect it failed.
    ! screen_pkg "$dpkg_list_string"
    unset -f apt-cache
}

@test "screen out pkgs not in any archive." {
    set -e
    # we expect it failed.
    ! screen_pkg "ii  a-nonexisted-pkg                                1.187.3                                     all          Firmware for Linux kernel drivers"
    echo in bat: JOB_STATUS=$JOB_STATUS
}

@test "screen out pkgs only on oem archive." {
    dpkg_list_string="ii  pkg-only-on-oemarchive                                1.187.3                                     all          Firmware for Linux kernel drivers"
    aptcache_medison_string="
    pkg-only-on-oem-archive | 20.04ubuntu7 | http://dell.archive.canonical.com focal/somerville-melisa amd64 Packages
    "
    apt_cache_policy_string="
    pkg-only-on-oem-archive:
     Installed: 20.04ubuntu7
     Candidate: 20.04ubuntu7
     Version table:
    *** 20.04ubuntu7 500
    500 http://dell.archive.canonical.com focal/somerville-melisa amd64 Packages
    500 http://dell.archive.canonical.com focal/somerville-melisa i386 Packages
    "

    export -f apt-cache
    # we expect it failed.
    ! screen_pkg "$dpkg_list_string"
    unset -f apt-cache
}
