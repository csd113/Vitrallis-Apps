# GPU utilisation on the PocketCHIP

Optimising this port needed a number for what the GPU was doing, not just a
frame rate. Frames per second cannot distinguish a GPU that is saturated from a
CPU that is spending the frame preparing submissions, and the two have opposite
fixes.

## What the hardware exposes

The Lima driver registers the Mali-400 as a devfreq device:

```
/sys/class/devfreq/1c40000.gpu/
    name                   1c40000.gpu
    available_frequencies  297000000
    cur_freq               297000000
    min_freq               297000000
    max_freq               297000000
    governor               simple_ondemand
```

**There is exactly one frequency.** The GPU's clock is fixed at 297 MHz on this
board — the `limits`/`opp` table has a single entry and the driver logs
`_opp_set_regulators: no regulator (mali) found` — so `simple_ondemand` has
nothing to choose between and `cur_freq` carries no information. This matters
because it rules out the tempting shortcut: **a frequency is not a utilisation
percentage and on this device it does not change at all.**

There is no `load` file in the devfreq directory and no readable Mali occupancy
counter.

What the kernel *does* provide is the devfreq governor's own measurement. The
governor polls the device's busy time every `polling_ms` and reports it through
the `devfreq_monitor` tracepoint, whose format is:

```
field:unsigned long freq;        offset:8
field:unsigned long busy_time;   offset:12
field:unsigned long total_time;  offset:16
field:unsigned int  polling_ms;  offset:20
field:__data_loc char[] dev_name; offset:24

print fmt: "... freq=%-12lu polling_ms=%-3u load=%-2lu",
    REC->freq, REC->polling_ms,
    REC->total_time == 0 ? 0 : (100 * REC->busy_time) / REC->total_time
```

The `load` field is therefore `100 * busy_time / total_time` — the fraction of
the polling window during which the GPU was not idle. That is a real
utilisation percentage, computed by the kernel from the device's own busy-time
accounting.

## How Places reads it

Vitrallis already keeps a dedicated tracefs instance for this, so nothing has
to be enabled globally and nothing has to run as root:

```
/sys/kernel/tracing/instances/vitrallis-gpu/     the private instance
/run/vitrallis-gpu/trace_pipe                    it, mounted 0640 root:chip
```

The `devfreq_monitor` event is enabled in that instance by
`vitrallis-gpu-trace.service`, and the `chip` user can read the pipe because
the mount is group-readable by `chip`.

`tools/bench/gpuwatch.sh` in this repository samples the pipe and reports the
mean, median, p95 and maximum `load` over a window, plus which frequencies were
seen:

```sh
~/bin/gpuwatch.sh 15            # 15 seconds
~/bin/gpuwatch.sh 15 out.csv    # also append time,load,freq rows
```

It is a shell script over `cat` and `awk`. It does not link into the game, it
does not run inside the frame loop, and it is not part of the shipped binary:
the game's cost is identical whether it is running or not. The one thing it
does require is that the reader keeps up — a `trace_pipe` that overflows prints
`LOST EVENTS`, which is why the sampler reports its sample count alongside the
percentages.

## Validation

A counter is only useful if it moves correctly. It was checked against four
workloads of increasing GPU demand:

| Workload | mean | median | p95 | max |
| --- | --- | --- | --- | --- |
| Idle desktop (Vitrallis shell, nothing animating) | 11.8 % | 0 % | 50 % | 55 % |
| Places, standing still in the office | 73.5 % | 96 % | 99 % | 99 % |
| Places, pool hall (heaviest reference view) | 76.0 % | 96 % | 99 % | 99 % |
| `glxgears` at 480 × 272, vsync-locked | 83.2 % | 93 % | 97 % | 97 % |

It reads near zero when nothing is drawing, rises with real GL work, and
saturates around 97–99 % rather than reaching exactly 100 (the governor's
sample window includes the gap between jobs). The ordering and the spread are
both sensible, and the readings changed as the renderer was optimised, which is
the property that matters.

## What the numbers meant

The counter is what turned the optimisation from guesswork into measurement.

* **Before the batching change:** GPU mean 40 %, median 44 %, with 170 draw
  calls and a `render` phase (CPU submission) of 36.7 ms. Low GPU occupancy next
  to a long CPU phase said the frame was being spent preparing submissions.
* **After:** 62 draw calls, `render` down to 11.7 ms, and GPU median at 96 %.
  The bottleneck moved to the GPU, which is where it should be.
* **Texture sweeping:** 64/128/256/512-texel sheets all produced the same 16 FPS
  at 96 % occupancy. A GPU that is saturated but indifferent to texture size is
  not bandwidth-bound, so the extra resolution is free and the cap stays at 256.
* **Pass 2 — the fragment stage was the frame:** a block-level probe removed the
  albedo fetch, the atlas reads, the emission term and the fog one at a time. On
  the pool view the GPU time fell from 46 ms to 23 ms as the fragment program
  shrank, while the busy fraction stayed 94–96 % median throughout. Once the
  renderer is GPU-bound, utilisation confirms *that* the GPU is the constraint
  but cannot rank two shader programs; the frame time and the probe did.

## Limitations

* The metric is a **device-busy fraction over a ~50 ms window**, not a cycle
  count. It cannot attribute work to a particular pass, and a frame that
  alternates between a busy GPU and an idle one averages out. Read it next to
  the frame-time percentiles, never instead of them.
* It covers the whole GPU device, so anything else drawing at the same time is
  included. On this device that is only the shell.
* The frequency field is reported for completeness and is always 297000000. It
  must not be read as a load figure.
