#!/usr/bin/env bash
# =============================================================================
#  setup.sh  —  Multi-Omics Reactome Pipeline  v3
#  NumPy 2.x compatible  |  Ubuntu 22.04 / macOS 14 / Python 3.10-3.12
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
step()  { echo -e "\n${CYAN}── $* ${NC}"; }

VENV_DIR=".venv_multiomics"
OS="$(uname -s)"; ARCH="$(uname -m)"
info "OS=${OS}  ARCH=${ARCH}"

# ── find Python ───────────────────────────────────────────────────────────────
step "Checking Python"
find_python() {
    for cmd in python3.12 python3.11 python3.10 python3 python; do
        command -v "$cmd" &>/dev/null || continue
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        maj="${ver%%.*}"; min="${ver##*.}"
        [ "$maj" -ge 3 ] && [ "$min" -ge 10 ] && { echo "$cmd"; return 0; }
    done
    return 1
}
PYTHON=$(find_python) || error "Python >= 3.10 not found."
info "Using: $PYTHON  ($(${PYTHON} --version))"

# ── virtual environment ───────────────────────────────────────────────────────
step "Virtual environment"
[ -d "${VENV_DIR}" ] && warn "Existing venv found — reusing." \
                      || "$PYTHON" -m venv "${VENV_DIR}"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
info "Activated: $VIRTUAL_ENV"

# ── bootstrap pip ─────────────────────────────────────────────────────────────
step "Upgrading pip / setuptools / wheel"
pip install --quiet --upgrade "pip>=24.0" "setuptools>=70.0" "wheel>=0.43"

# =============================================================================
# PACKAGES  (all pins verified against NumPy 2 ABI)
# =============================================================================

step "NumPy 2 + SciPy"
pip install --quiet \
    "numpy>=2.0,<3.0" \
    "scipy>=1.13.0"

step "Data wrangling"
pip install --quiet \
    "pandas>=2.2.0" \
    "pyarrow>=15.0" \
    "openpyxl>=3.1.0"          # Excel read/write support

step "Machine learning"
pip install --quiet \
    "scikit-learn>=1.5.0" \
    "joblib>=1.4.0" \
    "statsmodels>=0.14.2"

step "Bioinformatics / single-cell"
# anndata 0.10.7+ and scanpy 1.10.1+ ship wheels built against NumPy 2
pip install --quiet \
    "anndata>=0.10.7" \
    "scanpy>=1.10.1" \
    "harmonypy>=0.0.10" \
    "leidenalg>=0.10.2" \
    "python-igraph>=0.11.4"

step "pycombat (inmoose)"
pip install --quiet "inmoose>=0.4.0" \
    || warn "inmoose install failed — built-in ComBat fallback will be used."

step "Network analysis"
pip install --quiet \
    "networkx>=3.3" \
    "pyvis>=0.3.2"

step "Visualisation"
pip install --quiet \
    "matplotlib>=3.9.0" \
    "seaborn>=0.13.2"

step "HTTP + utilities"
pip install --quiet \
    "requests>=2.32.0" \
    "tqdm>=4.66.0"

# =============================================================================
# PyTorch — optional, GPU NMF
# =============================================================================
step "PyTorch (optional)"

