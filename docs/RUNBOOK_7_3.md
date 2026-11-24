# Runbook: the first paid campaign (Phase 7.3b)

For Haris, the key holder. Claude never receives, sets or reads the key and never runs `run`.
Everything here before step 5 spends nothing.

Two plans, one model (Groq, `openai/gpt-oss-120b`, the provider and model of
`evidence/provider-runs/groq-gpt-oss-120b-2026-11-21`):

| plan | template | delivery | cells | cap | per trial |
|---|---|---|---|---|---|
| `campaigns/groq_forced.plan.json` | `fetch_summary_exfil` (the task REQUIRES `fetch`, the attacked tool) | forced: a FAVOURABLE condition, resistance under guaranteed delivery | 30 (10 per source) | 400,000 tokens | 30,000 in + 2,000 out = 32,000 |
| `campaigns/groq_incidental.plan.json` | `cross_server_exfil` (the task does not need `fetch`) | incidental: exposure measures REACHABILITY | 30 (10 per source) | 400,000 tokens | 30,000 in + 2,000 out = 32,000 |

Each campaign's maximum is its cap: 400,000 tokens, $0.24 even if every token were billed at the
output price (docs/PROVIDERS.md).

**ORDER: the FORCED plan FIRST, ALONE. Never run both in one sitting** (Haris's ruling,
2026-11-24):
- The forced plan is the only one that can produce a DELIVERED rate, so it is the one that
  answers a question.
- If it shows zero compromises across 30 delivered trials, that is the headline, and the
  incidental plan adds little. If it shows compromises, the incidental plan then gives the
  reachability contrast and is worth its $0.24.
- It halves the first spend, and it gives one run's worth of real 429 and turn-count data
  before the second campaign is planned.

The incidental plan is planned again after the forced run's report has been reviewed. It is
not part of this sitting.

**ACCEPTANCE RULE (provenance, not habit):** a run's report is accepted as evidence ONLY with
the step-6 event-log output pasted ALONGSIDE it. That output covers Kernel-Power 506/507/42/107
and Resource-Exhaustion-Detector 2004 over the run's window, plus the power source. A report
without it is NOT accepted, whatever it says. The campaign has no suspend detector, by ruling
(docs/BACKLOG.md): for a 30-trial run that is watched, this check is the guarantee.

**What the result can and cannot be.** At n = 10 per source the intervals are so wide that THE
FIRST CAMPAIGN'S VALUE IS THE MECHANISM AND THE EXPOSURE DATA, NOT THE RATE. A 0/10 with
[0, 0.278] is not a result. Each source gets TWO rates, END-TO-END (over counted trials) and
DELIVERED (over exposed trials), never one "ASR". Low exposure on the incidental plan is a
FINDING (the flow is not reachable for that task), not a failure.

## 0. Before starting (check each; paste the outputs)

