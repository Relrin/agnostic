"""Scripted runs the mock model plays end to end, for demos and screenshots without a real model.

**Bug fix** (``persona="coder"``, a request that asks to fix something): the coder writes the module from the
request and a regression test, runs the tests in its sandbox (they fail), corrects the line with ``edit``, runs them
again (they pass) and copies both files to ``outputs/``. The commands really run, so the failure and the pass come
from the sandbox, not from this file. Paste ``INVOICE_BUGGY`` in a fenced block to reproduce it.

**Research** (``persona="web-researcher"``, a request to research or compare): three searches in one step, then a
cited comparison. ``web_search`` answers these queries from ``SEARCH_RESULTS``; the pages are real.
"""

BUG_FIX_TRIGGER = r"\b(fix|bug|failing|broken)\b"
RESEARCH_TRIGGER = r"\b(research|compare|comparison)\b"

INVOICE_BUGGY = '''def invoice_total(items, discount_pct=0, tax_pct=0):
    """Total of an invoice: line items, then the discount, then tax."""
    subtotal = sum(item["price"] * item["qty"] for item in items)
    discounted = subtotal * (1 - discount_pct / 100)
    taxed = discounted * (1 + tax_pct / 100)
    return round(taxed - subtotal * discount_pct / 100, 2)
'''

INVOICE_BUGGY_LINE = "    return round(taxed - subtotal * discount_pct / 100, 2)"
INVOICE_FIXED_LINE = "    return round(taxed, 2)"

INVOICE_TEST = """import unittest

from invoice import invoice_total


class InvoiceTotalTest(unittest.TestCase):
    def test_discount_is_applied_once(self):
        items = [{"price": 50.0, "qty": 2}]
        # 100.00, minus 10 % is 90.00, plus 20 % tax is 108.00
        self.assertEqual(invoice_total(items, discount_pct=10, tax_pct=20), 108.0)

    def test_no_discount_no_tax(self):
        self.assertEqual(invoice_total([{"price": 19.99, "qty": 3}]), 59.97)


if __name__ == "__main__":
    unittest.main()
"""

BUG_FIX_REASONING = (
    "Reproduce first: put the function in invoice.py, pin the expected total in a test and run it. The return "
    "line subtracts the discount from an amount that is already discounted, so I expect 98.0 instead of 108.0."
)
BUG_FIX_EDIT_REASONING = "The test fails as predicted (98.0 != 108.0). The discount is already in `discounted`."

BUG_FIX_SUMMARY = """Fixed: the discount was applied twice.

`discounted` already holds the subtotal minus the discount, and the return line subtracted \
`subtotal * discount_pct / 100` again after tax. For 2 × 50.00 with 10 % off and 20 % tax the invoice came to \
**98.00** instead of **108.00**.

```diff
-    return round(taxed - subtotal * discount_pct / 100, 2)
+    return round(taxed, 2)
```

- Reproduced it with `test_discount_is_applied_once` (failed with `98.0 != 108.0`), then both tests passed.
- Invoices without a discount were never affected, so only discounted invoices issued since the change need a check.
- `outputs/` has the fixed `invoice.py` and `test_invoice.py` to drop into the repository."""

RESEARCH_QUERIES = (
    "pgvector HNSW vs IVFFlat index",
    "pgvector HNSW m ef_construction ef_search defaults",
    "pgvector IVFFlat lists probes recommendation",
)

PGVECTOR_README = "https://github.com/pgvector/pgvector#indexing"
SUPABASE_HNSW = "https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes"
SUPABASE_IVF = "https://supabase.com/docs/guides/ai/vector-indexes/ivf-indexes"

SEARCH_RESULTS: dict[str, str] = {
    RESEARCH_QUERIES[0]: (
        f"1. pgvector README, Indexing ({PGVECTOR_README}): HNSW has better query performance than IVFFlat "
        "(speed-recall tradeoff) but slower build times and uses more memory; IVFFlat builds faster and uses less "
        "memory.\n"
        f"2. Supabase, HNSW indexes ({SUPABASE_HNSW}): HNSW is the recommended default; it can be created on an "
        "empty table and stays accurate as rows are added.\n"
        f"3. Supabase, IVFFlat indexes ({SUPABASE_IVF}): create the index after the table has data, since the lists "
        "are computed from the rows present at build time."
    ),
    RESEARCH_QUERIES[1]: (
        f"1. pgvector README ({PGVECTOR_README}): HNSW options m (max connections per layer, default 16) and "
        "ef_construction (candidate list size while building, default 64); hnsw.ef_search (default 40) trades speed "
        "for recall at query time; SET LOCAL inside a transaction sets it for one query.\n"
        f"2. Supabase, HNSW indexes ({SUPABASE_HNSW}): a higher ef_search gives better recall at some speed."
    ),
    RESEARCH_QUERIES[2]: (
        f"1. pgvector README ({PGVECTOR_README}): IVFFlat lists = rows / 1000 up to 1M rows, sqrt(rows) above; "
        "ivfflat.probes starts at sqrt(lists); there must be data in the table before the index is created.\n"
        f"2. Supabase, IVFFlat indexes ({SUPABASE_IVF}): the lists are fixed when the index is built."
    ),
}

RESEARCH_ANSWER = f"""**Use HNSW** for the knowledge-base embeddings. It answers queries faster at the same recall, \
works on an empty table and needs no rebuild as documents are added. IVFFlat only wins when build time or memory is \
the constraint.

| | HNSW | IVFFlat |
|---|---|---|
| Query speed at equal recall | better | lower |
| Build time and memory | slower, more | faster, less |
| Empty table at creation | fine | no: lists come from existing rows |
| As data grows | stays accurate | lists fixed at build: may need a rebuild |
| Knobs | `m` 16, `ef_construction` 64, `hnsw.ef_search` 40 | `lists` ≈ rows / 1000, `ivfflat.probes` ≈ √lists |

For about 1M rows of 1,536 dimensions:

```sql
CREATE INDEX ON kb_chunks USING hnsw (embedding vector_cosine_ops);
SET LOCAL hnsw.ef_search = 100;  -- more recall for this query
```

Sources: [pgvector README]({PGVECTOR_README}) · [Supabase: HNSW]({SUPABASE_HNSW}) · \
[Supabase: IVFFlat]({SUPABASE_IVF})"""
