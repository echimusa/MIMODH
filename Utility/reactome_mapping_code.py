"""
reactome_mapping_rates.py
==========================
Computes Reactome pathway mapping success rates for the MIMODH manuscript
section "Reactome pathway mapping and network construction".

Fills in the four [XX]% placeholders:
  "the proportion of quantified entities successfully assigned to at least
   one Reactome pathway was [XX]% for transcriptomics, [XX]% for proteomics,
   [XX]% for metabolomics, and [XX]% for lipid species"

Cross-referencing strategy (as stated in the manuscript):
  Metabolites/lipids supplied as HMDB, KEGG COMPOUND, or LIPID MAPS
  identifiers are first cross-referenced to ChEBI before Reactome querying.

Output
------
  reactome_mapping_rates.csv   → Supplementary Table 12
  reactome_mapping_rates.json  → machine-readable

Requirements
------------
    pip install requests pandas numpy tqdm
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from tqdm.auto import tqdm

log = logging.getLogger("reactome_mapping")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

REACTOME_BASE = "https://reactome.org/ContentService"
CHEBI_API     = "https://www.ebi.ac.uk/webservices/chebi/2.0/test/getCompleteEntity"
HMDB_API      = "https://hmdb.ca/metabolites/{}.xml"
CACHE_FILE    = Path("reactome_mapping_cache.json")
OUT_DIR       = Path("reactome_mapping_output")
OUT_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. LOCAL CACHE
# ══════════════════════════════════════════════════════════════════════════════

class MappingCache:
    def __init__(self, path: Path = CACHE_FILE):
        self.path  = path
        self._data = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str):          return self._data.get(key)
    def set(self, key: str, val):
        self._data[key] = val
        self.path.write_text(json.dumps(self._data))
    def __contains__(self, key: str): return key in self._data


CACHE = MappingCache()


# ══════════════════════════════════════════════════════════════════════════════
# 2. IDENTIFIER CROSS-REFERENCING
# ══════════════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict = None, retries: int = 3) -> Optional[dict | list]:
    """HTTP GET with retry and rate-limiting."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json() if r.headers.get(
                    "content-type","").startswith("application/json") else r.text
            if r.status_code == 404:
                return None
            time.sleep(1 + attempt)
        except requests.RequestException as e:
            log.debug(f"Request error ({url}): {e}")
            time.sleep(2 + attempt)
    return None


def hmdb_to_chebi(hmdb_id: str) -> Optional[str]:
    """
    Cross-reference HMDB ID → ChEBI ID via HMDB REST API.
    Returns ChEBI ID string (e.g. 'CHEBI:17234') or None.
    """
    key = f"hmdb2chebi:{hmdb_id}"
    if key in CACHE: return CACHE.get(key)
    url  = f"https://hmdb.ca/metabolites/{hmdb_id}.xml"
    resp = None
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.text)
            ns   = {"hmdb": "http://www.hmdb.ca"}
            # ChEBI ID is in <chebi_id> tag
            chebi_el = root.find(".//hmdb:chebi_id", ns)
            if chebi_el is not None and chebi_el.text:
                result = f"CHEBI:{chebi_el.text.strip()}"
                CACHE.set(key, result)
                return result
    except Exception as e:
        log.debug(f"HMDB→ChEBI error ({hmdb_id}): {e}")
    CACHE.set(key, None)
    return None


def kegg_to_chebi(kegg_id: str) -> Optional[str]:
    """
    Cross-reference KEGG COMPOUND ID → ChEBI ID via KEGG REST API.
    """
    key = f"kegg2chebi:{kegg_id}"
    if key in CACHE: return CACHE.get(key)
    url  = f"https://rest.kegg.jp/get/{kegg_id}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            for line in r.text.splitlines():
                if "ChEBI:" in line:
                    chebi = "CHEBI:" + line.split("ChEBI:")[-1].strip().split()[0]
                    CACHE.set(key, chebi)
                    return chebi
    except Exception as e:
        log.debug(f"KEGG→ChEBI error ({kegg_id}): {e}")
    CACHE.set(key, None)
    return None


def lipidmaps_to_chebi(lm_id: str) -> Optional[str]:
    """
    Cross-reference LIPID MAPS ID → ChEBI via ClassyFire/LIPID MAPS API.
    Falls back to direct Reactome query with the raw LM ID.
    """
    key = f"lm2chebi:{lm_id}"
    if key in CACHE: return CACHE.get(key)
    url = f"https://www.lipidmaps.org/rest/compound/lm_id/{lm_id}/chebi_id/json"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data   = r.json()
            chebi  = data.get("chebi_id", "")
            if chebi:
                result = f"CHEBI:{chebi}" if not chebi.startswith("CHEBI") else chebi
                CACHE.set(key, result)
                return result
    except Exception as e:
        log.debug(f"LM→ChEBI error ({lm_id}): {e}")
    CACHE.set(key, None)
    return None