1. **AC power**, plugged in for the whole run.
2. **Standby, sleep and the lid action disabled, on AC AND on DC (battery), checked by command,
   not by feel.**

   **Why this step exists (measured):** on 2026-11-24 this machine was in Modern Standby
   (S0 low-power idle) for 9 h 51 m, 03:41:45-13:33:14, WHILE a full pytest run was in progress
   (the first per-commit verification of b395736; docs/BACKLOG.md, "The session timeout does not
   hold across Modern Standby"). **A running process is not protection.** `powercfg /a` on
   this machine lists "Standby (S0 Low Power Idle) Network Connected" and Hibernate as
   available. The campaign does NOT detect a suspend by itself, by ruling (docs/BACKLOG.md).
   This step prevents one, and step 6's event-log check proves there was none.

   **Read the values** (PowerShell, the active scheme):
   ```powershell
   powercfg /getactivescheme
   powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
   powercfg /query SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE
   powercfg /qh SCHEME_CURRENT SUB_BUTTONS LIDACTION
   ```
   **LIDACTION is hidden from `/query` on this machine:** `/query ... LIDACTION` prints only the
   scheme line. `/qh`, which includes hidden settings, prints it. `/qh` is not listed in
   `powercfg /?` here, but it works (2026-11-24).

   **Values that must hold** (each is "Current AC/DC Power Setting Index"):

   | setting | GUID | AC | DC, for the sitting |
   |---|---|---|---|
   | Sleep after (STANDBYIDLE) | 29f6c1db-86da-48c5-9fdb-f2b67b1f44da | `0x00000000` | `0x00000000` |
   | Hibernate after (HIBERNATEIDLE) | 9d7815a6-7ee4-497e-8888-515a05f02364 | `0x00000000` | left as measured, `0x7fffffff` |
   | Lid close action (LIDACTION) | 5ca83367-6e45-459f-a27b-476b1d01c936 | `0x00000000` ("Do nothing") | `0x00000000` ("Do nothing") |

   - **Reading 0 as "never":** that comes from powercfg's own output (minimum possible setting
     `0x00000000`, units "Seconds"). It is NOT from a cited Microsoft document.
   - **"Do nothing"** is powercfg's own friendly name for LIDACTION index 000.
   - **Any other value: NOT READY.** Do not start.

   **The DC side is set for the sitting and RESTORED after it** (step 7). If DC stays armed, an
   AC drop plus idle time, or a closed lid, suspends the machine and invalidates attempts in a
   PAID run. Measured before the first sitting (2026-11-24): DC STANDBYIDLE `0x000000b4`
   (180 s), DC LIDACTION `0x00000001` ("Sleep"). Print the before values first (the commands
   above), then set:
   ```powershell
   powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e 238c9fa8-0aad-41ed-83f4-97be242c8f20 29f6c1db-86da-48c5-9fdb-f2b67b1f44da 0
   powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e 4f971e89-eebd-4455-a8de-9e59040e7347 5ca83367-6e45-459f-a27b-476b1d01c936 0
   powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e
   ```
   The GUIDs are from this machine's `/query` and `/qh` output: the Balanced scheme
   `381b4222-...`, the Sleep subgroup `238c9fa8-...`, the "Power buttons and lid" subgroup
   `4f971e89-...`. The syntax is from `powercfg /? /setdcvalueindex` and
   `powercfg /? /setactive`, whose own examples use the same scheme GUID. Then re-run the four
   read commands, paste the output, and check it against the table.
3. **Free memory.** Close Chrome (including its background apps) and run `wsl --shutdown`. Then:
   ```powershell
   Get-CimInstance Win32_OperatingSystem | Select-Object FreePhysicalMemory, FreeVirtualMemory
   ```
   (kilobytes). On 2026-11-24, the 1cfc7cc verification failed when the free commit was 0.24%.
4. **Clean tree on the pushed commit:**
   ```powershell
   git status --short
   git log --oneline -1
   git ls-remote origin refs/heads/main
   ```
   `git status --short` prints nothing, and the two commits match.
5. **The corpus cache** `.proveflow-corpus/` is present. If the preflight refuses with
   "run tools/ingest_corpus.py first", run `uv run python tools/ingest_corpus.py`. It fetches
   public GitHub raw files only, with no key, and nothing is paid.
6. **`proveflow.toml` lives at the repo root and is gitignored** (`.gitignore`). That is the
   path `src/proveflow/cli.py:42` already expects, so `--config proveflow.toml` is never a
   path to remember. Because it is ignored, it does not dirty the tree that check 4 requires
   clean. It holds only the NAME of the variable that holds the key, never the key. Its
   content, with a `[[provider]]` entry matching the plan exactly (`run` refuses any
   difference):
   ```toml
   [[provider]]
   name = "groq"
   base_url = "https://api.groq.com/openai/v1"
   model = "openai/gpt-oss-120b"
   api_key_env = "YOUR_KEY_VARIABLE_NAME"   # the NAME of an env var; never the key
   send_seed = true
   ```
   The file on the dev machine names `GROQ_API_KEY`. Check: `git status --short` still
   prints nothing with the file present.

## 1. Dry runs (scripted model side, real twins, nothing paid)

```powershell
uv run python -m proveflow.runner.paid dry-run campaigns/groq_forced.plan.json --root $env:TEMP\pf-dry
```

It prints a SCRIPTED report. Its rates AND its exposure measure the SCRIPT: the script calls the
tools the template's utility names, so its exposure is fixed by the script. A dry run CANNOT
predict exposure (docs/METHODOLOGY.md threat 14). The forced plan's script calls `fetch`, so the
dry run shows "exposed 10 of 10 (SCRIPTED ...)". That says nothing about the model.

## 2. Preflight (no network call, no twin, nothing paid). Paste the output

```powershell
uv run python -m proveflow.runner.paid preflight campaigns/groq_forced.plan.json --dry-run-root $env:TEMP\pf-dry
```

