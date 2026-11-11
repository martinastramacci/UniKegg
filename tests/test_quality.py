"""Quality metrics count biological pairs, not duplicate source assertions."""

import json

import pytest

from tests.make_fixture import generate
from tests.test_transform import command
from unikegg import tsv
from unikegg.dataset import BY_NAME, manifest, rows
from unikegg.quality import compare, metrics, report


def replace(directory, name, data):
    table = BY_NAME[name]
    with (directory / table["file"]).open("w", newline="") as stream:
        writer = tsv.writer(stream)
        writer.writerow(table["columns"])
        writer.writerows([row[c] for c in table["columns"]] for row in data)


def test_pairs_multiplicity_and_zero_denominators(tmp_path):
    directory = generate(tmp_path)
    genes = list(rows(directory, BY_NAME["GENE_KEGG"]))
    proteins = list(rows(directory, BY_NAME["PROTEIN_UNIPROT"]))
    links = list(rows(directory, BY_NAME["GENE_PROTEIN"]))
    # Duplicate source assertions remain one biological pair.
    original = metrics(directory)
    assert all(r["total_pairs"] == 1 and r["both_sources"] == 1
               for r in original["organisms"].values())
    first_gene, first_protein = genes[0], proteins[0]
    genes.append({**first_gene, "kegg_gene_id": first_gene["kegg_gene_id"] + "x"})
    proteins.append({**first_protein, "accession": "EXTRA", "entry_name": "EXTRA"})
    links.extend([
        {"kegg_gene_id": first_gene["kegg_gene_id"], "accession": "EXTRA",
         "mapping_source": "KEGG_CONV"},
        {"kegg_gene_id": genes[-1]["kegg_gene_id"], "accession": first_protein["accession"],
         "mapping_source": "UNIPROT_DR"},
    ])
    # Case-insensitive IDs match database/validator semantics.
    links[0]["accession"] = links[0]["accession"].lower()
    empty_code = genes[1]["kegg_gene_id"].split(":")[0]
    links = [r for r in links if not r["kegg_gene_id"].startswith(empty_code + ":")]
    genes[1]["gene_type"] = "RNA"
    for name, data in (("GENE_KEGG", genes), ("PROTEIN_UNIPROT", proteins), ("GENE_PROTEIN", links)):
        replace(directory, name, data)
    result = metrics(directory)["organisms"]
    first = result[first_gene["kegg_gene_id"].split(":")[0]]
    assert (first["total_pairs"], first["both_sources"], first["kegg_only"], first["uniprot_only"]) == (3, 1, 1, 1)
    assert first["genes_multiple_proteins"] == first["proteins_multiple_genes"] == 1
    assert first["protein_coverage_percent"] == 100
    assert result[empty_code]["cds_coverage_percent"] is None
    assert result[empty_code]["source_agreement_percent"] is None
    assert result[empty_code]["unmapped_proteins"] == 1


def test_report_comparison_and_integrity(tmp_path):
    baseline = generate(tmp_path / "baseline")
    current = generate(tmp_path / "current")
    links = list(rows(current, BY_NAME["GENE_PROTEIN"]))
    replace(current, "GENE_PROTEIN", links[2:])
    manifest(current, "synthetic")
    result = report(current, "synthetic", baseline)
    assert result["provenance"] is None
    assert result["dataset_sha256"] != result["baseline_sha256"]
    assert len(result["comparison"]["decreases_to_review"]) == 2
    assert result["measurements"]["current_snapshot_bytes"] > 0
    assert result["comparison"]["deltas"]["ath"]["total_pairs"] == -1
    (current / "gene_protein.tsv").write_text("broken")
    with pytest.raises(ValueError, match="Checksum"):
        report(current, "synthetic")


def test_comparison_selection_changes():
    result = compare({"organisms": {"hsa": {}}}, {"organisms": {"eco": {}}})
    assert result["added_organisms"] == ["hsa"]
    assert result["removed_organisms"] == ["eco"]
    assert result["deltas"] == {}


def test_quality_cli(tmp_path):
    generate(tmp_path / "data/processed")
    result = command(tmp_path, "quality", extra_env={"UNIKEGG_DATASET_KIND": "synthetic"})
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["quality"]["organisms"]) == 16
    assert command(tmp_path, "validate", "--compare-to", str(tmp_path)).returncode != 0
