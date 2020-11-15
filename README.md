# Plainbox Provider for pc sanity

This provider contains test cases and a test plan for pc sanity testing.

It depends on packages from ppa:checkbox-dev/ppa in build time.
The launchpad recipe build it daily : https://code.launchpad.net/~oem-solutions-engineers/+recipe/plainbox-provider-pc-sanity-daily-1

## Run autopkgtest to check build time and installation time sanity.

### option 1.
 - build testbed
$ `./autopkgtest.sh build`
 - run autopkgtest against current source.
$ `./autopkgtest.sh`


### options 2. run it by oem-scripts
$ run-autopkgtest lxc focal -C