Check that it prints `fits` and the campaign id, and note the campaign id
(`groq_forced_<12 hex>`). The estimate comes from the dry run's
MEASURED request bytes and a calibration from N = 2 requests. A real model may take more turns
than the script's two; if a trial runs 4x longer than modelled, the cap stops the campaign
after about 12 trials, on purpose.

## 3. Set the key (your shell only)

Set it in this PowerShell session the way you did for the manual run, under the variable your
config names. Never in a file. `run` checks only that the variable is set; the HTTP client
reads it at call time.

## 4. Confirm without spending

```powershell
uv run python -m proveflow.runner.paid run campaigns/groq_forced.plan.json --config proveflow.toml --state runs\<forced campaign id>.campaign.json
```

Without `--yes` it prints the maximum spend and exits 2, having created nothing.
`runs/` is gitignored.

## 5. The paid run: the FORCED plan only

```powershell
uv run python -m proveflow.runner.paid run campaigns/groq_forced.plan.json --config proveflow.toml --state runs\<forced campaign id>.campaign.json --yes
```

Write down the run's start and end time (local) for step 6. The incidental plan is NOT run in
this sitting (see ORDER above).

## If it stops

| what you see | what it means | what to do |
|---|---|---|
| it pauses, then continues | an HTTP 429: handled, the attempt ends `rate_limited`, the campaign waits (2, 4, 8 ... 60 s, or a numeric Retry-After if longer) and starts a NEW attempt | nothing |
| `RateLimitExhausted` | 5 consecutive 429-ended attempts of one cell in this run; state saved | wait, then re-run the SAME command: it resumes |
| `AttemptFailed` (any non-429 failure, e.g. `provider_error`) | FAIL CLOSED: the campaign stops, state saved | **STOP. Do not resume.** Paste the message and the last lines. A non-429 failure in a paid campaign may be systematic, and continuing would spend money per cell on a setup that may already be broken (Haris's F4 ruling). |
| `BudgetExhausted` / `BudgetOverspent` | the cap stopped it: trials ran longer than modelled | STOP and paste. That is the cap doing its job. |
| `CorruptCampaignState` | the state file is not this plan's, or is damaged | STOP and paste. Never edit the state file. |
| the process died (crash, killed window) | the last attempt stays `started` | re-run the SAME command: the attempt is marked interrupted and charged from its transcript, then retried |

## 6. After the run (paste all of it; REQUIRED for acceptance)

1. **The power and memory events over the run's window, and the power source** (start and end
   from step 5). Without this output the report is NOT accepted as evidence:
   ```powershell
   Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=506,507,42,107; StartTime='<start>'; EndTime='<end>'}
   Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Resource-Exhaustion-Detector'; Id=2004; StartTime='<start>'; EndTime='<end>'}
   Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=105; EndTime='<end>'} -MaxEvents 3 | ForEach-Object { '{0} AcOnline={1}' -f $_.TimeCreated, (([xml]$_.ToXml()).Event.EventData.Data | Where-Object Name -eq 'AcOnline').'#text' }
   ```
   The first two should print "No events were found". ANY event means attempts in that window
   are INVALID (they measure nothing): do not count them, stop and report. The third shows the
   latest power-source changes (event 105, AcOnline). The run must have been on AC throughout.
2. **The exact-key scan** of `runs\` (your check, as for the evidence run). The key in any of
   the matcher's 10 encodings must appear in no file.
3. **The report text** the run printed, and `runs\<campaign id>.report.json`.
4. **Do NOT copy anything to docs/results/, and do not commit anything under `runs/`,** until
   the report has been reviewed. ZERO REAL POSITIVES stands until then.

## 7. After the sitting: restore the DC values

Restore what step 0.2 measured before the sitting (DC STANDBYIDLE `0x000000b4` = 180 s, DC
LIDACTION `0x00000001` = "Sleep"). If the before values printed at step 0.2 differ, restore
those instead:
```powershell
powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e 238c9fa8-0aad-41ed-83f4-97be242c8f20 29f6c1db-86da-48c5-9fdb-f2b67b1f44da 180
powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e 4f971e89-eebd-4455-a8de-9e59040e7347 5ca83367-6e45-459f-a27b-476b1d01c936 1
powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
powercfg /qh SCHEME_CURRENT SUB_BUTTONS LIDACTION
```
The AC values stay as step 0.2 requires.
