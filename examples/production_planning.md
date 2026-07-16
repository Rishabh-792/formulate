# Example: production planning at Meridian Woodworks

**Problem statement (what you'd type into Formulate):**

> Meridian Woodworks builds chairs, tables, and desks. Every product passes
> through two machines: cutting and assembly. A chair needs 1 cutting hour
> and 2 assembly hours; a table needs 3 and 2; a desk needs 2 and 3. The
> cutting machine has 160 hours available per week and assembly has 250.
> Profit per unit is 25 for a chair, 110 for a table, and 75 for a desk.
> The market absorbs at most 100 chairs, 20 tables, and 30 desks per week.
> How many of each should we produce to maximize profit?

**Model shape:** pure LP — one continuous variable per product, one
capacity constraint per machine, one demand cap per product.

**Known optimum (hand-checkable):** tables and desks earn the most per
cutting hour, so both sell out (`table = 20`, `desk = 30`), consuming
`3*20 + 2*30 = 120` of the 160 cutting hours. The remaining 40 cutting
hours go to chairs (`chair = 40`); assembly stays slack
(`2*40 + 2*20 + 3*30 = 210 <= 250`). Swapping any chair capacity back into
tables or desks loses money, so:

```
objective = 25*40 + 110*20 + 75*30 = 5450
```

The end-to-end test asserts this value. Run it yourself:

```
python -m formulate.pipeline examples/production_planning.spec.json
```
