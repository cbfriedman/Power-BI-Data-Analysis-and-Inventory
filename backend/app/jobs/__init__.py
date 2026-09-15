"""Background jobs and the scheduler that runs them.

The scheduler is behind :class:`app.jobs.runner.JobRunner` so the choice of
APScheduler (ADR 0011) is a one-module swap, and so tests drive the jobs
with a fake runner and no threads.
"""
