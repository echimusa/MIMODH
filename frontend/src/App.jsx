/**
 * Multi-Omics Pipeline  —  React 18 Frontend
 * ============================================
 * Pages:
 *   /login    Amplify + Cognito sign-in
 *   /upload   File upload per modality → S3 presigned PUT
 *   /run      Configure and submit a pipeline job
 *   /jobs     Job list with live status polling
 *   /results  Interactive Plotly plots + file downloads
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  BrowserRouter as Router, Routes, Route,
  Navigate, Link, useNavigate, useParams,
} from "react-router-dom";
import { Amplify } from "aws-amplify";
import {
  withAuthenticator, useAuthenticator,
} from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";
import Plot from "react-plotly.js";
import awsconfig from "./aws-exports";

Amplify.configure(awsconfig);

const API = import.meta.env.VITE_API_URL;   // https://api.yourdomain.com

// ── API helper ────────────────────────────────────────────────────────────────
async function apiFetch(path, opts = {}, token = "") {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API error");
  }
  return res.json();
}

// ── hooks ─────────────────────────────────────────────────────────────────────
function useToken() {
  const { user } = useAuthenticator(c => [c.user]);
  return user?.signInUserSession?.idToken?.jwtToken || "";
}

function useJobPoller(jobId, token, onDone) {
  useEffect(() => {
    if (!jobId) return;
    const id = setInterval(async () => {
      try {
        const j = await apiFetch(`/jobs/${jobId}`, {}, token);
        if (j.status === "COMPLETED" || j.status === "FAILED") {
          clearInterval(id);
          onDone(j);
        }
      } catch {/* ignore */}
    }, 3000);
    return () => clearInterval(id);
  }, [jobId, token, onDone]);
}

// ══════════════════════════════════════════════════════════════════════════════
// LAYOUT
// ══════════════════════════════════════════════════════════════════════════════

