# GitHub Pages prerender refresh integration

The SurePlace frontend at `andywhite97/sureplace` prerenders public property, stay, agent, and agency detail pages during its GitHub Pages build. The backend can ask GitHub to rebuild the static HTML and sitemap after relevant content changes.

## Setup

1. Merge and deploy the frontend pull request that adds the `repository_dispatch` event named `content-published`.
2. Create a fine-grained GitHub personal access token scoped **only** to `andywhite97/sureplace`. Give it repository **Contents: Read and write**, needed by GitHub's repository dispatch endpoint. Do not place it in code or send it to clients.
3. In the Render **backend service** Environment settings, add:
   - `PRERENDER_GITHUB_TOKEN` = the token (secret)
   - `PRERENDER_GITHUB_REPOSITORY=andywhite97/sureplace`
   - `PRERENDER_DISPATCH_COOLDOWN_SECONDS=300` (optional)
   - `PRERENDER_DISPATCH_TIMEOUT_SECONDS=3` (optional)
4. Deploy the Django backend after merging this branch.
5. Publish or update a listing, then check `andywhite97/sureplace` → Actions → **Deploy GitHub Pages** for a `repository_dispatch` run. When the build finishes, inspect the listing HTML and generated `sitemap.xml`.

The token is never exposed to Angular. Without the token, dispatch is disabled and site visitors can still see live API data through browser rendering. **Do not set the token on the frontend deployment.**

## How it works

Django signals are registered by `core.apps.CoreConfig.ready()`. Published listing changes and removal, images, amenities, rooms, plus agency and agent changes schedule a post-commit callback. The callback sends an authenticated `POST https://api.github.com/repos/andywhite97/sureplace/dispatches` with `{"event_type":"content-published"}`. Failed calls are logged without credentials and do not break the user's save action.

A shared cache key prevents repeated dispatch calls within the configured cooldown (five minutes by default), and errors release the key to permit the next update to retry. On GitHub Pages, the workflow also runs every six hours as a safety net, and can be started manually.

### Operational limits

- A dispatch starts a full GitHub Actions build: it does not selectively regenerate a single URL.
- GitHub Actions builds may take some time. Changes to static HTML and link previews become visible only after the next successful deployment. The browser application continues fetching live data from Django.
- Edits during the cooldown period are picked up by a build which fetches the latest backend state, unless they land after its build-time fetch. The six-hour schedule catches later edits. For guaranteed per-change static freshness, implement a persistent outbox + scheduled dispatch worker.
- Cache throttling requires shared Redis for consistency across multiple API workers. The request runs after commit, with a three-second timeout by default, and no dependency on a running Celery worker.
- If the credentials expire or the API is unreachable, the scheduled build continues to provide a fallback.
