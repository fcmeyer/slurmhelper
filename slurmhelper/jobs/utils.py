"""
Definition of Job object class, associated methods, and TestableJob class extension.
"""

# This file contains the base job class, which is then augmented for each
# specific use case with tests, etc.
import logging
from pathlib import Path
from string import Formatter

import pandas as pd

from .classes import Job

logger = logging.getLogger("cli")


def compute_helpful_vars(job_dict, dirs):
    """
    Helper function, that adds what (I see as) helpful variables to
    your job dictionary.
    :param job_dict: a dictionary representing a row. for example, if
    you had a csv file with rows [sub,ses,task,run,order_id], and also
    defined globals [conda_env_path, matlab_path], you would get a dict
    {
        sub: NIDA2322 ses: 1, task: "rest", run: 2, order_id:5,
        conda_env_path:"/project2/conda/myenv", matlab_path:"/usr/bin/matlab"
    }
    :param dirs: output of ..utils.io:calculate_directories()
    :return: augmented job_dict
    """

    job_dict["job_id"] = "%05d" % job_dict["order_id"]

    # for bids
    if "run" in job_dict.keys():
        job_dict["run_id"] = "%02d" % job_dict["run"]

    return job_dict


def build_job_objects(dirs, config, job_list=None):
    """
    Helps automagically generate a list of job objects, given your spec.
    :param job_list: list of job ids from your array (integers) for which
    to generate scripts. If none, all jobs in db will be included.
    :param dirs: output of ..utils.io:calculate_directories()
    :param config: dict generated from reading the .yml spec
    :return: list of job objects! :)
    """
    # Read database file
    p_csvfile = Path(dirs["base"]).joinpath("db.csv")
    if p_csvfile.exists():
        df = pd.read_csv(p_csvfile)
    else:
        raise ValueError(
            "The specified database csv file does not exist:\n%s" % str(p_csvfile)
        )

    # We MUST have an order_id column!!
    if "order_id" not in df.columns:
        raise ValueError(
            "The dataframe MUST include a order_id column with job indices!!"
        )

    if job_list is not None:
        logger.info(
            "job range provided, so only looking at jobs for a particular subset..."
        )
        df = df[df.order_id.isin(job_list)]
        # filter rows and only keep the ones selected
    else:
        logger.warning("no job range provided, so looking at ALL the jobs.")

    # Parse string arguments
    # Source: https://stackoverflow.com/questions/13037401/get-keys-from-template
    fields = [i[1] for i in Formatter().parse(config["run_script"]) if i[1] is not None]

    # Parse fields provided in YAML and CSV files
    fields_df = df.columns.values.tolist()
    fields_global = list(config["script_global_settings"].keys())

    # create one dict per subject with info from csv rows, via pandas
    jobs = df.to_dict(orient="records")
    # enhance each job's dict with global parameters
    jobs_g = [{**row, **config["script_global_settings"]} for row in jobs]

    # If a custom vars function is provided in the YAML file, load it
    # if "compute_custom_vars" in config.keys():
    #    exec(config["compute_custom_vars"])  # overwrites the template function obj (?)

    # Enhance even more, with computed variables...
    jobs_gc = []
    for job in jobs_g:
        # Compute helpful vars! :)
        jd = compute_helpful_vars(job, dirs)

        # If a custom var computation function is provided in the YAML file, run it
        # if "compute_custom_vars" in config.keys():
        #    jd = compute_custom_vars(jd, dirs)

        # Append to our list
        jobs_gc.append(jd)

    # Identify fields that need to be provided and do not currently exist
    # assumption: first dict object has same keys as rest...
    # TODO: implement safety check?
    # fields_missing = list(set([f for f in fields if f not in jobs_gc[0].keys()]))  # ensure no dupes
    #
    # # If fields are missing, raise an exception - that ain't good!
    # if len(fields_missing) != 0:
    #     raise NameError('%d fields have not been provided or computed, but'
    #                     'are needed by your script: %s' % (len(fields_missing),
    #                                                        ' '.join(fields_missing)))

    # Ok. Now, construct job objects:
    job_obj_list = [
        Job(d["order_id"], dirs, job_dict=d, config=config) for d in jobs_gc
    ]

    return job_obj_list
