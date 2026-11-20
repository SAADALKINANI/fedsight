# 2-minute demo: shot list and narration

Record the live site at 1280x720 with any screen recorder (QuickTime, OBS, Loom). Read the narration in your
own words; it's written to be spoken, not recited. Total target: 1:50 to 2:05.

| Time | On screen | Say |
|------|-----------|-----|
| 0:00 | Landing page | "This is FedSight. It answers questions about GAO reports, FEMA rules and CDC data, and every sentence links back to the exact passage or table row it came from." |
| 0:12 | Type: *What did GAO find about FEMA's disaster workforce?* Press Ask. | "Say I'm an analyst and I want to know what GAO found about FEMA's disaster workforce." |
| 0:25 | Answer appears. Click citation **1**. Page scrolls to the source card with the quoted text. | "The answer is short and every claim has a numbered citation. Clicking one jumps to the quote in the report. The green badge means the quote was checked against the source text in code, not just trusted." |
| 0:45 | Open **How this answer was produced**. | "Here's the trace: it searched the documents, how many passages came back, and the checks that ran: citations verified, numbers grounded, no personal data." |
| 1:00 | Type: *How many major disaster declarations has Florida had since 2017?* | "It isn't only documents. For counts and totals the model writes a read-only SQL query against FEMA's open data." |
| 1:12 | Show the SQL block and result table in Sources. | "Here's the query it ran and the rows it got back. That's the audit trail. The SQL tool can only run a single SELECT, and it's limited to 50 rows and a time budget." |
| 1:30 | Type: *What is FEMA's budget request for fiscal year 2030?* | "Now a question the sources can't answer." |
| 1:38 | Grey "Not in sources" badge. | "It says so instead of guessing. That behaviour is tested, along with prompt-injection attempts, in the evaluation set." |
| 1:48 | Click **Evaluation** tab. | "These are the results from the last run of 60 test questions: answer accuracy, faithfulness, citation validity, how often it correctly declines, and cost per question." |
| 2:00 | GitHub repo page | "It's deployed on Cloud Run, the code and evaluation are on GitHub. Thanks for watching." |

## Tips

* Ask each question once beforehand so you know the answers look right, then clear the box and ask it on camera.
* Zoom the browser to 110% so the text is readable in a small video player.
* Use your own voice. If you'd rather not talk, add captions with the table text above.
