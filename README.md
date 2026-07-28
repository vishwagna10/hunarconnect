# HunarConnect

A two-sided marketplace connecting business owners with skilled informal
workers (embroiderers, tailors, carpenters, plumbers, electricians, painters,
catering help) — built for Hyderabad, mobile-friendly, and multilingual by
design.

## Quick start

```bash
pip install flask
python3 app.py
```

Then open **http://localhost:5000** — you'll land on the language picker
first, exactly as the spec requires. Pick a language, and every screen from
that point on (landing, registration, dashboards, matches, ratings) renders
only in that language.

The SQLite database (`hunarconnect.db`) is created automatically on first
run — no setup step needed.

## What's implemented

- **Language selection first.** You cannot reach registration/login without
  picking a language. The choice is stored in the session and reused on
  every later visit.
- **23 languages selectable** (English + all 22 scheduled languages).
  English, Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, Bengali,
  Gujarati, Punjabi, and Urdu are **fully translated**. The remaining 12
  languages (Assamese, Bodo, Dogri, Kashmiri, Konkani, Maithili, Manipuri,
  Nepali, Odia, Sanskrit, Santhali, Sindhi) are wired into the picker and
  switch correctly, but currently show English placeholder text — see
  `translations.py`, search for `TODO-TRANSLATE`. These need a native
  speaker's review before they're ready to ship; I didn't want to guess at
  translations I wasn't confident in.
- **Form persistence.** Every registration/profile field autosaves to the
  browser's local storage as you type (`static/js/persist.js`) and refills
  itself if you close the app mid-form and come back. Passwords are never
  persisted this way.
- **Owner flow:** register → post a job → ranked matches (same area,
  "interested" workers, and reliability all factored in) → connect (work
  agreement) → mark complete → optional 1–5★ rating of the worker.
- **Worker flow:** register with skills/about/rates/languages → dashboard
  of active/completed jobs → cancel (which reopens the job and flags a
  reliability warning) → job feed of open jobs matching their skills, with
  an "apply/interested" flag → optional 1–5★ rating of the owner after a
  job completes.
- **Ratings are mutual and genuinely optional on both sides** — skipping
  doesn't block anything; the job stays marked complete either way.
- **Backup suggestion:** if a worker cancels, the owner's "Find a Backup
  Worker" button reruns the match, automatically excluding whoever just
  cancelled.
- App icon (your handshake image) is wired in as the favicon and header logo.

## Project layout

```
app.py                 Flask routes, SQLite schema, matching/rating logic
translations.py        All UI strings per language
static/css/style.css   Styling (green/orange theme from your icon)
static/js/persist.js   Client-side form autosave
static/icons/          Your icon in several sizes
templates/              All page templates
```

## Known gaps / next steps

- 12 languages need real translations (see above).
- No SMS/OTP verification on phone numbers yet — registration trusts
  whatever's typed.
- No file/photo uploads for worker portfolios yet.
- Ratings currently only support flat comments; no photo evidence for
  disputes.
- This runs on Flask's dev server — for anything beyond local testing/demo,
  put it behind gunicorn + nginx (or similar) and switch the SQLite file to
  a proper Postgres database once you have concurrent users.
