# FedSight walkthrough: how I'd explain it in an interview

This is a study sheet for the Technology Showcase conversation. It covers the pitch, why each design choice was
made, what I'd say about the trade-offs, and the questions I expect. Everything here is something I can point to in
the code.

## The 60-second version

> FedSight answers questions about GAO reports, FEMA regulations and CDC data, and every sentence it writes links
> back to the passage or table row it came from. It's built for the kind of work a federal analyst does: the answer
> has to be checkable. Documents go through a hybrid search (vectors plus keywords, then a reranker). Numbers
> go through read-only SQL against FEMA and CDC datasets. Claude's citation feature ties each sentence to a source,
> and then my own code verifies every quote against the source text and every number against the evidence before the
> answer is shown. If it can't support an answer, it says so. I wrote a 60-question evaluation set with known answers,
> including questions the sources can't answer and prompt-injection attempts, and I run it before releases. It's
> deployed on Cloud Run, and the code, tests and results are on GitHub.

I built it with Claude Code as a coding assistant, which is the workflow the posting describes. I can explain every
file, because I made the decisions below and checked the output.

## How it maps to the posting

| The posting asks for | Where it shows up |
|---|---|
| Rapid prototyping with LLMs, coding assistants and agentic frameworks | Built end to end with Claude Code; the agent loop in `agent.py` is a small tool-using loop |
| RAG, semantic search, prompt engineering | `search.py` (hybrid retrieval, reranking), the system prompt and tool descriptions in `agent.py` |
| Simple agent behaviors | The model chooses between a document-search tool and a SQL tool, and can use both |
| Evaluating model outputs, testing workflows | `evals/` (golden set, scoring, LLM judge), 70+ unit tests, CI |
| Responsible AI guardrails | `guardrails.py` and `ops.py`: PII redaction, injection screening, output verification, rate and spend caps, audit log |
| Frontend, backend, APIs, data pipelines | `web/`, `api.py`, `scripts/build_*.py` |
| Legacy or regulated data environments | Read-only SQL with an allow-list, hashed client IDs, no secrets in the image, audit trail, honest handling of dated sources |
| Cloud (AWS, Azure or GCP) | Dockerfile + Cloud Run, key in Secret Manager (`docs/DEPLOY.md`) |
| Claude, Vertex AI, Azure OpenAI | Claude API with citations; the model client is injected, so swapping providers touches one file |
| Zero to prototype independently | The whole repo, including finding and cleaning the data |

## Design decisions and why

**Why hybrid search, not just vectors.** Government text is full of exact identifiers: "GAO-20-360", "44 CFR 206.110",
program acronyms. Vector search blurs those; BM25 nails them. Vectors catch paraphrases that keyword search misses.
I fuse the two rankings with reciprocal rank fusion (no score tuning needed), then rerank the top candidates with a
cross-encoder, which reads the question and passage together and is much more precise. Rerank scores below a threshold
are dropped, so "nothing relevant" is a possible outcome, and a cap per document keeps one long report from crowding
out the rest.

**Why Claude's citation blocks instead of asking the model to write citations.** If you ask a model to cite,
it can invent a plausible-looking reference. With `search_result` blocks and `citations: enabled`, the API returns
structured pointers to the exact text it was shown. I then check, in plain Python, that each cited quote really appears
in the provided text. That's a deterministic check on top of a model feature, and it's the thing I'd lead with when asked
about hallucinations.

**Why a SQL tool instead of putting tables in the vector index.** "How many major disaster declarations has Florida
had since 2017?" is a counting question. Embedding table rows and hoping the model adds them up is how you get a
confident wrong number. SQL gives an exact answer and an inspectable query. The risk is letting a model write SQL, so the
tool allows a single SELECT, uses a SQLite authorizer and `query_only`, returns at most 50 rows and has a time
budget. The tests try DROP, INSERT, ATTACH, PRAGMA and a runaway recursive query.

**Why force a tool call before answering.** `tool_choice: any` on the first step means the model can't answer from
memory. On the last step I switch to `tool_choice: none` so it must answer with what it has rather than looping.

**Why layered guardrails.** No single control is reliable, so there are several that fail differently:
1. Input: PII is redacted before the model or the logs see it; regex screening catches obvious injection and the
   request never reaches the model.
2. Prompt: documents and query results are labelled as data, not instructions.
3. Output: quotes verified against sources, numbers checked against evidence, citation coverage measured. Failing
   answers are replaced with an honest "couldn't support this" message.
4. Operations: rate limit per visitor, a daily cap as a spend ceiling, and an audit log with hashed client IDs.

