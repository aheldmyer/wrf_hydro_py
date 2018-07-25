# Note: All other imports for individual schedulers should be done in the respective scheduler
# class functions so that imports can be isolated to relevant schedulers
import copy

from abc import ABC, abstractmethod
from .job import Job

class Scheduler(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def add_job(self, job: Job):
        pass

    @abstractmethod
    def schedule(self):
        pass

class PBSCheyenne(Scheduler):
    """A Scheduler object compatible with PBS on the NCAR Cheyenne system."""
    def __init__(
            self,
            account: str,
            email_who: str = None,
            email_when: str = 'abe',
            nproc: int = 360,
            nnodes: int = None,
            ppn: int = 36,
            queue: str = 'regular',
            walltime: str = "12:00:00"):
        """Initialize an PBSCheyenne object.
        Args:
            account: The account string
            email_who: Email address for PBS notifications
            email_when: PBS email frequency options. Options include 'a' for on abort,
            'b' for before each job, and 'e' for after each job.
            nproc: Number of processors to request
            nnodes: Number of nodes to request
            ppn: Number of processors per node
            queue: The queue to use, options are 'regular', 'priority', and 'shared'
            walltime: The wall clock time in HH:MM:SS format, max time is 12:00:00
        """

        # Declare attributes.
        ## property construction
        self._sim_dir = None
        self._nproc = nproc
        self._nnodes = nnodes
        self._ppn = ppn

        # Attribute
        self.jobs = []
        self.scheduled_jobs = []

        # Setup exe cmd, will overwrite job exe cmd
        self._exe_cmd = 'mpiexec_mpt ./wrf_hydro.exe'

        ## Scheduler options dict
        ## TODO: Make this more elegant than hard coding for maintenance sake
        self.scheduler_opts = {'account':account,
                               'email_when':email_when,
                               'email_who':email_who,
                               'queue':queue,
                               'walltime':walltime}

    def add_job(self,job: Job):
        """Add a job to the scheduler"""
        job = copy.deepcopy(job)

        #Override job exe cmd with scheduler exe cmd
        job._exe_cmd = self._exe_cmd

        self.jobs.append(job)

    def schedule(self):
        """Schedule jobs that have been added to the scheduler"""
        import subprocess
        import shlex
        import pathlib
        import os

        current_dir = pathlib.Path(os.curdir)

        # TODO: Find a way to protect the job order so that once someone executes schedule...
        # they can't change the order, may not be an issue except for if scheduling fails
        # somewhere

        self._write_job_pbs()

        # Make lists to store pbs scripts and pbs job ids to get previous dependency
        pbs_jids = []
        pbs_scripts = []

        qsub_str = '/bin/bash -c "'
        for job_num, option in enumerate(self.jobs):

            # This gets the pbs script name and pbs jid for submission
            # the obs jid is stored in a list so that the previous jid can be retrieved for
            # dependency
            job_id = self.jobs[job_num].job_id
            pbs_scripts.append(str(self.jobs[job_num].job_dir) + '/job_' + job_id + '.pbs')
            pbs_jids.append('job_' + job_id)

            # If first job, schedule using hold
            if job_num == 0:
                qsub_str += pbs_jids[job_num] + "=`qsub -h " + pbs_scripts[job_num] + "`;"
            # Else schedule using job dependency on previous pbs jid
            else:
                qsub_str += pbs_jids[job_num] + "=`qsub -W depend=afterok:$" + pbs_jids[
                    job_num-1] + " " + pbs_scripts[job_num] + "`;"

        qsub_str += 'qrls $' + pbs_jids[0] + ";"
        qsub_str += '"'

        # This stacks up dependent jobs in PBS in the same order as the job list
        subprocess.run(shlex.split(qsub_str),
                       cwd=str(current_dir))

        # This releases the first job and triggers PBS to start the job sequence
        subprocess.run(shlex.split('qrls $' + pbs_jids[0]),
                       cwd=str(current_dir))

    def _write_job_pbs(self):
        """Private method to write bash PBS scripts for submitting each job """
        for job in self.jobs:

            # Write PBS script
            jobstr = ""
            jobstr += "#!/bin/sh\n"
            jobstr += "#PBS -N {0}\n".format(job.job_id)
            jobstr += "#PBS -A {0}\n".format(self.scheduler_opts['account'])
            jobstr += "#PBS -q {0}\n".format(self.scheduler_opts['queue'])

            if self.scheduler_opts['email_who'] is not None:
                jobstr += "#PBS -M {0}\n".format(self.scheduler_opts['email_who'])
                jobstr += "#PBS -m {0}\n".format(self.scheduler_opts['email_when'])
            jobstr += "\n"

            jobstr += "#PBS -l walltime={0}\n".format(self.scheduler_opts['walltime'])
            jobstr += "\n"

            prcstr = "select={0}:ncpus={1}:mpiprocs={1}\n"
            prcstr = prcstr.format(self.nnodes, self.ppn)


            jobstr += "#PBS -l " + prcstr
            jobstr += "\n"

            jobstr += "# Not using PBS standard error and out files to capture model output\n"
            jobstr += "# but these hidden files might catch output and errors from the scheduler.\n"
            jobstr += "#PBS -o {0}\n".format(job.job_dir)
            jobstr += "#PBS -e {0}\n".format(job.job_dir)
            jobstr += "\n"

            # End PBS Header

            # if job.modules:
            #    jobstr += 'module purge\n'
            #    jobstr += 'module load {0}\n'.format(job.modules)
            #    jobstr += "\n"

            jobstr += "# CISL suggests users set TMPDIR when running batch jobs on Cheyenne.\n"
            jobstr += "export TMPDIR=/glade/scratch/$USER/temp\n"
            jobstr += "mkdir -p $TMPDIR\n"
            jobstr += "\n"

            if self.scheduler_opts['queue'] == 'share':
                jobstr += "export MPI_USE_ARRAY=false\n"

            jobstr += 'python run_job.py --job_id {0}\n'.format(job.job_id)

            pbs_file = job.job_dir.joinpath('job_' + job.job_id + '.pbs')
            with pbs_file.open(mode='w') as f:
                f.write(jobstr)

            # Write the python run script for the job
            job._write_run_script()

    def _solve_nodes_cores(self):
        """Private method to solve the number of nodes and cores if not all three specified"""

        import math

        if not self._nproc and self._nnodes and self._ppn:
            self._nproc = self._nnodes * self._ppn
        if not self._nnodes and self._nproc and self._ppn:
            self._nnodes = math.ceil(self._nproc / self._ppn)
        if not self._ppn and self._nnodes and self._nproc:
            self._ppn = math.ceil(self._nproc / self._nnodes)

        if None in [self._nproc, self._nnodes, self._ppn]:
            raise ValueError("Not enough information to solve all of nproc, nnodes, ppn.")

    @property
    def nproc(self):
        self._solve_nodes_cores()
        return self._nproc

    @nproc.setter
    def nproc(self, value):
        self._nproc = value

    @property
    def nnodes(self):
        self._solve_nodes_cores()
        return self._nnodes

    @nnodes.setter
    def nnodes(self, value):
        self._nnodes = value

    @property
    def ppn(self):
        self._solve_nodes_cores()
        return self._ppn

    @ppn.setter
    def ppn(self, value):
        self._ppn = value
