"""Rewriting the nomenclature table must not churn it.

`lobemap nomenclature` and `ingest` rewrite `registry/nomenclature.csv` in
place, and the table is reviewed as a diff. A save that changes line endings
turns a one-row edit into a 477-line diff that hides the row.
"""

from __future__ import annotations

from pathlib import Path

from lobemap.core.names import Correspondence, Nomenclature

TABLE = Path(__file__).resolve().parents[1] / "registry" / "nomenclature.csv"


def test_saving_the_committed_table_reproduces_it_byte_for_byte(tmp_path):
    out = Nomenclature.load(TABLE).save(tmp_path / "nomenclature.csv")
    assert out.read_bytes() == TABLE.read_bytes()


def test_a_saved_table_uses_lf_line_endings(tmp_path):
    nom = Nomenclature(["DA1", "VA1d"], [
        Correspondence("a", "DA1(R)", ("DA1",), "exact"),
        Correspondence("a", "VA1d(R)", ("VA1d",), "exact"),
    ])
    text = nom.save(tmp_path / "n.csv").read_bytes()
    assert b"\r" not in text
    assert text.count(b"\n") == 3
