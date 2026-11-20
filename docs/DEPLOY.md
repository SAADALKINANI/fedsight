# Deploying FedSight to Google Cloud Run

Cloud Run bills per request and scales to zero, so a portfolio demo that gets a handful of visits a day
costs close to nothing. The only real cost is the Anthropic API, and the app caps that (see below).

## One-time setup

```bash
# 1. pick a project that has billing turned on
gcloud config set project YOUR_PROJECT_ID

# 2. turn on the services the deploy uses
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com secretmanager.googleapis.com

# 3. store the API key as a secret (it never goes in the image or the repo)
printf '%s' 'sk-ant-...' | gcloud secrets create anthropic-api-key --data-file=-

# 4. let the Cloud Run service account read it
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding anthropic-api-key \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
```

## Deploy

From the repo root:

```bash
gcloud run deploy fedsight \
    --source . \
    --region us-east4 \
    --allow-unauthenticated \
    --cpu 2 --memory 2Gi \
    --min-instances 0 --max-instances 2 \
    --concurrency 8 \
    --timeout 120 \
    --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest \
    --set-env-vars FEDSIGHT_RATE_LIMIT=15,FEDSIGHT_DAILY_CAP=200
```

`--source .` builds the Dockerfile with Cloud Build. The image downloads the embedding and reranking
models at build time, so a cold start only has to load them from disk (about 10 seconds).

The command prints the service URL. Check it:

```bash
curl https://YOUR-SERVICE-URL/api/health
```

## Cost controls

* `FEDSIGHT_RATE_LIMIT` limits questions per visitor per hour; `FEDSIGHT_DAILY_CAP` limits total questions per day.
  At roughly 3 cents a question, a 200-question day tops out around $6.
* `--max-instances 2` bounds compute.
* Set a monthly budget alert on the project (Billing > Budgets) and a spend limit on the Anthropic key.
* The rate limiter is in memory, so each Cloud Run instance counts separately. That's fine for a demo;
  a production service would move it to Redis or Memorystore.

## Updating

Re-run the same `gcloud run deploy` command. To rotate the key, add a new secret version and redeploy.

## Tearing it down

```bash
gcloud run services delete fedsight --region us-east4
gcloud secrets delete anthropic-api-key
```