function Nav() {
  const { signOut, user } = useAuthenticator(c => [c.user, c.signOut]);
  return (
    <nav style={styles.nav}>
      <span style={styles.brand}>🧬 MultiOmics</span>
      <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
        {[["Upload", "/upload"], ["Run", "/run"],
          ["Jobs", "/jobs"], ["Results", "/results"]].map(([l, p]) => (
          <Link key={p} to={p} style={styles.navLink}>{l}</Link>
        ))}
        <span style={{ color: "#94a3b8", fontSize: 12 }}>
          {user?.attributes?.email}
        </span>
        <button onClick={signOut} style={styles.btnSm}>Sign out</button>
      </div>
    </nav>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE: UPLOAD
// ══════════════════════════════════════════════════════════════════════════════

const MODALITIES = [
  { key: "transcriptomics", label: "Transcriptomics",  ext: ".csv,.tsv" },
  { key: "proteomics",      label: "Proteomics",       ext: ".csv,.tsv" },
  { key: "metabolomics",    label: "Metabolomics",     ext: ".csv,.tsv" },
  { key: "genomics",        label: "Genomics / SNP",   ext: ".csv,.tsv" },
  { key: "sc_rna",          label: "scRNA-seq",        ext: ".h5ad,.csv" },
  { key: "sc_atac",         label: "scATAC-seq",       ext: ".h5ad,.csv" },
  { key: "spatial",         label: "Spatial omics",    ext: ".h5ad" },
  { key: "metadata",        label: "Metadata / Clinical", ext: ".csv,.tsv,.xlsx" },
];

function UploadPage() {
  const token = useToken();
  const { user } = useAuthenticator(c => [c.user]);
  const uid = user?.username || "anon";
  const [uploads, setUploads] = useState({});   // modality → { key, name, status }
  const [msg, setMsg] = useState("");

  const handleFile = async (modality, file) => {
    setMsg(""); 
    setUploads(u => ({ ...u, [modality]: { name: file.name, status: "requesting" } }));
    try {
      const { upload_url, s3_key } = await apiFetch("/upload", {
        method: "POST",
        body: JSON.stringify({ user_id: uid, modality, filename: file.name,
                               content_type: file.type || "text/csv" }),
      }, token);
      setUploads(u => ({ ...u, [modality]: { name: file.name, status: "uploading", s3_key } }));
      await fetch(upload_url, { method: "PUT", body: file,
                                headers: { "Content-Type": file.type || "text/csv" } });
      setUploads(u => ({ ...u, [modality]: { name: file.name, status: "done", s3_key } }));
      // Persist to localStorage for /run page
      const saved = JSON.parse(localStorage.getItem("s3_keys") || "{}");
      saved[modality] = s3_key;
      localStorage.setItem("s3_keys", JSON.stringify(saved));
    } catch (e) {
      setUploads(u => ({ ...u, [modality]: { name: file.name, status: "error" } }));
      setMsg(e.message);
    }
  };

  return (
    <Page title="Upload Omics Data">
      <p style={styles.sub}>
        Upload files for each modality. Uploaded files are stored securely in S3
        and linked to your profile. You can skip any modality — synthetic data
        will be used for those.
      </p>
      {msg && <div style={styles.error}>{msg}</div>}
      <div style={styles.grid}>
        {MODALITIES.map(({ key, label, ext }) => {
          const u = uploads[key];
          return (
            <div key={key} style={styles.card}>
              <div style={styles.cardTitle}>{label}</div>
              <div style={{ color: "#64748b", fontSize: 11, marginBottom: 8 }}>
                {ext}
              </div>
              {u ? (
                <div style={{ fontSize: 12, color: STATUS_COLOR[u.status] }}>
                  {STATUS_ICON[u.status]} {u.name}
                </div>
              ) : (
                <label style={styles.uploadBtn}>
                  Choose file
                  <input type="file" accept={ext} style={{ display: "none" }}
                    onChange={e => e.target.files[0] &&
                      handleFile(key, e.target.files[0])} />
                </label>
              )}
            </div>
          );
        })}
      </div>
    </Page>
  );
}

const STATUS_COLOR = { requesting: "#94a3b8", uploading: "#fbbf24",
                        done: "#34d399", error: "#f87171" };
const STATUS_ICON  = { requesting: "⏳", uploading: "⬆", done: "✓", error: "✗" };

// ══════════════════════════════════════════════════════════════════════════════
// PAGE: RUN
// ══════════════════════════════════════════════════════════════════════════════

function RunPage() {
  const token = useToken();
  const nav   = useNavigate();
  const [cfg, setCfg] = useState({
    mode: "mixed", n_samples: 120, n_cells: 400,
    n_batches: 3, n_perm: 200, use_sagemaker: false,
  });
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async () => {
    setLoading(true); setMsg("");
    try {
      const s3_keys = JSON.parse(localStorage.getItem("s3_keys") || "{}");
      const { job_id } = await apiFetch("/jobs", {
        method: "POST",
        body: JSON.stringify({ ...cfg, s3_keys }),
      }, token);
      nav(`/jobs/${job_id}`);
    } catch (e) {
      setMsg(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Page title="Configure Pipeline Run">
      {msg && <div style={styles.error}>{msg}</div>}
      <div style={styles.form}>
        <Field label="Data mode">
          <select value={cfg.mode} onChange={e => setCfg({...cfg, mode: e.target.value})}
                  style={styles.input}>
            <option value="synthetic">Synthetic (demo)</option>
            <option value="mixed">Mixed (uploaded + synthetic)</option>
            <option value="real">Real (uploaded files only)</option>
          </select>
        </Field>
        {cfg.mode !== "real" && <>
          <Field label={`Samples (${cfg.n_samples})`}>
            <input type="range" min={10} max={2000} value={cfg.n_samples}
              onChange={e => setCfg({...cfg, n_samples: +e.target.value})}
              style={{ width: "100%" }} />
          </Field>
          <Field label={`Cells (${cfg.n_cells})`}>
            <input type="range" min={50} max={10000} value={cfg.n_cells}
              onChange={e => setCfg({...cfg, n_cells: +e.target.value})}
              style={{ width: "100%" }} />
          </Field>
        </>}
        <Field label={`GSEA permutations (${cfg.n_perm})`}>
          <input type="range" min={50} max={1000} value={cfg.n_perm}
            onChange={e => setCfg({...cfg, n_perm: +e.target.value})}
            style={{ width: "100%" }} />
        </Field>
        <Field label="Compute backend">
          <label style={{ color: "#cbd5e1", fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={cfg.use_sagemaker}
              onChange={e => setCfg({...cfg, use_sagemaker: e.target.checked})}
              style={{ marginRight: 8 }} />
            Use SageMaker AI (large jobs &gt; 500 samples)
          </label>
        </Field>
        <button onClick={submit} disabled={loading} style={styles.btnPrimary}>
          {loading ? "Submitting…" : "🚀 Run Pipeline"}
        </button>
      </div>
    </Page>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE: JOB LIST + JOB DETAIL
// ══════════════════════════════════════════════════════════════════════════════

function JobsPage() {
  const token = useToken();
  const [jobs, setJobs] = useState([]);

  useEffect(() => {
    // In production you'd have a GET /jobs?user_id=... endpoint
    const saved = JSON.parse(localStorage.getItem("job_history") || "[]");
    const poll  = async () => {
      const updated = await Promise.all(saved.map(async j => {
        try { return await apiFetch(`/jobs/${j.job_id}`, {}, token); }
        catch { return j; }
      }));
      setJobs(updated);
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [token]);

  return (
    <Page title="My Jobs">
      {jobs.length === 0
        ? <p style={styles.sub}>No jobs yet. Go to Run to submit one.</p>
        : jobs.map(j => (
          <Link key={j.job_id} to={`/results/${j.job_id}`}
                style={{ textDecoration: "none" }}>
            <div style={styles.jobRow}>
              <span style={styles.jobId}>{j.job_id.slice(0, 8)}…</span>
              <StatusBadge status={j.status} />
              <span style={{ color: "#64748b", fontSize: 11 }}>
                {j.submitted_at?.slice(0, 16).replace("T", " ")}
              </span>
              <span style={{ color: "#475569", fontSize: 11 }}>
                {j.progress || 0}%
              </span>
            </div>
          </Link>
        ))
      }
    </Page>
  );
}

function StatusBadge({ status }) {
  const MAP = {
    QUEUED: ["#fbbf24", "⏳"], RUNNING: ["#38bdf8", "⚙"],
    COMPLETED: ["#34d399", "✓"], FAILED: ["#f87171", "✗"],
    CANCELLED: ["#94a3b8", "⊘"],
  };
  const [color, icon] = MAP[status] || ["#64748b", "?"];
  return (
    <span style={{ ...styles.badge, background: color + "22", color }}>
      {icon} {status}
    </span>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE: RESULTS — interactive plots + downloads
// ══════════════════════════════════════════════════════════════════════════════

function ResultsPage() {
  const { jobId } = useParams();
  const token     = useToken();
  const [files, setFiles]   = useState({});
  const [jobStatus, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [imgSrc, setImgSrc]   = useState(null);
  const [activeFile, setActive] = useState(null);

  const load = useCallback(async (jid) => {
    try {
      const j = await apiFetch(`/jobs/${jid}`, {}, token);
      setJob(j);
      if (j.status === "COMPLETED") {
        const { files: f } = await apiFetch(`/results/${jid}`, {}, token);
        setFiles(f);
      }
    } catch (e) { /* keep polling */ }
    setLoading(false);
  }, [token]);

  useEffect(() => { if (jobId) load(jobId); }, [jobId, load]);
  useJobPoller(jobId, token, j => { setJob(j); if (j.status==="COMPLETED") load(jobId); });

  const viewFile = async (name, url) => {
    setActive(name);
    if (name.endsWith(".png") || name.endsWith(".html")) {
      setImgSrc({ url, name });
    }
  };

  if (loading) return <Page title="Results"><Spinner /></Page>;
  if (!jobStatus) return <Page title="Results"><p style={styles.sub}>Job not found.</p></Page>;
  if (jobStatus.status !== "COMPLETED") return (
    <Page title={`Job ${jobId?.slice(0,8)}…`}>
      <StatusBadge status={jobStatus.status} />
      {jobStatus.status === "FAILED" &&
        <div style={{ ...styles.error, marginTop: 16 }}>{jobStatus.error}</div>}
      <div style={{ color: "#64748b", marginTop: 16, fontSize: 13 }}>
        {jobStatus.status === "RUNNING"
          ? "Pipeline is running… this page auto-refreshes."
          : "Waiting in queue…"}
      </div>
      <ProgressBar pct={jobStatus.progress || 0} />
    </Page>
  );

  const plots  = Object.keys(files).filter(f => f.endsWith(".png"));
  const csvs   = Object.keys(files).filter(f => f.endsWith(".csv"));
  const htmls  = Object.keys(files).filter(f => f.endsWith(".html"));

  return (
    <Page title="Pipeline Results">
      {/* ── interactive network HTML ────────────────────────────────────── */}
      {htmls.length > 0 && (
        <Section title="Interactive Network">
          {htmls.map(h => (
            <a key={h} href={files[h]} target="_blank" rel="noopener noreferrer"
               style={styles.btnPrimary}>
              🌐 Open {h}
            </a>
          ))}
        </Section>
      )}

      {/* ── plots gallery ───────────────────────────────────────────────── */}
      {plots.length > 0 && (
        <Section title="Analysis Plots">
          <div style={styles.plotGrid}>
            {plots.map(p => (
              <div key={p} style={styles.plotCard}
                   onClick={() => viewFile(p, files[p])}>
                <img src={files[p]} alt={p}
                     style={{ width: "100%", borderRadius: 6 }}
                     onError={e => { e.target.style.display="none"; }} />
                <div style={{ color: "#94a3b8", fontSize: 10, marginTop: 4 }}>{p}</div>
                <a href={files[p]} download={p}
                   onClick={e => e.stopPropagation()}
                   style={styles.dlBtn}>⬇ Download</a>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── CSV previews ────────────────────────────────────────────────── */}
      {csvs.length > 0 && (
        <Section title="Data Downloads">
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {csvs.map(c => (
              <a key={c} href={files[c]} download={c} style={styles.btnSm}>
                📄 {c}
              </a>
            ))}
          </div>
        </Section>
      )}

      {/* ── enlarged plot modal ─────────────────────────────────────────── */}
      {imgSrc && (
        <div style={styles.modal} onClick={() => setImgSrc(null)}>
          <div style={styles.modalInner} onClick={e => e.stopPropagation()}>
            <button style={styles.modalClose} onClick={() => setImgSrc(null)}>✕</button>
            {imgSrc.name.endsWith(".png")
              ? <img src={imgSrc.url} alt={imgSrc.name}
                     style={{ maxWidth: "90vw", maxHeight: "85vh", borderRadius: 8 }} />
              : <iframe src={imgSrc.url} title={imgSrc.name}
                        style={{ width: "88vw", height: "80vh", border: "none" }} />
            }
            <a href={imgSrc.url} download={imgSrc.name} style={{ ...styles.btnPrimary, marginTop: 12 }}>
              ⬇ Download
            </a>
          </div>
        </div>
      )}
    </Page>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// SHARED UI COMPONENTS
// ══════════════════════════════════════════════════════════════════════════════

function Page({ title, children }) {
  return (
    <div style={styles.page}>
      <h2 style={styles.pageTitle}>{title}</h2>
      {children}
    </div>
  );
}
function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <h3 style={styles.sectionTitle}>{title}</h3>
      {children}
    </div>
  );
}
function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ color: "#94a3b8", fontSize: 12, display: "block", marginBottom: 6 }}>
        {label}
      </label>
      {children}
    </div>
  );
}
function Spinner() {
  return <div style={{ color: "#60a5fa", fontSize: 24, textAlign: "center" }}>⏳ Loading…</div>;
}
function ProgressBar({ pct }) {
  return (
    <div style={{ background: "#1e293b", borderRadius: 8, height: 8, margin: "16px 0" }}>
      <div style={{ background: "#60a5fa", width: `${pct}%`, height: "100%",
                    borderRadius: 8, transition: "width 0.5s" }} />
    </div>
  );
}

// ── styles ────────────────────────────────────────────────────────────────────
const styles = {
  nav:         { background: "#0f172a", borderBottom: "1px solid #1e293b",
                 padding: "12px 24px", display: "flex", alignItems: "center",
                 justifyContent: "space-between" },
  brand:       { color: "#60a5fa", fontWeight: 700, fontSize: 16 },
  navLink:     { color: "#94a3b8", textDecoration: "none", fontSize: 13,
                 ":hover": { color: "#fff" } },
  page:        { maxWidth: 960, margin: "32px auto", padding: "0 20px" },
  pageTitle:   { color: "#f1f5f9", fontWeight: 700, fontSize: 20, marginBottom: 8 },
  sectionTitle:{ color: "#60a5fa", fontWeight: 600, fontSize: 14,
                 borderBottom: "1px solid #1e293b", paddingBottom: 6, marginBottom: 14 },
  sub:         { color: "#64748b", fontSize: 13, marginBottom: 20 },
  error:       { background: "#7f1d1d22", border: "1px solid #f87171",
                 color: "#fca5a5", padding: 12, borderRadius: 8, fontSize: 13 },
  grid:        { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px,1fr))",
                 gap: 12 },
  card:        { background: "#0f172a", border: "1px solid #1e293b",
                 borderRadius: 10, padding: 14 },
  cardTitle:   { color: "#e2e8f0", fontWeight: 600, fontSize: 13, marginBottom: 4 },
  uploadBtn:   { display: "inline-block", background: "#1e3a5f", color: "#60a5fa",
                 padding: "6px 14px", borderRadius: 6, cursor: "pointer", fontSize: 12 },
  form:        { background: "#0f172a", border: "1px solid #1e293b",
                 borderRadius: 12, padding: 24, maxWidth: 500 },
  input:       { background: "#1e293b", color: "#f1f5f9", border: "1px solid #334155",
                 borderRadius: 6, padding: "6px 10px", width: "100%", fontSize: 13 },
  btnPrimary:  { background: "#1d4ed8", color: "#fff", border: "none",
                 padding: "10px 22px", borderRadius: 8, cursor: "pointer",
                 fontSize: 13, fontWeight: 600, display: "inline-block",
                 textDecoration: "none" },
  btnSm:       { background: "#1e293b", color: "#94a3b8", border: "1px solid #334155",
                 padding: "6px 14px", borderRadius: 6, cursor: "pointer",
                 fontSize: 12, textDecoration: "none", display: "inline-block" },
  badge:       { padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600 },
  jobRow:      { background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8,
                 padding: "12px 16px", marginBottom: 8, display: "flex",
                 gap: 20, alignItems: "center" },
  jobId:       { color: "#60a5fa", fontFamily: "monospace", fontSize: 12 },
  plotGrid:    { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px,1fr))",
                 gap: 14 },
  plotCard:    { background: "#0f172a", border: "1px solid #1e293b", borderRadius: 10,
                 padding: 10, cursor: "pointer" },
  dlBtn:       { display: "inline-block", marginTop: 6, fontSize: 11, color: "#60a5fa",
                 textDecoration: "none" },
  modal:       { position: "fixed", inset: 0, background: "#00000088",
                 display: "flex", alignItems: "center", justifyContent: "center", zIndex: 999 },
  modalInner:  { background: "#0f172a", borderRadius: 12, padding: 20, position: "relative",
                 display: "flex", flexDirection: "column", alignItems: "center" },
  modalClose:  { position: "absolute", top: 10, right: 14, background: "none",
                 border: "none", color: "#94a3b8", fontSize: 20, cursor: "pointer" },
};

// ══════════════════════════════════════════════════════════════════════════════
// ROOT
// ══════════════════════════════════════════════════════════════════════════════

function AppInner() {
  return (
    <div style={{ background: "#050d1a", minHeight: "100vh", fontFamily: "system-ui, sans-serif" }}>
      <Nav />
      <Routes>
        <Route path="/" element={<Navigate to="/upload" />} />
        <Route path="/upload"       element={<UploadPage />} />
        <Route path="/run"          element={<RunPage />} />
        <Route path="/jobs"         element={<JobsPage />} />
        <Route path="/jobs/:jobId"  element={<ResultsPage />} />
        <Route path="/results"      element={<ResultsPage />} />
        <Route path="/results/:jobId" element={<ResultsPage />} />
      </Routes>
    </div>
  );
}

export default withAuthenticator(function App() {
  return (
    <Router>
      <AppInner />
    </Router>
  );
});
