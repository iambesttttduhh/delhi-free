# Switches

Two ways to take this site down. Both are fired from the **Actions** tab in the
GitHub repository — no terminal, no local setup.

## Pause — reversible

Actions → **Site switch (pause / resume)** → Run workflow → choose:

- `pause` — unpublishes Pages. The address returns 404 within a minute.
- `resume` — publishes it again from `main`. Live within a minute or two.
- `status` — prints the current state.

Nothing is deleted. The repo, the events, the images and the fonts stay exactly
as they are. Pause and resume as often as you like.

## Close for good — irreversible

Actions → **Close the site for good** → Run workflow → type `DELETE` in the box.

That will:

1. unpublish Pages, so the address stops serving
2. delete every file in the repository and replace them with a one-line
   "This site has been closed" page
3. commit that removal

The confirmation box is checked inside the workflow: type anything other than
`DELETE` and the job refuses to run.

**To remove the repository itself** — the last trace — go to Settings → scroll
to the bottom → Delete this repository. A workflow cannot do that with its own
token; it needs your account.

## What "gone" really means

Deleting removes *your* copies. It does not reach Google's cache, the Wayback
Machine, or anything anyone has saved. GitHub also keeps deleted repositories
recoverable for 90 days.

## Before you pause

Search engines keep showing a URL for a while after it 404s. Pausing stops
visitors reaching the site; it does not instantly remove it from results.
