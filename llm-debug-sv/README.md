# LLM Debug SV: Three-Zero Detector

This mini-dataset contains a small FSM from 18-240 adapted to demonstrate common LLM mistakes in SystemVerilog finite-state machines.

## Modules

- `found3zeros_correct.sv` — Reference implementation of a Mealy/Moore-style FSM that drives an active-low output (`found3zeros_N`) when three consecutive zeros have been observed (state `SAW000`).
- `found3zeros_buggy.sv` — Intentionally buggy variant. The next-state transition from `SAW00` on `b==0` incorrectly goes to `SAW0` instead of `SAW000`. This subtle error prevents reaching the detection state in many sequences and causes assertion failures under test.
- `tb_found3zeros.sv` — Self-checking testbench that instantiates either module via a compile-time define and compares the DUT output against a simple 3-bit shift-register golden model.

Additional small modules (each has a correct and a buggy version):

- `edge_detect_rise_correct.sv` / `edge_detect_rise_buggy.sv` — Pulse when `b` rises. Bug: reset initializes history to 1, masking first pulses.
- `majority3_correct.sv` / `majority3_buggy.sv` — Majority-of-3. Bug: threshold uses `>=1` (acts like OR) instead of `>=2`.
- `satcounter2_correct.sv` / `satcounter2_buggy.sv` — 2-bit saturating counter at 3. Bug: wraps around (no saturation) from 3->0.
- `odd_parity8_correct.sv` / `odd_parity8_buggy.sv` — Odd parity of 8-bit data. Bug: computes even parity using `^data`.
- `encoder4to2_correct.sv` / `encoder4to2_buggy.sv` — 4-to-2 one-hot encoder. Bug: swapped codes for inputs 0010 and 0100.
- `edge_detect_fall_correct.sv` / `edge_detect_fall_buggy.sv` — Falling-edge one-shot. Bug: reset initializes history to 0, masking the first falling edge.
- `onehot8_check_correct.sv` / `onehot8_check_buggy.sv` — One-hot checker. Bug: uses `>=1` instead of `==1`, allowing multi-hot.
- `adder4_carry_correct.sv` / `adder4_carry_buggy.sv` — 4-bit adder with carry. Bug: ignores carry-in (`cin`).
- `prienc8to3_correct.sv` / `prienc8to3_buggy.sv` — Priority encoder (MSB-high). Bug: reversed priority (LSB wins).

- `seqdet_101_correct.sv` / `seqdet_101_buggy.sv` — 101 sequence detector. Bug: output uses wrong state bit (`currState[1]`) instead of `currState[2]`.
- `fsm_ABwin11_correct.sv` / `fsm_ABwin11_buggy.sv` — A/B-driven FSM that “wins” on two consecutive ones of the selected signal. Bug: from `NONE`, {A,B}=01 incorrectly stays in `NONE` instead of going to `B1`.
- `library_decoder_correct.sv` / `library_decoder_buggy.sv` — Parameterized Decoder. Bug: off-by-one index writes `D[I+1]` (also risks overflow).

## How it works

Input `b` is sampled on the rising edge of `clock`. When the last three sampled bits are `000`, the output is low (`found3zeros_N == 0`), otherwise it is high.

## Simulate

You can simulate with any SV simulator. Examples below assume Icarus Verilog (`iverilog`) and `vvp` are installed, or Verilator. Adjust commands for your tool of choice.

### Icarus Verilog

- Correct:

```sh
iverilog -g2012 -o sim_correct tb_found3zeros.sv found3zeros_correct.sv && vvp sim_correct
```

- Buggy:

```sh
iverilog -g2012 -DBUGGY -o sim_buggy tb_found3zeros.sv found3zeros_buggy.sv && vvp sim_buggy
```

Waveform VCD is written to `found3zeros.vcd`.

For the additional pairs (combinational/sequential), you can write tiny benches or integrate into existing regressions. Example with Icarus for the majority module (combinational):

```sh
iverilog -g2012 -o sim_majority tutorial/llm-debug-sv/majority3_correct.sv && vvp sim_majority # drives nothing, just compiles
```

For sequential ones like the edge detector or counter, instantiate in a small testbench that generates a clock/reset and drives a few inputs.

Quick compile checks (Icarus Verilog):

```sh
iverilog -g2012 tutorial/llm-debug-sv/seqdet_101_correct.sv -o /tmp/ok && vvp /tmp/ok
iverilog -g2012 tutorial/llm-debug-sv/library_decoder_buggy.sv -o /tmp/ok && vvp /tmp/ok
```

### Verilator (optional)

```sh
verilator -Wall --cc --exe --build -DBUGGY \
  tb_found3zeros.sv found3zeros_buggy.sv \
  --top-module tb_found3zeros
./obj_dir/Vtb_found3zeros
```

## What to look for

- The correct design's assertions should pass silently and `Test completed` should print at the end.
- The buggy design will trigger assertion errors around sequences that include `...000...` because it fails to transition into `SAW000` from `SAW00` when `b==0`.

## Attribution

Original state machine adapted from your `hw5/hw5prob2.sv` in this repository. Active-low output and state names are preserved to make diffs easy for LLM debugging tasks.
