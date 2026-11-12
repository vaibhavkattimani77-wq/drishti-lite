# validation/

`reference_check.xlsx` is the Gate 1 independent check (spec §6).

1. Run a clean analysis in the app (Data > Ignore cache), one openFDA data date only.
2. Sheet **Reference check**: type a, a+b, a+c and N for three pairs, plus the app's values. Every
   match cell must be TRUE and the last row must say YES for all three pairs.
3. Sheet **Hand check (calculator)**: recompute Pair 1 with a calculator, step by step. This makes the
   check independent of both the app and the Excel formulas.

The workbook template was prepared with Claude; the counts, app values and hand calculations are
entered by the reviewer.
