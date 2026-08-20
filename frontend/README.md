# MultiOmics-Reactome Web Frontend

React 18 single-page application. Upload data, launch pipeline runs, watch
progress, explore results, download the MIMODH XML record.

---

## Local development

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Requires a backend. Either start the local stack from the repository root:

```bash
docker compose up --build      # API on http://localhost:8000
```

or point at a deployed API (see environment variables below).

---

## Environment variables

Vite exposes only variables prefixed `VITE_`. Create `frontend/.env.local`:

```env
VITE_API_URL=http://localhost:8000
VITE_AWS_REGION=eu-west-2
VITE_COGNITO_POOL_ID=eu-west-2_XXXXXXXXX
VITE_COGNITO_CLIENT_ID=your_app_client_id
VITE_S3_DATA_BUCKET=multiomics-prod-data-123456789012
```

All five values are printed in the deployment summary produced by
`scripts/deploy_aws.sh`. `.env.local` is git-ignored.

For production builds the deployment script injects them automatically:

```bash
VITE_API_URL=https://api.example.org npm run build
```

---

## Build and deploy

```bash
npm run build        # -> frontend/dist/
npm run preview      # serve dist/ locally to check the production build
```

Deployment is handled by `scripts/deploy_aws.sh`, which:

1. builds with the correct `VITE_*` values for your stage
2. syncs `dist/` to the web S3 bucket with immutable cache headers
3. uploads `index.html` separately with `no-cache` so releases take effect immediately
4. invalidates the CloudFront cache

Manual deploy:

```bash
aws s3 sync dist/ s3://<web-bucket>/ --delete \
  --cache-control "public,max-age=31536000,immutable" --exclude index.html
aws s3 cp dist/index.html s3://<web-bucket>/index.html \
  --cache-control "no-cache,must-revalidate"
aws cloudfront create-invalidation --distribution-id <ID> --paths "/*"
```

---

## Features

| | |
|---|---|
| **Auth** | Cognito sign-in; JWT attached to every API call |
| **Upload** | Drag-and-drop for all 7 modalities; presigned S3 PUT URLs |
| **Configure** | MIMODH tier selector, study metadata, synthetic parameters |
| **Run** | Submits a job, polls `/jobs/{id}`, shows stage progress |
| **Results** | Plotly interactive network, DE volcano, pathway heatmap |
| **Download** | Every artifact, including `mimodh_record.xml` |

### Integration method

Query the deployment for what it supports, then offer only those:

```js
const { available, methods, default: dflt } =
  await fetch(`${API}/integration-methods`).then(r => r.json());
// available -> ["nmf","mofa","snf","mcia"]
```

Submit it with the job:

```js
await fetch(`${API}/jobs`, {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${jwt}` },
  body: JSON.stringify({ mode: "real", integration_method: "mcia", n_perm: 200 }),
});
```

`integration_method` is validated server-side against
`nmf | mofa | snf | mcia | diablo`; anything else returns 422.

---

## Project structure

```
frontend/
├── index.html            Vite entry point
├── package.json
├── src/
│   ├── main.jsx          React root
│   └── App.jsx           Application shell and all views
└── dist/                 Build output (git-ignored)
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `react`, `react-dom` 18 | UI framework |
| `plotly.js`, `react-plotly.js` | Interactive network and charts |
| `vite` 5 | Dev server and bundler |
| `@vitejs/plugin-react` | JSX transform, HMR |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Failed to fetch` in console | Backend not running, or `VITE_API_URL` wrong |
| CORS error on upload | Data bucket CORS must list your exact origin — re-run `deploy_aws.sh` |
| Blank page after deploy | Check the CloudFront origin path and that `index.html` uploaded |
| 403 on page refresh | Add a CloudFront custom error response: 403 → `/index.html` (200) |
| Auth loop / immediate sign-out | `VITE_COGNITO_CLIENT_ID` mismatch, or app client has a secret (it must not) |
| Stale build after deploy | CloudFront cache — the deploy script invalidates it; wait ~1 min |
| `npm ci` fails | Delete `package-lock.json` and `node_modules`, then `npm install` |

Debug the API directly:

```bash
curl https://api.example.org/health          # {"status":"ok","version":"3.0.0"}
curl https://api.example.org/docs            # Swagger UI
```
