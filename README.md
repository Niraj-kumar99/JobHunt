# Job Bot: entry-level PM & BA jobs across Europe

Scans the careers sites of the 336 European companies in `companies.csv`. It runs **every morning
automatically**, and also **whenever you press "Run workflow"** on GitHub. It reports only **new** postings that match all of these:

| Filter | Rule |
|---|---|
| Title | Project / Product / Program Manager, Project or Product Coordinator, Product Owner, Business Analyst, PMO roles (and junior/associate versions) |
| Location | Office anywhere in Europe, or remote in Europe/EMEA |
| Language | Job description in English |
| Experience | 0–1 years. Senior/lead titles, internships, and postings asking for 2+ years are dropped |
| Recency | Posted in the last 5 days |

Results come out as a **report page**, an **Excel file**, and a table right in the GitHub run summary.

---

## Setup (about 10 minutes, one time)

1. **Create a GitHub account** at github.com if you don't have one (free).
2. **Create a new repository**: click **+** (top right) → **New repository** → name it `job-bot`.
   Choose **Public** if you want the free report web page (step 6). Choose **Private** if you only want the spreadsheet; private works fine too.
   Click **Create repository**.
3. **Upload the files**: on the new repository page, click **uploading an existing file**, then drag in
   *everything* from this folder, **including the `.github` folder**. On a Mac, Finder hides
   folders starting with a dot: press **Cmd + Shift + .** in Finder to show it. Click **Commit changes**.
   - Check that the file `.github/workflows/scrape.yml` appears in the repository. Without it nothing runs.
4. **Allow the bot to save its memory**: repository **Settings** → **Actions** → **General** →
   *Workflow permissions* → select **Read and write permissions** → **Save**.
5. **First run**: go to the **Actions** tab. If asked, click **"I understand my workflows, go ahead and enable them"**.
   Then click **Job scraper** → **Run workflow** → **Run workflow**. The run takes roughly 10–25 minutes.
6. *(Optional, public repos)* **Report web page**: **Settings** → **Pages** → *Source*: **Deploy from a branch**,
   Branch **main**, folder **/docs** → **Save**. After the next run, your page is at
   `https://<your-username>.github.io/job-bot/`. Bookmark it on your phone.

## Using it

- **Run it now**: **Actions** → **Job scraper** → **Run workflow**. The GitHub mobile app has the same button.
- **Automatic**: every day at 05:17 UTC (07:17 Berlin in summer). To change the time, edit the `cron` line in
  `.github/workflows/scrape.yml`.
- **See results**:
  - open the finished run: the summary shows a table of new jobs with links, and **job-matches** at the bottom downloads the Excel file;
  - or open `output/job_matches.xlsx` in the repository. It has three sheets: new matches, last 30 days, and coverage;
  - or the report page from step 6.

**About the first run:** every job on the sites is "new" at that point. So the first run reports only postings from the last 5 days, and silently records the rest. From the second run on, you only see jobs that appeared since the previous run.

## Adjusting the filters

Edit `config.yaml` on GitHub (click the file → pencil icon → **Commit changes**):

- `max_age_days`: the 5-day window.
- `allow_unstated_experience`: many postings never state the years required. With `false` (the default), they are kept only when they look entry-level: a junior/associate/graduate/coordinator title, or wording like "recent graduates". Set it to `true` to see more postings and judge them yourself.
- `title_patterns` / `search_terms`: which job titles count.
- `include_internships`: set it to `true` if you also want internships.

## How it reads the sites, and its limits

Most big employers don't build their own job listings. They use a job platform such as Workday, Greenhouse, Lever, SmartRecruiters, Ashby, Workable, Recruitee, Personio or SuccessFactors. On the first run, the bot detects which platform each company uses and reads that platform's job feed. This is much more reliable than scraping the web page, and it gives exact posting dates.

For companies where no platform is detected, it reads the careers page directly. It looks for structured job data and for job links matching your titles.

Some sites can't be read automatically. They need a real browser, block automated visitors, or use an in-house system. Those companies are listed under **Coverage** on the report page, with the reason. To fix one, find a job link from that company's site and fill in the `ats` and `ats_id` columns in `companies.csv`:

| A job link looks like | ats | ats_id |
|---|---|---|
| `boards.greenhouse.io/acme/...` | greenhouse | acme |
| `jobs.lever.co/acme/...` | lever | acme |
| `jobs.eu.lever.co/acme/...` | lever | eu/acme |
| `jobs.ashbyhq.com/acme/...` | ashby | acme |
| `jobs.smartrecruiters.com/AcmeGroup/...` | smartrecruiters | AcmeGroup |
| `apply.workable.com/acme/...` | workable | acme |
| `acme.recruitee.com/...` | recruitee | acme |
| `acme.jobs.personio.de/...` | personio | acme.jobs.personio.de |
| `acme.wd3.myworkdayjobs.com/en-US/External/...` | workday | acme.wd3.myworkdayjobs.com\|acme\|External |
| a SuccessFactors site such as `jobs.acme.com` | successfactors | jobs.acme.com |

You can add or remove companies in `companies.csv` the same way. Only `name` and `careers_url` are required.

The filters work from the text of each posting, so they will occasionally be wrong. A job may state its experience requirement unclearly, or list locations in an unusual way. Each match shows the experience reason it was kept for (e.g. "requires 0-1 yrs", "entry-level title"), so you can judge it quickly.

## Running it on your own computer (optional)

```
pip install -r requirements.txt
python -m jobbot run                  # full scan
python -m jobbot run --limit 20       # quick test on the first 20 companies
python -m jobbot check "Adyen"        # see which platform was found and why each job passed or failed
```

## Files

- `companies.csv`: the companies to scan.
- `config.yaml`: the filter settings.
- `data/`: the bot's memory (jobs already seen, detected platforms, past matches). Delete `seen_jobs.json` to start fresh.
- `docs/index.html`: the report page.
- `output/`: the Excel and CSV results.
- `jobbot/`: the code.
