#!/usr/bin/env python3
"""
Copyright (C) 2020 Canonical Ltd.

Authors
  Adrian Lane <adrian.lane@canonical.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License version 3,
as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

Tests IPMI subsystem on SUT.
"""

import re
import os
import shutil
import sys
import argparse
import logging
from subprocess import (
    Popen,
    check_call,
    PIPE,
    TimeoutExpired,
    SubprocessError)


class IpmiTest(object):
    def __init__(self):
        # paths to kernel_module binaries
        self.path_lsmod = self._get_path('lsmod')
        self.path_modprobe = self._get_path('modprobe')
        # kernel modules to load/verify
        self.kernel_modules = (
            'ipmi_si',
            'ipmi_devintf',
            'ipmi_powernv',
            'ipmi_ssif',
            'ipmi_msghandler')
        # paths to freeipmi tools
        self.path_ipmi_chassis = self._get_path('ipmi-chassis')
        self.path_ipmi_config = self._get_path('ipmi-config')
        self.path_bmc_info = self._get_path('bmc-info')
        self.path_ipmi_locate = self._get_path('ipmi-locate')
        # function subprocess commands
        self.cmd_kernel_mods = [
            'sudo', self.path_lsmod]
        self.cmd_ipmi_chassis = [
            'sudo', self.path_ipmi_chassis, '--get-status']
        self.cmd_ipmi_channel = [
            'sudo', self.path_ipmi_config, '--checkout',
            '--lan-channel-number']
        self.cmd_bmc_info = [
            'sudo', self.path_bmc_info]
        self.cmd_ipmi_locate = [
            'sudo', self.path_ipmi_locate]
        # min. ipmi version to pass
        self.ipmi_ver = 2.0
        # subprocess call timeout (s)
        self.subproc_timeout = 10
        # raised subproc exceptions to handle
        self.sub_proc_excs = (
            TimeoutExpired,
            SubprocessError,
            OSError,
            TypeError)

    # fetch absolute path via shutil lib w/ exception handling
    def _get_path(self, binary):
        try:
            path_full = shutil.which(binary)
            return path_full
        except (self.sub_proc_excs[2:3]):
            logging.info('Unable to stat path via shutil lib!')
            logging.info('Using relative paths...')
            return binary

    # subprocess stdin/stderr handling
    def _subproc_logging(self, cmd):
        process = Popen(
            cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True)
        output, error = process.communicate(timeout=self.subproc_timeout)
        logging.debug('## Debug Output: ##')
        if (len(output) > 0):
                        # padding
            logging.debug('   [Stdout]\n')
            logging.debug(f'{output}\n')
        if (len(error) > 0):
                        # padding
            logging.debug('   [Stderr]\n')
            logging.debug(f'{error}\n')
        logging.debug('## End Debug Output ##\n')
        return output

    # post-process exception handling
    def _proc_exc(self, exc, subtest):
        if (type(exc) == TimeoutExpired):
            logging.info(
                f'Timeout calling {subtest}!'
                f' ({self.subproc_timeout}s)\n')
        elif (type(exc) == TypeError):
            logging.info(
                f'Error calling {subtest}!'
                ' Check your paths!\n')
        else:
            logging.info(f'Error calling {subtest}!\n')

    # kernel_mods() helper function to call modprobe
    def _modprobe_hlpr(self, module):
        try:
            check_call(
                [self.path_modprobe, module],
                stderr=PIPE, timeout=self.subproc_timeout)
        except self.sub_proc_excs:
            logging.info(f'* Unable to load module {module}!')
            logging.info('  **********************************************')
            logging.info(f'  Warning: proceeding, but in-band IPMI may fail')
            logging.info('  **********************************************')
        else:
            logging.info(f'- Successfully loaded module {module}')

    # check (and load) kernel modules
    def kernel_mods(self):
        logging.info('-----------------------')
        logging.info('Verifying kernel modules:')
        try:
            output = self._subproc_logging(self.cmd_kernel_mods)
            for module in self.kernel_modules:
                if module in output:
                    logging.info(f'- {module} already loaded')
                else:
                    self._modprobe_hlpr(module)
            logging.info('')
        except self.sub_proc_excs as exc:
            self._proc_exc(exc, 'lsmod')

    # get ipmi chassis data
    # pass if called w/o error
    def impi_chassis(self):
        logging.info('-----------------------')
        logging.info('Fetching chassis status:')
        try:
            self._subproc_logging(self.cmd_ipmi_chassis)
        except self.sub_proc_excs as exc:
            self._proc_exc(exc, 'ipmi_chassis()')
            return 1
        else:
            logging.info('Fetched chassis status!\n')
            return 0

    # get power status via ipmi chassis data
    # pass if called w/o error & system power field present
    def pwr_status(self):
        logging.info('-----------------------')
        logging.info('Fetching power status:')
        regex = re.compile('^System Power')
        try:
            output = self._subproc_logging(self.cmd_ipmi_chassis)
            for line in output.rstrip().split('\n'):
                if re.search(regex, line):
                    logging.info('Fetched power status!\n')
                    return 0
            else:
                logging.info('Unable to retrieve power status via IPMI.\n')
                return 1
        except self.sub_proc_excs as exc:
            self._proc_exc(exc, 'pwr_status()')
            return 1

    # ipmi_channel discovery loop
    def _ipmi_channel_hlpr(self, i, matches, channel):
        regex = re.compile('Section User')
        cmd = self.cmd_ipmi_channel
        if (len(cmd) > 4):
            cmd.pop(-1)
        cmd.append(str(i))
        output = self._subproc_logging(cmd)
        for line in output.rstrip().split('\n'):
            if re.search(regex, line):
                matches.append(1)
                channel.append(i)
                break
        return (matches, channel)

    # get ipmi channel(s) in use
    # pass if user data returns after calling ipmi-config
    def ipmi_channel(self):
        logging.info('-----------------------')
        logging.info('Fetching IPMI channel:')
        matches = []
        # support multiple channels
        channel = []
        # test channels 0 - 15
        for i in range(16):
            try:
                self._ipmi_channel_hlpr(i, matches, channel)
            except self.sub_proc_excs as exc:
                self._proc_exc(exc, 'ipmi_channel()')
                return 1
        else:
            if (sum(matches) > 0):
                logging.info(f'Found {sum(matches)} channel(s)!')
                logging.info(f'IPMI Channel(s): {channel}\n')
                return 0
            else:
                logging.info('Unable to fetch IPMI channel!\n')
                return 1

    # call bmc-info
    # pass if called w/o error
    def bmc_info(self):
        logging.info('-----------------------')
        logging.info('Fetching BMC information:')
        try:
            self._subproc_logging(self.cmd_bmc_info)
        except self.sub_proc_excs as exc:
            self._proc_exc(exc, 'bmc_info()')
            return 1
        else:
            logging.info('Fetched BMC information!\n')
            return 0

    # fetch ipmi version via bmc-info sdout
    # pass if ipmi version >= self.ipmi_ver
    def ipmi_version(self):
        logging.info('-----------------------')
        logging.info('Testing IPMI version:')
        try:
            output = self._subproc_logging(self.cmd_bmc_info)
            # Prefer .index() over .find() for exception handling
            res_index = output.index('IPMI Version')
            version = output[(res_index + 24):(res_index + 27)]
            logging.info(f'IPMI Version: {version}\n')
            if (float(version) < float(self.ipmi_ver)):
                logging.info(f'IPMI Version below {self.ipmi_ver}!\n')
                return 1
            else:
                return 0
        except self.sub_proc_excs as exc:
            self._proc_exc(exc, 'ipmi_version()')
            return 1

    # call ipmi-locate
    # pass if driver is loaded
    def ipmi_locate(self):
        logging.info('-----------------------')
        logging.info('Testing ipmi-locate:')
        regex = re.compile('driver:')
        try:
            output = self._subproc_logging(self.cmd_ipmi_locate)
            if re.search(regex, output):
                logging.info('Located IPMI driver!\n')
                return 0
            else:
                logging.info('Unable to locate IPMI driver!\n')
                return 1
        except self.sub_proc_excs as exc:
            self._proc_exc(exc, 'ipmi_locate()')
            return 1

    # initialize kernel modules and run ipmi tests
    def run_test(self):
        # load/val kernel modules
        self.kernel_mods()
        # tally results
        results = [self.impi_chassis(),
                   self.pwr_status(),
                   self.ipmi_channel(),
                   self.bmc_info(),
                   self.ipmi_version(),
                   self.ipmi_locate()]
        return results


def main():
    # init logging subsystem
    # instantiate argparse as parser
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true',
                        help='debug/verbose output (stdout/stderr)')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='suppress output')
    args = parser.parse_args()
    if ((not args.quiet) or args.debug):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
    if (not args.quiet):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)
    if args.debug:
        console_handler.setLevel(logging.DEBUG)

    # instantiate IpmiTest as ipmi_test
    # pass to [results] for post-processing
    ipmi_test = IpmiTest()
    results = ipmi_test.run_test()
    # tally results
    if (sum(results) > 0):
        print ('-----------------------')
        print ('## IPMI tests failed! ##')
        print (
            f'## Chassis: {results[0]}  Power: {results[1]}  ',
            f'Channel: {results[2]}  BMC: {results[3]}  ',
            f'IPMI Version: {results[4]}  IPMI Locate: {results[5]} ##')
        return 1
    else:
        print ('-----------------------')
        print ('## IPMI tests passed! ##')
        return 0


# call main()
if __name__ == '__main__':
    sys.exit(main())