"""Synthetic cold chain logger downloads in the exact formats the devices write.

Every module writes one logger family's files exactly as the device lays them out on
its USB drive, from a seeded simulation, so the same arguments always give
byte-identical output:

- `fridgetag`: Berlinger Fridge-tag 2 / 2E / 2L history reports (`.txt` + `.pdf`)
- `ems`: WHO PQS E006 EMS drives (CURRENT_DATA, SYNC, DATA_HISTORY, 60DTR summary PDF)
- `haier`: Haier HETL-01 30-day temperature recorder exports (`HE<serial>.CSV`)
- `metafridge`: Aucma MetaFridge CFD-50 SDD 30 DTR reports (`.csv` + `.pdf`)
- `scenarios`: the named scenario catalogue and curated multi-file stories
- `damage`: deliberately broken variants for parser tests
- `library`: the test library, curated cases with the outcome an app should show

Everything written is made up. Never add real device data to this package.
"""

__version__ = "0.3.1"
