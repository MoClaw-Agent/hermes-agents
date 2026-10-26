# CAMeL NER GPU/CPU Device Configuration

## Problem

CAMeL NER uses PyTorch for inference. If the GPU is incompatible (e.g. Quadro M1200 sm_50 vs PyTorch requiring sm_75+), NER returns all "O" tags (no entities extracted).

## Solution

Set `CAMEL_NER_DEVICE` in `.env`:
- `auto` (default) — probe GPU, force CPU if no CC >= 7.5 GPU
- `cpu` — force CPU via `CUDA_VISIBLE_DEVICES=""`
- `gpu` — force GPU (will crash on incompatible hardware)

## Implementation

The setting is read at module load time in `retrieval/camel_nlp/_bootstrap.py` before any torch import. The bootstrap has two layers:

1. **Module-level GPU check** — reads `CAMEL_NER_DEVICE` and sets `CUDA_VISIBLE_DEVICES` accordingly
2. **`_force_cuda_disabled_for_unsupported_gpu()`** — also respects the setting (skips if explicitly set to `cpu` or `gpu`)

## Verification

```bash
# Test all 3 modes
for mode in cpu gpu auto; do
  CAMEL_NER_DEVICE=$mode python -c "import retrieval.camel_nlp._bootstrap; print('$mode:', __import__('os').environ.get('CUDA_VISIBLE_DEVICES', 'NOT_SET'))"
done
```

## PyTorch Version Compatibility

- PyTorch 2.11.0+ requires sm_75+ (Turing or newer)
- Older PyTorch versions (2.0-2.3 era) shipped sm_50 kernels
- Check compatibility: `python -c "import torch; print(torch.cuda.get_device_capability(0))"`
- If capability < (7, 5), force CPU or downgrade PyTorch
