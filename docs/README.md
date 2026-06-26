# Docs

Deeper documentation for the golf pipeline. The top-level [README](../README.md)
is the front door - overview, setup, and how to run. These docs go a level down:
how it's put together and where everything lives.

Read in this order if you're new:

1. **[Architecture](architecture.md)** - the big picture. How a shot travels
   from a CSV to an analysis-ready table, the medallion layers, and the three
   ways the pipeline runs (by hand, Airflow, Spark).
2. **[Data model](data-model.md)** - the common schema, the conforming idea,
   and the gold star schema with its SCD2 dimensions and the club-gapping mart.
3. **[Codebase tour](codebase-tour.md)** - a guided walk through the repo so you
   can find things fast and know what each part does.
4. **[Strategy engine](strategy-engine.md)** - the modeling layer on top of gold:
   a calibrated ball-flight model, Monte-Carlo dispersion, strokes-gained scoring,
   and a shot-selection optimizer on a 2-D hole.

Everything here is meant to be read by a human, not generated. If a diagram and
two sentences explain a thing, that's all it gets.
