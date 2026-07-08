from datetime import date

import pytest

from litrex.labelling import llm_client
from litrex.schema import Cooccurrence


def test_label_row_not_yet_implemented():
    row = Cooccurrence(
        target="ENSG00000146648",
        disease="EFO_0003060",
        text="...",
        publication_id="PMID:12345",
        publication_date=date(2024, 1, 1),
        section="abstract",
    )
    with pytest.raises(NotImplementedError):
        llm_client.label_row(client=None, row=row, target_name="EGFR", disease_name="NSCLC")
