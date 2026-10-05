# CSCI E-103 — Data Engineering for Analytics

Coursework repository: assignments, case studies, and final project.

## Layout

```
assignments/assignment-01/
  notebooks/   Databricks notebooks in source format (# COMMAND ----------)
  exports/     HTML exports -- GITIGNORED. Release artifacts, not source.
  data/        Local data staging — gitignored, never committed
case-studies/
final-project/
docs/          Course notes, design decisions
```

## Conventions

- **Notebooks are stored in Databricks source format**, not `.ipynb`.
  Plain Python with `# COMMAND ----------` separators diffs cleanly in Git.
- **Data files are never committed.** Datasets live in a Databricks Volume;
  this repo holds only the code that reads and transforms them.
- **HTML exports are never committed.** They contain cell outputs, and cell
  outputs contain the data. They attach to a tagged GitHub Release and are
  archived to the audit volume, so a submission is reproducible from its tag
  rather than frozen in the tree.

## Environment

- Databricks Free Edition (Unity Catalog, serverless compute)
- Apache Spark via PySpark DataFrame API
- JetBrains IntelliJ IDEA for local editing
