"""Stage 4: docs/04-sampling.md."""

from datetime import date

import pyarrow as pa
import pyarrow.compute as pc


def filter_window(table: pa.Table, start: date, end: date, sections: list[str]) -> pa.Table:
    mask = pc.and_(
        pc.and_(
            pc.greater_equal(table["publication_date"], pa.scalar(start)),
            pc.less_equal(table["publication_date"], pa.scalar(end)),
        ),
        pc.is_in(table["section"], value_set=pa.array(sections)),
    )
    return table.filter(mask)


def coverage(table: pa.Table, total_diseases: int, total_targets: int) -> dict[str, float]:
    n_diseases = pc.count_distinct(table["disease"]).as_py()
    n_targets = pc.count_distinct(table["target"]).as_py()
    return {
        "disease_coverage": n_diseases / total_diseases,
        "target_coverage": n_targets / total_targets,
    }


def ontology_spread(table: pa.Table) -> dict:
    raise NotImplementedError("Concrete spread metric not yet defined (docs/10-open-questions.md).")


def draw_sample(table: pa.Table, total_diseases: int, total_targets: int) -> tuple[pa.Table, dict]:
    raise NotImplementedError
