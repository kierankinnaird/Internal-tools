Small internal tools for construction and cost engineers, run locally on each person's computer. Each tool is a self contained module that can run on it's own or later be plugged into a shared application.

## Safety of the local app

The app has no login, so it only answers requests that come from its own pages, addressed to this computer (`hosts/security.py`).
A web page open in another tab cannot make your browser create or delete anything here, other sites cannot frame it, and
it will not answer to a name other than `127.0.0.1`, `localhost` or `::1`. To reach it by another name on purpose, set the
environment variable `NMC_ALLOWED_HOSTS` to a comma-separated list of names before starting it.

Work in progress.