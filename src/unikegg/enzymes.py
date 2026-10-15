"""EC descriptions from the official UniProt ENZYME RDF distribution."""

import json
import lzma
import xml.etree.ElementTree as ET
from pathlib import Path

from unikegg.dataset import sha256
from unikegg.identifiers import EC_RE

URL = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/rdf/enzyme.rdf.xz"
NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "up": "http://purl.uniprot.org/core/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
}
EC_FIELDS = ["name", "catalytic_activity", "comment"]


def read_catalog(path):
    path = Path(path)
    metadata = path.parent / "manifest.json"
    if path.name == "enzyme.rdf.xz" and metadata.exists():
        item = json.loads(metadata.read_text())
        if item.get("url") != URL or item.get("sha256") != sha256(path):
            raise ValueError("ENZYME catalog checksum/source mismatch")
    with lzma.open(path) as stream:
        root = ET.parse(stream).getroot()
    if root.tag != f"{{{NS['rdf']}}}RDF":
        raise ValueError("Expected UniProt ENZYME RDF")
    nodes = {}
    for node in root.findall("rdf:Description", NS):
        identifier = node.get(f"{{{NS['rdf']}}}about")
        if identifier and not EC_RE.fullmatch(identifier.split("#", 1)[0]):
            continue
        if not identifier or identifier in nodes:
            raise ValueError("Missing/duplicate ENZYME RDF identifier")
        nodes[identifier] = node

    def texts(node, tag):
        return " ".join(" ".join("".join(e.itertext()).split()) for e in node.findall(tag, NS))

    result = {}
    for identifier, node in nodes.items():
        if not EC_RE.fullmatch(identifier):
            continue
        activities = []
        for activity in node.findall("up:activity", NS):
            reference = activity.get(f"{{{NS['rdf']}}}resource")
            if reference not in nodes or not texts(nodes[reference], "rdfs:label"):
                raise ValueError(f"Unresolved ENZYME activity: {identifier}: {reference}")
            activities.append(texts(nodes[reference], "rdfs:label"))
        result[identifier] = [
            texts(node, "skos:prefLabel"), " ".join(activities), texts(node, "rdfs:comment"),
        ]
    if not result:
        raise ValueError("Empty ENZYME catalog")
    return result
