# Working in this repository

This project contains the F1 Fantasy advisor skill at
`skill-dev/f1-fantasy-advisor/SKILL.md`. Read it for Fantasy data, prediction or
lineup tasks, even when the skill is not separately installed. Resolve its
`scripts/` and `references/` paths relative to that skill directory; run commands
from the user's Fantasy workspace, where private `data/` belongs.

For a request to calculate this week's teams, start with
`skill-dev/f1-fantasy-advisor/references/race-week-runbook.md`. It covers target
selection, evidence collection, current account inputs, execution and reporting.
Use `forecast-inputs.md` for schemas and `forecast-model.md` for scoring details.
The active v1 entrypoint is `scripts/fantasy_forecast.py run` under the skill.
Historical/live optimizers serve different purposes; they do not predict the
next race. Default `--allow` is 10, with ordinary fixed 2x and independent
evaluation of all three managed teams unless the user narrows the request.

`data/`, `now.md`, `LOCAL_WORKING_NOTES.md` and `todolist.md` are ignored local
state. Do not put private account snapshots or downloaded evidence into committed
examples. Demo and Replay teams are test inputs, never current account state.
Read saved account facts before asking for information; unknown remaining free
transfers cannot be recovered from public feeds or assumed from a stale lineup.

When modifying Python behavior, run the relevant tests with
`python3 -m unittest discover -s tests`. For skill/document changes, check command
and schema accuracy and local reference links. Preserve existing work and local
account records; a forecast does not authorize account updates or transfers.
