# Easy Social

A small Twitter-like social media app built with Flask.

## Features

- Register, log in, and log out with Flask-Login.
- Create posts containing text, images, videos, or a combination.
- Create poll posts with 2 to 4 options and live vote percentages.
- Repost existing posts.
- Comment on posts.
- Follow and unfollow users.
- View a personalized feed from yourself and people you follow.
- Media uploads with extension-based image/video validation.

## Setup

Install Poetry and Task, then install the project dependencies:

```bash
task install
task init-db
task run
```

The app uses SQLite by default and creates `instance/easy_social.sqlite`.

Useful environment variables:

```bash
SECRET_KEY=change-me
DATABASE_URL=sqlite:////absolute/path/to/db.sqlite
```

## Vercel and Supabase

This repo includes Vercel and Supabase deployment wiring:

- `app.py` exposes the Flask app for Vercel.
- `vercel.json` keeps Vercel project configuration in the repo.
- `requirements.txt` lists runtime dependencies for Vercel, including Postgres and Supabase Storage clients.
- `scripts/setup_supabase.py` creates the app tables and the public Storage bucket.

Create a Supabase project, then use its transaction pooler connection string for Vercel because Vercel runs the app as serverless functions. Set these environment variables in Vercel:

```bash
SECRET_KEY=use-a-long-random-value
DATABASE_URL=postgres://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
MEDIA_STORAGE_BACKEND=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_STORAGE_BUCKET=easy-social-media
```

Initialize Supabase from your machine after installing Poetry dependencies and exporting the same variables:

```bash
task install
task setup-supabase
```

## Supabase Connection Check

To test the local `.env` database and Storage bucket credentials without starting the app:

```bash
task test-supabase-connection
```

This command connects to Supabase Postgres, confirms the configured Storage bucket exists, then uploads, downloads, and deletes a small healthcheck object.

Deploy with the Vercel CLI or connect the Git repository in Vercel:

```bash
vercel deploy
```

The Supabase bucket is created as public so post media can be rendered directly in feeds. Keep `SUPABASE_SERVICE_ROLE_KEY` server-side only; do not expose it in client JavaScript.

To load sample users, follows, posts, comments, and reposts:

```bash
task import-fake-data
```

The import task loads local `.env` credentials when present, so it imports into Supabase when `DATABASE_URL` points at the Supabase database. If no `DATABASE_URL` is set, it uses the local SQLite default.

## Tests

The default test task runs unit and Flask integration tests. Selenium UI tests
are excluded from the default pytest configuration.

```bash
task test
```

Tests are split with pytest markers so new tests can join CI by marker:

```bash
task test-unit
task test-integration
task test-ui
```

The Selenium UI tests run against a temporary live Flask server. By default they
use headless Chrome. Set `SELENIUM_BROWSER=firefox` for Firefox or
`SELENIUM_HEADLESS=0` to watch the browser.

## CI

GitHub Actions runs separate workflows:

- `Unit Tests` installs dependencies with `task install` and runs `task test-unit`.
- `Integration Tests` installs dependencies with `task install`, runs
  `task test-integration`, then runs Selenium with `task test-ui`.