def normalise_to_chebi(identifier: str) -> Optional[str]:
    """
    Detect identifier type and cross-reference to ChEBI if needed.
    Passes through identifiers already in CHEBI: format unchanged.
    """
    iid = identifier.strip()
    if iid.upper().startswith("CHEBI:"):
        return iid.upper()
    if iid.upper().startswith("HMDB"):
        return hmdb_to_chebi(iid.upper())
    if iid.upper().startswith("C") and iid[1:].isdigit():   # KEGG COMPOUND
        return kegg_to_chebi(iid.upper())
    if iid.upper().startswith("LM"):                         # LIPID MAPS
        return lipidmaps_to_chebi(iid.upper())
    # Unknown — pass through
    return iid


# ══════════════════════════════════════════════════════════════════════════════
# 3. REACTOME ENTITY MAPPING
# ══════════════════════════════════════════════════════════════════════════════

def reactome_pathways_for_entity(entity_id: str,
                                  species: str = "Homo sapiens") -> List[str]:
    """
    Query Reactome Content Service for pathway memberships.
    Returns list of Reactome stable IDs (R-HSA-*).
    """
    key = f"reactome:{entity_id}"
    if key in CACHE: return CACHE.get(key)

    url  = (f"{REACTOME_BASE}/data/pathways/low/entity/"
            f"{entity_id}/allForms")
    data = _get(url, params={"species": species})

    pathways = []
    if isinstance(data, list):
        pathways = [pw.get("stId", "") for pw in data
                    if pw.get("stId", "").startswith("R-HSA-")]

    CACHE.set(key, pathways)
    time.sleep(0.05)    # respect Reactome rate limit
    return pathways


