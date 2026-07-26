# Data directory

No user data is stored in this repository.

Interview Tracker keeps each user's SQLite database, generated dashboard,
configuration, logs, and backups in:

`~/Library/Application Support/InterviewTracker/`

The `data/` directory remains only as a migration landing point for older
installations. `install.sh` securely imports a legacy `data/interviews.json`
file into the private SQLite database and removes the repository copy after
verification.
