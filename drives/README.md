# Drive reports

How real optical drives behave: which discs they write, at what speed, and what goes wrong. Nobody publishes this anymore, and it disappears as drives do.

Each report is one JSON file describing one burn on one drive, following [`schema.json`](schema.json), at

```
drives/reports/<vendor>-<model>/<yyyy-mm-dd>-<short-id>.json
```

with the vendor and model in lowercase, and spaces replaced by dashes. For example: `drives/reports/pioneer-bd-rw-bdr-xd08/2026-11-25-a1b2.json`.

To contribute, open a pull request with your report, or send the details through [krouton.app/drives](https://krouton.app/drives/). Krouton will be able to write these files itself.

Reports are dedicated to the public domain (CC0). Leave out anything personal: no serial numbers, no names of the files you burned, and no names unless you want credit.
