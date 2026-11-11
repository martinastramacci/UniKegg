"""Dataset-level integration metrics; source agreement is not biological proof."""

import json
import os
import sys
import time
from collections import Counter
from contextlib import redirect_stdout

from unikegg.dataset import BY_NAME, rows, verified_snapshot


def metrics(directory):
    def read(name):
        return rows(directory, BY_NAME[name])

    organisms = {int(r["organism_id"]): r["kegg_code"] for r in read("ORGANISM")}
    genes = {
        r["kegg_gene_id"].lower(): (int(r["organism_id"]), r["gene_type"].upper() == "CDS")
        for r in read("GENE_KEGG")
    }
    proteins = {
        r["accession"].lower(): int(r["organism_id"]) for r in read("PROTEIN_UNIPROT")
    }
    pairs = {}
    for row in read("GENE_PROTEIN"):
        pair = (row["kegg_gene_id"].lower(), row["accession"].lower())
        bit = 1 if row["mapping_source"].upper() == "KEGG_CONV" else 2
        pairs[pair] = pairs.get(pair, 0) | bit
    gene_degree, protein_degree = Counter(), Counter()
    counts = {oid: Counter() for oid in organisms}
    for (gene, accession), sources in pairs.items():
        gene_degree[gene] += 1
        protein_degree[accession] += 1
        c = counts[genes[gene][0]]
        c["total_pairs"] += 1
        c[{1: "kegg_only", 2: "uniprot_only", 3: "both_sources"}[sources]] += 1
    for gene, (oid, cds) in genes.items():
        c = counts[oid]
        c["genes"] += 1
        c["unmapped_genes"] += gene_degree[gene] == 0
        c["genes_multiple_proteins"] += gene_degree[gene] > 1
        if cds:
            c["cds_genes"] += 1
            c["covered_cds_genes"] += gene_degree[gene] > 0
    for accession, oid in proteins.items():
        c = counts[oid]
        c["proteins"] += 1
        c["unmapped_proteins"] += protein_degree[accession] == 0
        c["proteins_multiple_genes"] += protein_degree[accession] > 1
    fields = (
        "genes", "cds_genes", "covered_cds_genes", "unmapped_genes", "proteins",
        "unmapped_proteins", "total_pairs", "both_sources", "kegg_only", "uniprot_only",
        "genes_multiple_proteins", "proteins_multiple_genes",
    )
    result = {}
    for oid, code in sorted(organisms.items(), key=lambda item: item[1]):
        c = counts[oid]
        result[code] = {name: c[name] for name in fields}
        for name, numerator, denominator in (
            ("cds_coverage_percent", c["covered_cds_genes"], c["cds_genes"]),
            ("protein_coverage_percent", c["proteins"] - c["unmapped_proteins"], c["proteins"]),
            ("source_agreement_percent", c["both_sources"], c["total_pairs"]),
        ):
            result[code][name] = round(100 * numerator / denominator, 6) if denominator else None
    return {"format_version": 1, "organisms": result}


def compare(current, baseline):
    current, baseline = current["organisms"], baseline["organisms"]
    deltas, warnings = {}, []
    for code in sorted(current.keys() & baseline.keys()):
        deltas[code] = {
            key: round(value - baseline[code][key], 6)
            if value is not None and baseline[code][key] is not None else None
            for key, value in current[code].items()
        }
        for key in ("cds_coverage_percent", "protein_coverage_percent", "source_agreement_percent"):
            if deltas[code][key] is not None and deltas[code][key] < 0:
                warnings.append({"organism": code, "metric": key, "delta": deltas[code][key]})
    return {
        "added_organisms": sorted(current.keys() - baseline.keys()),
        "removed_organisms": sorted(baseline.keys() - current.keys()),
        "deltas": deltas,
        "decreases_to_review": warnings,
    }


def report(directory, kind, baseline=None):
    started = time.perf_counter()
    with verified_snapshot(directory, kind) as (snapshot, manifest, fingerprint):
        quality = metrics(snapshot)
        result = {
            "format_version": 1,
            "dataset_sha256": fingerprint,
            "dataset_kind": kind,
            "quality": quality,
            "provenance": manifest.get("provenance"),
            "derivations": manifest.get("derivations", []),
        }
        snapshot_bytes = sum(p.stat().st_size for p in snapshot.iterdir())
    if baseline is not None:
        with verified_snapshot(baseline, kind) as (snapshot, _, fingerprint):
            result["baseline_sha256"] = fingerprint
            result["comparison"] = compare(quality, metrics(snapshot))
    peak = None
    if sys.platform in {"linux", "darwin"}:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "linux":
            peak *= 1024
    result["measurements"] = {
        "elapsed_seconds": time.perf_counter() - started,
        "process_peak_rss_bytes": peak,
        "current_snapshot_bytes": snapshot_bytes,
        "scope": "copy, validate and report; includes baseline when supplied; no MySQL",
    }
    return result


def run(directory, baseline=None):
    with redirect_stdout(sys.stderr):
        result = report(directory, os.environ.get("UNIKEGG_DATASET_KIND", "swissprot"), baseline)
    print(json.dumps(result, indent=2))
