# Render Deployment Handoff

Live service: [`https://northwind-expense-review.onrender.com`](https://northwind-expense-review.onrender.com)

This repository can be redeployed through a Render Blueprint:

[`https://dashboard.render.com/blueprint/new?repo=https://github.com/Balavardhanreddysheelam/northwind-expense-review`](https://dashboard.render.com/blueprint/new?repo=https://github.com/Balavardhanreddysheelam/northwind-expense-review)

The public repository excludes the hiring-team attachments and private evaluation package. The deployed application uses the synthetic demo dataset in `app/public_demo.py`. Reviewers can upload held-out receipts through the browser.

## Resources Render should create

| Resource | Expected name | Plan |
|---|---|---|
| Web service | `northwind-expense-review` | Free |
| PostgreSQL database | `northwind-expense-review-db` | Free |

The Blueprint connects `DATABASE_URL` from the database to the web service automatically.

## Environment variables

Verify these values before applying the Blueprint:

| Variable | Value | Required action |
|---|---|---|
| `OPENAI_API_KEY` | New rotated OpenAI project key | Paste directly into Render. Never commit or send it in chat. |
| `OPENAI_MODEL` | `gpt-5.4-mini-2026-03-17` | Already configured |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Already configured |
| `ENABLE_EMBEDDINGS` | `true` | Already configured |
| `SEED_DEMO_SUBMISSIONS` | `true` | Already configured |

## Deploy

1. Open the Blueprint link above while signed into Render.
2. Confirm the web service and PostgreSQL database names.
3. Paste a newly rotated key into `OPENAI_API_KEY`.
4. Apply the Blueprint.
5. Wait for the web service status to become `Live`.

The first build can take several minutes. A free web service can take about one minute to wake after inactivity.

## Live verification

| Check | URL or action | Expected result |
|---|---|---|
| Health | [`/health`](https://northwind-expense-review.onrender.com/health) | `{"status":"ok"}` |
| Dashboard | [`/`](https://northwind-expense-review.onrender.com/) | Synthetic demo submissions are visible |
| Flagged review | Open the flagged demo submission | Findings include exact policy quotations |
| Policy answer | Ask `What is the dinner meal cap?` | Grounded answer with a cited clause |
| Refusal path | Ask `What is the weather tomorrow?` | Explicit refusal |
| Upload | Submit a TXT receipt | New submission appears in history |
| Override | Add an override with a comment | Timestamped audit entry appears |
| Persistence | Redeploy or restart, then reopen history | Submission and override remain present |

## Troubleshooting

- If the build fails, inspect the Render build logs first.
- If startup fails, verify `DATABASE_URL` is connected from the Blueprint database and `OPENAI_API_KEY` is present.
- If the site is slow on the first request, allow the free web service to wake.
- If model calls fail, rotate the OpenAI key and update only the Render secret.
- Free Render PostgreSQL databases expire after 30 days. Upgrade if the review window requires longer availability.
