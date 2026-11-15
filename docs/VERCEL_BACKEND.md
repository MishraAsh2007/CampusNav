# Deploy the backend project on Vercel

Use a separate Vercel project for the backend, importing the repository's `main`
branch with **Root Directory `./`**. Keep the frontend project's root at `frontend`.

The backend uses three configuration files:

- `vercel.json` selects the FastAPI framework and explicitly sets an empty
  `buildCommand`. This API has no custom compilation step. Dependency installation
  still runs automatically.
- `pyproject.toml` selects `backend.main:app` as the application entrypoint.
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

This entrypoint deploys the Data API. See [the integrated application guide](CURRENT_INTEGRATION.md#vercel-deployment-configuration)
for the routing deployment and frontend API URL settings needed for Python
outdoor/indoor routing.
