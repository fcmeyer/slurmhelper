import logging
import os
import shutil
import pprint

import numpy as np
import pandas as pd

from argparse import ArgumentError

from .parser import valid_specs
from ..jobs.cli_helpers import prep_job, prep_job_array, generate_run_scripts
from ..utils.io import (
    calculate_directories,
    calculate_directories_midwayscratch,
    calculate_directories_amarel,
    copy_or_clean,
    initialize_directories,
    is_valid_db,
)
from ..utils.reporting import (
    list_slurm,
    check_runtimes,
    check_completed,
    check_queue,
    check_log,
)


class SlurmhelperCLI:
    """
    Command-line entrypoint class. Implements a switch to run various commands.
    """

    def __init__(self):
        from .parser import build_parser

        # Build parser, and parse arguments
        parser = build_parser()
        args = parser.parse_args()

        # copy args to the object for easier access later on :)
        self.args = args

        # Initialize logging
        self.__initialize_logging()

        # A manual check - need user id if using midway
        if (
            "cluster" in args
            and "userid" in args
            and args.cluster in {"midway2-scratch", "amarel"}
            and args.userid is None
        ):
            raise ArgumentError(
                "If you are using midway2-scratch or Amarel, you must provide your user ID!"
            )

        if args.operation == "check":
            print(
                f"\nSlurmhelper will run the {args.operation} {args.check_operation} operation."
            )
        else:
            print(f"\nSlurmhelper will run the {args.operation} operation.")

        self.logger.info("Arguments specified:")
        self.logger.info(args)

        # Load spec
        if ("spec_builtin" in self.args) or ("spec_file" in self.args):
            self.__initialize_config()
        else:
            self.config = dict()
            self.logger.info("Did not load any job specification.")

        if ("cluster" in self.args) or ("wd_path" in self.args):
            self.__initialize_paths()

        # Compile job list, if required
        # below are the exceptions where one wouldn't need a job list:
        if not (
            (args.operation in {"list", "init", "submit"})
            or (
                args.operation == "gen-scripts"
                and args.ids is None
                and args.range is None
            )
            or (
                args.operation == "check"
                and ("ids" not in self.args and "range" not in self.args)
                or args.range is None
                and args.ids is None
                # and args.check_operation in {"queue", "completion","runtime"}
            )
        ):
            self.__initialize_job_list()

        # run my operation! :)
        operation = getattr(self, args.operation.replace("-", "_"))
        operation()

    def __initialize_logging(self):
        log_format = "[%(levelname)s] - %(message)s"
        # set verbosity based on arguments!
        if ("verbose" in self.args) and self.args.verbose:
            logging.basicConfig(level=20, format=log_format)  # info
        elif ("debug" in self.args) and self.args.debug:
            logging.basicConfig(level=10, format=log_format)  # debug
        else:
            logging.basicConfig(level=30, format=log_format)  # warning

        self.logger = logging.getLogger("cli")

    def __initialize_config(self):
        from slurmhelper.specs import load_builtin_spec, load_job_spec

        if self.args.spec_file is not None:
            self.config = load_job_spec(self.args.spec_file)
            self.logger.info(
                f"Loaded user-given specification from {self.args.spec_file}"
            )
        else:
            to_load = self.args.spec_builtin[0].split(":")
            spec = to_load[0]
            if len(to_load) == 1:
                version = valid_specs[spec]["latest"]
            else:
                version = to_load[1]
            self.config = load_builtin_spec(spec, version)
            self.logger.info(
                f"Loaded built-in job specification: {spec} version {version}"
            )

    def __initialize_paths(self):
        # Calculate directories
        if "base_directory_name" not in self.config.keys():
            self.logger.warning(
                "Base working dir name not specified in your spec; using default ('working')"
            )
            base_dir_name = "working"
        else:
            base_dir_name = self.config["base_directory_name"]

        # paths!
        if self.args.cluster is not None:
            if self.args.cluster[0] == "midway2-scratch":
                self.paths = calculate_directories_midwayscratch(
                    self.args.userid[0], base_dir_name
                )
            elif self.args.cluster[0] == "amarel":
                self.paths = calculate_directories_amarel(
                    self.args.userid[0], base_dir_name
                )
        else:
            self.paths = calculate_directories(self.args.wd_path[0], base_dir_name)

        self.logger.info("Directory tree generated:")
        self.logger.info(pprint.pformat(self.paths))

    def __initialize_job_list(self):
        # load database thingy
        self.__load_database()
        # get valid job ids:
        self.__valid_ids = set(self.db.order_id.values.tolist())

        self.job_list = []
        if self.args.ids is not None:
            self.job_list += self.args.ids
        else:
            self.job_list += np.arange(
                self.args.range[0], self.args.range[1] + 1
            ).tolist()

        print(
            "A total of {n} jobs would be affected by this call.".format(
                n=len(self.job_list)
            )
        )

        self.logger.info("\nThese jobs are:")
        self.logger.info(self.job_list)

        # Leverage DB to ensure job ids provided do not exceed range, or are invalid in some other way!
        if not set(self.job_list).issubset(self.__valid_ids):
            raise AssertionError(
                f"Some job ids provided are not in the scope of "
                f"the csv database we are using. These are: "
                f"{set(self.job_list) - self.__valid_ids}"
            )

    def init(self):
        initialize_directories(self.paths)
        self.__validate_and_copy_db(self.args.db[0])
        print("Directory initialization concluded.")
        if self.args.full:
            print("The --full flag was used, so scripts will now be generated.")
            self.gen_scripts()  # generate template scripts for all jobs

    def submit(self):
        from ..jobs.submit import submit_sbatch

        sb_id = self.args.sbatch_id[0]
        submit_sbatch(sb_id, self.paths)

    def list(self):
        list_slurm(self.paths)

    def gen_scripts(self):
        if hasattr(self, "job_list"):
            generate_run_scripts(self.paths, self.config, self.args, self.job_list)
        else:
            generate_run_scripts(self.paths, self.config, self.args)
        print("Script generation operation concluded.")

    def copy(self):
        copy_or_clean(self.job_list, "copy", self.paths["job_scripts"])

    def clean(self):
        copy_or_clean(self.job_list, "clean", self.paths["job_scripts"])

    def reset(self):
        self.logger.info("Will clean first, and copy next!")

        try:
            copy_or_clean(self.job_list, "clean", self.paths["job_scripts"])
            copy_or_clean(self.job_list, "copy", self.paths["job_scripts"])
        except Exception as e:
            raise e

    def prep(self):
        if self.args.do_reset:
            print(
                "The --do-reset flag was used. Clean and then copy will be run prior "
                "to job prep for pertinent ids."
            )
            self.reset()
        elif self.args.do_clean:
            print(
                "The --do-clean flag was used. Clean scripts will be run for affected job ids "
                "prior to sbatch submission script prep."
            )
            self.clean()
        elif self.args.do_copy:
            print(
                "The --do-copyflag was used. Input copy scripts will be run for affected job ids "
                "prior to sbatch submission script prep."
            )
            self.copy()

        prep_job(self.config, self.job_list, self.paths, self.args)

    def prep_array(self):
        if self.args.do_reset:
            print(
                "The --do-reset flag was used. Clean and then copy will be run prior "
                "to job prep for pertinent ids."
            )
            self.reset()
        elif self.args.do_clean:
            print(
                "The --do-clean flag was used. Clean scripts will be run for affected job ids "
                "prior to sbatch submission script prep."
            )
            self.clean()
        elif self.args.do_copy:
            print(
                "The --do-copy flag was used. Input copy scripts will be run for affected job ids "
                "prior to sbatch submission script prep."
            )
            self.copy()

        prep_job_array(self.config, self.job_list, self.paths, self.args)

    def check(self):
        if hasattr(self, "job_list"):
            jl = self.job_list
        else:
            jl = None

        self.logger.debug(jl)

        if self.args.check_operation == "queue":
            check_queue()
        elif self.args.check_operation == "runtime":
            check_runtimes(self.paths, self.config, jl)
        elif self.args.check_operation == "completion":
            check_completed(
                self.paths,
                self.config,
                job_list=jl,
                return_completed_list=False,
                failed_report=self.args.show_failed_logs,
            )
        elif self.args.check_operation == "log":
            if self.args.job_id is not None:
                id = self.args.job_id[0]
                type = "job"
            else:
                id = self.args.sbatch_id[0]
                type = "sbatch"
            check_log(
                id,
                type,
                self.paths,
                self.config,
                head=self.args.head,
                tail=self.args.tail,
                full=self.args.full,
            )

    def validate_spec(self):
        # Not yet implemented.
        self.logger.critical("Not yet implemented.")

    def __load_database(self):
        self.db = pd.read_csv(os.path.join(self.paths["base"], "db.csv"))

    def __validate_and_copy_db(self, db_file):
        self.logger.info(f"validating file {db_file}")
        if not is_valid_db(db_file):
            raise ValueError(
                "Your DB file does not contain an order_id column. Please provide a valid db file in order"
                "to proceed."
            )
        else:
            self.logger.info("Copying file")
            shutil.copy2(db_file, os.path.join(self.paths["base"], "db.csv"))


def main():
    SlurmhelperCLI()
