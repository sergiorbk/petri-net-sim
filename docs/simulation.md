# Running a simulation

Simulation is stochastic: transitions fire on their own distributions
(exponential, deterministic, normal, uniform), so two runs of the same net
are two samples, not one answer repeated.

## Three ways to start

| Button | What it does |
|--------|--------------|
| **Run** | Plays the run as an animation, tokens moving at the playback rate |
| **Run & Step** | Computes the whole run, then pauses on step 0 so you walk it yourself |
| **Final state** | Computes the whole run and lands on its last snapshot, no animation |

All three compute the same run. **Final state** is the one to reach for when
the question is where the net ended up rather than how it got there: a minute
of simulated time at the default rate is a minute of watching.

Run & Step and Final state both keep the whole history, so the arrows step
back and forth through it. Final state simply starts you at the far end.

## What a run is made of

| Control | Meaning |
|---------|---------|
| **Duration** | How much simulated time to run, in the unit beside it |
| **Visual / Scientific** | Whether a snapshot is taken every N time units, or every N transition firings |
| **Step** | The N for whichever of those is selected |
| **Playback rate** | Simulated time per real second, for the animation only |

Scientific mode is the one to use when you care about the sequence of events
rather than the clock: one snapshot per firing means nothing is skipped
between two samples.

## Statistics

When a run finishes, the playback bar offers **Statistics**, which opens over
the canvas:

![The statistics panel over the canvas: a legend of every series, tokens per place over time, transition buffers over time](assets/statistics.png)

- **Tokens per place over time** and **transition buffers over time**, as line
  charts against the simulation clock.
- A **legend** where each series can be switched off, so a busy net can be
  read one queue at a time.
- A **summary table**: points, minimum, maximum, mean and last value per
  series.

Series are named after the elements they came from. In a composed model,
where objects can hold elements of the same name, a name is qualified with
its object (`Arrivals_Ready (Generator)`) only when it would otherwise be
ambiguous.

### Getting the numbers out

Three buttons in the panel header:

| Export | What you get |
|--------|--------------|
| **CSV** | One `time` column and one column per series, ready to open in Excel or load into PowerBI |
| **PNG** | Both charts in one raster image, at 2x, on an opaque background |
| **SVG** | The same, as vectors, for a figure that has to survive being scaled |

The CSV is wide, not tidy: a row per time value, a column per series. Where a
series has no sample at some time, its previous value is carried forward,
because a marking holds until it changes. That is the shape a spreadsheet
pivots without further work.

## Where a simulation runs

By default the built-in Python engine, in the backend. `SIMULATION_ENGINE=remote`
sends the model to a [petri-server](petriobjmodelpaint.md) instance instead,
the Java engine from PetriObjModelPaint. Composed Petri-object models are
computed by the engine that understands objects either way.

The choice is per deployment, not per run. See
[configuration.md](configuration.md).
