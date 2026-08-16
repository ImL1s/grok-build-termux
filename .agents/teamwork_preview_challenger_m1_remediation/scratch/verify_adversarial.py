import os
import subprocess
import tempfile
import sys

def run_cmd(cmd, cwd=None):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return res.returncode, res.stdout, res.stderr

print("Starting Empirical Adversarial Challenge...")
