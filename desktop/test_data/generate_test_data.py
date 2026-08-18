"""
generate_test_data.py — Generate bundled CSV test data for the Desktop app.
Run once during build or first launch:
    python desktop/test_data/generate_test_data.py
Outputs 4 CSV files used by "Load Bundled Test Data" button.
"""
import sys, random
from pathlib import Path
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).parent
SEED    = 42
N       = 40          # samples
BATCHES = 3

rng = np.random.default_rng(SEED)
idx = [f"S{i:03d}" for i in range(N)]
batch  = np.repeat(np.arange(BATCHES), [14, 13, 13])
cond   = np.array(["Case"]*20 + ["Control"]*20)
rng.shuffle(cond)
rng.shuffle(batch)

# ── Gene symbols ──────────────────────────────────────────────────────────────
GENES = [
    "TP53","EGFR","BRCA1","BRCA2","KRAS","MYC","VEGFA","AKT1","MTOR","PIK3CA",
    "PTEN","CDK2","CDK4","CCND1","RB1","CDKN2A","MDM2","BCL2","BAX","CASP3",
    "CASP9","ATM","CHEK1","CHEK2","RAD51","PALB2","NBN","MRE11","RAD50","H2AFX",
    "IDH1","IDH2","VHL","HIF1A","ERBB2","FGFR1","MET","ALK","BRAF","RAF1",
    "MAP2K1","MAPK1","MAPK3","HRAS","NRAS","JAK1","JAK2","STAT3","IL6","TNF",
    "TGFB1","SMAD2","SMAD3","SMAD4","WNT3A","CTNNB1","APC","NOTCH1","HES1","SHH",
    "GLI1","E2F1","HDAC1","DNMT1","EZH2","SIRT1","AMPK","TSC1","TSC2","CCNB1",
]
PROTEINS = [
    "P04637","P00533","P38398","P51587","P01116","P01106","P15692","P31749",
    "P42345","P42336","P60484","P24941","P11802","P24385","P06400","P42771",
    "Q00987","P10415","Q07812","P42574","P55211","P10606","Q9UKV3","Q13315",
]
CHEBI_IDS = [
    "CHEBI:15422","CHEBI:16761","CHEBI:17634","CHEBI:16015","CHEBI:16947",
    "CHEBI:30031","CHEBI:16810","CHEBI:15361","CHEBI:16908","CHEBI:57692",
    "CHEBI:15846","CHEBI:17627","CHEBI:15351","CHEBI:16240","CHEBI:25703",
    "CHEBI:17855","CHEBI:15843","CHEBI:18012","CHEBI:30616","CHEBI:16675",
]

def _inject(X, batch, shift=1.5):
    X = X.copy().astype(float)
    for b in np.unique(batch):
        m = batch == b
        X[m] += rng.normal(0, shift, X.shape[1])
        X[m] *= rng.lognormal(0, 0.3, X.shape[1])
    return X

cm = cond == "Case"

# ── Transcriptomics ───────────────────────────────────────────────────────────
mu  = np.abs(rng.normal(5, 3, (N, len(GENES))))
tx  = rng.negative_binomial(5, np.clip(5/(5+mu), 0.01, 0.99)).astype(float)
tx[cm, :15] *= 3.0
tx  = np.maximum(_inject(tx, batch, 1.5), 0)
tx_df = pd.DataFrame(tx.round(3), index=idx, columns=GENES)
tx_df.index.name = "sample_id"
tx_df.to_csv(OUT_DIR / "transcriptomics_test.csv")
print(f"  transcriptomics_test.csv  {tx_df.shape}")

# ── Proteomics ────────────────────────────────────────────────────────────────
pr  = rng.lognormal(10, 2, (N, len(PROTEINS))).astype(float)
pr[cm, :6] *= 2.5
pr  = np.maximum(_inject(pr, batch, 2.0), 0)
pr_df = pd.DataFrame(pr.round(4), index=idx, columns=PROTEINS)
pr_df.index.name = "sample_id"
pr_df.to_csv(OUT_DIR / "proteomics_test.csv")
print(f"  proteomics_test.csv       {pr_df.shape}")

# ── Metabolomics ──────────────────────────────────────────────────────────────
me  = rng.lognormal(8, 1.5, (N, len(CHEBI_IDS))).astype(float)
me[cm, :5] *= 2.0
me  = np.maximum(_inject(me, batch, 2.5), 0)
me_df = pd.DataFrame(me.round(4), index=idx, columns=CHEBI_IDS)
me_df.index.name = "sample_id"
me_df.to_csv(OUT_DIR / "metabolomics_test.csv")
print(f"  metabolomics_test.csv     {me_df.shape}")

# ── Metadata ──────────────────────────────────────────────────────────────────
ages   = rng.integers(22, 78, N)
sexes  = rng.choice(["M", "F"], N)
bmis   = rng.normal(26, 4, N).clip(16, 45).round(1)
stages = rng.choice(["Stage I", "Stage II", "Stage III", "Stage IV"], N,
                    p=[0.2, 0.3, 0.3, 0.2])
treats = rng.choice(["Chemo", "Immunotherapy", "None"], N, p=[0.4, 0.3, 0.3])
rins   = rng.normal(8.2, 0.8, N).clip(5.0, 10.0).round(1)

meta_df = pd.DataFrame({
    "condition":     cond,
    "batch":         batch,
    "age":           ages,
    "sex":           sexes,
    "bmi":           bmis,
    "tissue_type":   "Primary tumour",
    "disease_stage": stages,
    "treatment":     treats,
    "platform":      rng.choice(["Illumina NovaSeq 6000", "Illumina HiSeq 4000"], N),
    "library_prep":  "polyA",
    "rin_score":     rins,
    "quality_passed": True,
    "reference_genome": "GRCh38.p14",
    "data_repository":  "local",
}, index=idx)
meta_df.index.name = "sample_id"
meta_df.to_csv(OUT_DIR / "metadata_test.csv")
print(f"  metadata_test.csv         {meta_df.shape}")
print("Done — test data generated.")
