# Copyright (C) 2017 Pier Carlo Chiodi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
from logging.config import fileConfig
import os

from ..config.program import program_config
from ..errors import MissingFileError, ARouteServerError

class ARouteServerCommand(object):

    COMMAND_NAME = None
    COMMAND_HELP = None
    NEEDS_CONFIG = False

    def __init__(self, args):
        self.args = args
        if self.NEEDS_CONFIG:
            self._setup()

    @classmethod
    def attach_to_parser(cls, parser):
        sub_parser = parser.add_parser(
            cls.COMMAND_NAME,
            help=cls.COMMAND_HELP)
        cls.add_arguments(sub_parser)

    @classmethod
    def add_arguments(cls, parser):
        if cls.NEEDS_CONFIG:
            cls.add_program_config_arguments(parser)

    @classmethod
    def add_program_config_arguments(cls, parser):

        parser.add_argument(
            "--cfg",
            help="ARouteServer configuration file.",
            metavar="FILE",
            dest="cfg_program",
            default=program_config.DEFAULT_CFG_PATH)

        group = parser.add_argument_group(
            title="Program configuration",
            description="The following arguments override those provided "
                        "in the program's configuration file."
        )

        group.add_argument(
            "--cache-dir",
            help="Cache directory.",
            metavar="DIR",
            dest="cache_dir")

        group.add_argument(
            "--logging-config-file",
            help="Logging configuration file, in Python fileConfig() format ("
                "https://docs.python.org/2/library/logging.config.html"
                "#configuration-file-format)",
            dest="logging_config_file")

    def _setup(self):
        logging_setted_up = False

        def setup_logging(path):
            if not os.path.exists(path):
                raise MissingFileError(path)

            try:
                fileConfig(path)
            except Exception as e:
                raise ARouteServerError(
                    "Error processing the logging configuration file "
                    "{}: {}".format(path, str(e))
                )

        if self.args.logging_config_file:
            setup_logging(self.args.logging_config_file)
            logging_setted_up = True

        if self.args.cfg_program:
            try:
                program_config.load(self.args.cfg_program)
            except MissingFileError as e:
                raise ARouteServerError(
                    "{} - Please configure your system by running the "
                    "'arouteserver setup' command or provide the "
                    "program configuration file path using the "
                    "'--cfg' argument.".format(str(e))
                )

        program_config.parse_cli_args(self.args)

        # Logging setup: if no command line arg given, use the path from
        # program's config file.

        if not logging_setted_up:
            log_ini_path = program_config.get("logging_config_file")
            if log_ini_path:
                setup_logging(log_ini_path)

    def run(self):
        raise NotImplementedError()