I'm upfront that the regex screen is the weakest layer; it only stops lazy attacks. That's why the evaluation set
includes injection prompts the regex does *not* catch (for example asking for the rules translated into French).

**Why the evaluation set looks the way it does.** Accuracy on easy questions is a vanity number. The set deliberately
mixes document facts, regulation text, SQL numbers whose ground truth I computed separately with pandas, questions that
need both a document and data, questions the sources can't answer (the correct behaviour is to decline), and injection.
Answers are scored two ways: required facts must appear (deterministic), and a small Claude model judges
correctness against a reference and whether every claim is supported by the sources. I report both and I report
misses, because a perfect score would mean the test is too easy.

**Why Cloud Run.** Scale to zero means the demo costs almost nothing idle, and the container is portable. The
embedding and reranking models are baked into the image at build time to avoid slow cold starts. The API key is a Secret
Manager secret, never in the image.

**Why small local embedding models.** They run on CPU, cost nothing per query, and keep the document text on infrastructure I
control. I measured throughput on the machine I was using; a 12-layer model would have taken about 45 minutes to embed the
corpus, so I picked a 6-layer model (`snowflake-arctic-embed-xs`) that took about 13 minutes and relied on the keyword
search and reranker to cover the difference.

## Honest limitations (say these before they ask)

* **GAO coverage stops in mid-2020.** gao.gov blocks scripted downloads, so I used the public GovReport research dataset.
  FEMA regulations and CDC pages are current. In production I'd ingest GAO directly with permission or via its
  published feeds.
* **87 reports, not all of GAO.** The index is a curated slice on disaster response, public health, IT and program
  integrity.
* **The rate limiter is per instance and in memory.** Fine for a demo; production would use a shared store.
* **Faithfulness is partly judged by another model.** That judge can be wrong, which is why the deterministic checks
  sit beside it.
* **Provisional CDC counts get revised.** The data tables are a snapshot, and answers say which period they refer to.

## Questions I expect, and short answers

**How do you know it doesn't hallucinate?** I don't claim it can't. I reduced the ways it can: forced retrieval, citations
returned by the API, my own verification of every quote and number, and a decline path. Then I measure it. The
evaluation tab shows the current numbers, including the misses.

**What happens when the documents contain instructions?** The prompt says document text is data, and the tool results
come back as search-result blocks rather than as user turns. I also test it with injection prompts. I wouldn't claim it's
immune; I'd say it's layered and measured.

**What would you change to run this inside an agency?** Authentication and per-user authorization, document-level
access controls carried through retrieval, a shared rate limiter, logs shipped to the agency's SIEM, FedRAMP-authorized
model hosting (for example Claude through Vertex AI or Bedrock in a GovCloud environment), and a human review step for
high-impact answers.

**How would you scale it?** The index is small enough to run in memory. Past a few hundred thousand passages I'd move
retrieval to a managed vector store, precompute embeddings in a pipeline, and cache frequent questions.

**What was the hardest part?** Getting verification to be strict without rejecting good answers: for example, the
checker has to treat "1,293" and "1293" the same and ignore single digits like "3 recommendations". I also had to make
every passage's citation ID unique, because several passages from one report share a URL and the numbering broke.

**What would you do next?** Re-ingest newer GAO reports, add a feedback button that feeds the evaluation set, add
Vertex AI as a second model provider, and track answer quality over time in CI with a smaller smoke set.

## Stories for the behavioral questions (use your own words; these are real things that happened in this build)

**Bias for building.** I started with an empty folder and a job posting and ended up with a deployed,
tested app with an evaluation page. I'd rather ship a working thin version and improve it than design for weeks.

**Grit.** The GAO website blocks scripted access. I didn't work around it; I switched to a public research dataset, wrote
down the date limitation in the README and the app, and kept going. Later, the embedding job was going to take 45 minutes;
I benchmarked it, switched models, and finished in a quarter of the time.

**Mission-first.** I designed around what an analyst or auditor needs: a source for every claim, an honest "I don't know",
and an audit trail. The most useful feature isn't a good answer, it's an answer you can check.

**Limitless curiosity.** I learned Claude's citation feature, the SQLite authorizer API, reciprocal rank fusion and
cross-encoder reranking for this, and read the documentation instead of guessing.

## 5-minute live demo plan

1. Ask a document question; click a citation to show the quote.
2. Open "How this answer was produced"; point out the checks.
3. Ask a counting question; show the SQL and rows.
4. Ask something out of scope; show the decline.
5. Show the Evaluation tab, then `evals/golden.json` and `tests/`.
6. Show the repo, CI badge and the Cloud Run service.
