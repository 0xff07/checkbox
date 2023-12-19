# This file is part of Checkbox.
#
# Copyright 2023 Canonical Ltd.
#
# Checkbox is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3,
# as published by the Free Software Foundation.
#
# Checkbox is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Checkbox.  If not, see <http://www.gnu.org/licenses/>.
import textwrap

from metabox.core.actions import AssertPrinted, AssertRetCode
from metabox.core.scenario import Scenario
from metabox.core.utils import tag


@tag("resume")
class ResumeAfterCrash(Scenario):
    modes = ["remote"]
    launcher = textwrap.dedent(
        """
        [launcher]
        launcher_version = 1
        stock_reports = text
        [test plan]
        unit = 2021.com.canonical.certification::agent-resume-crash-then-reboot
        forced = yes
        [test selection]
        forced = yes
        [ui]
        type = silent
        """
    )
    steps = [
        AssertRetCode(1),
        AssertPrinted("job crashed  : Crash the agent"),
        AssertPrinted("job passed   : Emulate the reboot"),
    ]
