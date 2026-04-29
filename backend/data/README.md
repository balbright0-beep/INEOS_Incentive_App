# Bundled Reference Data

## `zip_tax_rates.csv`

Combined US sales tax rate (state + county + city + special districts)
keyed by 5-digit ZIP code. ~39,600 rows covering all US states + DC.

**Used by:** `app/services/geo.py:zip_to_combined_tax_rate`, surfaced
through `GET /api/lookup/zip/{zip}` as the `tax_rate` field on the
payment calculator.

**Source:** [Woocommerce-US-ZipCodes-TaxRates](https://github.com/MirzaAreebBaig/Woocommerce-US-ZipCodes-TaxRates),
which compiles publicly-available data from [Avalara](https://www.avalara.com/taxrates/en/state-rates.html).
The upstream repo's CSV is the only authoritative copy of the
combined rate — Avalara publishes per-state CSVs with the same data
in a different format.

**License:** GPL-3.0 (data file only — does not affect the rest of
this repo's licensing per the FSF position that GPL applies to
software, not data tables).

**Refresh cadence:** Tax rates change quarterly in many states.
Re-fetch the file every 3-6 months and check it in:

    curl -L https://raw.githubusercontent.com/MirzaAreebBaig/Woocommerce-US-ZipCodes-TaxRates/main/tax_rates.csv \
      -o backend/data/zip_tax_rates.csv

The Incentive App caches the parsed rates in process memory at
first read (~50 ms / 1.1 MB), so a redeploy is enough to pick up
a refreshed file.

**Schema (10 cols, header row):**

    Country code,State code,Postcode / ZIP,City,Rate %,Tax name,Priority,Compound,Shipping,Tax class

We only use `State code`, `Postcode / ZIP`, and `Rate %`. Other
columns are kept verbatim from the source so re-pulling is a
straight overwrite — no transformation step.

**Coverage notes:**
- Alaska ZIPs are mostly 0% (no state sales tax; some boroughs add
  local tax — those will be 0 in this dataset, so AK estimates may
  be slightly low. Override the rate per-deal in the calculator if
  the customer is in an AK locality with local tax.)
- Special-district / RTA / stadium / convention-center surcharges
  that don't map cleanly to a residential ZIP may be missed.
- Vehicle-specific rates (some states tax motor vehicles at a rate
  different from general sales tax — e.g., VA's 4.15% motor vehicle
  rate vs 5.3% general sales tax) are not encoded. The calculator's
  rate field is editable for these cases.
