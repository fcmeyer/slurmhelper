"""
Utility functions leveraged for I/O filesystem operations.
"""

import logging
import os
import subprocess
from pathlib import Path
from time import sleep

import pandas as pd
import progressbar

logger = logging.getLogger("cli")


def pkg_data_dir():
    return os.path.join(Path(__file__).parent.parent, "data")


def pkg_specs_dir():
    return os.path.join(Path(__file__).parent.parent, "specs")


def load_db(db_file):
    """
    Read input table used to construct database of runs
    :param db_file: path to CSV file to read
    :return: pandas dataframe with CSV stuffs :)
    """
    return pd.read_csv(db_file)


def is_valid_db(db_file):
    db = load_db(db_file)
    return "order_id" in db.columns


def calculate_directories(basepath, base_dir_name):
    """
    Calculate the directory structure we want to build for running
    our files.
    :param basepath: directory where working dir will be created
    :param base_dir_name: name of working dir (from your spec)
    :return: dict with path structure
    """
    base = os.path.join(basepath, base_dir_name)
    return {
        "base": base,
        "checks": os.path.join(base, "checks"),
        "slurm_scripts": os.path.join(base, "scripts", "slurm"),
        "slurm_logs": os.path.join(base, "logs", "slurm"),
        "job_scripts": os.path.join(base, "scripts", "jobs"),
        "job_logs": os.path.join(base, "logs", "jobs"),
        "job_inputs": os.path.join(base, "inputs"),
        "job_work": os.path.join(base, "work"),
        "crashes": os.path.join(base, "crashes"),
    }


def calculate_directories_midwayscratch(userid, base_dir_name):
    """
    Wrapper for calculate directories function; points to user scratch
    partition in the UChicago Midway2 cluster.
    :param userid: useridID of user
    :param base_dir_name: name of working directory to be created
    :return: dict with path structure
    """
    basepath = os.path.join("/", "home", userid, "scratch-midway2")
    return calculate_directories(basepath, base_dir_name)

def calculate_directories_amarel(userid, base_dir_name):
    """
    Wrapper for calculate directories function: points to user scratch
    partition in the Rutgers University Amarel cluster.
    :param userid: RUNetID of user
    :param base_dir_name: name of the working directory to be created
    :return: dict with path structure
    """
    basepath = os.path.join("/", "scratch", userid)
    return calculate_directories(basepath, base_dir_name)

def initialize_directories(dirs):
    """
    Creates the directory tree for this configuration, if not exists already.
    :param dirs: dict, output of calculate_directories()
    :return:
    """
    for key in dirs.keys():
        p = Path(dirs[key])
        p.mkdir(parents=True, exist_ok=True)


def write_job_script(job_id, sbatch_id, dirs, script):
    """
    Helper function to facilitate writing a command line script for a given job, to
    the appropriate place in the working directory hierarchy.
    :param job_id: str, job identifier (e.g., 00001)
    :param sbatch_id: str, sbatch submission script identifier (e.g., 001)
    :param dirs: dict, output of calculate_directories()
    :param script: (long) str, script to write
    :return:
    """
    # Save script file to scripts directory
    sbatch_name = "{job_name}.sh".format(job_name=job_id)
    path_sbatch_dir = Path(dirs["slurm_scripts"])
    if not path_sbatch_dir.exists():
        logger.warning(
            "The sbatch dir does not exist. are you sure you "
            "initialized this working directory tree correctly?"
            "We will make it for you, but just a heads-up..."
        )
        # create path if not exists
        path_sbatch_dir.mkdir(exist_ok=True)
    # Now, figure out the script's path...
    path_sbatch = path_sbatch_dir.joinpath(sbatch_name)
    # Don't want to keep going if this file exists already
    if path_sbatch.exists():
        raise ValueError(
            "The sbatch_id value provided, {sbatch_id:04d}, has already been used, as evidenced by "
            "an existing script with the same id. Aborting. "
            "Choose a different ID!".format(sbatch_id=sbatch_id)
        )
    else:
        with open(path_sbatch, "w") as f:
            f.write(script)
            logger.info(f"Wrote file: {path_sbatch}")


def copy_or_clean(job_list, operation, path_scripts):
    """
    Helper function designed to facilitate:

    a) copying inputs from cold storage to the "hot" partition for computation (rationale: UChicago
       HPC does not allow jobs to directly access cold storage, so this must be done pre-submission).

    b) cleaning files related to a job from the working directory

    This is completed by leveraging bash scripts created for a given job (jobid_<clean/copy>.sh).

    :param job_list: list o' job ids to work with
    :param operation: either copy or clear
    :param path_scripts: where do we expect to find the scripts generated from R (abs path)
    :return: nothin', just some good ol' stuff done via bash
    """
    if not (operation == "copy" or operation == "clean"):
        raise AssertionError("invalid operation specified: %s" % (operation))
    logger.info("========== BEGIN DOING STUFF ==========")
    for i in progressbar.progressbar(range(len(job_list)), redirect_stdout=True):
        job_id = job_list[i]
        logger.info(
            "----------- BEGIN DOING STUFF FOR JOB {job_id:05d} -----------".format(
                job_id=job_id
            )
        )
        script_name = "{job_id:05d}_{operation}.sh".format(
            job_id=job_id, operation=operation
        )
        target_path = os.path.join(path_scripts, script_name)
        logger.info("RUNNING: bash {tgt_path}".format(tgt_path=target_path))
        subprocess.run(["bash", target_path])
        logger.info(
            "----------- DONE DOING STUFF FOR JOB {job_id:05d} -----------".format(
                job_id=job_id
            )
        )
        sleep(0.1)
    logger.info("========== TOTALLY DONE! YEE HAW :) ==========")
