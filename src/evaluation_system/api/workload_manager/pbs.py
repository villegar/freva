from __future__ import annotations
import logging
import math
import os

from .core import Job

logger = logging.getLogger(__name__)


def pbs_format_bytes_ceil(n):
    """Format bytes as text.

    PBS expects KiB, MiB or Gib, but names it KB, MB, GB  KB.

    >>> pbs_format_bytes_ceil(1)
    '1B'
    >>> pbs_format_bytes_ceil(1234)
    '1234B'
    >>> pbs_format_bytes_ceil(12345678)
    '13MB'
    >>> pbs_format_bytes_ceil(1234567890)
    '1177MB'
    >>> pbs_format_bytes_ceil(15000000000)
    '14GB'
    """
    if n >= 10 * (1024**3):
        return "%dGB" % math.ceil(n / (1024**3))
    if n >= 10 * (1024**2):
        return "%dMB" % math.ceil(n / (1024**2))
    if n >= 10 * 1024:
        return "%dkB" % math.ceil(n / 1024)
    return "%dB" % n


class PBSJob(Job):
    submit_command = "qsub"
    cancel_command = "qdel"
    config_name = "pbs"

    def __init__(
        self,
        scheduler=None,
        name=None,
        queue=None,
        project=None,
        resource_spec=None,
        walltime="",
        job_extra=[],
        **base_class_kwargs,
    ):
        super().__init__(scheduler=scheduler, name=name, **base_class_kwargs)

        # Try to find a project name from environment variable
        project = project or os.environ.get("PBS_ACCOUNT")

        header_lines = []
        # PBS header build
        if self.job_name is not None:
            header_lines.append("#PBS -N %s" % self.job_name)
        if queue is not None:
            header_lines.append("#PBS -q %s" % queue)
        if project is not None:
            header_lines.append("#PBS -A %s" % project)
        if resource_spec is None:
            # Compute default resources specifications
            resource_spec = "select=1:ncpus=%d" % self.worker_cores
            memory_string = pbs_format_bytes_ceil(self.worker_memory)
            resource_spec += ":mem=" + memory_string
            logger.info(
                "Resource specification for PBS not set, initializing it to %s"
                % resource_spec
            )
        if resource_spec is not None:
            header_lines.append("#PBS -l %s" % resource_spec)
        if walltime is not None:
            header_lines.append("#PBS -l walltime=%s" % walltime)
        if self.log_directory is not None:
            header_lines.append("#PBS -e %s/" % self.log_directory)
            header_lines.append("#PBS -o %s/" % self.log_directory)
        header_lines.extend(["#PBS %s" % arg for arg in job_extra])

        # Declare class attribute that shall be overridden
        self.job_header = "\n".join(header_lines)

        logger.debug("Job script: \n %s" % self.job_script())
