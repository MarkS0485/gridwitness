# GridWitness give-back card

Paste one of these into a dashboard (Settings → Dashboards → Edit → raw config, or "Add card → Manual").
Everything here uses core cards + the sensors this integration creates — no custom frontend resource
to install.

Replace `XXXXXXXX` with your node's short id (visible in the device name "GridWitness node XXXXXXXX").

## Your node vs the grid + contribution stats

```yaml
type: vertical-stack
cards:
  - type: history-graph
    title: Your node frequency
    hours_to_show: 6
    entities:
      - entity: sensor.gridwitness_node_XXXXXXXX_node_frequency
        name: My node
  - type: glance
    title: Your contribution
    columns: 3
    entities:
      - entity: sensor.gridwitness_node_XXXXXXXX_samples_contributed_today
        name: Today
      - entity: sensor.gridwitness_node_XXXXXXXX_samples_contributed_total
        name: All time
      - entity: sensor.gridwitness_node_XXXXXXXX_clock_offset
        name: Clock offset
  - type: entities
    title: Link health
    entities:
      - entity: binary_sensor.gridwitness_node_XXXXXXXX_server_link
        name: Server link
      - entity: sensor.gridwitness_node_XXXXXXXX_unsent_buffer_backlog
        name: Unsent backlog
```

## Overlaying the national trace (optional)

The "your node vs the grid" overlay is best with
[apexcharts-card](https://github.com/RomRider/apexcharts-card) (install via HACS) once a national
reference sensor is available. Overlay `sensor.gridwitness_node_XXXXXXXX_node_frequency` against the
national 1 s frequency series (published by the ingest server, or NESO's public feed) on the same
axis to *see* your node catch grid events.

> **Note on "live":** this card reads your node's **live** local values. It never reads the research
> lake (which is deliberately held ≥7 days behind real time for the historical GridSim model), so
> what you see here is genuinely now, not a week stale.
