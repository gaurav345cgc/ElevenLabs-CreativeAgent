# When the pipeline stops — operator guide

Use this when a meditation run fails, before a production batch, or when a non-technical reviewer needs to see what went wrong.

## One command

From the project folder in PowerShell:

```powershell
.\scripts\audit.ps1
```

To save a copy for email or Slack:

```powershell
.\scripts\audit.ps1 -SaveReport
```

The saved file is: `output/audit-report.txt`

## How to read the report

Each line is marked:

| Mark | Meaning |
|------|---------|
| **OK** | Healthy — no action needed |
| **WARN** | Working, but something may need attention soon |
| **FAIL** | Blocked — fix this before running again |

The report checks:

1. **Cloud API** — AWS intake API and database
2. **ElevenLabs credits** — voice synthesis balance (typical run ≈ 4,700 credits)
3. **Last pipeline run** — saved progress from the last `run.ps1`
4. **Transcript** — Agent 1 (write) + Agent 2 (enhance) status
5. **Audio job** — Agent 3 (TTS) status
6. **Final MP3** — whether the finished file exists on disk

## Common failures (plain English)

### ElevenLabs credits exhausted

**Symptom:** Audio job FAIL, message mentions quota or credits.

**Fix:** Top up at [elevenlabs.io](https://elevenlabs.io). Free tier is 10,000 characters/month (~2 full meditations). After topping up, ask engineering to replay TTS or run `.\scripts\run.ps1` to resume.

### Cloud API unavailable (503)

**Symptom:** Cloud API FAIL, or compose step fails with Service Unavailable.

**Fix:** Wait 2–5 minutes and run `.\scripts\audit.ps1` again. The system retries automatically. If it persists, contact engineering.

### Audio job REVIEW_REQUIRED

**Symptom:** Agent 3 stopped; status REVIEW_REQUIRED.

**Fix:** Run the audit and share `output/audit-report.txt` with engineering. Often caused by credits or a chunk error in CloudWatch.

## After fixing an issue

Resume (does not start over from scratch):

```powershell
.\scripts\run.ps1
```

Start a completely new meditation:

```powershell
.\scripts\run.ps1 -Fresh
```

## For technical staff

- Full logs: CloudWatch `/aws/lambda/creative-agent-dev-tts-worker` and `creative-agent-dev-enhancer`
- JSON audit: `.\scripts\audit.ps1 -Json`
- Checkpoint file: `output/.pipeline_run.json`
