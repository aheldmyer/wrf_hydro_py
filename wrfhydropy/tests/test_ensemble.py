import copy
import deepdiff
import os
import pathlib
import pandas
import pytest
import subprocess

from wrfhydropy.core.domain import Domain
from wrfhydropy.core.job import Job
from wrfhydropy.core.model import Model
from wrfhydropy.core.schedulers import PBSCheyenne
from wrfhydropy.core.simulation import Simulation
from wrfhydropy.core.ensemble import EnsembleSimulation
from wrfhydropy.core.ioutils import WrfHydroTs


@pytest.fixture()
def model(model_dir):
    model = Model(
        source_dir=model_dir,
        model_config='nwm_ana'
    )
    return model


@pytest.fixture()
def domain(domain_dir):
    domain = Domain(
        domain_top_dir=domain_dir,
        domain_config='nwm_ana',
        compatible_version='v5.1.0'
    )
    return domain


@pytest.fixture()
def simulation(model, domain):
    sim = Simulation()
    sim.add(model)
    sim.add(domain)
    return sim


@pytest.fixture()
def simulation_compiled(model, domain, tmpdir):
    sim = Simulation()
    sim.add(model)
    sim.add(domain)
    sim.model.compile_log = subprocess.run(
        'pwd',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    wrf_hydro_exe = pathlib.Path(tmpdir).joinpath('wrf_hydro_exe.dum')
    wrf_hydro_exe.touch()
    sim.model.wrf_hydro_exe = wrf_hydro_exe
    return sim


@pytest.fixture()
def job():
    job = Job(
        job_id='test_job_1',
        model_start_time='1984-10-14',
        model_end_time='2017-01-04',
        restart=False,
        exe_cmd='bogus exe cmd',
        entry_cmd='bogus entry cmd',
        exit_cmd='bogus exit cmd'
    )
    return job


@pytest.fixture()
def scheduler():
    scheduler = PBSCheyenne(
        account='fake_acct',
        email_who='elmo',
        email_when='abe',
        nproc=216,
        nnodes=6,
        ppn=None,
        queue='regular',
        walltime="12:00:00"
    )
    return scheduler


def test_ensemble_init():
    ens = EnsembleSimulation()
    assert type(ens) is EnsembleSimulation
    # Not sure why this dosent vectorize well.
    atts = ['members', '_EnsembleSimulation__member_diffs', 'jobs', 'scheduler', 'ncores']
    for kk in ens.__dict__.keys():
        assert kk in atts


def test_ensemble_addsimulation(simulation, job, scheduler, simulation_compiled):
    sim = simulation
    ens1 = EnsembleSimulation()
    ens2 = EnsembleSimulation()

    # This sim does not have a pre-compiled model
    with pytest.raises(Exception) as e_info:
            ens1.add([sim])

    sim = simulation_compiled
    ens1.add([sim])
    ens2.add(sim)
    assert deepdiff.DeepDiff(ens1, ens2) == {}

    # add a sim with job and make sure it is deleted.
    sim.add(job)
    sim.add(scheduler)
    ens1 = EnsembleSimulation()
    ens1.add(sim)
    assert all([len(mm.jobs) == 0 for mm in ens1.members])
    assert all([mm.scheduler is None for mm in ens1.members])


def test_ensemble_addjob(simulation, job):
    ens1 = EnsembleSimulation()
    ens1.add(job)
    assert deepdiff.DeepDiff(ens1.jobs[0], job) == {}

    job.job_id = 'a_different_id'
    ens1.add(job)
    assert deepdiff.DeepDiff(ens1.jobs[1], job) == {}


def test_ensemble_addscheduler(simulation, scheduler):
    ens1 = EnsembleSimulation()
    ens1.add(scheduler)
    assert deepdiff.DeepDiff(ens1.scheduler, scheduler) == {}

    sched2 = copy.deepcopy(scheduler)
    sched2.nnodes = 99
    ens1.add(sched2)
    assert deepdiff.DeepDiff(ens1.scheduler, sched2) == {}    


def test_ensemble_replicate(simulation_compiled):
    sim = simulation_compiled
    ens1 = EnsembleSimulation()
    ens2 = EnsembleSimulation()
    ens1.add(sim)
    ens1.replicate_member(4)
    ens2.add([sim, sim, sim, sim])
    assert deepdiff.DeepDiff(ens1, ens2) == {}


def test_ensemble_length(simulation_compiled):
    sim = simulation_compiled
    ens1 = EnsembleSimulation()
    ens1.add(sim)
    ens1.replicate_member(4)
    assert len(ens1) == 4
    assert ens1.N == 4
    # How to assert an error?
    # assert ens1.replicate_member(4) == "WTF mate?"


def test_get_diff_dicts(simulation_compiled):
    sim = simulation_compiled
    ens = EnsembleSimulation()
    ens.add([sim, sim, sim, sim])
    answer = {
        'number': ['000', '001', '002', '003'],
        'run_dir': ['member_000', 'member_001', 'member_002', 'member_003']
    }
    assert ens.member_diffs == answer


def test_set_diff_dicts(simulation_compiled):
    sim = simulation_compiled
    ens = EnsembleSimulation()
    ens.add([sim, sim, sim, sim, sim])
    ens.set_member_diffs(('base_hrldas_namelist', 'noahlsm_offline', 'indir'), 
                       ['./FOO' if mm == 2 else './FORCING' for mm in range(len(ens))])
    answer = {
        ('base_hrldas_namelist', 'noahlsm_offline', 'indir'):
        ['./FORCING', './FORCING', './FOO', './FORCING', './FORCING'],
        'number': ['000', '001', '002', '003', '004'],
        'run_dir': ['member_000', 'member_001', 'member_002', 'member_003', 'member_004']
    }
    assert ens.member_diffs == answer


def test_addjob(simulation, job):
    ens1 = EnsembleSimulation()
    ens1.add(job)
    assert deepdiff.DeepDiff(ens1.jobs[0], job) == {}

    job.job_id = 'a_different_id'
    ens1.add(job)
    assert deepdiff.DeepDiff(ens1.jobs[1], job) == {}


def test_addscheduler(simulation, scheduler):
    ens1 = EnsembleSimulation()
    ens1.add(scheduler)
    assert deepdiff.DeepDiff(ens1.scheduler, scheduler) == {}

    scheduler.queue = 'no-queue'
    ens1.add(scheduler)
    assert deepdiff.DeepDiff(ens1.scheduler, scheduler) == {}


def test_parallel_compose(simulation_compiled, job, scheduler, tmpdir):
    sim = simulation_compiled
    ens = EnsembleSimulation()
    ens.add(job)
    ens.add(scheduler)

    with pytest.raises(Exception) as e_info:
        ens.compose()

    ens.add([sim, sim])

    compose_dir = pathlib.Path(tmpdir).joinpath('ensemble_compose')
    os.mkdir(str(compose_dir))
    os.chdir(str(compose_dir))

    ens.compose()

    # The job gets heavily modified on compose.
    answer = {
        '_entry_cmd': 'bogus entry cmd',
        '_exe_cmd': 'bogus exe cmd',
        '_exit_cmd': 'bogus exit cmd',
        '_hrldas_namelist': {
            'noahlsm_offline': {
                'btr_option': 1,
                'canopy_stomatal_resistance_option': 1,
                'hrldas_setup_file': './NWM/DOMAIN/wrfinput_d01.nc',
                'indir': './FORCING',
                'restart_filename_requested': './NWM/RESTART/RESTART.2011082600_DOMAIN1'
            },
            'wrf_hydro_offline': {
                'forc_typ': 1
            }
        },
        '_hrldas_times': {
            'noahlsm_offline': {
                'kday': 11770,
                'khour': None,
                'restart_filename_requested': None,
                'start_day': 14,
                'start_hour': 0,
                'start_min': 0,
                'start_month': 10,
                'start_year': 1984
            }
        },
        '_hydro_namelist': {
            'hydro_nlist': {
                'aggfactrt': 4,
                'channel_option': 2,
                'chanobs_domain': 0,
                'chanrtswcrt': 1,
                'chrtout_domain': 1,
                'geo_static_flnm': './NWM/DOMAIN/geo_em.d01.nc',
                'restart_file': './NWM/RESTART/HYDRO_RST.2011-08-26_00:00_DOMAIN1',
                'udmp_opt': 1
            },
            'nudging_nlist': {
                'maxagepairsbiaspersist': 3,
                'minnumpairsbiaspersist': 1,
                'nudginglastobsfile': './NWM/RESTART/nudgingLastObs.2011-08-26_00:00:00.nc'
            }
        },
        '_hydro_times': {
            'hydro_nlist': {
                'restart_file': None
            },
            'nudging_nlist': {
                'nudginglastobsfile': None
            }
        },
        '_job_end_time': None,
        '_job_start_time': None,
        '_job_submission_time': None,
        '_model_end_time': pandas.Timestamp('2017-01-04 00:00:00'),
        '_model_start_time': pandas.Timestamp('1984-10-14 00:00:00'),
        'exit_status': None,
        'job_id': 'test_job_1',
        'restart': False
    }

    # This fails, 
    # deepdiff.DeepDiff(answer, ens.members[0].jobs[0].__dict__)
    # Iterate on keys to "declass"
    for kk in ens.members[0].jobs[0].__dict__.keys():
        assert ens.members[0].jobs[0].__dict__[kk] == answer[kk]

    # Check the scheduler too
    assert ens.members[0].scheduler.__dict__ == scheduler.__dict__