install_torch_cpu()  { pip install --quiet "torch>=2.3.0" \
    --index-url https://download.pytorch.org/whl/cpu; }
install_torch_cuda() { pip install --quiet "torch>=2.3.0" \
    --index-url https://download.pytorch.org/whl/cu121; }

if [ "${OS}" = "Linux" ] && command -v nvidia-smi &>/dev/null; then
    info "NVIDIA GPU detected — CUDA wheels"
    install_torch_cuda || { warn "CUDA torch failed; trying CPU."; install_torch_cpu; }
elif [ "${OS}" = "Darwin" ] && [ "${ARCH}" = "arm64" ]; then
    info "Apple Silicon — MPS-enabled torch"
    pip install --quiet "torch>=2.3.0" || warn "PyTorch optional — skipped."
else
    info "CPU-only torch"
    install_torch_cpu || warn "PyTorch optional — skipped."
fi

# =============================================================================
# VERIFY
# =============================================================================
step "Verification"
python - <<'PYCHECK'
import importlib, sys

GREEN="\033[92m"; YELLOW="\033[93m"; RED="\033[91m"; NC="\033[0m"

REQUIRED = [
    ("numpy",       "2.0"),  ("scipy",      "1.13"),
    ("pandas",      "2.2"),  ("sklearn",    "1.5"),
    ("anndata",     "0.10"), ("scanpy",     "1.10"),
    ("harmonypy",   None),   ("statsmodels","0.14"),
    ("networkx",    "3.3"),  ("matplotlib", "3.9"),
    ("seaborn",     "0.13"), ("tqdm",       None),
    ("requests",    None),   ("openpyxl",   None),
]
OPTIONAL = [
    ("inmoose", None, "pycombat batch correction"),
    ("torch",   None, "GPU-accelerated NMF"),
    ("pyvis",   None, "interactive HTML network"),
    ("igraph",  None, "Leiden clustering backend"),
]

ok = True
for pkg, min_ver in REQUIRED:
    try:
        mod = importlib.import_module(pkg)
        ver = getattr(mod, "__version__", "?")
        ok_ver = True
        if min_ver:
            parts_have = [int(x) for x in ver.split(".")[:2] if x.isdigit()]
            parts_need = [int(x) for x in min_ver.split(".")[:2]]
            ok_ver = parts_have >= parts_need
        sym = f"{GREEN}✓{NC}" if ok_ver else f"{YELLOW}⚠{NC}"
        print(f"  {sym} {pkg:<20} {ver}")
        if not ok_ver:
            print(f"       ^ needs >= {min_ver}")
            ok = False
    except ImportError:
        print(f"  {RED}✗{NC} {pkg:<20} MISSING")
        ok = False

print()
for pkg, _, desc in OPTIONAL:
    try:
        mod = importlib.import_module(pkg)
        ver = getattr(mod, "__version__", "?")
        print(f"  {GREEN}✓{NC} {pkg:<20} {ver}  [{desc}]")
    except ImportError:
        print(f"  {YELLOW}○{NC} {pkg:<20} not installed  [{desc}]")

# NumPy 2 ABI check
import numpy as np
if int(np.__version__.split(".")[0]) < 2:
    print(f"\n  {RED}NumPy < 2 — upgrade: pip install 'numpy>=2.0'{NC}")
    ok = False
else:
    print(f"\n  {GREEN}NumPy {np.__version__} ABI ✓{NC}")

sys.exit(0 if ok else 1)
PYCHECK

# =============================================================================
# FREEZE + ACTIVATION HELPER
# =============================================================================
step "Saving requirements.txt"
pip freeze > requirements.txt
info "Saved requirements.txt"

cat > activate_env.sh <<ACTIVATE
#!/usr/bin/env bash
source "$(pwd)/${VENV_DIR}/bin/activate"
echo "Multi-omics env active: \$VIRTUAL_ENV"
ACTIVATE
chmod +x activate_env.sh

# =============================================================================
# USAGE CHEATSHEET
# =============================================================================
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Activate:         source activate_env.sh"
echo ""
echo "  ── Run modes ──────────────────────────────────────────────"
echo "  Synthetic test:   python multiomics_reactome.py --mode synthetic"
echo ""
echo "  Validate only:    python multiomics_reactome.py --mode real \\"
echo "                      --transcriptomics data/rna.csv \\"
echo "                      --metadata data/meta.csv \\"
echo "                      --validate-only"
echo ""
echo "  Mixed (real tx + synthetic rest):"
echo "                    python multiomics_reactome.py --mode mixed \\"
echo "                      --transcriptomics data/rna.csv \\"
echo "                      --proteomics data/prot.tsv \\"
echo "                      --metadata data/meta.csv"
echo ""
echo "  All real inputs:  python multiomics_reactome.py --mode real \\"
echo "                      --transcriptomics data/rna.csv \\"
echo "                      --proteomics data/prot.tsv \\"
echo "                      --metabolomics data/met.csv \\"
echo "                      --sc-rna data/scrna.h5ad \\"
echo "                      --sc-atac data/scatac.h5ad \\"
echo "                      --spatial data/visium_dir/ \\"
echo "                      --metadata data/meta.csv"
echo ""
echo "  All options:      python multiomics_reactome.py --help"
echo ""
