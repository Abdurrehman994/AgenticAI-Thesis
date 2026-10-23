"""Read custom properties and assembly structure from the SolidWorks sample files into data/cad_extract.json.

Needs SolidWorks running (COM). Files are opened read-only and silently; nothing is saved or changed.

Properties are read from the file's Custom tab ("properties") and from each configuration's Configuration
Specific tab ("configurations"): many parts keep their description there. Values are the evaluated ones
(a material link reads as "Brass", not as its expression); empty values are left out.

    python scripts/extract_cad.py
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pythoncom
import win32com.client as win32

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "cad_extract.json"
FOLDERS = ["ESS-0010_CADData", "3DCD-0011_CADData"]
READ_ONLY_SILENT = 1 | 2  # swOpenDocOptions_Silent | swOpenDocOptions_ReadOnly
DOC_TYPES = {".sldprt": 1, ".sldasm": 2}


SUMMARY_FIELDS = {"title": 0, "subject": 1, "keywords": 3, "comment": 4}  # swSummInfoField_e


def byref(vt: int, value) -> win32.VARIANT:
    return win32.VARIANT(pythoncom.VT_BYREF | vt, value)


def read_properties(doc, configuration: str = "") -> dict:
    """Evaluated values of one property tab: "" is the Custom tab, else a configuration's."""
    manager = doc.Extension.CustomPropertyManager(configuration)
    properties = {}
    for name in manager.GetNames or []:
        raw, resolved = byref(pythoncom.VT_BSTR, ""), byref(pythoncom.VT_BSTR, "")
        manager.Get5(name, False, raw, resolved, byref(pythoncom.VT_BOOL, False))
        if resolved.value.strip():
            properties[name] = resolved.value
    return properties


def read_configurations(doc) -> dict:
    found = {name: read_properties(doc, name) for name in doc.GetConfigurationNames or []}
    return {name: properties for name, properties in found.items() if properties}


def read_summary(doc) -> dict:
    found = {name: doc.SummaryInfo(index) for name, index in SUMMARY_FIELDS.items()}
    return {name: value for name, value in found.items() if value}


def read_children(doc) -> dict:
    """Direct children of an assembly: file name -> instance count."""
    components = doc.GetComponents(True) or []  # True = top level only
    return dict(Counter(os.path.basename(c.GetPathName).lower() for c in components if c.GetPathName))


def main() -> None:
    sw = win32.Dispatch("SldWorks.Application")
    entries = {}
    for folder in FOLDERS:
        for path in sorted((DATA / folder).rglob("*"), key=lambda p: p.name.lower()):
            doc_type = DOC_TYPES.get(path.suffix.lower())
            if doc_type is None or path.name.startswith("~$"):  # "~$" = SolidWorks lock file
                continue
            was_open = sw.GetOpenDocumentByName(str(path)) is not None
            doc = sw.OpenDoc6(str(path), doc_type, READ_ONLY_SILENT, "", byref(pythoncom.VT_I4, 0), byref(pythoncom.VT_I4, 0))
            key = path.relative_to(DATA).as_posix()
            if doc is None:
                entries[key] = {"error": "could not open"}
                continue
            entry = {
                "kind": "assembly" if doc_type == 2 else "part",
                "properties": read_properties(doc),
                "configurations": read_configurations(doc),
                "summary": read_summary(doc),
            }
            if doc_type == 2:
                entry["children"] = read_children(doc)
            entries[key] = entry
            if not was_open:
                sw.CloseDoc(doc.GetTitle)
    OUT.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"{len(entries)} files -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
