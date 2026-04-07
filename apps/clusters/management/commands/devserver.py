import os
import subprocess
import sys

from daphne.management.commands.runserver import Command as DaphneCommand

_celery_proc = None


class Command(DaphneCommand):
    help = "Start Daphne dev server + Celery worker together."

    def handle(self, *args, **options):
        # Django's auto-reloader forks: RUN_MAIN=true in the inner (Django) process.
        # Start Celery only in the outer (watcher) process so it runs exactly once.
        if os.environ.get("RUN_MAIN") != "true":
            self._start_celery()
        try:
            super().handle(*args, **options)
        finally:
            if os.environ.get("RUN_MAIN") != "true":
                self._stop_celery()

    def _start_celery(self):
        global _celery_proc
        if _celery_proc and _celery_proc.poll() is None:
            return
        cmd = [
            sys.executable, "-m", "celery",
            "-A", "talos_dashboard",
            "worker",
            "-l", "info",
            "--concurrency", "2",
        ]
        self.stdout.write(self.style.SUCCESS("Starting Celery worker..."))
        _celery_proc = subprocess.Popen(cmd)

    def _stop_celery(self):
        global _celery_proc
        if _celery_proc and _celery_proc.poll() is None:
            self.stdout.write(self.style.WARNING("Stopping Celery worker..."))
            _celery_proc.terminate()
            try:
                _celery_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _celery_proc.kill()
        _celery_proc = None