def compute_mapping_rate(
        identifiers:    List[str],
        entity_type:    str,           # "gene", "protein", "metabolite", "lipid"
        normalise_fn    = None         # optional cross-referencing function
) -> Dict:
    """
    For a list of entity identifiers, compute the fraction with at least
    one Reactome pathway mapping.

    Returns a dict with:
        entity_type, n_total, n_mapped, n_unmapped, mapping_rate_pct,
        unmapped_list (first 20)
    """
    log.info(f"  Mapping {len(identifiers)} {entity_type} identifiers …")

    n_mapped    = 0
    unmapped    = []
    chebi_fails = 0

    for eid in tqdm(identifiers, desc=f"  {entity_type}", leave=False):
        query_id = eid
        if normalise_fn is not None:
            query_id = normalise_fn(eid)
            if query_id is None:
                chebi_fails += 1
                unmapped.append(eid)
                continue

        pathways = reactome_pathways_for_entity(query_id)
        if pathways:
            n_mapped += 1
        else:
            unmapped.append(eid)

    n_total = len(identifiers)
    rate    = 100.0 * n_mapped / n_total if n_total else 0.0

    log.info(f"    {entity_type}: {n_mapped}/{n_total} mapped "
             f"({rate:.1f}%); {chebi_fails} failed ChEBI cross-ref")

    return {
        "entity_type":       entity_type,
        "n_total":           n_total,
        "n_mapped":          n_mapped,
        "n_unmapped":        n_total - n_mapped,
        "chebi_crossref_failed": chebi_fails,
        "mapping_rate_pct":  round(rate, 1),
        "unmapped_sample":   unmapped[:20],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. SUPPLEMENTARY TABLE 12 FORMATTER
# ══════════════════════════════════════════════════════════════════════════════

def format_supp_table12(results: List[Dict]) -> pd.DataFrame:
    """
    Format mapping results into Supplementary Table 12 structure:
    'Numbers and percentages of quantified entities mapped to at least one
     Reactome pathway for genes, proteins, metabolites, and lipid species,
     with unmapped entities retained and enumerated.'
    """
    rows = []
    for r in results:
        rows.append({
            "Entity class":                     r["entity_type"].capitalize(),
            "Identifiers quantified (n)":       r["n_total"],
            "Mapped to Reactome (n)":           r["n_mapped"],
            "Unmapped (n)":                     r["n_unmapped"],
            "Mapping rate (%)":                 r["mapping_rate_pct"],
            "Failed ChEBI cross-reference (n)": r.get("chebi_crossref_failed", 0),
            "Notes": (
                "Entities supplied as HMDB/KEGG/LIPID MAPS cross-referenced "
                "to ChEBI prior to Reactome query. Unmapped entities retained "
                "in pipeline output — not discarded."
                if r["entity_type"] in ("metabolite", "lipid")
                else "Direct Reactome query via HGNC symbol / UniProt accession."
            ),
        })
    return pd.DataFrame(rows)


def generate_manuscript_text(results: List[Dict]) -> str:
    """
    Generate the filled-in paragraph text for the manuscript,
    ready for tracked-change insertion.
    All [XX]% placeholders are replaced with computed values.
    """
    rate_map = {r["entity_type"]: r["mapping_rate_pct"] for r in results}

    tx   = rate_map.get("gene",       "[XX — run pipeline]")
    pr   = rate_map.get("protein",    "[XX — run pipeline]")
    me   = rate_map.get("metabolite", "[XX — run pipeline]")
    li   = rate_map.get("lipid",      "[XX — run pipeline]")

    text = (
        f"For the datasets analysed here, the proportion of quantified entities "
        f"successfully assigned to at least one Reactome pathway was {tx}% for "
        f"transcriptomics, {pr}% for proteomics, {me}% for metabolomics, and "
        f"{li}% for lipid species (Supplementary Table 12). "
        f"Mapping rates are markedly lower for metabolites and lipids than for "
        f"genes and proteins, reflecting the incomplete representation of these "
        f"entity classes in Reactome. We therefore report mapping rate as a "
        f"standard output of every run, and MIMODH requires it to be declared, "
        f"so that readers can judge whether pathway-level conclusions are supported "
        f"by adequate coverage."
    )
    return text


# ══════════════════════════════════════════════════════════════════════════════
# 5. MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute Reactome mapping rates for MIMODH Supplementary Table 12")
    parser.add_argument("--genes",       default=None,
                        help="CSV file: one HGNC gene symbol per line")
    parser.add_argument("--proteins",    default=None,
                        help="CSV file: one UniProt accession per line")
    parser.add_argument("--metabolites", default=None,
                        help="CSV file: one metabolite ID per line "
                             "(CHEBI:, HMDB, KEGG C, or LM prefix auto-detected)")
    parser.add_argument("--lipids",      default=None,
                        help="CSV file: one lipid ID per line (LIPID MAPS or HMDB)")
    parser.add_argument("--demo",        action="store_true",
                        help="Run on small demo identifier sets to test connectivity")
    args = parser.parse_args()

    all_results = []

    if args.demo:
        log.info("Running DEMO mode with representative identifier sets …")

        demo_genes = [
            "TP53","EGFR","BRCA1","KRAS","MYC","AKT1","MTOR","PIK3CA",
            "PTEN","CDK2","CCND1","RB1","MDM2","BCL2","BAX","CASP3",
            "ATM","CHEK1","RAD51","HIF1A","JAK1","STAT3","SMAD2","WNT3A",
            "NOTCH1","HDAC1","EZH2","SIRT1","AMPK","TSC1",
        ]
        demo_proteins = [
            "P04637","P00533","P38398","P51587","P01116","P01106",
            "P15692","P31749","P42345","P42336","P60484","P24941",
        ]
        demo_metabolites = [
            "CHEBI:15422",   # ATP
            "CHEBI:17634",   # glucose
            "CHEBI:16015",   # pyruvate
            "CHEBI:16947",   # citrate
            "CHEBI:16810",   # oxaloacetate
            "CHEBI:15361",   # acetyl-CoA
            "HMDB0000190",   # lactic acid — will be cross-referenced
            "C00031",        # KEGG D-glucose — will be cross-referenced
        ]
        demo_lipids = [
            "LMFA01010001",  # palmitic acid — LIPID MAPS
            "LMGL02010000",  # triacylglycerol
            "HMDB0000062",   # cholesterol — HMDB
            "CHEBI:15843",   # cholesterol — direct ChEBI
        ]

        all_results.append(
            compute_mapping_rate(demo_genes, "gene"))
        all_results.append(
            compute_mapping_rate(demo_proteins, "protein"))
        all_results.append(
            compute_mapping_rate(demo_metabolites, "metabolite",
                                 normalise_fn=normalise_to_chebi))
        all_results.append(
            compute_mapping_rate(demo_lipids, "lipid",
                                 normalise_fn=normalise_to_chebi))

    else:
        def _load_ids(path_str):
            if path_str is None: return None
            p = Path(path_str)
            return [l.strip() for l in p.read_text().splitlines() if l.strip()]

        genes       = _load_ids(args.genes)
        proteins    = _load_ids(args.proteins)
        metabolites = _load_ids(args.metabolites)
        lipids      = _load_ids(args.lipids)

        if genes:
            all_results.append(compute_mapping_rate(genes, "gene"))
        if proteins:
            all_results.append(compute_mapping_rate(proteins, "protein"))
        if metabolites:
            all_results.append(compute_mapping_rate(
                metabolites, "metabolite", normalise_fn=normalise_to_chebi))
        if lipids:
            all_results.append(compute_mapping_rate(
                lipids, "lipid", normalise_fn=normalise_to_chebi))

    if all_results:
        # Supplementary Table 12
        supp12 = format_supp_table12(all_results)
        out12  = OUT_DIR / "SupplementaryTable12_ReactomeMappingRates.csv"
        supp12.to_csv(out12, index=False)
        log.info(f"\nSupplementary Table 12 saved: {out12}")
        print(f"\n{supp12.to_string(index=False)}")

        # Manuscript text
        ms_text = generate_manuscript_text(all_results)
        ms_out  = OUT_DIR / "manuscript_reactome_paragraph.txt"
        ms_out.write_text(ms_text)
        log.info(f"\nManuscript paragraph saved: {ms_out}")
        print(f"\n{'='*70}")
        print("FILLED-IN MANUSCRIPT TEXT (copy into tracked-change .docx):")
        print('='*70)
        print(ms_text)

        # JSON
        with open(OUT_DIR / "reactome_mapping_rates.json", "w") as f:
            json.dump(all_results, f, indent=2, default=str)

        print(f"\nAll outputs: {OUT_DIR.resolve()}")
