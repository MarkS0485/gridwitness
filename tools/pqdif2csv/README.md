# pqdif2csv

Converts a PQDIF (IEEE 1159.3) file to a long-format CSV containing **only frequency and voltage**,
for the GridWitness `survey_ingest` worker to read. It is the single component that understands the
PQDIF binary format, so the dependency-light Python worker can support PQDIF by shelling out.

```
pqdif2csv <file.pqd>            # CSV to stdout
pqdif2csv <file.pqd> out.csv    # CSV to a file
```

Output columns: `timestamp,phase,channel,value` where `channel` is `frequency` or `voltage`, `phase`
is `L1|L2|L3|1p`, and `timestamp` is ISO-8601 UTC. RMS/instantaneous voltage and frequency series are
emitted; current, power, harmonics/THD and everything else are filtered out here — so the "only
frequency and voltage leave" guarantee holds for the binary path too.

## Build

```
dotnet build -c Release
```

Targets **net48** because GSF.PQDIF (the MIT-licensed reference implementation) ships only .NET
Framework assemblies. `Microsoft.NETFramework.ReferenceAssemblies` lets `dotnet build` produce it
without a full Visual Studio install. The worker finds it via `GW_PQDIF2CSV` (path to the exe) or on
`PATH`; where it is absent, PQDIF files are skipped with a manifest note and CSV/TXT still process.

## Local workflow (no server changes needed)

PQDIF runs on Windows. Uploaded `.pqd` files wait in the server inbox (status `pqdif_pending`); the
Linux worker never discards them. To process them locally:

```powershell
.\convert-local.ps1 -Folder C:\surveys\pending      # every .pqd -> <name>.csv (long format)
```

Then upload the resulting `.csv` files through the normal "Contribute a survey" page — the worker
recognises the long format (`timestamp,phase,channel,value`) and stages them like any other survey.
That closes the loop without a Windows-hosted worker or Mono.

## Note

Because it is .NET Framework, native PQDIF support otherwise requires a Windows-hosted worker with
`GW_PQDIF2CSV` set, or Mono. Validate the mapping against a real `.pqd` from your analyser before
relying on it — the frequency/voltage/phase classification follows the PQDIF logical model
(QuantityMeasured=Voltage with RMS/Instantaneous characteristic; QuantityCharacteristic=Frequency)
but real-world files vary and this has not been exercised against a sample here.
