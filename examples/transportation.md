# Example: freight routing at Northlake Beverages

**Problem statement (what you'd type into Formulate):**

> Northlake Beverages bottles at two plants, Avonford (60 pallets/day) and
> Brightmoor (80 pallets/day), and ships to three warehouses: Carverton
> needs 50 pallets, Dunmore 40, and Eastvale 50. Freight cost per pallet:
> from Avonford it is 4 to Carverton, 6 to Dunmore, 9 to Eastvale; from
> Brightmoor it is 5, 3, and 2. How should we route shipments to meet all
> demand at minimum cost?

**Model shape:** classic balanced transportation LP — one continuous
variable per (plant, warehouse) lane, supply caps, demand floors.

**Known optimum (hand-checkable):** Brightmoor owns its cheap lanes:
Eastvale at 2 (50 pallets) and Dunmore at 3 (its remaining 30). Avonford
covers Carverton at 4 (50) and tops up Dunmore at 6 (10). Any single-lane
swap raises cost by at least 4 per pallet, so:

```
objective = 50*2 + 30*3 + 50*4 + 10*6 = 450
```

The end-to-end test asserts this value. Run it yourself:

```
python -m formulate.pipeline examples/transportation.spec.json
```
