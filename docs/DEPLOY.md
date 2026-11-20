# Deploying FedSight

Two ways to run it in public. The first is free and needs no credit card, which is what the live demo uses.
The second is the production-style option.

## Option 1: Hugging Face Spaces (free)

A Docker Space gives you 2 CPUs and 16 GB of memory at no cost, builds the Dockerfile on its own servers,
and sleeps after a couple of idle days (the first visit after that waits about a minute for it to wake).

1. Make a free account at huggingface.co and create a token with **write** access
   (Settings > Access Tokens).
2. From the repo root:

```bash
pip install huggingface_hub
export HF_TOKEN=hf_...                  # the token from step 1
export ANTHROPIC_API_KEY=sk-ant-...     # a key made just for this deployment
python scripts/deploy_hf.py --space YOUR_HF_USERNAME/fedsight
```

The script creates the Space, stores the API key as a Space secret (it is never in the repo or the image),
sets the rate limits, uploads the files the Dockerfile needs, and waits for the build. The live app is at
`https://YOUR_HF_USERNAME-fedsight.hf.space`. Build output is under the Space's **Logs** tab.

To redeploy after a change, run the same command again.

## Option 2: Google Cloud Run
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
