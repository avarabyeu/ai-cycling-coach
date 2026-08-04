"""
Personal coaching constants.

Copy this file to `config.py` and edit your values. `config.py` is gitignored,
so your personal numbers stay local:

    cp config.example.py config.py

The scripts fall back to the defaults below if `config.py` is missing.
"""

# Functional Threshold Power in watts.
# Best measured via a 20-minute all-out test on fresh legs:
#     FTP ≈ 0.95 × avg power for the best 20 minutes
# Re-test every 6-8 weeks or after a significant training block.
FTP = 250

# Maximum heart rate in bpm.
# Best derived from a hard interval session's observed peak (+ a few bpm buffer).
# The 220 - age formula is only a rough estimate.
HRMAX = 185
