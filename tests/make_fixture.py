"""Generate invented records for all twenty tables; contains no upstream data."""

import argparse
import csv
from pathlib import Path

from unikegg.dataset import CODES, TABLES, manifest


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = {t["name"]: [] for t in TABLES}
    data["ORTOLOGIA_KEGG"] = [["K00001", 'Synthetic "orthology"', "Synthetic definition"]]
    data["PATHWAY_RIFERIMENTO"] = [["map00010", "Synthetic pathway"]]
    data["REAZIONE_KEGG"] = [["R00001", "Synthetic reaction", "", "C00001 = C00001"]]
    data["COMPOSTO_KEGG"] = [["C00001", "Synthetic compound", "H2O", "18.0106", "18.015"]]
    data["TERMINE_GO"] = [["GO:0000001", "Synthetic term", "MF"]]
    data["NUMERO_EC"] = [["1.1.1.1"]]
    for index, code in enumerate(sorted(CODES), 1):
        accession, gene, pathway = f"SYN{index:06d}", f"{code}:demo1", f"{code}00010"
        data["ORGANISMO"].append([index, code, 9000000 + index, f"Synthetic {code}"])
        data["GENE_KEGG"].append([gene, index, "CDS", "demo", "Synthetic gene"])
        data["PROTEIN_UNIPROT"].append(
            [accession, index, f"SYN_{index}", 'Synthetic "quoted" protein', 4, 400, "1", 1, "MACK"]
        )
        data["PATHWAY_ORGANISMO"].append([pathway, index, "map00010"])
        data["PROTEIN_ISOFORM"].append(
            [accession + "-1", accession, 1, "Synthetic isoform", "DISPLAYED", ""]
        )
        for source in ["KEGG_CONV", "UNIPROT_DR"]:
            data["GENE_PROTEINA"].append([gene, accession, source])
        data["GENE_ORTOLOGIA"].append([gene, "K00001"])
        data["GENE_PATHWAY"].append([gene, pathway])
        data["PROTEINA_GO"].append([accession, "GO:0000001", "", ""])
        data["PROTEINA_EC"].append([accession, "1.1.1.1"])
    data["ORTOLOGIA_REAZIONE"] = [["K00001", "R00001"]]
    data["PATHWAY_REAZIONE"] = [["map00010", "R00001"]]
    data["REAZIONE_COMPOSTO"] = [["R00001", "C00001"]]
    data["REAZIONE_EC"] = [["R00001", "1.1.1.1"]]
    for table in TABLES:
        with (directory / table["file"]).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerow(table["columns"])
            writer.writerows(data[table["name"]])
    manifest(directory, "synthetic")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/processed"))
    generate(parser.parse_args().output)
