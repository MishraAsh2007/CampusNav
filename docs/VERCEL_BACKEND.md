# Deploy the backend project on Vercel

Use a separate Vercel project for the backend, importing the repository's `main`
branch with **Root Directory `./`**. Keep the frontend project's root at `frontend`.

The backend uses three configuration files:

- `vercel.json` selects the FastAPI framework and explicitly sets an empty
  `buildCommand`. This API has no custom compilation step. Dependency installation
  still runs automatically.
- `pyproject.toml` selects `campus_routing.integrated:app`, which serves both
  the routing endpoints and the existing Data API from this one backend project.
- `requirements.txt` supplies the Python runtime dependencies.

These correspond to Vercel's [FastAPI deployment guide](https://vercel.com/docs/frameworks/backend/fastapi)
and [Build Command configuration](https://vercel.com/docs/project-configuration/vercel-json#buildcommand).

## Fix `Command "None" exited with 127`

The shell tried to execute the literal word `None`. This error does not indicate
a Python exception in the application. A dashboard Build Command override is a
likely source; the repository does not define a command with that value.

In the **backend** project's Settings → Build and Deployment:

| Setting | Value |
| --- | --- |
| Framework Preset | FastAPI |
| Root Directory | `./` (repository root) |
| Build Command | Empty; remove any literal `None` and disable the override |
| Install Command | Automatic; leave the override disabled |
| Output Directory | Default; leave the override disabled |

The repository's empty `buildCommand` overrides the dashboard command for new
deployments. Do not enter the words `None`, `null`, or an `uvicorn` command in
the Build Command field. Vercel starts the exported app through its Python runtime.

Deploy the latest `main` commit, rather than redeploying the old failed commit.
If the same error persists, inspect the log immediately before the failed command
to identify whether it came from the Build Command or another project override.

## Database and validation

Configure `MONGODB_URI` and any existing database/admin environment settings in
the Vercel dashboard; do not commit credentials. Consult [the backend guide](../backend/BACKEND.md)
for the supported variables. A working import and local startup do not verify
Atlas connectivity from Vercel.

After a successful deployment, open `/health` and `/docs` on the backend's domain.
If the build succeeds but requests fail, inspect the runtime logs for that request;
that is a separate failure from the shell command described above.

## Connect the map frontend to routing and data

Only **two Vercel projects** are needed with this configuration. The backend
project at root `./` now serves the Data API, `/plan`, `/route`, `/journey`, and
the available indoor navigation endpoints together. The existing Data API stays
mounted at `/api/data`; its original source entrypoint is still available for
standalone development.

1. Deploy the latest `main` in the **backend project**. Keep Framework FastAPI,
   Root Directory `./`, and the Build Command override disabled.
2. Copy the backend's production URL, for example `https://your-backend.vercel.app`.
3. Create the **frontend project** from the same repository: Root Directory
   `frontend`, Framework Vite, Build Command `npm run build`, Output Directory `dist`.
   `frontend/vercel.json` explicitly supplies the frontend build settings; the
   repository-root `vercel.json` supplies the different backend settings.
4. In the **frontend** project's Settings → Environment Variables, add:

   ```text
   VITE_API_BASE_URL=https://your-backend.vercel.app
   VITE_ROUTING_API_URL=https://your-backend.vercel.app
   VITE_INDOOR_API_URL=https://your-backend.vercel.app
   VITE_ROUTING_ENGINE=remote
   ```

   Replace the example URL with the actual backend URL, without `/docs` or a
   trailing slash. Apply it to the Vercel environments you deploy.
5. Remove `VITE_CAMPUSNAV_INTEGRATED` and `VITE_CAMPUSNAV_DEMO` if previously set
   to `1` on the frontend project. They force same-origin requests or demo data.
6. Redeploy the **frontend** so Vite includes the URLs in its build. Its URL is
   the one users open to see the map.

The combined service inherits `CORS_ORIGINS` for requests from the separate map
project, defaulting to the existing Data API policy of `*`. Set it to your actual
frontend origin to restrict access, and redeploy the backend. If you set the
more specific `ROUTING_CORS_ORIGINS`, include the frontend origin there too.

## Check the connection

On the backend domain:

- `/health` should report `status: "ok"`, `synthetic: false`, and graph node/edge counts.
- `/docs` should list `/plan`, `/route`, `/journey`, and `/indoor/route`.
- `/api/data/health` checks the mounted Data API.

The committed residence graph and public indoor maps support the available live
routes. Generated private drawing pilots and authenticated source plans are not
bundled in Git and will not appear just by deploying the repository. Scraper
refresh/publication remains a separate process. See [the integration guide](CURRENT_INTEGRATION.md).

## A page is missing or the frontend is blank

- Check the latest deployment status for **each** project. A failed build does
  not publish a working app at its deployment URL.
- Test the backend's `/health`, `/docs`, and `/api/data/health` URLs. The API's
  root URL is not the user-facing map. A Vercel-branded 404 at `/health` points to
  deployment/project routing; an application JSON error points to the app/runtime.
- The frontend project must use Root Directory `frontend`, and its deployed
  `index.html` must reference JavaScript assets that return 200 from `/assets/`.
  The root FastAPI project settings are not the frontend build settings.
- Verify the frontend uses the **production backend domain**, not a localhost
  URL, a `/docs` URL, or a stale failed-deployment URL. Redeploy the frontend after
  changing environment variables.
- If the HTML and assets load but the app is blank, inspect the first browser
  console error and the failed Network requests. Record the two project URLs
  and deployment statuses before changing unrelated settings.
