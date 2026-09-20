"""Generate invented records for all twenty tables; contains no upstream data."""

import argparse
import csv
from pathlib import Path

from unikegg import tsv
from unikegg.dataset import CODES, TABLES, manifest


def generate(directory, edge_cases=False, legacy_quoting=False):
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
    if edge_cases:
        data["COMPOSTO_KEGG"][0][1] = "NULL"
        data["COMPOSTO_KEGG"][0][3] = "99999999999999.9999999999"
        data["GENE_KEGG"][0][3] = "NULL"
        data["GENE_KEGG"][1][3] = ""
        data["PROTEIN_UNIPROT"][0][3] = 'Line one\nLine two\t"quoted" \\path café 🧬'
        data["PROTEIN_UNIPROT"][0][4:6] = [200000, 20000000]
        data["PROTEIN_UNIPROT"][0][8] = "A" * 200000
        data["PROTEIN_UNIPROT"][1][3] = r"\N"
        data["PROTEIN_UNIPROT"][2][3] = ""
        data["PROTEIN_UNIPROT"][3][3] = " "
        data["PROTEIN_UNIPROT"][4][3] = "\u0301"
        data["TERMINE_GO"][0][1] = "λ" * 500
        data["NUMERO_EC"].append(["3.5.1.n3"])
        human = next(
            p[0] for p in data["PROTEIN_UNIPROT"] if p[1] == sorted(CODES).index("hsa") + 1
        )
        data["PROTEINA_EC"].append([human, "3.5.1.n3"])
        data["REAZIONE_EC"].append(["R00001", "3.5.1.n3"])
    for table in TABLES:
        with (directory / table["file"]).open("w", encoding="utf-8", newline="") as stream:
            writer = (
                csv.writer(stream, delimiter="\t", lineterminator="\n")
                if legacy_quoting
                else tsv.writer(stream)
            )
            writer.writerow(table["columns"])
            writer.writerows(data[table["name"]])
    manifest(directory, "synthetic")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/processed"))
    parser.add_argument("--edge-cases", action="store_true")
    parser.add_argument("--legacy-quoting", action="store_true")
    args = parser.parse_args()
    generate(args.output, args.edge_cases, args.legacy_quoting)
