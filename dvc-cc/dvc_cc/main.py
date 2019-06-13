#from collections import OrderedDict
from collections import OrderedDict

from dvc_cc.version import VERSION
from dvc_cc.cli_modes import cli_modes

from dvc_cc.git.main import main as git_main
from dvc_cc.git.main import DESCRIPTION as GIT_DESCRIPTION

from dvc_cc.run.main import main as run_main
from dvc_cc.run.main import DESCRIPTION as run_DESCRIPTION

from dvc_cc.run_all_defined.main import main as run_all_defined_main
from dvc_cc.run_all_defined.main import DESCRIPTION as RUN_ALL_DEFINED_DESCRIPTION

from dvc_cc.output_to_tmp.main import main as output_to_tmp_main
from dvc_cc.output_to_tmp.main import DESCRIPTION as output_to_tmp_DESCRIPTION

from dvc_cc.init.main import main as init_main
from dvc_cc.init.main import DESCRIPTION as INIT_DESCRIPTION

from dvc_cc.status.main import main as status_main
from dvc_cc.status.main import DESCRIPTION as STATUS_DESCRIPTION

from dvc_cc.cancel.main import main as cancel_main
from dvc_cc.cancel.main import DESCRIPTION as CANCEL_DESCRIPTION

from dvc_cc.setting.main import main as setting_main
from dvc_cc.setting.main import DESCRIPTION as SETTING_DESCRIPTION

from dvc_cc.dummy.main import main as dummy_main
from dvc_cc.dummy.main import DESCRIPTION as DUMMY_DESCRIPTION

SCRIPT_NAME = 'dvc-cc'
TITLE = 'tools'
DESCRIPTION = 'DVC-CC (C) 2019  Jonas Annuscheit. This software is distributed under the AGPL-3.0 LICENSE.'
MODES = OrderedDict([
    ('git', {'main': git_main, 'description': GIT_DESCRIPTION}),
    ('run', {'main': run_main, 'description': run_DESCRIPTION}),
    ('run-all-defined', {'main': run_all_defined_main, 'description': RUN_ALL_DEFINED_DESCRIPTION}),
    ('output-to-tmp', {'main': output_to_tmp_main, 'description': output_to_tmp_DESCRIPTION}),
    ('init', {'main': init_main, 'description': INIT_DESCRIPTION}),
    ('status', {'main': status_main, 'description': STATUS_DESCRIPTION}),
    ('cancel', {'main': cancel_main, 'description': CANCEL_DESCRIPTION}),
    ('setting', {'main': setting_main, 'description': SETTING_DESCRIPTION}),
    ('dummy', {'main': dummy_main, 'description': DUMMY_DESCRIPTION})
])


def main():
    cli_modes(SCRIPT_NAME, TITLE, DESCRIPTION, MODES, VERSION)